"""ETF 日线（tushare fund_daily，按代码清单同步）。"""
from sqlalchemy import Column, Date, String
from sqlalchemy.dialects.mysql import DECIMAL

from app.database import Base


class FundDaily(Base):
    __tablename__ = "fund_daily"
    __table_args__ = {"comment": "ETF 日线（tushare fund_daily，常用网格标的）"}

    ts_code = Column(String(12), primary_key=True, comment="ETF 代码（如 510300.SH）")
    trade_date = Column(Date, primary_key=True, comment="交易日")
    open = Column(DECIMAL(12, 4), comment="开盘价（元）")
    high = Column(DECIMAL(12, 4), comment="最高价（元）")
    low = Column(DECIMAL(12, 4), comment="最低价（元）")
    close = Column(DECIMAL(12, 4), comment="收盘价（元）")
    vol = Column(DECIMAL(18, 2), comment="成交量（手）")
    amount = Column(DECIMAL(20, 2), comment="成交额（千元）")
