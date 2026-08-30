"""沪深港通资金流向（tushare moneyflow_hsgt，北向/南向，万元）。"""
from sqlalchemy import Column, Date
from sqlalchemy.dialects.mysql import DECIMAL

from app.database import Base


class HsgtFlow(Base):
    __tablename__ = "hsgt_flow"

    trade_date = Column(Date, primary_key=True)
    north_money = Column(DECIMAL(16, 2))  # 北向净买入（万元）
    south_money = Column(DECIMAL(16, 2))  # 南向净买入（万元）
    hgt = Column(DECIMAL(16, 2))  # 沪股通（万元）
    sgt = Column(DECIMAL(16, 2))  # 深股通（万元）
