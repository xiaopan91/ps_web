"""板块体系（推倒 tushare stock_basic.industry 粗分类后重建）。

board_type：
- sw_l1 / sw_l2 / sw_l3：申万 2021 版行业（31/134/346 个），成分来自 index_member_all，
  指数日线无权限（sw_daily 需 5000 分），由 board_daily 按成分股自建聚合
- theme：中证/国证主题指数（预置清单，如 931743.CSI 半导体设备），成分来自
  index_weight 最新月末快照，行情直接用 index_daily 里的官方指数日线
"""
from sqlalchemy import Column, Date, Index, String
from sqlalchemy.dialects.mysql import DECIMAL

from app.database import Base


class BoardGroup(Base):
    __tablename__ = "board_group"
    __table_args__ = {"comment": "板块目录（申万层级 + 主题指数）"}

    board_code = Column(String(16), primary_key=True, comment="板块代码（如 931743.CSI / 801080.SI）")
    board_type = Column(String(8), nullable=False, comment="类型（sw_l1/sw_l2/sw_l3/theme）")
    board_name = Column(String(32), nullable=False, comment="板块名")


class BoardMember(Base):
    __tablename__ = "board_member"
    __table_args__ = {"comment": "板块成分股（申万为当前成分 is_new=Y；主题为最新月末快照）"}

    board_code = Column(String(16), primary_key=True, comment="板块代码")
    ts_code = Column(String(12), primary_key=True, comment="股票代码")
    weight = Column(DECIMAL(10, 4), comment="指数内权重（%，主题指数有，申万为空）")


class BoardDaily(Base):
    __tablename__ = "board_daily"
    __table_args__ = (
        Index("ix_board_daily_date", "trade_date"),
        {"comment": "板块日频指标（申万自建聚合；theme 的 ret 字段直接取官方指数涨跌幅）"},
    )

    board_code = Column(String(16), primary_key=True, comment="板块代码")
    trade_date = Column(Date, primary_key=True, comment="交易日")
    n_stocks = Column(DECIMAL(8), comment="当日有行情的成分家数")
    up_count = Column(DECIMAL(8), comment="上涨家数")
    down_count = Column(DECIMAL(8), comment="下跌家数")
    ret_eq = Column(DECIMAL(10, 4), comment="等权日收益（%；theme 为官方指数涨跌幅）")
    ret_cap = Column(DECIMAL(10, 4), comment="加权日收益（%；theme 同官方涨跌幅）")
    amount = Column(DECIMAL(18, 4), comment="成分成交额（亿元）")
    amount_share = Column(DECIMAL(10, 4), comment="占全市场成交额比（%）")
    turnover_med = Column(DECIMAL(10, 4), comment="流通换手率中位数（%）")
    circ_mv = Column(DECIMAL(18, 4), comment="成分流通市值合计（亿元）")
