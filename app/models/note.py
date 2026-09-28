"""通用笔记：可挂载到任意实体（小模块/个股/指数/ETF...）。

scope  = 实体类型（fin_sub=理财小模块，预留 stock/index/etf 等）
scope_key = 实体标识（小模块名 / ts_code / 板块代码 ...）
content 存超文本（HTML），服务端做基础净化（去脚本与事件属性）。
"""
from datetime import datetime

from sqlalchemy import Column, DateTime, Index, Integer, String, Text

from app.database import Base


class Note(Base):
    __tablename__ = "note"
    __table_args__ = (Index("ix_note_scope_key", "scope", "scope_key"),
                      {"comment": "通用超文本笔记（按 scope+scope_key 挂载到任意实体）"})

    id = Column(Integer, primary_key=True, autoincrement=True, comment="笔记ID")
    scope = Column(String(30), nullable=False, comment="实体类型（fin_sub/stock/index/etf...）")
    scope_key = Column(String(100), nullable=False, comment="实体标识（小模块名/ts_code 等）")
    title = Column(String(100), default="", comment="标题")
    content = Column(Text, comment="内容（超文本 HTML）")
    created_at = Column(DateTime, default=datetime.now, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, comment="更新时间")
