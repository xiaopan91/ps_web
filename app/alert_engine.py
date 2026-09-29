"""报警规则引擎：评估规则 + Server酱 微信推送。

取数：股票 daily_bar / ETF fund_daily / 指数 index_daily+index_ext 四表统一，
按 ts_code 取最近 N 天的日线序列（收盘/前收/涨跌幅/成交量），再做规则判定。

评估入口 evaluate_all()：
- 当日已有 AlertLog 且非 force → 跳过（每日防重，链式/定时/手动互不重复）
- 逐条启用规则判定 → 触发写 AlertLog、one_shot 自动停用
- 有触发且配置了 Server酱 SendKey → 聚合一条消息推送
"""
import json
from datetime import date, datetime, timedelta

import pandas as pd
import requests
from sqlalchemy import text

from app.database import engine

# 标的类型 → 行情表（四表统一，列对齐：close/vol/amount）
TABLES = {"stock": "daily_bar", "etf": "fund_daily", "index": "index_daily"}

RULE_LABELS = {
    "price_above": "价格高于", "price_below": "价格低于",
    "pct_up": "涨幅超", "pct_down": "跌幅超",
    "new_high": "创N日新高", "new_low": "创N日新低",
    "ma_cross_up": "上穿均线", "ma_cross_down": "下穿均线",
    "vol_spike": "放量",
    "pe_below": "PE低于", "pe_above": "PE高于",
    "pe_pct_below": "PE分位低于", "pe_pct_above": "PE分位高于",
    "streak_up": "连涨达", "streak_down": "连跌达",
}


def _config() -> dict:
    df = pd.read_sql(text(
        "SELECT serverchan_key, last_eval_date FROM alert_config WHERE id = 1"), engine)
    if df.empty:
        return {"serverchan_key": "", "last_eval_date": None}
    return {"serverchan_key": df.iloc[0]["serverchan_key"] or "",
            "last_eval_date": df.iloc[0]["last_eval_date"]}


def _save_config(cfg: dict):
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO alert_config (id, serverchan_key, updated_at) VALUES (1, :k, :t) "
            "ON DUPLICATE KEY UPDATE serverchan_key = :k, updated_at = :t"),
            {"k": cfg.get("serverchan_key", ""), "t": datetime.now()})


def _mark_evaluated():
    """记录评估运行日（当日防重）。"""
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO alert_config (id, last_eval_date, updated_at) VALUES (1, :d, :t) "
            "ON DUPLICATE KEY UPDATE last_eval_date = :d, updated_at = :t"),
            {"d": date.today(), "t": datetime.now()})


def send_serverchan(title: str, message: str) -> bool:
    """Server酱·微信推送。成功返回 True。"""
    key = _config()["serverchan_key"].strip()
    if not key:
        return False
    try:
        r = requests.post(f"https://sctapi.ftqq.com/{key}.send",
                          data={"title": title[:32], "desp": message[:3000]},
                          timeout=15)
        return r.ok and r.json().get("code") == 0
    except Exception:
        return False


