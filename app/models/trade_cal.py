"""交易日历（tushare trade_cal，上交所）。"""
from sqlalchemy import CHAR, Column, Date, Integer

from app.database import Base


class TradeCal(Base):
    __tablename__ = "trade_cal"
    __table_args__ = {"comment": "交易日历（上交所，含未来日期）"}

    exchange = Column(CHAR(4), primary_key=True, comment="交易所（SSE=上交所）")
    cal_date = Column(Date, primary_key=True, comment="日历日期")
    is_open = Column(Integer, comment="是否交易日（0=休市 1=交易）")
