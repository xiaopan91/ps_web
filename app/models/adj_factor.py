"""复权因子（tushare pro.adj_factor），前/后复权计算用。"""
from sqlalchemy import Column, Date, String
from sqlalchemy.dialects.mysql import DECIMAL

from app.database import Base


class AdjFactor(Base):
    __tablename__ = "adj_factor"

    ts_code = Column(String(12), primary_key=True)
    trade_date = Column(Date, primary_key=True)
    adj_factor = Column(DECIMAL(20, 8))
