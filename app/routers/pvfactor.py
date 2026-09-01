"""量价综合因子接口（宏观预测模块）。

因子：量价同步度(20日) / Amihud(3日) / 量确认动量(10日) 截面分位等权合成，
符号按各自 IC 方向调整（- + -）。构造与 FACTOR_RESEARCH.md 一致，
样本外（2016~2022）已验证：日均截面 IC +0.045、12 个自然年全正。

计算较重（个股截面），带进程内缓存（TTL 30 分钟）。
"""
import time
from datetime import timedelta

import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import text

from app.database import engine

router = APIRouter(prefix="/api/pvfactor", tags=["pvfactor"])

DAYS = {"90": 90, "250": 250, "750": 750}
_CACHE = {}  # days -> (computed_at, payload)
TTL = 1800
_RANK_CACHE = {}  # date -> payload（按日期排名，上限 120 个日期）


def _clean(obj):
    """递归把 NaN/Inf 洗成 None（JSON 不接受越界浮点）。"""
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_clean(v) for v in obj]
    if isinstance(obj, float) and not np.isfinite(obj):
        return None
    return obj


def _compute(days: int | None, need_top: bool):
    # 取数窗口：目标天数 + 60 个交易日预热（滚动窗口用），按交易日历精确截取
    with engine.connect() as conn:
        cal = [r[0] for r in conn.execute(text(
            "SELECT cal_date FROM trade_cal WHERE exchange='SSE' AND is_open=1 "
            "AND cal_date <= CURDATE() ORDER BY cal_date DESC"))]
    start = cal[min(len(cal) - 1, (days or len(cal)) + 60)]
    df = pd.read_sql(text(
        "SELECT d.ts_code, d.trade_date, d.close, d.pct_chg, d.vol, d.high, d.low, "
        "       d.amount, b.name, b.industry "
        "FROM daily_bar d LEFT JOIN stock_basic b ON b.ts_code = d.ts_code "
        "WHERE d.trade_date >= :s ORDER BY d.ts_code, d.trade_date"),
        engine, params={"s": start})
    for c in ("close", "pct_chg", "vol", "high", "low", "amount"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["abs_ret"] = df["pct_chg"].abs()
    df["sign1"] = np.sign(df["pct_chg"])
    g = df.groupby("ts_code", sort=False)

    df["vol_ma5"] = g["vol"].transform(lambda x: x.rolling(5).mean())
    df["pv_sync_d"] = df["sign1"] * (df["vol"] / df["vol_ma5"] - 1)
    df["pv_sync20"] = g["pv_sync_d"].transform(lambda x: x.rolling(20).mean())
    df["illiq_d"] = (df["abs_ret"] / df["amount"].replace(0, np.nan) * 1e9)
    df["amihud3"] = g["illiq_d"].transform(lambda x: x.rolling(3).mean())
    df["amt_ma5"] = g["amount"].transform(lambda x: x.rolling(5).mean())
    df["amt_ma20"] = g["amount"].transform(lambda x: x.rolling(20).mean())
    df["ret_10"] = g["close"].pct_change(10, fill_method=None)
    df["vw_mom10"] = df["ret_10"] * (df["amt_ma5"] / df["amt_ma20"] - 1)
    df["next_ret"] = g["pct_chg"].shift(-1)
    # pct_chg 单位为百分点（2.5=+2.5%）。新股上市首日无涨跌幅限制（±1000 个点级），
    # 组合净值按 ±50 个百分点截尾（该类收益不可交易）；IC 用秩相关不受影响
    df["next_ret"] = df["next_ret"].clip(-50, 50)
    df["trade_date"] = df["trade_date"].astype(str)

    sub = df.dropna(subset=["pv_sync20", "amihud3", "vw_mom10", "next_ret"]).copy()
    if sub.empty:
        return {"dates": [], "latest": None}

    signs = {"pv_sync20": -1, "amihud3": +1, "vw_mom10": -1}
    sub["comp"] = sum(sg * sub.groupby("trade_date")[col].rank(pct=True)
                      for col, sg in signs.items()) / 3

    # 逐日截面 IC / 多头 D10 / 市场基准
    def day_stats(d):
        ic = d["comp"].rank().corr(d["next_ret"].rank())
        q = d["comp"].rank(pct=True)
        return pd.Series({
            "ic": ic,
            "top": d.loc[q >= 0.9, "next_ret"].mean(),
            "base": d["next_ret"].mean(),
            "n": len(d),
        })
    daily = sub.groupby("trade_date").apply(day_stats, include_groups=False)
    # top/base 单位为百分点 → 复利时 /100 转小数
    daily["nav_top"] = (1 + daily["top"] / 100).cumprod()
    daily["nav_base"] = (1 + daily["base"] / 100).cumprod()
    daily["ric"] = daily["ic"].rolling(60, min_periods=20).mean()

    view = daily if days is None else daily.tail(days)
    ann_top = (view["nav_top"].iloc[-1]) ** (242 / len(view)) - 1 if len(view) > 60 else None

    # 当日 Top20 名单
    top_list = []
    if need_top and not daily.empty:
        last_day = sub["trade_date"].max()
        d = sub[sub["trade_date"] == last_day].nlargest(20, "comp")
        top_list = [{"ts_code": r.ts_code,
                     "name": r.name if isinstance(r.name, str) else r.ts_code,
                     "industry": r.industry if isinstance(r.industry, str) else None,
                     "score": round(float(r.comp), 4)}
                    for r in d.itertuples()]

    latest = {
        "trade_date": view.index[-1],
        "ic60": None if pd.isna(view["ric"].iloc[-1]) else round(float(view["ric"].iloc[-1]), 4),
        "ann_top": None if ann_top is None else round(float(ann_top) * 100, 1),
        "win_rate": None if len(view) < 60 else round(float((view["top"] > 0).mean()) * 100, 0),
        "n_stocks": int(view["n"].iloc[-1]),
        "nav_top": round(float(view["nav_top"].iloc[-1]), 4),
        "nav_base": round(float(view["nav_base"].iloc[-1]), 4),
    }
    return {
        "dates": list(view.index),
        "nav_top": [round(float(v), 4) for v in view["nav_top"]],
        "nav_base": [round(float(v), 4) for v in view["nav_base"]],
        "ric": [None if pd.isna(v) else round(float(v), 4) for v in view["ric"]],
        "top_list": top_list,
        "latest": latest,
    }


@router.get("/overview")
def overview(days: str = Query(default="250"), refresh: int = 0):
    n = DAYS.get(days)
    key = days if n else "all"
    ts, payload = _CACHE.get(key, (0, None))
    fresh = time.time() - ts < TTL
    if payload is None or not fresh or refresh:
        payload = _clean(_compute(n, need_top=not fresh))
        _CACHE[key] = (time.time(), payload)
    return payload


@router.get("/rank")
def rank(date: str = Query(pattern=r"^\d{4}-\d{2}-\d{2}$")):
    """任意交易日全市场合成因子排名（含次日涨跌，研究验证用）。"""
    date = date.strip()
    if date in _RANK_CACHE:
        return _RANK_CACHE[date]

    with engine.connect() as conn:
        last_data = str(conn.execute(text(
            "SELECT MAX(trade_date) FROM daily_bar")).scalar())
        opens = [str(r[0]) for r in conn.execute(text(
            "SELECT cal_date FROM trade_cal WHERE exchange='SSE' AND is_open=1 "
            "AND cal_date <= :d ORDER BY cal_date"), {"d": last_data})]
    if not opens:
        raise HTTPException(404, "无交易日历数据")
    actual = min(date, last_data)
    if actual not in opens:
        opens_lt = [d for d in opens if d <= actual]
        actual = opens_lt[-1] if opens_lt else None
    if not actual:
        raise HTTPException(404, f"{date} 之前无行情数据")
    # 次一交易日（用于次日涨跌列）
    i = opens.index(actual)
    next_day = opens[i + 1] if i + 1 < len(opens) else None

    # ---- 快路径：pv_rank 预计算表（每日流水线/ pvrank 任务维护） ----
    rows_q = pd.read_sql(text(
        "SELECT r.ts_code, r.score, r.pct_chg, r.next_ret, b.name, b.industry "
        "FROM pv_rank r LEFT JOIN stock_basic b ON b.ts_code = r.ts_code "
        "WHERE r.trade_date = :d ORDER BY r.score DESC"),
        engine, params={"d": actual})
    if not rows_q.empty:
        rows = [{"rank": i + 1,
                 "ts_code": r.ts_code,
                 "name": r.name if isinstance(r.name, str) else r.ts_code,
                 "industry": r.industry if isinstance(r.industry, str) else None,
                 "pct_chg": None if pd.isna(r.pct_chg) else round(float(r.pct_chg), 2),
                 "score": round(float(r.score), 4),
                 "next_ret": None if (r.next_ret is None or pd.isna(r.next_ret))
                             else round(float(r.next_ret), 2)}
                for i, r in enumerate(rows_q.itertuples())]
        k = max(1, len(rows) // 10)
        top_next = [x["next_ret"] for x in rows[:k] if x["next_ret"] is not None]
        all_next = [x["next_ret"] for x in rows if x["next_ret"] is not None]
        payload = {
            "date": actual, "next_day": next_day, "total": len(rows),
            "top10_next_avg": round(float(np.mean(top_next)), 2) if top_next else None,
            "market_next_avg": round(float(np.mean(all_next)), 2) if all_next else None,
            "rows": rows,
        }
        if len(_RANK_CACHE) > 120:
            _RANK_CACHE.pop(next(iter(_RANK_CACHE)))
        _RANK_CACHE[date] = payload
        return _clean(payload)
    # ---- 慢路径：实时计算 ----

    # 取数窗口：actual 往前 60 个交易日（含），到 next_day（如有）
    start = opens[max(0, i - 59)]
    end = next_day or actual

    df = pd.read_sql(text(
        "SELECT d.ts_code, d.trade_date, d.close, d.pct_chg, d.vol, d.high, d.low, "
        "       d.amount, b.name, b.industry, b2.turnover_rate_f "
        "FROM daily_bar d LEFT JOIN stock_basic b ON b.ts_code = d.ts_code "
        "LEFT JOIN daily_basic b2 ON b2.ts_code = d.ts_code AND b2.trade_date = d.trade_date "
        "WHERE d.trade_date BETWEEN :s AND :e ORDER BY d.ts_code, d.trade_date"),
        engine, params={"s": start, "e": end})
    if df.empty:
        raise HTTPException(404, f"{actual} 无行情数据")
    for c in ("close", "pct_chg", "vol", "high", "low", "amount", "turnover_rate_f"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["trade_date"] = df["trade_date"].astype(str)
    df["abs_ret"] = df["pct_chg"].abs()
    df["sign1"] = np.sign(df["pct_chg"])
    g = df.groupby("ts_code", sort=False)
    df["vol_ma5"] = g["vol"].transform(lambda x: x.rolling(5).mean())
    df["pv_sync_d"] = df["sign1"] * (df["vol"] / df["vol_ma5"] - 1)
    df["pv_sync20"] = g["pv_sync_d"].transform(lambda x: x.rolling(20).mean())
    df["illiq_d"] = df["abs_ret"] / df["amount"].replace(0, np.nan) * 1e9
    df["amihud3"] = g["illiq_d"].transform(lambda x: x.rolling(3).mean())
    df["amt_ma5"] = g["amount"].transform(lambda x: x.rolling(5).mean())
    df["amt_ma20"] = g["amount"].transform(lambda x: x.rolling(20).mean())
    df["ret_10"] = g["close"].pct_change(10, fill_method=None)
    df["vw_mom10"] = df["ret_10"] * (df["amt_ma5"] / df["amt_ma20"] - 1)

    cur = df[df["trade_date"] == actual].copy()
    signs = {"pv_sync20": -1, "amihud3": +1, "vw_mom10": -1,
             "turnover_rate_f": -1}
    parts = []
    for col, sg in signs.items():
        if cur[col].notna().sum() > 100:
            parts.append(sg * cur[col].rank(pct=True))
    if not parts:
        raise HTTPException(404, f"{actual} 因子数据不足")
    cur["comp"] = sum(parts) / len(parts)

    # 次日涨跌（仅当存在次一交易日数据）
    nxt = None
    if next_day:
        nxt = df[df["trade_date"] == next_day][["ts_code", "pct_chg"]] \
            .rename(columns={"pct_chg": "next_ret"})
    cur = cur.merge(nxt, on="ts_code", how="left") if nxt is not None else \
        cur.assign(next_ret=np.nan)
    cur = cur.dropna(subset=["comp"]).sort_values("comp", ascending=False)

    rows = [{"rank": i + 1,
             "ts_code": r.ts_code,
             "name": r.name if isinstance(r.name, str) else r.ts_code,
             "industry": r.industry if isinstance(r.industry, str) else None,
             "pct_chg": None if pd.isna(r.pct_chg) else round(float(r.pct_chg), 2),
             "score": round(float(r.comp), 4),
             "next_ret": None if (next_day is None or pd.isna(r.next_ret))
                         else round(float(r.next_ret), 2)}
            for i, r in enumerate(cur.itertuples())]
    top_next = [r["next_ret"] for r in rows[:max(1, len(rows) // 10)]
                if r["next_ret"] is not None]
    all_next = [r["next_ret"] for r in rows if r["next_ret"] is not None]
    payload = {
        "date": actual, "next_day": next_day if next_day and next_day <= last_data else None,
        "total": len(rows),
        "top10_next_avg": round(float(np.mean(top_next)), 2) if top_next else None,
        "market_next_avg": round(float(np.mean(all_next)), 2) if all_next else None,
        "rows": rows,
    }
    if len(_RANK_CACHE) > 120:
        _RANK_CACHE.pop(next(iter(_RANK_CACHE)))
    _RANK_CACHE[date] = payload
    return _clean(payload)
