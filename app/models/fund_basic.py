"""ETF 基金基本信息（tushare fund_basic）。"""
from sqlalchemy import Column, Date, String

from app.database import Base


class FundBasic(Base):
    __tablename__ = "fund_basic"

    ts_code = Column(String(12), primary_key=True)
    name = Column(String(64))
    management = Column(String(64))  # 基金公司
    fund_type = Column(String(32))  # 类型
    list_date = Column(Date)  # 上市日期
    market = Column(String(8))  # E: ETF
