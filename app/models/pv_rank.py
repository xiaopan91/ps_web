"""量价综合分（个股-日截面因子缓存，sync_data.py pvrank 子命令重建）。

因子构造与 FACTOR_RESEARCH.md 一致：量价同步度(20日)/Amihud(3日)/
量确认动量(10日)/换手率，按 IC 方向调整后截面百分位等权（0~1，越大越靠前）。
"""
from sqlalchemy import Column, Date, Index, String
from sqlalchemy.dialects.mysql import DECIMAL

from app.database import Base


class PvRank(Base):
    __tablename__ = "pv_rank"
    __table_args__ = (
        Index("ix_pv_rank_date_score", "trade_date", "score"),
        {"comment": "量价综合分个股日表（截面合成因子缓存，pvrank 子命令增量重建）"},
    )

    ts_code = Column(String(12), primary_key=True, comment="股票代码")
    trade_date = Column(Date, primary_key=True, comment="交易日")
    score = Column(DECIMAL(10, 6), comment="合成因子值（0~1 截面分位，越大排序越前）")
    pct_chg = Column(DECIMAL(10, 4), comment="当日涨跌幅（%，百分点）")
    next_ret = Column(DECIMAL(10, 4), comment="次日涨跌幅（%，研究对照用；最新交易日为空）")
