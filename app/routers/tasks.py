"""任务中心接口：任务清单 / 运行 / 历史 / 日志 / 定时规则。"""
import json
from datetime import datetime, time as dt_time
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from app.database import SessionLocal
from app.models.task import TaskRun, TaskSchedule
from app.task_registry import TASKS, TASK_INDEX
from app.task_runner import (TaskBusyError, current, read_log, run_task)

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@router.get("")
def list_tasks():
    """任务注册表（含参数 schema）。"""
    return TASKS


@router.get("/current")
def current_task():
    return current()


@router.post("/{task_id}/run")
def run(task_id: str, body: dict = None):
    body = body or {}
    try:
        run_id = run_task(task_id, body.get("params", {}), trigger="manual")
        return {"run_id": run_id}
    except TaskBusyError as exc:
        raise HTTPException(409, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.get("/runs")
def runs(limit: int = 50):
    db = SessionLocal()
    rows = db.execute(select(TaskRun).order_by(TaskRun.id.desc())
                      .limit(min(limit, 500))).scalars().all()
    db.close()
    return [{
        "id": r.id, "task_id": r.task_id, "task_name": r.task_name,
        "params": r.params, "status": r.status, "trigger": r.trigger,
        "exit_code": r.exit_code, "duration_s": r.duration_s,
        "started_at": r.started_at.strftime("%Y-%m-%d %H:%M:%S")
                      if r.started_at else None,
        "finished_at": r.finished_at.strftime("%Y-%m-%d %H:%M:%S")
                       if r.finished_at else None,
        "log_tail": (r.log_tail or "")[-2000:],
    } for r in rows]


@router.get("/runs/{run_id}/log")
def run_log(run_id: int, tail: Optional[int] = None):
    text = read_log(run_id, tail)
    if text is None:
        raise HTTPException(404, "运行记录不存在")
    return {"log": text}


# ---------------------------------------------------------------- 定时规则

class ScheduleIn(BaseModel):
    task_id: str
    run_time: str  # HH:MM
    weekdays: list[int]
    params: dict = {}
    note: str = ""


def _rule_out(s):
    return {"id": s.id, "task_id": s.task_id, "task_name": s.task_name,
            "params": s.params, "run_time": s.run_time.strftime("%H:%M"),
            "weekdays": [int(x) for x in s.weekdays.split(",")],
            "enabled": bool(s.enabled),
            "last_run_at": s.last_run_at.strftime("%Y-%m-%d %H:%M")
                           if s.last_run_at else None,
            "note": s.note}


@router.get("/schedules")
def list_schedules():
    db = SessionLocal()
    rows = db.execute(select(TaskSchedule).order_by(TaskSchedule.id)).scalars().all()
    db.close()
    return [_rule_out(s) for s in rows]


@router.post("/schedules")
def add_schedule(body: ScheduleIn):
    task = TASK_INDEX.get(body.task_id)
    if not task:
        raise HTTPException(400, f"未知任务: {body.task_id}")
    try:
        hh, mm = body.run_time.split(":")
        rt = dt_time(int(hh), int(mm))
    except ValueError:
        raise HTTPException(400, "时间格式应为 HH:MM")
    if not body.weekdays or not all(1 <= w <= 7 for w in body.weekdays):
        raise HTTPException(400, "weekdays 取值 1~7（1=周一）")
    db = SessionLocal()
    sch = TaskSchedule(task_id=task["id"], task_name=task["name"],
                       params=body.params, run_time=rt,
                       weekdays=",".join(str(w) for w in sorted(body.weekdays)),
                       enabled=1, note=body.note)
    db.add(sch)
    db.commit()
    result = _rule_out(sch)
    db.close()
    return result


@router.patch("/schedules/{sid}")
def patch_schedule(sid: int, body: dict):
    db = SessionLocal()
    sch = db.get(TaskSchedule, sid)
    if not sch:
        db.close()
        raise HTTPException(404, "规则不存在")
    if "enabled" in body:
        sch.enabled = 1 if body["enabled"] else 0
    if "note" in body:
        sch.note = body["note"]
    if "run_time" in body:
        try:
            hh, mm = body["run_time"].split(":")
            sch.run_time = dt_time(int(hh), int(mm))
        except ValueError:
            db.close()
            raise HTTPException(400, "时间格式应为 HH:MM")
    if "weekdays" in body:
        ws = body["weekdays"]
        if not isinstance(ws, list) or not ws or not all(1 <= int(w) <= 7 for w in ws):
            db.close()
            raise HTTPException(400, "weekdays 应为 1~7 的非空数组")
        sch.weekdays = ",".join(str(int(w)) for w in sorted(ws))
    db.commit()
    result = _rule_out(sch)
    db.close()
    return result


@router.delete("/schedules/{sid}")
def del_schedule(sid: int):
    db = SessionLocal()
    sch = db.get(TaskSchedule, sid)
    if not sch:
        db.close()
        raise HTTPException(404, "规则不存在")
    db.delete(sch)
    db.commit()
    db.close()
    return {"ok": True}
