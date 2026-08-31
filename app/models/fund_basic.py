"""ETF 基金基本信息（tushare fund_basic）。"""
from sqlalchemy import Column, Date, String

from app.database import Base


class FundBasic(Base):
    __tablename__ = "fund_basic"
    __table_args__ = {"comment": "ETF 基金基本信息（tushare fund_basic）"}

    ts_code = Column(String(12), primary_key=True, comment="ETF 代码")
    name = Column(String(64), comment="基金简称")
    management = Column(String(64), comment="基金管理公司")
    fund_type = Column(String(32), comment="基金类型（股票型/债券型等）")
    list_date = Column(Date, comment="上市日期")
    market = Column(String(8), comment="市场（E=场内）")
