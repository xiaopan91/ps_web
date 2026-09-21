"""行业观察接口：行业日频聚合表的快照与单行业趋势序列。

数据源 sync_data.py industry 预计算的 industry_daily 表。
"""
import time

import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import text

from app.database import engine

router = APIRouter(prefix="/api/industry", tags=["industry"])

_CACHE = {}
_TTL = 600  # overview 缓存 10 分钟


def _cum_nav(piv: pd.DataFrame) -> pd.DataFrame:
    """各行业等权收益（%）透视表 → 累计净值。缺数据日按 0 收益近似。"""
    return (1 + piv.fillna(0) / 100).cumprod()


def _load_all() -> pd.DataFrame:
    df = pd.read_sql(text(
        "SELECT industry, trade_date, n_stocks, up_count, down_count, ret_eq, "
        "       ret_cap, amount, amount_share, turnover_med, circ_mv "
        "FROM industry_daily ORDER BY trade_date"), engine)
    for c in ("n_stocks", "up_count", "down_count", "ret_eq", "ret_cap",
              "amount", "amount_share", "turnover_med", "circ_mv"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


@router.get("/overview")
def overview():
    """全部行业快照：多窗口涨幅、相对强弱排名、成交占比变化 + 趋势摘要。"""
    key = ("overview",)
    hit = _CACHE.get(key)
    if hit and time.time() - hit[0] < _TTL:
        return hit[1]

    df = _load_all()
    if df.empty:
        return {"latest_date": None, "rows": [], "summary": {},
                "note": "industry_daily 无数据，请先跑 sync_data.py industry"}

    piv = df.pivot_table(index="trade_date", columns="industry",
                         values="ret_eq", aggfunc="first")
    cum = _cum_nav(piv)
    dates = cum.index

    def win(n: int) -> pd.Series:
        if len(cum) > n:
            return (cum.iloc[-1] / cum.iloc[-1 - n] - 1) * 100
        return pd.Series(np.nan, index=cum.columns)

    r1, r5, r20, r60 = win(1), win(5), win(20), win(60)

    # 全市场等权基准（按当日有行情家数加权各行业等权收益）
    w = piv.notna().astype(float)
    mkt_ret = (piv.fillna(0) * w).sum(axis=1) / w.sum(axis=1)
    mkt_cum = (1 + mkt_ret / 100).cumprod()
    mkt_r20 = (mkt_cum.iloc[-1] / mkt_cum.iloc[-21] - 1) * 100 if len(mkt_cum) > 20 else np.nan

    # 相对强弱：行业净值 / 全市场等权净值，及 20 日前排名变化
    rs_now = cum.iloc[-1] / mkt_cum.iloc[-1]
    rs_rank = rs_now.rank(ascending=False)
    if len(cum) > 20:
        rs_rank_ago = (cum.iloc[-21] / mkt_cum.iloc[-21]).rank(ascending=False)
        rs_chg = rs_rank_ago - rs_rank
    else:
        rs_chg = pd.Series(np.nan, index=cum.columns)

    # 30 日窗口 RS：只用最近 30 个交易日的相对表现，对短期轮动敏感
    if len(cum) > 30:
        rs30 = ((cum.iloc[-1] / cum.iloc[-31])
                / (mkt_cum.iloc[-1] / mkt_cum.iloc[-31])) * 100
        rs30_rank = rs30.rank(ascending=False)
    else:
        rs30 = pd.Series(np.nan, index=cum.columns)
        rs30_rank = pd.Series(np.nan, index=cum.columns)

    latest = df[df["trade_date"] == dates[-1]].set_index("industry")
    ago20 = (df[df["trade_date"] == dates[-21]].set_index("industry")
             if len(dates) > 20 else latest)
    up_ratio = latest["up_count"] / (latest["up_count"] + latest["down_count"]) * 100

    share_chg = latest["amount_share"] - ago20["amount_share"]
    rows = pd.DataFrame({
        "industry": cum.columns,
        "n_stocks": latest["n_stocks"].reindex(cum.columns).values,
        "r1": r1.values, "r5": r5.values, "r20": r20.values, "r60": r60.values,
        "up_ratio": up_ratio.reindex(cum.columns).values,
        "rs_rank": rs_rank.values.astype(int),
        "rs_chg": rs_chg.values,
        "rs30": rs30.values,
        "rs30_rank": rs30_rank.values.astype(int),
        "share": latest["amount_share"].reindex(cum.columns).values,
        "share_chg": share_chg.reindex(cum.columns).values,
        "turnover_med": latest["turnover_med"].reindex(cum.columns).values,
        "circ_mv": latest["circ_mv"].reindex(cum.columns).values,
    })
    rows = rows.sort_values("r20", ascending=False)
    rows["momentum_rank"] = range(1, len(rows) + 1)

    def tops(s: pd.Series, k=3, asc=False):
        s = s.dropna()
        s = s.sort_values(ascending=asc).head(k)
        return [{"industry": i, "v": round(float(v), 2)} for i, v in s.items()]

    summary = {
        "latest_date": dates[-1].isoformat(),
        "mkt_r20": round(float(mkt_r20), 2),
        "strong20": tops(r20), "weak20": tops(r20, asc=True),
        "flow_in": tops(share_chg), "flow_out": tops(share_chg, asc=True),
        "beat_market": int((r20 > mkt_r20).sum()), "total": int(len(rows)),
    }
    payload = {"latest_date": summary["latest_date"], "summary": summary,
               "rows": rows.replace({np.nan: None}).to_dict("records")}
    _CACHE[key] = (time.time(), payload)
    return payload


@router.get("/detail")
def detail(industry: str, days: int = Query(default=250, ge=30, le=3000)):
    """单行业序列：等权/加权净值 vs 全市场等权基准 + RS + 成交占比。"""
    df = pd.read_sql(text(
        "SELECT trade_date, ret_eq, ret_cap, amount_share, up_count, down_count, "
        "       turnover_med FROM industry_daily WHERE industry = :i "
        "ORDER BY trade_date"), engine, params={"i": industry})
    if df.empty:
        raise HTTPException(404, f"未知行业或无数据: {industry}")
    df = df.tail(days)
    for c in ("ret_eq", "ret_cap", "amount_share", "up_count", "down_count", "turnover_med"):
        df[c] = pd.to_numeric(df[c], errors="coerce")

    mkt = pd.read_sql(text(
        "SELECT trade_date, SUM(ret_eq) / COUNT(ret_eq) AS mkt_eq "
        "FROM industry_daily WHERE trade_date BETWEEN :s AND :e GROUP BY trade_date"),
        engine, params={"s": df["trade_date"].min(), "e": df["trade_date"].max()})
    mkt_ret = pd.to_numeric(mkt.set_index("trade_date")["mkt_eq"], errors="coerce") \
        .reindex(df["trade_date"]).fillna(0)

    # 用 numpy 数组计算，避免 nav(整数索引) 与 mkt(日期索引) 对不齐产生 NaN
    nav_eq = ((1 + df["ret_eq"].fillna(0) / 100).cumprod() * 100).to_numpy()
    nav_cap = ((1 + df["ret_cap"].fillna(0) / 100).cumprod() * 100).to_numpy()
    mkt_nav = ((1 + mkt_ret / 100).cumprod() * 100).to_numpy()
    rs = nav_eq / mkt_nav * 100
    up_ratio = df["up_count"] / (df["up_count"] + df["down_count"]) * 100

    def col(s, d=2):
        return [None if pd.isna(v) else round(float(v), d) for v in s]

    return {
        "industry": industry,
        "dates": [d.isoformat() for d in df["trade_date"]],
        "nav_eq": col(nav_eq),                            # 期初=100
        "nav_cap": col(nav_cap),
        "mkt_nav": col(mkt_nav),
        "rs": col(rs),
        "amount_share": col(df["amount_share"], 3),
        "up_ratio": col(up_ratio, 1),
        "turnover_med": col(df["turnover_med"]),
    }
