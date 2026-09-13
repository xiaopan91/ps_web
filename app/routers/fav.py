"""个股收藏接口：分组管理 + 多对多成员归属。

无外键（与库内惯例一致），删组时手动级联删成员。
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, text

from app.database import SessionLocal
from app.models.stock_group import StockGroup, StockGroupMember

router = APIRouter(prefix="/api/fav", tags=["fav"])


class GroupIn(BaseModel):
    name: str


class MemberIn(BaseModel):
    group_id: int
    ts_code: str


def _member_snapshot():
    """全部分组成员拼上 stock_basic 名称/行业 + 最新收盘/涨跌幅。"""
    db = SessionLocal()
    rows = db.execute(text(
        "SELECT m.group_id, m.ts_code, b.name, b.industry, "
        "       d.close, d.pct_chg, m.added_at "
        "FROM stock_group_member m "
        "LEFT JOIN stock_basic b ON b.ts_code = m.ts_code "
        "LEFT JOIN daily_bar d ON d.ts_code = m.ts_code "
        "  AND d.trade_date = (SELECT MAX(trade_date) FROM daily_bar) "
        "ORDER BY m.group_id, m.added_at, m.ts_code")).fetchall()
    db.close()
    out = {}
    for r in rows:
        out.setdefault(r.group_id, []).append({
            "ts_code": r.ts_code,
            "name": r.name if isinstance(r.name, str) else r.ts_code,
            "industry": r.industry if isinstance(r.industry, str) else None,
            "close": None if r.close is None else float(r.close),
            "pct_chg": None if r.pct_chg is None else float(r.pct_chg),
        })
    return out


@router.get("/groups")
def list_groups():
    """全部分组及成员（含行情快照）。"""
    snap = _member_snapshot()
    db = SessionLocal()
    groups = db.execute(select(StockGroup).order_by(StockGroup.id)).scalars().all()
    db.close()
    return [{"id": g.id, "name": g.name, "count": len(snap.get(g.id, [])),
             "members": snap.get(g.id, [])} for g in groups]


@router.post("/groups")
def add_group(body: GroupIn):
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "分组名不能为空")
    db = SessionLocal()
    dup = db.execute(select(StockGroup).where(StockGroup.name == name)).scalar_one_or_none()
    if dup:
        db.close()
        raise HTTPException(409, f"分组已存在: {name}")
    g = StockGroup(name=name)
    db.add(g)
    db.commit()
    result = {"id": g.id, "name": g.name, "count": 0, "members": []}
    db.close()
    return result


@router.patch("/groups/{gid}")
def rename_group(gid: int, body: GroupIn):
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "分组名不能为空")
    db = SessionLocal()
    g = db.get(StockGroup, gid)
    if not g:
        db.close()
        raise HTTPException(404, "分组不存在")
    dup = db.execute(select(StockGroup).where(
        StockGroup.name == name, StockGroup.id != gid)).scalar_one_or_none()
    if dup:
        db.close()
        raise HTTPException(409, f"分组已存在: {name}")
    g.name = name
    db.commit()
    result = {"id": g.id, "name": g.name}
    db.close()
    return result


@router.delete("/groups/{gid}")
def del_group(gid: int):
    db = SessionLocal()
    g = db.get(StockGroup, gid)
    if not g:
        db.close()
        raise HTTPException(404, "分组不存在")
    db.execute(text("DELETE FROM stock_group_member WHERE group_id = :g"), {"g": gid})
    db.delete(g)
    db.commit()
    db.close()
    return {"ok": True}


@router.post("/members")
def add_member(body: MemberIn):
    db = SessionLocal()
    if not db.get(StockGroup, body.group_id):
        db.close()
        raise HTTPException(404, "分组不存在")
    dup = db.get(StockGroupMember, (body.group_id, body.ts_code))
    if not dup:
        db.add(StockGroupMember(group_id=body.group_id, ts_code=body.ts_code))
        db.commit()
    db.close()
    return {"ok": True}  # 幂等：已存在视为成功


@router.delete("/members/{group_id}/{ts_code}")
def del_member(group_id: int, ts_code: str):
    db = SessionLocal()
    m = db.get(StockGroupMember, (group_id, ts_code))
    if m:
        db.delete(m)
        db.commit()
    db.close()
    return {"ok": True}  # 幂等：不存在视为成功


@router.get("/stock_groups")
def stock_groups(code: str):
    """某股的分组归属：全部分组 + belongs 标记（星标弹层用）。"""
    db = SessionLocal()
    groups = db.execute(select(StockGroup).order_by(StockGroup.id)).scalars().all()
    members = {m.group_id for m in db.execute(
        select(StockGroupMember).where(StockGroupMember.ts_code == code)).scalars().all()}
    db.close()
    return {"code": code, "groups": [
        {"id": g.id, "name": g.name, "belongs": g.id in members} for g in groups]}