def _load_series(target_type: str, ts_code: str, days: int = 260) -> pd.DataFrame:
    """最近 days 个交易日的日线序列（升序）：close, pre_close, vol, amount, trade_date。"""
    table = TABLES.get(target_type)
    if not table:
        raise ValueError(f"未知标的类型: {target_type}")
    df = pd.read_sql(text(
        f"SELECT trade_date, close, vol, amount FROM {table} "
        f"WHERE ts_code = :c AND close IS NOT NULL "
        f"ORDER BY trade_date DESC LIMIT :n"),
        engine, params={"c": ts_code, "n": days})
    if df.empty:
        return df
    df = df.iloc[::-1].reset_index(drop=True)          # 转升序
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    for c in ("vol", "amount"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df["prev_close"] = df["close"].shift(1)
    df["pct"] = (df["close"] / df["prev_close"] - 1) * 100
    return df


def _pe_series(ts_code: str, years: int = 5) -> pd.Series:
    """股票 PE-TTM 历史序列（近 N 年）。"""
    start = (date.today() - timedelta(days=int(years * 365.25))).isoformat()
    df = pd.read_sql(text(
        "SELECT trade_date, pe_ttm FROM daily_basic "
        "WHERE ts_code = :c AND trade_date >= :s AND pe_ttm IS NOT NULL "
        "ORDER BY trade_date"),
        engine, params={"c": ts_code, "s": start})
    if df.empty:
        return pd.Series(dtype="float64")
    return pd.to_numeric(df["pe_ttm"], errors="coerce").dropna()


def _eval_rule(rule_type: str, p: dict, s: pd.DataFrame, pe: pd.Series | None) -> tuple[bool, str]:
    """返回 (是否触发, 人类可读的判定说明)。"""
    if s.empty:
        return False, "无行情数据"

    last = s.iloc[-1]
    close, prev, pct = float(last["close"]), float(last["prev_close"] or last["close"]), float(last["pct"] or 0)

    if rule_type == "price_above":
        t = float(p["threshold"])
        return close >= t, f"收盘 {close} ≥ 阈值 {t}"
    if rule_type == "price_below":
        t = float(p["threshold"])
        return close <= t, f"收盘 {close} ≤ 阈值 {t}"
    if rule_type == "pct_up":
        t = float(p["pct"])
        return pct >= t, f"涨幅 {pct:+.2f}% ≥ +{t}%"
    if rule_type == "pct_down":
        t = -abs(float(p["pct"]))
        return pct <= t, f"涨幅 {pct:+.2f}% ≤ {t}%"
    if rule_type in ("new_high", "new_low"):
        n = int(p["days"])
        win = s["close"].iloc[-(n + 1):]
        if len(win) < 2:
            return False, "历史不足"
        hi, lo = float(win.max()), float(win.min())
        if rule_type == "new_high":
            return close >= hi, f"收盘 {close} 创近 {n} 日新高（{hi}）"
        return close <= lo, f"收盘 {close} 创近 {n} 日新低（{lo}）"
    if rule_type in ("ma_cross_up", "ma_cross_down"):
        n = int(p["window"])
        if len(s) < n + 1:
            return False, "历史不足"
        ma = s["close"].rolling(n).mean()
        ma_y, ma_t = float(ma.iloc[-2]), float(ma.iloc[-1])
        if rule_type == "ma_cross_up":
            hit = prev <= ma_y and close > ma_t
            return hit, f"收盘 {close} 上穿 MA{n}（昨 {ma_y:.2f} → 今 {ma_t:.2f}）"
        hit = prev >= ma_y and close < ma_t
        return hit, f"收盘 {close} 下穿 MA{n}（昨 {ma_y:.2f} → 今 {ma_t:.2f}）"
    if rule_type == "vol_spike":
        n, mult = int(p["days"]), float(p["mult"])
        if len(s) < n + 1 or float(s["vol"].iloc[-(n + 1):-1].mean() or 0) == 0:
            return False, "历史不足"
        avg = float(s["vol"].iloc[-(n + 1):-1].mean())
        v = float(last["vol"] or 0)
        return v >= avg * mult, f"成交量 {v:.0f} ≥ 近{n}日均量 {avg:.0f} × {mult}"
    if rule_type in ("pe_below", "pe_above"):
        t = float(p["threshold"])
        if pe is None or pe.empty:
            return False, "无 PE 数据"
        cur = float(pe.iloc[-1])
        if rule_type == "pe_below":
            return cur <= t, f"PE-TTM {cur:.2f} ≤ {t}"
        return cur >= t, f"PE-TTM {cur:.2f} ≥ {t}"
    if rule_type in ("pe_pct_below", "pe_pct_above"):
        t = float(p["pct"])
        if pe is None or pe.empty:
            return False, "无 PE 数据"
        cur = float(pe.iloc[-1])
        rank = float((pe < cur).mean() * 100)          # 当前值的历史分位
        if rule_type == "pe_pct_below":
            return rank <= t, f"PE-TTM {cur:.2f}，历史分位 {rank:.0f}% ≤ {t}%"
        return rank >= t, f"PE-TTM {cur:.2f}，历史分位 {rank:.0f}% ≥ {t}%"
    if rule_type in ("streak_up", "streak_down"):
        n = int(p["days"])
        if len(s) < n + 1:
            return False, "历史不足"
        cnt = 0
        for i in range(len(s) - 1, 0, -1):
            if float(s["close"].iloc[i]) > float(s["close"].iloc[i - 1]):
                if rule_type != "streak_up":
                    break
                cnt += 1
            elif float(s["close"].iloc[i]) < float(s["close"].iloc[i - 1]):
                if rule_type != "streak_down":
                    break
                cnt += 1
            else:
                break
            if cnt >= n:
                break
        hit = cnt >= n
        word = "连涨" if rule_type == "streak_up" else "连跌"
        return hit, f"{word} {cnt} 天 ≥ {n} 天"
    return False, f"未知规则类型 {rule_type}"


def evaluate_all(force: bool = False) -> dict:
    """评估全部启用规则。返回统计 dict 供接口/任务日志使用。"""
    today = date.today()
    if not force and _config().get("last_eval_date") == today:
        return {"skipped": True, "reason": f"今日({today})已评估过，force 可重评"}
    rules = pd.read_sql(text(
        "SELECT id, name, target_type, ts_code, rule_type, params, one_shot "
        "FROM alert_rule WHERE enabled = 1"), engine)
    _mark_evaluated()   # 无论结果如何，标记今日已评估

    triggered, errors = [], []
    pe_cache = {}
    for r in rules.itertuples():
        try:
            p = json.loads(r.params) if isinstance(r.params, str) else (r.params or {})
            needs_pe = r.rule_type.startswith("pe_")
            pe = None
            if needs_pe:
                if r.ts_code not in pe_cache:
                    pe_cache[r.ts_code] = _pe_series(r.ts_code, int(p.get("years", 5)))
                pe = pe_cache[r.ts_code]
            s = _load_series(r.target_type, r.ts_code)
            hit, desc = _eval_rule(r.rule_type, p, s, pe)
            if hit:
                last = s.iloc[-1]
                trig_date = pd.to_datetime(last["trade_date"]).date()
                title = r.name or f"{r.ts_code} {RULE_LABELS.get(r.rule_type, r.rule_type)}"
                msg = (f"【{title}】{r.ts_code}\n"
                       f"{desc}\n"
                       f"收盘 {float(last['close'])}（{float(last['pct'] or 0):+.2f}%）· {trig_date}")
                triggered.append({"rule_id": int(r.id), "ts_code": r.ts_code,
                                  "name": title, "trade_date": trig_date,
                                  "rule_type": r.rule_type, "message": msg,
                                  "one_shot": int(r.one_shot or 0)})
        except Exception as e:                     # 单条规则异常不阻断整体
            errors.append(f"规则#{r.id} {r.rule_type}: {e}")

    notified = 0
    if triggered:
        ok = send_serverchan(
            f"每日报警：{len(triggered)} 条触发",
            "\n\n".join(t["message"] for t in triggered)) if _config()["serverchan_key"].strip() else False
        notified = 1 if ok else 0
        with engine.begin() as conn:
            for t in triggered:
                conn.execute(text(
                    "INSERT INTO alert_log (rule_id, ts_code, name, trade_date, rule_type, "
                    "message, notified, created_at) VALUES (:rid, :c, :n, :d, :rt, :m, :nf, :at)"),
                    {"rid": t["rule_id"], "c": t["ts_code"], "n": t["name"],
                     "d": t["trade_date"], "rt": t["rule_type"], "m": t["message"],
                     "nf": notified, "at": datetime.now()})
                if t["one_shot"]:
                    conn.execute(text("UPDATE alert_rule SET enabled = 0, "
                                      "last_triggered_date = :d WHERE id = :i"),
                                 {"d": t["trade_date"], "i": t["rule_id"]})
                else:
                    conn.execute(text("UPDATE alert_rule SET last_triggered_date = :d WHERE id = :i"),
                                 {"d": t["trade_date"], "i": t["rule_id"]})
    return {"skipped": False, "rules": int(len(rules)), "triggered": len(triggered),
            "notified": bool(notified), "errors": errors}
