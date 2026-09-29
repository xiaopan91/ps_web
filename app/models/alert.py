"""每日报警：规则、触发记录、通知渠道配置。

- AlertRule：报警规则（标的 + 规则类型 + JSON 参数），可启停、可一次性
- AlertLog：触发记录（含推送状态），按日防重的依据
- AlertConfig：通知渠道配置（单行，id=1），当前支持 Server酱·微信
"""
from datetime import datetime

from sqlalchemy import JSON, Column, Date, DateTime, Index, Integer, String, Text

from app.database import Base


class AlertRule(Base):
    __tablename__ = "alert_rule"
    __table_args__ = (Index("ix_alert_rule_enabled", "enabled"),
                      {"comment": "报警规则（标的+规则类型+JSON参数）"})

    id = Column(Integer, primary_key=True, autoincrement=True, comment="规则ID")
    name = Column(String(60), default="", comment="规则备注名")
    target_type = Column(String(10), nullable=False, comment="标的类型（stock/etf/index）")
    ts_code = Column(String(16), nullable=False, comment="标的代码（如 600519.SH / 510300.SH / 000300.SH）")
    rule_type = Column(String(20), nullable=False, comment="规则类型（price_above/pct_up/new_high/...）")
    params = Column(JSON, default={}, comment="规则参数（如 {\"threshold\": 100}）")
    enabled = Column(Integer, default=1, comment="是否启用（1/0）")
    one_shot = Column(Integer, default=0, comment="触发一次后自动停用（1/0）")
    last_triggered_date = Column(Date, comment="最近触发日期")
    note = Column(String(100), comment="说明")
    created_at = Column(DateTime, default=datetime.now, comment="创建时间")


class AlertLog(Base):
    __tablename__ = "alert_log"
    __table_args__ = (Index("ix_alert_log_date", "trade_date"),
                      {"comment": "报警触发记录（按日防重的依据）"})

    id = Column(Integer, primary_key=True, autoincrement=True, comment="记录ID")
    rule_id = Column(Integer, comment="规则ID（规则删除后保留记录）")
    ts_code = Column(String(16), comment="标的代码")
    name = Column(String(50), comment="标的名称")
    trade_date = Column(Date, comment="触发数据日期")
    rule_type = Column(String(20), comment="规则类型")
    message = Column(Text, comment="报警内容")
    notified = Column(Integer, default=0, comment="微信推送是否成功（1/0）")
    created_at = Column(DateTime, default=datetime.now, comment="触发时间")


class AlertConfig(Base):
    __tablename__ = "alert_config"
    __table_args__ = {"comment": "通知渠道配置（单行 id=1）"}

    id = Column(Integer, primary_key=True, comment="固定为 1")
    serverchan_key = Column(String(100), default="", comment="Server酱 SendKey（sct.ftqq.com 获取）")
    last_eval_date = Column(Date, comment="上次评估运行日（当日防重，与数据日期无关）")
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, comment="更新时间")
