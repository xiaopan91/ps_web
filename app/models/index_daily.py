"""指数日线（tushare index_daily，13 只核心/风格指数）。"""
from sqlalchemy import Column, Date, Index, String
from sqlalchemy.dialects.mysql import DECIMAL

from app.database import Base


class IndexDaily(Base):
    __tablename__ = "index_daily"
    __table_args__ = (
        Index("ix_index_daily_date", "trade_date"),
        {"comment": "指数日线（tushare index_daily，13 只核心/风格指数）"},
    )

    ts_code = Column(String(12), primary_key=True, comment="指数代码（如 000001.SH 上证指数）")
    trade_date = Column(Date, primary_key=True, comment="交易日")
    open = Column(DECIMAL(12, 4), comment="开盘点位")
    high = Column(DECIMAL(12, 4), comment="最高点位")
    low = Column(DECIMAL(12, 4), comment="最低点位")
    close = Column(DECIMAL(12, 4), comment="收盘点位")
    pct_chg = Column(DECIMAL(10, 4), comment="涨跌幅（%）")
    vol = Column(DECIMAL(20, 2), comment="成交量（手）")
    amount = Column(DECIMAL(22, 2), comment="成交额（千元）")
