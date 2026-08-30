"""指数日线（tushare index_daily，13 只核心/风格指数）。"""
from sqlalchemy import Column, Date, Index, String
from sqlalchemy.dialects.mysql import DECIMAL

from app.database import Base


class IndexDaily(Base):
    __tablename__ = "index_daily"

    ts_code = Column(String(12), primary_key=True)  # 000001.SH
    trade_date = Column(Date, primary_key=True)
    open = Column(DECIMAL(12, 4))
    high = Column(DECIMAL(12, 4))
    low = Column(DECIMAL(12, 4))
    close = Column(DECIMAL(12, 4))
    pct_chg = Column(DECIMAL(10, 4))  # 涨跌幅 %
    vol = Column(DECIMAL(20, 2))  # 成交量（手）
    amount = Column(DECIMAL(22, 2))  # 成交额（千元）


Index("ix_index_daily_date", IndexDaily.trade_date)
