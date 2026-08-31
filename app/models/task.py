"""任务中心：运行历史与定时规则。"""
from sqlalchemy import JSON, Column, DateTime, Integer, String, Text, Time
from sqlalchemy.dialects.mysql import LONGTEXT

from app.database import Base


class TaskRun(Base):
    __tablename__ = "task_run"
    __table_args__ = {"comment": "任务运行历史（手动/定时触发的脚本执行记录）"}

    id = Column(Integer, primary_key=True, autoincrement=True, comment="运行ID")
    task_id = Column(String(32), comment="任务标识（注册表 id）")
    task_name = Column(String(64), comment="任务名称（冗余，便于展示）")
    params = Column(JSON, comment="运行参数（JSON）")
    status = Column(String(16), comment="状态（running/success/failed）")
    trigger = Column(String(16), comment="触发方式（manual=手动 schedule=定时）")
    exit_code = Column(Integer, comment="进程退出码（0=正常）")
    log_file = Column(String(255), comment="全量日志文件路径(logs/tasks/)")
    log_tail = Column(LONGTEXT, comment="日志末尾（快速预览用）")
    started_at = Column(DateTime, comment="开始时间")
    finished_at = Column(DateTime, comment="结束时间")
    duration_s = Column(Integer, comment="耗时（秒）")


class TaskSchedule(Base):
    __tablename__ = "task_schedule"
    __table_args__ = {"comment": "定时执行规则（内置调度线程每30秒检查）"}

    id = Column(Integer, primary_key=True, autoincrement=True, comment="规则ID")
    task_id = Column(String(32), comment="任务标识（注册表 id）")
    task_name = Column(String(64), comment="任务名称（冗余）")
    params = Column(JSON, comment="运行参数（JSON）")
    run_time = Column(Time, comment="计划时间（HH:MM）")
    weekdays = Column(String(20), comment="星期几（1=周一…7=周日，逗号分隔）")
    enabled = Column(Integer, comment="是否启用（1/0）")
    last_run_at = Column(DateTime, comment="最近触发时间（防当日重复）")
    note = Column(String(255), comment="备注")
