"""个股数据接口：搜索 + 日线（含复权）。"""
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.stock import DailyResponse, SearchItem, StockInfo

router = APIRouter(prefix="/api/stock", tags=["stock"])

# range 预设对应的天数（自然日，足够覆盖对应交易天数）
RANGE_DAYS = {"3m": 95, "6m": 185, "1y": 370, "3y": 1100}
ADJUSTS = ("none", "qfq", "hfq")


@router.get("/search", response_model=list[SearchItem])
def search(q: str = Query(min_length=1), db: Session = Depends(get_db)):
    """按名称/代码模糊搜索在市股票。"""
    rows = db.execute(
        text(
            "SELECT ts_code, name, industry FROM stock_basic "
            "WHERE name LIKE :p OR ts_code LIKE :p OR symbol LIKE :p "
            "ORDER BY ts_code LIMIT 20"
        ),
        {"p": f"%{q}%"},
    ).fetchall()
    return [{"ts_code": r[0], "name": r[1], "industry": r[2]} for r in rows]


@router.get("/daily", response_model=DailyResponse)
def daily(
    code: str,
    range: str = "1y",
    adjust: str = "qfq",
    db: Session = Depends(get_db),
):
    """个股日线。adjust: none 不复权 / qfq 前复权（锚定最新价）/ hfq 后复权。"""
    if range not in RANGE_DAYS and range != "all":
        raise HTTPException(400, f"range 取值: {list(RANGE_DAYS) + ['all']}")
    if adjust not in ADJUSTS:
        raise HTTPException(400, f"adjust 取值: {list(ADJUSTS)}")

    info_row = db.execute(
        text(
            "SELECT ts_code, name, industry, market, list_date "
            "FROM stock_basic WHERE ts_code = :c"
        ),
        {"c": code},
    ).fetchone()
    if not info_row:
        raise HTTPException(404, f"未知股票代码: {code}")

    start = (
        date(1990, 1, 1)
        if range == "all"
        else date.today() - timedelta(days=RANGE_DAYS[range])
    )
    rows = db.execute(
        text(
            "SELECT d.trade_date, d.open, d.high, d.low, d.close, d.vol, "
            "       d.amount, d.pct_chg, a.adj_factor "
            "FROM daily_bar d LEFT JOIN adj_factor a "
            "  ON a.ts_code = d.ts_code AND a.trade_date = d.trade_date "
            "WHERE d.ts_code = :c AND d.trade_date >= :s "
            "ORDER BY d.trade_date"
        ),
        {"c": code, "s": start},
    ).fetchall()

    # 前复权锚点：最新可用复权因子
    latest_adj = None
    for r in rows:
        if r.adj_factor is not None:
            latest_adj = float(r.adj_factor)

    bars = []
    for r in rows:
        adj = float(r.adj_factor) if r.adj_factor is not None else None
        if adjust == "none" or adj is None or latest_adj in (None, 0):
            factor = 1.0
        elif adjust == "hfq":
            factor = adj
        else:  # qfq
            factor = adj / latest_adj
        bars.append(
            {
                "d": r.trade_date.isoformat(),
                "o": float(r.open) * factor,
                "h": float(r.high) * factor,
                "l": float(r.low) * factor,
                "c": float(r.close) * factor,
                "v": float(r.vol) if r.vol is not None else None,
                "amount": float(r.amount) if r.amount is not None else None,
                "pct": float(r.pct_chg) if r.pct_chg is not None else None,
            }
        )

    latest = None
    if bars:
        last = bars[-1]
        latest = {
            "trade_date": last["d"],
            "close": last["c"],
            "pct": last["pct"],
        }

    return {
        "info": {
            "ts_code": info_row[0],
            "name": info_row[1],
            "industry": info_row[2],
            "market": info_row[3],
            "list_date": info_row[4].isoformat() if info_row[4] else None,
        },
        "latest": latest,
        "bars": bars,
    }
