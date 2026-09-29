"""港股与场外基金数据（个人理财标的行情扩展）。

- HkBasic / HkDaily：港股基础信息与日线（tushare hk_basic / hk_daily）
- FundNav：场外基金净值（tushare fund_nav，按代码同步，净值一般 T+1 公布）
"""
from sqlalchemy import Column, Date, Integer, String, UniqueConstraint
from sqlalchemy.dialects.mysql import DECIMAL

from app.database import Base


class HkBasic(Base):
    __tablename__ = "hk_basic"
    __table_args__ = {"comment": "港股基础信息（tushare hk_basic）"}

    ts_code = Column(String(12), primary_key=True, comment="港股代码（如 00700.HK）")
    name = Column(String(64), comment="名称")
    list_date = Column(Date, comment="上市日期")


class HkDaily(Base):
    __tablename__ = "hk_daily"
    __table_args__ = {"comment": "港股日线（tushare hk_daily，按交易日全市场同步）"}

    ts_code = Column(String(12), primary_key=True, comment="港股代码")
    trade_date = Column(Date, primary_key=True, comment="交易日")
    open = Column(DECIMAL(14, 4), comment="开盘价（港元）")
    high = Column(DECIMAL(14, 4), comment="最高价")
    low = Column(DECIMAL(14, 4), comment="最低价")
    close = Column(DECIMAL(14, 4), comment="收盘价")
    change = Column(DECIMAL(12, 4), comment="涨跌额")
    pct_change = Column(DECIMAL(10, 4), comment="涨跌幅（%）")


class FundNav(Base):
    __tablename__ = "fund_nav"
    __table_args__ = (
        UniqueConstraint("ts_code", "nav_date", name="uk_fund_nav_code_date"),
        {"comment": "场外基金净值（tushare fund_nav）"},
    )

    id = Column(Integer, primary_key=True, autoincrement=True, comment="自增ID")
    ts_code = Column(String(12), nullable=False, comment="基金代码（如 110011.OF）")
    nav_date = Column(Date, nullable=False, comment="净值日期")
    unit_nav = Column(DECIMAL(12, 4), comment="单位净值")
    accum_nav = Column(DECIMAL(12, 4), comment="累计净值")
    ann_date = Column(Date, comment="公告日期")
