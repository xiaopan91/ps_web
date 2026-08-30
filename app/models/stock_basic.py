"""股票基本信息（tushare stock_basic，在市股票）。"""
from sqlalchemy import Column, Date, String

from app.database import Base


class StockBasic(Base):
    __tablename__ = "stock_basic"

    ts_code = Column(String(12), primary_key=True)  # 000001.SZ
    symbol = Column(String(12))  # 000001
    name = Column(String(32))  # 平安银行
    area = Column(String(16))  # 地区
    industry = Column(String(32))  # 行业
    market = Column(String(16))  # 市场（主板/创业板/科创板...）
    list_date = Column(Date)  # 上市日期
