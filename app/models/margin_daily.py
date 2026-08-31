"""融资融券交易汇总（tushare margin，每交易所一行/日）。"""
from sqlalchemy import CHAR, Column, Date
from sqlalchemy.dialects.mysql import DECIMAL

from app.database import Base


class MarginDaily(Base):
    __tablename__ = "margin_daily"
    __table_args__ = {"comment": "融资融券交易汇总（tushare margin，每交易所一行/日）"}

    trade_date = Column(Date, primary_key=True, comment="交易日")
    exchange_id = Column(CHAR(8), primary_key=True, comment="交易所（SSE=沪 SZSE=深）")
    rzye = Column(DECIMAL(20, 2), comment="融资余额（元）")
    rzmre = Column(DECIMAL(20, 2), comment="融资买入额（元）")
    rzche = Column(DECIMAL(20, 2), comment="融资偿还额（元）")
    rqye = Column(DECIMAL(20, 2), comment="融券余额（元）")
    rzrqye = Column(DECIMAL(20, 2), comment="融资融券余额（元）")
