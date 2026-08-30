"""每日指标（tushare daily_basic：换手率/量比/市值等，按日全市场）。"""
from sqlalchemy import Column, Date, String
from sqlalchemy.dialects.mysql import DECIMAL

from app.database import Base


class DailyBasic(Base):
    __tablename__ = "daily_basic"

    ts_code = Column(String(12), primary_key=True)
    trade_date = Column(Date, primary_key=True)
    turnover_rate = Column(DECIMAL(10, 4))  # 换手率 %
    turnover_rate_f = Column(DECIMAL(10, 4))  # 流通换手率 %
    volume_ratio = Column(DECIMAL(10, 4))  # 量比
    pe = Column(DECIMAL(12, 4))  # 市盈率
    circ_mv = Column(DECIMAL(18, 4))  # 流通市值（万元）
    total_mv = Column(DECIMAL(18, 4))  # 总市值（万元）
