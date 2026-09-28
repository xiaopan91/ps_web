"""个人理财：标的级持仓体系（v2）。

层级：大模块 module（低风险/中风险/高风险）→ 小模块 sub（存款/债基/红利etf 等）
→ 标的 FinItem（可关联库内行情：股票/ETF/指数）。

- FinBalance：标的余额记录，最新一条 = 当前余额，历史保留
- FinTransfer：移仓（标的间转移），录入时自动调整双方余额
- FinTarget：小模块目标配置百分比，用于调仓差额计算
- FinSnapshot：v1 分类快照（已下线页面，表与数据保留）
"""
from datetime import datetime

from sqlalchemy import Column, Date, DateTime, Index, Integer, String
from sqlalchemy.dialects.mysql import DECIMAL

from app.database import Base

MODULES = ["低风险", "中风险", "高风险"]
PRESET_SUBS = {
    "低风险": ["存款", "债基"],
    "中风险": ["红利etf", "宽基etf", "海外etf"],
    "高风险": ["个股", "行业etf"],
}
ASSET_TYPES = ["股票", "ETF", "指数", "其他"]


class FinItem(Base):
    __tablename__ = "fin_item"
    __table_args__ = (Index("ix_fin_item_module_sub", "module", "sub"),
                      {"comment": "理财标的（大模块-小模块-标的 三级分类的叶子）"})

    id = Column(Integer, primary_key=True, autoincrement=True, comment="标的ID")
    module = Column(String(20), nullable=False, comment="大模块（低风险/中风险/高风险）")
    sub = Column(String(30), nullable=False, comment="小模块（如 存款/债基/红利etf）")
    name = Column(String(50), nullable=False, comment="标的显示名")
    asset_type = Column(String(10), default="其他", comment="资产类型（股票/ETF/指数/其他，决定行情来源表）")
    ts_code = Column(String(12), comment="关联库内行情代码（如 600519.SH，其他类为空）")
    note = Column(String(100), comment="备注")
    created_at = Column(DateTime, default=datetime.now, comment="创建时间")


class FinBalance(Base):
    __tablename__ = "fin_balance"
    __table_args__ = (
        Index("ix_fin_balance_item_date", "item_id", "date"),
        {"comment": "标的余额记录（最新一条=当前余额，历史保留画曲线）"},
    )

    id = Column(Integer, primary_key=True, autoincrement=True, comment="记录ID")
    item_id = Column(Integer, nullable=False, comment="标的ID（fin_item.id）")
    date = Column(Date, nullable=False, comment="余额日期")
    amount = Column(DECIMAL(18, 2), nullable=False, comment="余额（元）")
    note = Column(String(100), comment="备注")
    created_at = Column(DateTime, default=datetime.now, comment="录入时间")


class FinTransfer(Base):
    __tablename__ = "fin_transfer"
    __table_args__ = {"comment": "标的间移仓记录（录入时自动调整双方余额）"}

    id = Column(Integer, primary_key=True, autoincrement=True, comment="移仓ID")
    date = Column(Date, nullable=False, comment="移仓日期")
    from_item = Column(Integer, nullable=False, comment="转出标的ID")
    to_item = Column(Integer, nullable=False, comment="转入标的ID")
    amount = Column(DECIMAL(18, 2), nullable=False, comment="移仓金额（元）")
    note = Column(String(100), comment="备注")
    created_at = Column(DateTime, default=datetime.now, comment="录入时间")


class FinTarget(Base):
    __tablename__ = "fin_target"
    __table_args__ = {"comment": "小模块目标配置百分比（调仓差额计算用）"}

    sub = Column(String(30), primary_key=True, comment="小模块名")
    target_pct = Column(DECIMAL(6, 2), nullable=False, default=0, comment="目标百分比（%）")
    updated_at = Column(DateTime, default=datetime.now, comment="更新时间")


class FinSnapshot(Base):
    __tablename__ = "fin_snapshot"
    __table_args__ = (
        Index("ix_fin_snapshot_date", "snap_date"),
        {"comment": "个人资产快照（v1 分类口径，页面已下线，表与数据保留）"},
    )

    id = Column(Integer, primary_key=True, autoincrement=True, comment="快照ID")
    snap_date = Column(Date, nullable=False, comment="快照日期")
    category = Column(String(20), nullable=False, comment="资产分类（v1 口径）")
    amount = Column(DECIMAL(18, 2), nullable=False, comment="金额（元，负债类记正数、汇总时计入减项）")
    note = Column(String(100), comment="备注")
    created_at = Column(DateTime, default=datetime.now, comment="录入时间")
