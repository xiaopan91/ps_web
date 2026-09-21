"""行业日频聚合表（自建行业指数：从个股日线 + daily_basic 按行业聚合）。

行业分类取 tushare stock_basic.industry（非申万官方指数口径）。
由 sync_data.py industry 全量/增量预计算，页面只读本表。
"""
from sqlalchemy import Column, Date, Index, String
from sqlalchemy.dialects.mysql import DECIMAL

from app.database import Base


class IndustryDaily(Base):
    __tablename__ = "industry_daily"
    __table_args__ = (
        Index("ix_industry_daily_date", "trade_date"),
        {"comment": "行业日频聚合（等权/加权收益、成交占比、上涨家数等，自建行业指数）"},
    )

    industry = Column(String(20), primary_key=True, comment="行业（tushare stock_basic.industry）")
    trade_date = Column(Date, primary_key=True, comment="交易日")
    n_stocks = Column(DECIMAL(8), comment="当日有行情的家数")
    up_count = Column(DECIMAL(8), comment="上涨家数")
    down_count = Column(DECIMAL(8), comment="下跌家数")
    ret_eq = Column(DECIMAL(10, 4), comment="等权日收益（%，当日有行情个股的 pct_chg 均值）")
    ret_cap = Column(DECIMAL(10, 4), comment="流通市值加权日收益（%）")
    amount = Column(DECIMAL(18, 4), comment="成交额（亿元）")
    amount_share = Column(DECIMAL(10, 4), comment="占全市场成交额比（%）")
    turnover_med = Column(DECIMAL(10, 4), comment="流通换手率中位数（%）")
    circ_mv = Column(DECIMAL(18, 4), comment="行业流通市值合计（亿元）")
