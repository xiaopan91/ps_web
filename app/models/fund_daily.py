"""ETF 日线（tushare fund_daily，按代码清单同步）。"""
from sqlalchemy import Column, Date, String
from sqlalchemy.dialects.mysql import DECIMAL

from app.database import Base


class FundDaily(Base):
    __tablename__ = "fund_daily"

    ts_code = Column(String(12), primary_key=True)  # 510300.SH
    trade_date = Column(Date, primary_key=True)
    open = Column(DECIMAL(12, 4))
    high = Column(DECIMAL(12, 4))
    low = Column(DECIMAL(12, 4))
    close = Column(DECIMAL(12, 4))
    vol = Column(DECIMAL(18, 2))  # 成交量（手）
    amount = Column(DECIMAL(20, 2))  # 成交额（千元）
