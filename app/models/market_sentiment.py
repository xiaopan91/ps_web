"""市场情绪日表（由 daily_bar/daily_basic/margin_daily/hsgt_flow/index_daily
聚合计算出的缓存表，scripts/sync_data.py sentiment 子命令重建）。"""
from sqlalchemy import Column, Date, Integer
from sqlalchemy.dialects.mysql import DECIMAL

from app.database import Base


class MarketSentiment(Base):
    __tablename__ = "market_sentiment"

    trade_date = Column(Date, primary_key=True)
    up_count = Column(Integer)  # 上涨家数
    down_count = Column(Integer)  # 下跌家数
    flat_count = Column(Integer)  # 平盘家数
    limit_up = Column(Integer)  # 涨停家数（自算，含 ST 阈值处理）
    limit_down = Column(Integer)  # 跌停家数
    max_streak = Column(Integer)  # 最高连板高度（近两年窗口计算）
    total_amount = Column(DECIMAL(20, 2))  # 两市总成交额（元）
    amount_ratio = Column(DECIMAL(10, 4))  # 量能比：5日均额/20日均额
    median_pct = Column(DECIMAL(10, 4))  # 个股涨跌幅中位数 %
    mean_pct = Column(DECIMAL(10, 4))  # 均值 %
    std_pct = Column(DECIMAL(10, 4))  # 截面标准差（离散度）
    avg_turnover_f = Column(DECIMAL(10, 4))  # 流通换手率均值 %
    margin_balance = Column(DECIMAL(20, 2))  # 两融余额（元）
    margin_net_buy = Column(DECIMAL(20, 2))  # 两融净买入（元）
    north_net = Column(DECIMAL(16, 2))  # 北向净买入（万元）
    sh_pct = Column(DECIMAL(10, 4))  # 上证指数涨跌幅 %
    divergence = Column(DECIMAL(10, 4))  # 背离：中位数 - 上证
