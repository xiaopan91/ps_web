"""通用笔记接口：GET/POST/PUT/DELETE，按 scope+key 挂载。

内容为超文本（HTML）。入库前做基础净化：移除 <script>/<style>/<iframe> 等
危险标签、on* 事件属性与 javascript: 链接（个人单用户场景下的基础防线）。
"""
import re
from datetime import datetime

import pandas as pd
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

from app.database import engine

router = APIRouter(prefix="/api/notes", tags=["notes"])

SCOPES = {"fin_sub", "stock", "index", "etf", "board"}   # 预留扩展：个股/指数/ETF/板块

_DANGER_BLOCK = re.compile(r"<\s*/?\s*(script|style|iframe|object|embed|form|link|meta)\b[^>]*>",
                           re.IGNORECASE)
_ON_ATTR = re.compile(r"\son\w+\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", re.IGNORECASE)
_JS_URL = re.compile(r"(href|src)\s*=\s*(\"|')\s*(javascript|vbscript|data):[^\"']*(\"|')",
                     re.IGNORECASE)


def sanitize_html(html: str) -> str:
    if not html:
        return ""
    html = _DANGER_BLOCK.sub("", html)
    html = _ON_ATTR.sub("", html)
    html = _JS_URL.sub(r"\1=\"#\"", html)
    return html


class NoteIn(BaseModel):
    scope: str
    key: str
    title: str = ""
    content: str = ""


def _row(r) -> dict:
    return {"id": int(r.id), "scope": r.scope, "key": r.scope_key,
            "title": r.title or "", "content": r.content or "",
            "updated_at": str(r.updated_at or r.created_at or "")}


@router.get("")
def list_notes(scope: str, key: str):
    """某实体下的笔记列表（按更新时间倒序）。"""
    if scope not in SCOPES:
        raise HTTPException(400, f"scope 取值: {sorted(SCOPES)}")
    df = pd.read_sql(text(
        "SELECT id, scope, scope_key, title, content, created_at, updated_at FROM note "
        "WHERE scope = :s AND scope_key = :k ORDER BY updated_at DESC, id DESC"),
        engine, params={"s": scope, "k": key})
    return [_row(r) for r in df.itertuples()]


@router.post("")
def add_note(body: NoteIn):
    if body.scope not in SCOPES:
        raise HTTPException(400, f"scope 取值: {sorted(SCOPES)}")
    if not body.key.strip():
        raise HTTPException(400, "key 不能为空")
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO note (scope, scope_key, title, content, created_at, updated_at) "
            "VALUES (:s, :k, :t, :c, :at, :at)"),
            {"s": body.scope, "k": body.key.strip(),
             "t": body.title.strip()[:100], "c": sanitize_html(body.content),
             "at": datetime.now()})
    return {"ok": True}


@router.put("/{note_id}")
def update_note(note_id: int, body: NoteIn):
    with engine.begin() as conn:
        n = conn.execute(text("UPDATE note SET title = :t, content = :c, updated_at = :at "
                              "WHERE id = :i"),
                         {"t": body.title.strip()[:100], "c": sanitize_html(body.content),
                          "at": datetime.now(), "i": note_id}).rowcount
    if not n:
        raise HTTPException(404, "笔记不存在")
    return {"ok": True}


@router.delete("/{note_id}")
def del_note(note_id: int):
    with engine.begin() as conn:
        n = conn.execute(text("DELETE FROM note WHERE id = :i"), {"i": note_id}).rowcount
    if not n:
        raise HTTPException(404, "笔记不存在")
    return {"ok": True}
