"""报警接口：规则 CRUD、历史、渠道配置、测试发送、手动评估。"""
import json
from datetime import datetime

import pandas as pd
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

from app.alert_engine import RULE_LABELS, _config, _save_config, evaluate_all, send_serverchan
from app.database import engine

router = APIRouter(prefix="/api/alerts", tags=["alerts"])

VALID_TARGETS = {"stock", "etf", "index", "index_ext"}


class RuleIn(BaseModel):
    name: str = ""
    target_type: str
    ts_code: str
    rule_type: str
    params: dict = {}
    enabled: bool = True
    one_shot: bool = False
    note: str = ""


def _rule_row(r) -> dict:
    return {"id": int(r.id), "name": r.name or "", "target_type": r.target_type,
            "ts_code": r.ts_code, "rule_type": r.rule_type,
            "params": json.loads(r.params) if isinstance(r.params, str) else (r.params or {}),
            "enabled": int(r.enabled or 0), "one_shot": int(r.one_shot or 0),
            "last_triggered_date": str(r.last_triggered_date) if r.last_triggered_date else None,
            "note": r.note or ""}


@router.get("/rule_types")
def rule_types():
    """规则类型清单（前端动态表单用）。"""
    return [{"type": k, "label": v} for k, v in RULE_LABELS.items()]


@router.get("/rules")
def list_rules():
    df = pd.read_sql(text(
        "SELECT * FROM alert_rule ORDER BY enabled DESC, id DESC"), engine)
    return [_rule_row(r) for r in df.itertuples()]


@router.post("/rules")
def add_rule(body: RuleIn):
    _check(body)
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO alert_rule (name, target_type, ts_code, rule_type, params, "
            "enabled, one_shot, note, created_at) "
            "VALUES (:n, :tt, :c, :rt, :p, :e, :os, :note, :at)"),
            {"n": body.name.strip(), "tt": body.target_type, "c": body.ts_code.strip(),
             "rt": body.rule_type, "p": json.dumps(body.params),
             "e": 1 if body.enabled else 0, "os": 1 if body.one_shot else 0,
             "note": body.note.strip() or None, "at": datetime.now()})
    return {"ok": True}


def _check(body: RuleIn):
    if body.target_type not in VALID_TARGETS:
        raise HTTPException(400, f"target_type 须为 {sorted(VALID_TARGETS)}")
    if not body.ts_code.strip():
        raise HTTPException(400, "ts_code 不能为空")
    if body.rule_type not in RULE_LABELS:
        raise HTTPException(400, f"rule_type 须为 {sorted(RULE_LABELS)}")


@router.put("/rules/{rule_id}")
def update_rule(rule_id: int, body: RuleIn):
    _check(body)
    with engine.begin() as conn:
        n = conn.execute(text(
            "UPDATE alert_rule SET name = :n, target_type = :tt, ts_code = :c, "
            "rule_type = :rt, params = :p, enabled = :e, one_shot = :os, note = :note "
            "WHERE id = :i"),
            {"n": body.name.strip(), "tt": body.target_type, "c": body.ts_code.strip(),
             "rt": body.rule_type, "p": json.dumps(body.params),
             "e": 1 if body.enabled else 0, "os": 1 if body.one_shot else 0,
             "note": body.note.strip() or None, "i": rule_id}).rowcount
    if not n:
        raise HTTPException(404, "规则不存在")
    return {"ok": True}


@router.patch("/rules/{rule_id}/enabled")
def toggle_rule(rule_id: int, body: dict):
    with engine.begin() as conn:
        n = conn.execute(text("UPDATE alert_rule SET enabled = :e WHERE id = :i"),
                         {"e": 1 if body.get("enabled") else 0, "i": rule_id}).rowcount
    if not n:
        raise HTTPException(404, "规则不存在")
    return {"ok": True}


@router.delete("/rules/{rule_id}")
def del_rule(rule_id: int):
    with engine.begin() as conn:
        n = conn.execute(text("DELETE FROM alert_rule WHERE id = :i"), {"i": rule_id}).rowcount
    if not n:
        raise HTTPException(404, "规则不存在")
    return {"ok": True}


@router.get("/history")
def history(limit: int = 100):
    df = pd.read_sql(text(
        "SELECT id, rule_id, ts_code, name, trade_date, rule_type, message, notified, created_at "
        f"FROM alert_log ORDER BY id DESC LIMIT :l"), engine, params={"l": min(limit, 500)})
    return [{"id": int(r.id), "rule_id": int(r.rule_id or 0), "ts_code": r.ts_code,
             "name": r.name, "trade_date": str(r.trade_date), "rule_type": r.rule_type,
             "message": r.message, "notified": int(r.notified or 0),
             "created_at": str(r.created_at)} for r in df.itertuples()]


@router.get("/config")
def get_config():
    return _config()


@router.put("/config")
def put_config(body: dict):
    _save_config({"serverchan_key": (body.get("serverchan_key") or "").strip()})
    return {"ok": True}


@router.post("/test")
def test_push():
    key = _config()["serverchan_key"].strip()
    if not key:
        raise HTTPException(400, "请先保存 Server酱 SendKey（sct.ftqq.com 免费获取）")
    ok = send_serverchan("ps_web 报警测试", "这是一条测试消息，收到即通知渠道配置成功。")
    if not ok:
        raise HTTPException(502, "推送失败：请检查 SendKey 是否正确")
    return {"ok": True}


@router.post("/evaluate")
def evaluate(body: dict = None):
    force = bool((body or {}).get("force"))
    return evaluate_all(force=force)
