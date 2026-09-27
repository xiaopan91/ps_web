"""个人理财接口：资产快照录入/删除 + 定期回顾聚合分析。

净资产 = Σ(资产类分类) − Σ(负债类分类，金额记正数)。
"""
from datetime import date, datetime

import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

from app.database import engine
from app.models.finance import CATEGORIES, DEBT_CATEGORIES

router = APIRouter(prefix="/api/fin", tags=["finance"])


class SnapshotIn(BaseModel):
    snap_date: str   # YYYY-MM-DD
    category: str
    amount: float
    note: str = ""


@router.get("/categories")
def categories():
    return CATEGORIES


@router.get("/snapshots")
def list_snapshots():
    df = pd.read_sql(text(
        "SELECT id, snap_date, category, amount, note, created_at FROM fin_snapshot "
        "ORDER BY snap_date DESC, id DESC"), engine)
    return [{
        "id": int(r.id),
        "snap_date": pd.Timestamp(r.snap_date).strftime("%Y-%m-%d"),
        "category": r.category,
        "amount": round(float(r.amount), 2),
        "note": r.note or "",
        "created_at": pd.Timestamp(r.created_at).strftime("%Y-%m-%d %H:%M")
        if r.created_at else None,
    } for r in df.itertuples()]


@router.post("/snapshots")
def add_snapshot(body: SnapshotIn):
    if body.category not in CATEGORIES:
        raise HTTPException(400, f"分类须为 {CATEGORIES}")
    try:
        d = datetime.strptime(body.snap_date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(400, "日期格式应为 YYYY-MM-DD")
    if not np.isfinite(body.amount) or body.amount == 0:
        raise HTTPException(400, "金额不能为 0")
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO fin_snapshot (snap_date, category, amount, note, created_at) "
            "VALUES (:d, :c, :a, :n, :t)"),
            {"d": d, "c": body.category, "a": round(body.amount, 2),
             "n": body.note.strip() or None, "t": datetime.now()})
    return {"ok": True}


@router.delete("/snapshots/{sid}")
def del_snapshot(sid: int):
    with engine.begin() as conn:
        n = conn.execute(text("DELETE FROM fin_snapshot WHERE id = :i"), {"i": sid}).rowcount
    if not n:
        raise HTTPException(404, "记录不存在")
    return {"ok": True}


@router.get("/summary")
def summary():
    """按快照日期聚合：净资产序列、最新配置、月度变化。"""
    df = pd.read_sql(text(
        "SELECT snap_date, category, amount FROM fin_snapshot"), engine)
    if df.empty:
        return {"dates": [], "net": [], "assets": [], "debt": [],
                "alloc_date": None, "alloc": [],
                "monthly": [], "categories": CATEGORIES}
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce")
    df = df.dropna(subset=["amount"])
    df["snap_date"] = pd.to_datetime(df["snap_date"]).dt.date
    df["is_debt"] = df["category"].isin(DEBT_CATEGORIES)

    g = df.groupby(["snap_date", "category"])["amount"].sum().reset_index()
    g["is_debt"] = g["category"].isin(DEBT_CATEGORIES)
    g["signed"] = np.where(g["is_debt"], -g["amount"], g["amount"])

    daily = g.groupby("snap_date").agg(
        net=("signed", "sum"),
        assets=("signed", lambda s: s[s > 0].sum()),
        debt=("signed", lambda s: -s[s < 0].sum()),
    ).reset_index().sort_values("snap_date")
    # 同日多次录入天然聚合；不同分类同日合并为一个快照点
    alloc = (g[g["snap_date"] == g["snap_date"].max()]
             .sort_values("amount", ascending=False))
    monthly = daily.copy()
    monthly["month"] = monthly["snap_date"].map(lambda d: d.strftime("%Y-%m"))
    monthly = monthly.groupby("month")["net"].last().reset_index()
    monthly["net"] = monthly["net"].round(2)
    monthly["chg"] = monthly["net"].diff()
    # 含 None 的列表赋回 DataFrame 浮点列会被强转回 NaN，None 转换必须在 to_dict 之后
    monthly_records = monthly.to_dict("records")
    for r in monthly_records:
        r["chg"] = None if pd.isna(r["chg"]) else round(float(r["chg"]), 2)

    return {
        "dates": [d.isoformat() for d in daily["snap_date"]],
        "net": [round(float(v), 2) for v in daily["net"]],
        "assets": [round(float(v), 2) for v in daily["assets"]],
        "debt": [round(float(v), 2) for v in daily["debt"]],
        "alloc_date": daily["snap_date"].iloc[-1].isoformat(),
        "alloc": [{"category": r.category, "amount": round(float(r.amount), 2)}
                  for r in alloc.itertuples()],
        "monthly": monthly_records,
        "categories": CATEGORIES,
    }
