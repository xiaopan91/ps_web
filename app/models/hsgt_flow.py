"""沪深港通资金流向（tushare moneyflow_hsgt，北向/南向）。"""
from sqlalchemy import Column, Date
from sqlalchemy.dialects.mysql import DECIMAL

from app.database import Base


class HsgtFlow(Base):
    __tablename__ = "hsgt_flow"
    __table_args__ = {"comment": "沪深港通资金流向（tushare moneyflow_hsgt）"}

    trade_date = Column(Date, primary_key=True, comment="交易日")
    north_money = Column(DECIMAL(16, 2), comment="北向净买入（万元）")
    south_money = Column(DECIMAL(16, 2), comment="南向净买入（万元）")
    hgt = Column(DECIMAL(16, 2), comment="沪股通净买入（万元）")
    sgt = Column(DECIMAL(16, 2), comment="深股通净买入（万元）")
