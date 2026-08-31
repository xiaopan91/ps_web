"""任务执行器 + 内置调度器。

- run_task：子进程执行注册表脚本，日志落盘 logs/tasks/，状态写 task_run
- 串行单任务：运行中再触发抛 TaskBusyError（HTTP 层转 409）
- scheduler_loop：FastAPI lifespan 启动的守护线程，每 30 秒检查定时规则；
  命中条件 = 启用 + 今日未跑 + 当前在「计划时刻起 30 分钟窗口」内 + 空闲
  （窗口机制兼顾服务停机错过后的补跑）
"""
import json
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import select, update

from app.database import Base, SessionLocal, engine
from app.models.task import TaskRun, TaskSchedule
from app.task_registry import SCRIPTS_DIR, TASK_INDEX

LOG_DIR = Path(__file__).resolve().parent.parent / "logs" / "tasks"
LOG_DIR.mkdir(parents=True, exist_ok=True)


class TaskBusyError(Exception):
    """已有任务在运行。"""


def _build_argv(task, params):
    """按参数 schema 组命令行；缺失必填参数抛 ValueError。"""
    argv = [sys.executable, str(SCRIPTS_DIR / task["script"]), *task["args"]]
    for p in task["params"]:
        v = params.get(p["key"])
        if p.get("positional"):
            if v not in (None, ""):
                argv.append(str(v))
            continue
        if v not in (None, ""):
            argv.extend([p["flag"], str(v)])
        elif p.get("required"):
            raise ValueError(f"缺少必填参数：{p['label']}")
    return argv


def run_task(task_id, params=None, trigger="manual"):
    """启动任务（非阻塞），返回运行记录 id。"""
    task = TASK_INDEX.get(task_id)
    if not task:
        raise ValueError(f"未知任务: {task_id}")
    params = params or {}
    argv = _build_argv(task, params)  # 校验必填参数

    with _lock:
        if _current["proc"] is not None:
            raise TaskBusyError(f"任务「{_current['name']}」正在运行，请稍后再试")
        db = SessionLocal()
        run = TaskRun(task_id=task_id, task_name=task["name"],
                      params=params, status="running", trigger=trigger,
                      started_at=datetime.now())
        db.add(run)
        db.commit()
        run_id, started = run.id, run.started_at
        db.close()

        log_file = LOG_DIR / f"run_{run_id}.log"
        fh = open(log_file, "w", encoding="utf-8", errors="replace")
        proc = subprocess.Popen(argv, stdout=fh, stderr=subprocess.STDOUT,
                                 cwd=str(SCRIPTS_DIR.parent))
        _current.update(proc=proc, run_id=run_id, name=task["name"],
                        log_file=str(log_file), started=started)

    threading.Thread(target=_wait_done, args=(proc, run_id, log_file, fh),
                     daemon=True).start()
    return run_id


def _wait_done(proc, run_id, log_file, fh):
    code = proc.wait()
    fh.close()
    tail = _read_tail(log_file, 50)
    with _lock:
        _current.update(proc=None, run_id=None, name=None,
                        log_file=None, started=None)
    db = SessionLocal()
    run = db.get(TaskRun, run_id)
    run.exit_code = code
    run.status = "success" if code == 0 else "failed"
    run.finished_at = datetime.now()
    run.duration_s = int((run.finished_at - run.started_at).total_seconds())
    run.log_tail = tail
    db.commit()
    db.close()


def _read_tail(log_file, n=50):
    try:
        lines = Path(log_file).read_text(encoding="utf-8",
                                         errors="replace").splitlines()
        return "\n".join(lines[-n:])
    except OSError:
        return ""


def current():
    """当前运行中的任务（含实时日志尾部），空闲返回 None。"""
    with _lock:
        cur = dict(_current)
    if cur["proc"] is None:
        return None
    elapsed = int((datetime.now() - cur["started"]).total_seconds())
    return {"run_id": cur["run_id"], "name": cur["name"],
            "elapsed_s": elapsed, "log_tail": _read_tail(cur["log_file"], 30)}


def read_log(run_id, tail=None):
    """读运行日志全文或末尾 N 行。"""
    db = SessionLocal()
    run = db.get(TaskRun, run_id)
    db.close()
    if not run or not run.log_file:
        return None
    path = Path(run.log_file)
    if not path.exists():
        return run.log_tail or ""
    text = path.read_text(encoding="utf-8", errors="replace")
    if tail:
        return "\n".join(text.splitlines()[-tail:])
    return text


def cleanup_orphans():
    """应用启动时把遗留 running 记录标记为失败（服务重启导致中断）。"""
    Base.metadata.create_all(engine)  # 幂等建表
    db = SessionLocal()
    db.execute(update(TaskRun)
               .where(TaskRun.status == "running")
               .values(status="failed", exit_code=-1,
                       finished_at=datetime.now(),
                       log_tail="服务重启导致中断"))
    db.commit()
    db.close()


# ---------------------------------------------------------------- 调度器

_lock = threading.Lock()
_current = {"proc": None, "run_id": None, "name": None,
            "log_file": None, "started": None}


def _tick():
    now = datetime.now()
    db = SessionLocal()
    try:
        rules = db.execute(select(TaskSchedule)
                           .where(TaskSchedule.enabled == 1)).scalars().all()
        for sch in rules:
            try:
                weekdays = {int(x) for x in sch.weekdays.split(",")}
            except ValueError:
                continue
            if now.isoweekday() not in weekdays:
                continue
            sched_at = now.replace(hour=sch.run_time.hour,
                                   minute=sch.run_time.minute,
                                   second=0, microsecond=0)
            if not (sched_at <= now <= sched_at + timedelta(minutes=30)):
                continue  # 不在触发窗口
            if sch.last_run_at and sch.last_run_at.date() == now.date():
                continue  # 今日已跑
            if _current["proc"] is not None:
                continue  # 有任务在跑（下次 tick 若仍在窗口内会补）
            try:
                run_task(sch.task_id, sch.params or {}, trigger="schedule")
                sch.last_run_at = now
                db.commit()
                print(f"[scheduler] 定时触发 {sch.task_name} "
                      f"({now:%H:%M})", flush=True)
            except Exception as exc:
                print(f"[scheduler] 触发失败 {sch.task_id}: {exc}",
                      flush=True)
    finally:
        db.close()


def scheduler_loop():
    while True:
        try:
            _tick()
        except Exception as exc:  # 调度线程永不退出
            print(f"[scheduler] tick 异常: {exc}", flush=True)
        time.sleep(30)
