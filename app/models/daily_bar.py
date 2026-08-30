"""A股日线行情（tushare pro.daily，按交易日全市场批量）。"""
from sqlalchemy import Column, Date, Index, String
from sqlalchemy.dialects.mysql import DECIMAL

from app.database import Base


class DailyBar(Base):
    __tablename__ = "daily_bar"

    ts_code = Column(String(12), primary_key=True)  # 000001.SZ
    trade_date = Column(Date, primary_key=True)  # 交易日
    open = Column(DECIMAL(12, 4))
    high = Column(DECIMAL(12, 4))
    low = Column(DECIMAL(12, 4))
    close = Column(DECIMAL(12, 4))
    pre_close = Column(DECIMAL(12, 4))  # 昨收（除权除息后）
    change = Column(DECIMAL(12, 4))  # 涨跌额
    pct_chg = Column(DECIMAL(10, 4))  # 涨跌幅 %
    vol = Column(DECIMAL(16, 2))  # 成交量（手）
    amount = Column(DECIMAL(18, 2))  # 成交额（千元）


Index("ix_daily_bar_trade_date", DailyBar.trade_date)
