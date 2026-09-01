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
from fastapi import APIRouter, Query
from sqlalchemy import text

from app.database import engine

router = APIRouter(prefix="/api/pvfactor", tags=["pvfactor"])

DAYS = {"90": 90, "250": 250, "750": 750}
_CACHE = {}  # days -> (computed_at, payload)
TTL = 1800


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
