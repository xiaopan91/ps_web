"""北向资金/成交额 因子接口（宏观预测模块）。

因子定义：north_ratio = 北向净买入 ÷ 两市总成交额（无量纲，展示为 bp 万分之）。
数据源：market_sentiment 日表（north_net 万元、total_amount 元），
由每日 18:00「每日增量更新」任务自动刷新。
"""
import pandas as pd
from fastapi import APIRouter, Query
from sqlalchemy import text

from app.database import engine
from app.routers.sentiment import _rolling_pct

router = APIRouter(prefix="/api/north", tags=["north"])

DAYS = {"90": 90, "250": 250, "750": 750}


@router.get("/overview")
def overview(days: str = Query(default="250")):
    """当日因子值 + 历史序列（北向、成交额、比值及其滚动分位、上证）。"""
    df = pd.read_sql(text(
        "SELECT trade_date, north_net, total_amount, sh_pct FROM market_sentiment "
        "ORDER BY trade_date"), engine)
    df = df.dropna(subset=["north_net", "total_amount"]).reset_index(drop=True)
    if df.empty:
        return {"dates": [], "latest": None}

    df["north_yi"] = df["north_net"].astype(float) / 1e4      # 万元 → 亿元
    df["amount_yi"] = df["total_amount"].astype(float) / 1e8  # 元 → 亿元
    # 北向净买入(万元)×1e8÷成交额(元) = 无量纲比 ×1e4 = bp（万分之）
    df["ratio_bp"] = df["north_net"].astype(float) * 1e8 / df["total_amount"].astype(float)
    # 滚动 3 年分位（与情绪分同口径：750 日窗、最少 120 日）
    df["pctile"] = _rolling_pct(df["ratio_bp"]).mul(100)

    sh = pd.read_sql(text(
        "SELECT trade_date, close FROM index_daily WHERE ts_code='000001.SH' "
        "ORDER BY trade_date"), engine)
    df = df.merge(sh, on="trade_date", how="left")
    df["trade_date"] = df["trade_date"].astype(str)

    n = DAYS.get(days)
    view = df if n is None else df.tail(n)

    def col(name, digits=None):
        out = []
        for v in view[name]:
            if v is None or pd.isna(v):
                out.append(None)
            else:
                out.append(round(float(v), digits) if digits is not None else float(v))
        return out

    last, prev = df.iloc[-1], (df.iloc[-2] if len(df) > 1 else None)
    latest = {
        "trade_date": last["trade_date"],
        "north_yi": round(float(last["north_yi"]), 1),
        "amount_yi": round(float(last["amount_yi"]), 0),
        "ratio_bp": round(float(last["ratio_bp"]), 2),
        "pctile": None if pd.isna(last["pctile"]) else round(float(last["pctile"]), 0),
        "prev_ratio_bp": None if prev is None else round(float(prev["ratio_bp"]), 2),
        "sh_pct": None if pd.isna(last["sh_pct"]) else round(float(last["sh_pct"]), 2),
    }
    return {
        "dates": list(view["trade_date"]),
        "north_yi": col("north_yi", 1),
        "amount_yi": col("amount_yi", 0),
        "ratio_bp": col("ratio_bp", 2),
        "pctile": col("pctile", 0),
        "sh_close": col("close", 1),
        "latest": latest,
    }
