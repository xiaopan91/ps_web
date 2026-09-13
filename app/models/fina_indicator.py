"""财务指标（tushare fina_indicator，季频逐只全历史）。

update_flag 不能当版本选择器（多数报告期只有 '1'），全版本入库；
查询端按「每期最早公告日」取数，防前视以 ann_date 为准。
"""
from sqlalchemy import Column, Date, String
from sqlalchemy.dialects.mysql import DECIMAL

from app.database import Base


class FinaIndicator(Base):
    __tablename__ = "fina_indicator"
    __table_args__ = {"comment": "财务指标（tushare fina_indicator，季频，原始披露口径）"}

    ts_code = Column(String(12), primary_key=True, comment="股票代码")
    end_date = Column(Date, primary_key=True, comment="报告期（季度末）")
    update_flag = Column(String(2), primary_key=True, comment="披露版本标记（不能当版本选择器，见表注释）")
    ann_date = Column(Date, comment="公告日（防前视对齐用）")
    eps = Column(DECIMAL(12, 4), comment="每股收益（元）")
    bps = Column(DECIMAL(12, 4), comment="每股净资产（元），PB=收盘价/bps")
    roe = Column(DECIMAL(12, 4), comment="净资产收益率（%）")
    grossprofit_margin = Column(DECIMAL(12, 4), comment="销售毛利率（%）")
    netprofit_margin = Column(DECIMAL(12, 4), comment="销售净利率（%）")
    debt_to_assets = Column(DECIMAL(12, 4), comment="资产负债率（%）")
    or_yoy = Column(DECIMAL(12, 4), comment="营业收入同比增长率（%）")
    netprofit_yoy = Column(DECIMAL(12, 4), comment="归母净利润同比增长率（%）")
