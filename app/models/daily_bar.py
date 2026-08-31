"""A股日线行情（tushare pro.daily，按交易日全市场批量）。"""
from sqlalchemy import Column, Date, Index, String
from sqlalchemy.dialects.mysql import DECIMAL

from app.database import Base


class DailyBar(Base):
    __tablename__ = "daily_bar"
    __table_args__ = (
        Index("ix_daily_bar_trade_date", "trade_date"),
        {"comment": "A股日线行情（tushare pro.daily，全市场按日批量）"},
    )

    ts_code = Column(String(12), primary_key=True, comment="股票代码（如 000001.SZ）")
    trade_date = Column(Date, primary_key=True, comment="交易日")
    open = Column(DECIMAL(12, 4), comment="开盘价（元）")
    high = Column(DECIMAL(12, 4), comment="最高价（元）")
    low = Column(DECIMAL(12, 4), comment="最低价（元）")
    close = Column(DECIMAL(12, 4), comment="收盘价（元）")
    pre_close = Column(DECIMAL(12, 4), comment="昨收价（除权除息后，元）")
    change = Column(DECIMAL(12, 4), comment="涨跌额（元）")
    pct_chg = Column(DECIMAL(10, 4), comment="涨跌幅（%）")
    vol = Column(DECIMAL(16, 2), comment="成交量（手）")
    amount = Column(DECIMAL(18, 2), comment="成交额（千元）")
