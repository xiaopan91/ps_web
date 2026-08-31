"""复权因子（tushare pro.adj_factor / fund_adj，股票与 ETF 共用此表）。"""
from sqlalchemy import Column, Date, String
from sqlalchemy.dialects.mysql import DECIMAL

from app.database import Base


class AdjFactor(Base):
    __tablename__ = "adj_factor"
    __table_args__ = {"comment": "复权因子（股票 adj_factor 与 ETF fund_adj 共用）"}

    ts_code = Column(String(12), primary_key=True, comment="证券代码（股票或 ETF）")
    trade_date = Column(Date, primary_key=True, comment="交易日")
    adj_factor = Column(DECIMAL(20, 8), comment="复权因子")
