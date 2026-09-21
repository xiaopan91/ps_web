"""板块观察接口：申万层级 / 主题指数的快照与单板块趋势序列。

数据源 board_daily（申万为成分股自建聚合；theme 的 ret 字段=官方指数涨跌幅）。
全市场等权基准用申万二级板块计算（每只个股恰属一个 L2，家数加权=全市场等权）。
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
TYPES = ("sw_l1", "sw_l2", "sw_l3", "theme")


def _load_boards(btype: str) -> pd.DataFrame:
    return pd.read_sql(text(
        "SELECT d.board_code, b.board_name, d.trade_date, d.n_stocks, d.up_count, "
        "       d.down_count, d.ret_eq, d.amount, d.amount_share, d.turnover_med, d.circ_mv "
        "FROM board_daily d JOIN board_group b ON b.board_code = d.board_code "
        "WHERE b.board_type = :t ORDER BY d.trade_date"),
        engine, params={"t": btype})


def _market_benchmark() -> pd.Series:
    """全市场等权日收益（申万 L2 家数加权，覆盖全部个股）。"""
    df = pd.read_sql(text(
        "SELECT d.trade_date, d.ret_eq, d.n_stocks FROM board_daily d "
        "JOIN board_group b ON b.board_code = d.board_code "
        "WHERE b.board_type = 'sw_l2'"), engine)
    df["ret_eq"] = pd.to_numeric(df["ret_eq"], errors="coerce").fillna(0)
    df["n_stocks"] = pd.to_numeric(df["n_stocks"], errors="coerce").fillna(0)
    g = df.groupby("trade_date")
    mkt = g.apply(lambda x: (x["ret_eq"] * x["n_stocks"]).sum() / x["n_stocks"].sum(),
                  include_groups=False)
    return (1 + mkt / 100).cumprod()


@router.get("/overview")
def overview(type: str = Query(default="sw_l2")):
    """板块快照：多窗口涨幅、相对强弱排名（累计 + 30 日窗口）+ 趋势摘要。"""
    if type not in TYPES:
        raise HTTPException(400, f"type 取值: {list(TYPES)}")
    key = ("overview", type)
    hit = _CACHE.get(key)
    if hit and time.time() - hit[0] < _TTL:
        return hit[1]

    df = _load_boards(type)
    if df.empty:
        return {"latest_date": None, "type": type, "rows": [], "summary": {},
                "note": "board_daily 无该类型数据，请先跑 sync_data.py board / industry 聚合"}

    piv = df.pivot_table(index="trade_date", columns="board_code",
                         values="ret_eq", aggfunc="first")
    cum = (1 + piv.fillna(0) / 100).cumprod()
    dates = cum.index

    def win(n: int) -> pd.Series:
        if len(cum) > n:
            return (cum.iloc[-1] / cum.iloc[-1 - n] - 1) * 100
        return pd.Series(np.nan, index=cum.columns)

    r1, r5, r20, r60 = win(1), win(5), win(20), win(60)

    mkt_cum = _market_benchmark().reindex(dates).ffill()
    mkt_r20 = ((mkt_cum.iloc[-1] / mkt_cum.iloc[-21] - 1) * 100
               if len(mkt_cum) > 20 else np.nan)

    latest = df[df["trade_date"] == dates[-1]].set_index("board_code")
    ago20 = (df[df["trade_date"] == dates[-21]].set_index("board_code")
             if len(dates) > 20 else latest)
    up_ratio = latest["up_count"] / (latest["up_count"] + latest["down_count"]) * 100
    share_chg = latest["amount_share"] - ago20["amount_share"]
    names = df.groupby("board_code")["board_name"].last()

    rows = pd.DataFrame({
        "industry": cum.columns,
        "name": names.reindex(cum.columns).values,
        "n_stocks": latest["n_stocks"].reindex(cum.columns).values,
        "r1": r1.values, "r5": r5.values, "r20": r20.values, "r60": r60.values,
        "up_ratio": up_ratio.reindex(cum.columns).values,
        "share": latest["amount_share"].reindex(cum.columns).values,
        "share_chg": share_chg.reindex(cum.columns).values,
        "turnover_med": latest["turnover_med"].reindex(cum.columns).values,
        "circ_mv": latest["circ_mv"].reindex(cum.columns).values,
    }).sort_values("r20", ascending=False)
    rows["momentum_rank"] = range(1, len(rows) + 1)

    # 热度：每日等权涨幅排名，进入前 N 记为上榜（板块少的类型自适应下调上榜线）
    n_boards = len(cum.columns)
    hot_n = min(10, max(5, round(n_boards * 0.08)))
    rank_df = piv.rank(ascending=False, axis=1)
    hv = (rank_df <= hot_n).values
    streak_arr = np.zeros_like(hv, dtype=int)
    prev = np.zeros(hv.shape[1], dtype=int)
    for i in range(hv.shape[0]):
        prev = (prev + 1) * hv[i]
        streak_arr[i] = prev
    rank_today = rank_df.iloc[-1]
    streak_today = pd.Series(streak_arr[-1], index=rank_df.columns)
    hits5 = (rank_df <= hot_n).tail(5).sum()
    rows["rank_today"] = rank_today.reindex(cum.columns).fillna(hot_n + 1).astype(int).values
    rows["streak"] = streak_today.values
    rows["hits5"] = hits5.reindex(cum.columns).fillna(0).astype(int).values

    def tops(s: pd.Series, k=3, asc=False):
        s = s.dropna().sort_values(ascending=asc).head(k)
        return [{"industry": str(names.get(i, i)), "v": round(float(v), 2)}
                for i, v in s.items()]

    summary = {
        "latest_date": dates[-1].isoformat(),
        "mkt_r20": round(float(mkt_r20), 2),
        "strong20": tops(r20), "weak20": tops(r20, asc=True),
        "flow_in": tops(share_chg), "flow_out": tops(share_chg, asc=True),
        "beat_market": int((r20 > mkt_r20).sum()), "total": int(len(rows)),
        "hot_n": hot_n,
        "heat": [
            {"code": str(code), "industry": str(names.get(code, code)),
             "r1": round(float(piv.iloc[-1][code]), 2),
             "streak": int(streak_today.get(code, 0)),
             "hits5": int(hits5.get(code, 0))}
            for code in rank_df.iloc[-1].dropna().sort_values().index[:hot_n]
        ],
    }
    payload = {"latest_date": summary["latest_date"], "type": type,
               "summary": summary,
               "rows": rows.replace({np.nan: None}).to_dict("records")}
    _CACHE[key] = (time.time(), payload)
    return payload


@router.get("/members")
def members(board_code: str):
    """板块成分股清单（含最新交易日行情快照），按成交额降序。"""
    g = pd.read_sql(text(
        "SELECT board_name, board_type FROM board_group WHERE board_code = :c"),
        engine, params={"c": board_code})
    if g.empty:
        raise HTTPException(404, f"未知板块: {board_code}")
    df = pd.read_sql(text(
        "SELECT m.ts_code, b.name, b.industry, m.weight, "
        "       d.close, d.pct_chg, d.amount, b2.turnover_rate_f, b2.circ_mv, b2.pe_ttm "
        "FROM board_member m "
        "LEFT JOIN stock_basic b ON b.ts_code = m.ts_code "
        "LEFT JOIN daily_bar d ON d.ts_code = m.ts_code "
        "  AND d.trade_date = (SELECT MAX(trade_date) FROM daily_bar) "
        "LEFT JOIN daily_basic b2 ON b2.ts_code = m.ts_code "
        "  AND b2.trade_date = (SELECT MAX(trade_date) FROM daily_basic) "
        "WHERE m.board_code = :c "
        "ORDER BY d.amount DESC"), engine, params={"c": board_code})

    def num(s, d=2):
        return [None if pd.isna(v) else round(float(v), d) for v in s]

    members = [{
        "ts_code": r.ts_code,
        "name": r.name if isinstance(r.name, str) else r.ts_code,
        "industry": r.industry if isinstance(r.industry, str) else None,
        "weight": None if pd.isna(r.weight) else round(float(r.weight), 2),
        "close": None if pd.isna(r.close) else round(float(r.close), 2),
        "pct_chg": None if pd.isna(r.pct_chg) else round(float(r.pct_chg), 2),
        "amount": None if pd.isna(r.amount) else round(float(r.amount) / 1e5, 3),
        "turnover_f": None if pd.isna(r.turnover_rate_f) else round(float(r.turnover_rate_f), 2),
        "circ_mv": None if pd.isna(r.circ_mv) else round(float(r.circ_mv) / 1e4, 1),
        "pe_ttm": None if pd.isna(r.pe_ttm) else round(float(r.pe_ttm), 2),
    } for r in df.itertuples()]
    return {"board_code": board_code, "board_name": g["board_name"].iloc[0],
            "board_type": g["board_type"].iloc[0], "total": len(members),
            "members": members}


@router.get("/detail")
def detail(board_code: str, days: int = Query(default=250, ge=30, le=3000)):
    """单板块序列：净值（theme=官方指数）vs 全市场等权基准 + RS + 资金序列。"""
    df = pd.read_sql(text(
        "SELECT d.trade_date, d.ret_eq, d.ret_cap, d.amount_share, d.up_count, "
        "       d.down_count, d.turnover_med, b.board_name, b.board_type "
        "FROM board_daily d JOIN board_group b ON b.board_code = d.board_code "
        "WHERE d.board_code = :c ORDER BY d.trade_date"),
        engine, params={"c": board_code})
    if df.empty:
        raise HTTPException(404, f"未知板块或无数据: {board_code}")
    df = df.tail(days)
    for c in ("ret_eq", "ret_cap", "amount_share", "up_count", "down_count", "turnover_med"):
        df[c] = pd.to_numeric(df[c], errors="coerce")

    mkt = _market_benchmark().reindex(df["trade_date"]).ffill()   # 已是净值（期初=1，全历史）
    # 用 numpy 数组计算，避免 nav(整数索引) 与 mkt(日期索引) 对不齐产生 NaN
    nav_eq = ((1 + df["ret_eq"].fillna(0) / 100).cumprod() * 100).to_numpy()
    nav_cap = ((1 + df["ret_cap"].fillna(0) / 100).cumprod() * 100).to_numpy()
    mkt_nav = (mkt / mkt.bfill().iloc[0] * 100).to_numpy()        # 归一到窗口首日=100
    up_ratio = df["up_count"] / (df["up_count"] + df["down_count"]) * 100

    def col(s, d=2):
        return [None if pd.isna(v) else round(float(v), d) for v in s]

    return {
        "board_code": board_code,
        "board_name": df["board_name"].iloc[0],
        "board_type": df["board_type"].iloc[0],
        "dates": [d.isoformat() for d in df["trade_date"]],
        "nav_eq": col(nav_eq),        # theme=官方指数净值（期初=100）；申万=等权自建
        "nav_cap": col(nav_cap),      # 申万=加权自建；theme 同官方
        "mkt_nav": col(mkt_nav),
        "amount_share": col(df["amount_share"], 3),
        "up_ratio": col(up_ratio, 1),
        "turnover_med": col(df["turnover_med"]),
    }
