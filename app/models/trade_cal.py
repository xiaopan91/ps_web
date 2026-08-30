"""交易日历（tushare trade_cal，上交所）。"""
from sqlalchemy import CHAR, Column, Date, Integer

from app.database import Base


class TradeCal(Base):
    __tablename__ = "trade_cal"

    exchange = Column(CHAR(4), primary_key=True)  # 交易所 SSE/SZSE
    cal_date = Column(Date, primary_key=True)
    is_open = Column(Integer)  # 0休市 1交易
