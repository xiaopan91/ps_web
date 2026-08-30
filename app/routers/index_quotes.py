"""指数行情接口：指数列表 + 指数日线（无复权概念）。"""
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db
from app.routers.stock import RANGE_DAYS

router = APIRouter(prefix="/api/index", tags=["index"])

# 与 scripts/sync_data.py 的 INDICES 对应
INDEX_NAMES = {
    "000001.SH": "上证指数", "399001.SZ": "深证成指", "000300.SH": "沪深300",
    "000905.SH": "中证500", "000852.SH": "中证1000", "399303.SZ": "国证2000",
    "000016.SH": "上证50", "000688.SH": "科创50", "399006.SZ": "创业板指",
    "399673.SZ": "创业板50", "399005.SZ": "中小100", "000015.SH": "上证红利",
    "399102.SZ": "创业板综",
}


@router.get("/list")
def list_indices(db: Session = Depends(get_db)):
    """库内已有的指数列表。"""
    rows = db.execute(text(
        "SELECT ts_code, MAX(trade_date) FROM index_daily GROUP BY ts_code"
    )).fetchall()
    return [{"ts_code": r[0], "name": INDEX_NAMES.get(r[0], r[0]),
             "latest_date": r[1].isoformat() if r[1] else None}
            for r in rows]


@router.get("/daily")
def daily(code: str, range: str = "1y", db: Session = Depends(get_db)):
    """指数日线（K线按点数，成交额按亿元）。"""
    if range not in RANGE_DAYS and range != "all":
        raise HTTPException(400, f"range 取值: {list(RANGE_DAYS) + ['all']}")
    if code not in INDEX_NAMES:
        raise HTTPException(404, f"未知指数代码: {code}")

    start = (date(1990, 1, 1) if range == "all"
             else date.today() - timedelta(days=RANGE_DAYS[range]))
    rows = db.execute(text(
        "SELECT trade_date, open, high, low, close, pct_chg, vol, amount "
        "FROM index_daily WHERE ts_code = :c AND trade_date >= :s "
        "ORDER BY trade_date"), {"c": code, "s": start}).fetchall()

    bars = [{"d": r[0].isoformat(),
             "o": float(r[1]), "h": float(r[2]), "l": float(r[3]),
             "c": float(r[4]), "pct": float(r[5]) if r[5] is not None else None,
             "v": (float(r[7]) / 1e5) if r[7] is not None else None}  # 成交额千元→亿元
            for r in rows]

    latest = None
    if bars:
        latest = {"trade_date": bars[-1]["d"], "close": bars[-1]["c"],
                  "pct": bars[-1]["pct"]}
    return {"info": {"ts_code": code, "name": INDEX_NAMES[code]},
            "latest": latest, "bars": bars}
