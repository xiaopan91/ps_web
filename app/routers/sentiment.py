"""市场情绪接口：历史序列 + 合成情绪分（滚动分位数）。"""
import pandas as pd
from fastapi import APIRouter, Query
from sqlalchemy import text

from app.database import engine

router = APIRouter(prefix="/api/sentiment", tags=["sentiment"])

# 合成情绪分的因子（列名, 中文名, 是否反向）
# 2024-08-19 起北向净买为推算口径，与此前数据不可比，已从合成分中移除
FACTORS = [
    ("breadth", "涨跌比", False),
    ("limit_up", "涨停数", False),
    ("max_streak", "连板高度", False),
    ("amount_ratio", "量能比", False),
    ("avg_turnover_f", "换手率", False),
    ("margin_net_buy", "两融净买", False),
    ("std_pct", "离散度", True),  # 反向：分歧越大越冷
]


def _rolling_pct(s: pd.Series, window=750, min_periods=120) -> pd.Series:
    """滚动分位数（0~1）：当前值在历史窗口中的位置，无未来函数。"""
    return s.rolling(window, min_periods=min_periods).apply(
        lambda x: (x[-1] >= x).mean(), raw=True)


@router.get("/history")
def history(days: str = Query(default="250")):
    """情绪历史。days: 90/250/750/all。合成分基于全历史滚动分位数。"""
    df = pd.read_sql(text(
        "SELECT trade_date, up_count, down_count, flat_count, limit_up, limit_down, "
        "max_streak, total_amount, amount_ratio, median_pct, mean_pct, std_pct, "
        "avg_turnover_f, margin_balance, margin_net_buy, north_net, sh_pct, divergence "
        "FROM market_sentiment ORDER BY trade_date"), engine)
    if df.empty:
        return {"dates": [], "score": [], "sh_close": [], "factors": {},
                "latest": None}

    df["breadth"] = (df["up_count"] - df["down_count"]) / (
        df["up_count"] + df["down_count"])

    # 各因子滚动分位数 → 等权合成（0~100）
    factor_scores = {}
    for col, _label, reverse in FACTORS:
        if col not in df:
            continue
        s = df[col].astype(float)
        if reverse:
            s = -s
        factor_scores[col] = _rolling_pct(s).mul(100)
    score_df = pd.DataFrame(factor_scores)
    df["score"] = score_df.mean(axis=1, skipna=True)

    sh = pd.read_sql(text(
        "SELECT trade_date, close FROM index_daily "
        "WHERE ts_code='000001.SH' ORDER BY trade_date"), engine)
    df = df.merge(sh, on="trade_date", how="left")
    df["trade_date"] = df["trade_date"].astype(str)

    n = {"90": 90, "250": 250, "750": 750}.get(days)
    view = df if n is None else df.tail(n)

    def col(name):
        return [None if pd.isna(v) else (float(v) if not isinstance(v, str) else v)
                for v in view[name]]

    factors_now = {}
    for c, s in factor_scores.items():
        v = s.iloc[-1]
        factors_now[c] = None if pd.isna(v) else round(float(v), 0)

    last = view.iloc[-1]
    latest = {
        "trade_date": last["trade_date"],
        "score": None if pd.isna(last["score"]) else round(float(last["score"]), 1),
        "up": int(last["up_count"]), "down": int(last["down_count"]),
        "limit_up": None if pd.isna(last["limit_up"]) else int(last["limit_up"]),
        "limit_down": None if pd.isna(last["limit_down"]) else int(last["limit_down"]),
        "max_streak": None if pd.isna(last["max_streak"]) else int(last["max_streak"]),
        "total_amount_yi": None if pd.isna(last["total_amount"]) else round(
            float(last["total_amount"]) / 1e8, 0),  # 亿元
        "amount_ratio": None if pd.isna(last["amount_ratio"]) else round(
            float(last["amount_ratio"]), 3),
        "median_pct": None if pd.isna(last["median_pct"]) else round(
            float(last["median_pct"]), 2),
        "margin_balance_yi": None if pd.isna(last["margin_balance"]) else round(
            float(last["margin_balance"]) / 1e8, 0),
        "north_net_yi": None if pd.isna(last["north_net"]) else round(
            float(last["north_net"]) / 10000, 1),  # 万→亿
        "sh_close": None if pd.isna(last["close"]) else round(float(last["close"]), 1),
        "factors": factors_now,
    }

    return {
        "dates": list(view["trade_date"]),
        "score": col("score"),
        "sh_close": col("close"),
        "up": col("up_count"),
        "down": col("down_count"),
        "limit_up": col("limit_up"),
        "limit_down": col("limit_down"),
        "max_streak": col("max_streak"),
        "total_amount": col("total_amount"),
        "amount_ratio": col("amount_ratio"),
        "median_pct": col("median_pct"),
        "margin_balance": col("margin_balance"),
        "north_net": col("north_net"),
        "factor_scores": {c: [None if pd.isna(v) else round(float(v), 0)
                              for v in factor_scores[c].tail(len(view))]
                          for c in factor_scores},
        "latest": latest,
    }
