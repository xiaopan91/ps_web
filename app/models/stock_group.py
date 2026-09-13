"""个股收藏分组（一股可入多组：group × member 多对多）。"""
from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String

from app.database import Base


class StockGroup(Base):
    __tablename__ = "stock_group"
    __table_args__ = {"comment": "收藏分组（自定义组合，如：核心池/观察池）"}

    id = Column(Integer, primary_key=True, autoincrement=True, comment="分组ID")
    name = Column(String(32), unique=True, nullable=False, comment="分组名")
    created_at = Column(DateTime, default=datetime.now, comment="创建时间")


class StockGroupMember(Base):
    __tablename__ = "stock_group_member"
    __table_args__ = {"comment": "分组成员（复合主键，一股可入多组）"}

    group_id = Column(Integer, primary_key=True, comment="分组ID")
    ts_code = Column(String(12), primary_key=True, comment="股票代码")
    added_at = Column(DateTime, default=datetime.now, comment="加入时间")
