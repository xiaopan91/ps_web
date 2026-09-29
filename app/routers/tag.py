"""个股标签接口：标签清单（含使用数）、个股打标/摘标、标签删除。

打标时标签不存在则自动创建（自定义新增与从旧标签选择二合一）。
"""
from datetime import datetime

import pandas as pd
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

from app.database import engine

router = APIRouter(prefix="/api/tags", tags=["tags"])


class TagIn(BaseModel):
    name: str


@router.get("")
def all_tags():
    """全部标签（按使用数降序、同名次按名称），供选择列表。"""
    df = pd.read_sql(text(
        "SELECT t.id, t.name, COUNT(s.ts_code) AS count "
        "FROM tag t LEFT JOIN stock_tag s ON s.tag_id = t.id "
        "GROUP BY t.id, t.name ORDER BY count DESC, t.name"), engine)
    return [{"id": int(r.id), "name": r.name, "count": int(r.count)}
            for r in df.itertuples()]


@router.get("/stock/{ts_code}")
def stock_tags(ts_code: str):
    df = pd.read_sql(text(
        "SELECT t.id, t.name FROM stock_tag s JOIN tag t ON t.id = s.tag_id "
        "WHERE s.ts_code = :c ORDER BY t.name"), engine, params={"c": ts_code})
    return [{"id": int(r.id), "name": r.name} for r in df.itertuples()]


@router.post("/stock/{ts_code}")
def add_stock_tag(ts_code: str, body: TagIn):
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "标签名不能为空")
    if len(name) > 30:
        raise HTTPException(400, "标签名最长 30 字")
    with engine.begin() as conn:
        tag_id = conn.execute(text(
            "SELECT id FROM tag WHERE name = :n"), {"n": name}).scalar()
        if not tag_id:
            tag_id = conn.execute(text(
                "INSERT INTO tag (name, created_at) VALUES (:n, :t)"),
                {"n": name, "t": datetime.now()}).lastrowid
        conn.execute(text(
            "INSERT IGNORE INTO stock_tag (ts_code, tag_id, created_at) VALUES (:c, :i, :t)"),
            {"c": ts_code, "i": tag_id, "t": datetime.now()})
    return {"ok": True, "id": int(tag_id), "name": name}


@router.delete("/stock/{ts_code}/{tag_id}")
def remove_stock_tag(ts_code: str, tag_id: int):
    with engine.begin() as conn:
        n = conn.execute(text(
            "DELETE FROM stock_tag WHERE ts_code = :c AND tag_id = :i"),
            {"c": ts_code, "i": tag_id}).rowcount
    if not n:
        raise HTTPException(404, "该标的没有此标签")
    return {"ok": True}


@router.delete("/{tag_id}")
def del_tag(tag_id: int):
    """删除标签本身（同时清除所有标的上的该标签）。"""
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM stock_tag WHERE tag_id = :i"), {"i": tag_id})
        n = conn.execute(text("DELETE FROM tag WHERE id = :i"), {"i": tag_id}).rowcount
    if not n:
        raise HTTPException(404, "标签不存在")
    return {"ok": True}
