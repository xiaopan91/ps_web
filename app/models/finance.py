"""个人理财：资产快照（定期记录各类资产/负债余额，用于回顾分析）。

分类固定枚举见 CATEGORIES；"负债"分类金额记正数，汇总时计入减项。
"""
from datetime import datetime

from sqlalchemy import Column, Date, DateTime, Index, Integer, String
from sqlalchemy.dialects.mysql import DECIMAL

from app.database import Base

CATEGORIES = ["现金", "存款", "理财", "基金", "股票", "公积金", "负债", "其他"]
DEBT_CATEGORIES = {"负债"}


class FinSnapshot(Base):
    __tablename__ = "fin_snapshot"
    __table_args__ = (
        Index("ix_fin_snapshot_date", "snap_date"),
        {"comment": "个人资产快照（定期记录各类资产/负债余额，理财回顾用）"},
    )

    id = Column(Integer, primary_key=True, autoincrement=True, comment="快照ID")
    snap_date = Column(Date, nullable=False, comment="快照日期")
    category = Column(String(20), nullable=False, comment="资产分类（现金/存款/理财/基金/股票/公积金/负债/其他）")
    amount = Column(DECIMAL(18, 2), nullable=False, comment="金额（元，负债类记正数、汇总时计入减项）")
    note = Column(String(100), comment="备注")
    created_at = Column(DateTime, default=datetime.now, comment="录入时间")
