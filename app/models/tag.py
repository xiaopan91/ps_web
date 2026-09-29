"""个股标签：可自定义标签并打在个股上（多对多）。

ts_code 维度关联，未来可扩展到 ETF/指数。
"""
from datetime import datetime

from sqlalchemy import Column, DateTime, Index, Integer, String, UniqueConstraint

from app.database import Base


class Tag(Base):
    __tablename__ = "tag"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="标签ID")
    name = Column(String(30), nullable=False, unique=True, comment="标签名（唯一）")
    created_at = Column(DateTime, default=datetime.now, comment="创建时间")


class StockTag(Base):
    __tablename__ = "stock_tag"
    __table_args__ = (
        Index("ix_stock_tag_tag", "tag_id"),
        {"comment": "个股↔标签 关联"},
    )

    ts_code = Column(String(16), primary_key=True, comment="标的代码")
    tag_id = Column(Integer, primary_key=True, comment="标签ID")
    created_at = Column(DateTime, default=datetime.now, comment="打标时间")
