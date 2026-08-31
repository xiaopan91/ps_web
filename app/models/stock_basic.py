"""股票基本信息（tushare stock_basic，在市股票）。"""
from sqlalchemy import Column, Date, String

from app.database import Base


class StockBasic(Base):
    __tablename__ = "stock_basic"
    __table_args__ = {"comment": "股票基本信息（tushare stock_basic，在市股票）"}

    ts_code = Column(String(12), primary_key=True, comment="股票代码（如 000001.SZ）")
    symbol = Column(String(12), comment="证券代码（不含交易所后缀）")
    name = Column(String(32), comment="股票名称")
    area = Column(String(16), comment="所属地区")
    industry = Column(String(32), comment="所属行业")
    market = Column(String(16), comment="市场（主板/创业板/科创板/北交所）")
    list_date = Column(Date, comment="上市日期")
