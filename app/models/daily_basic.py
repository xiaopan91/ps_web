"""每日指标（tushare daily_basic：换手率/量比/市值等，按日全市场）。"""
from sqlalchemy import Column, Date, String
from sqlalchemy.dialects.mysql import DECIMAL

from app.database import Base


class DailyBasic(Base):
    __tablename__ = "daily_basic"
    __table_args__ = {"comment": "每日指标（tushare daily_basic：换手/量比/市值）"}

    ts_code = Column(String(12), primary_key=True, comment="股票代码")
    trade_date = Column(Date, primary_key=True, comment="交易日")
    turnover_rate = Column(DECIMAL(10, 4), comment="换手率（%）")
    turnover_rate_f = Column(DECIMAL(10, 4), comment="流通换手率（%）")
    volume_ratio = Column(DECIMAL(10, 4), comment="量比")
    pe = Column(DECIMAL(12, 4), comment="市盈率（总市值/净利润）")
    circ_mv = Column(DECIMAL(18, 4), comment="流通市值（万元）")
    total_mv = Column(DECIMAL(18, 4), comment="总市值（万元）")
