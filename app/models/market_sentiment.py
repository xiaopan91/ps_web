"""市场情绪日表（由底层数据表聚合的计算缓存，sync_data.py sentiment 重建）。"""
from sqlalchemy import Column, Date, Integer
from sqlalchemy.dialects.mysql import DECIMAL

from app.database import Base


class MarketSentiment(Base):
    __tablename__ = "market_sentiment"
    __table_args__ = {"comment": "市场情绪日表（聚合缓存，sentiment 子命令重建）"}

    trade_date = Column(Date, primary_key=True, comment="交易日")
    up_count = Column(Integer, comment="上涨家数")
    down_count = Column(Integer, comment="下跌家数")
    flat_count = Column(Integer, comment="平盘家数")
    limit_up = Column(Integer, comment="涨停家数（自算：主板10%/创业板科创板20%/北交所30%/ST 5%）")
    limit_down = Column(Integer, comment="跌停家数（阈值同涨停）")
    max_streak = Column(Integer, comment="最高连板天数（近两年窗口计算）")
    total_amount = Column(DECIMAL(20, 2), comment="两市总成交额（元）")
    amount_ratio = Column(DECIMAL(10, 4), comment="量能比（5日均额/20日均额）")
    median_pct = Column(DECIMAL(10, 4), comment="个股涨跌幅中位数（%）")
    mean_pct = Column(DECIMAL(10, 4), comment="个股涨跌幅均值（%）")
    std_pct = Column(DECIMAL(10, 4), comment="涨跌幅截面标准差（离散度）")
    avg_turnover_f = Column(DECIMAL(10, 4), comment="全市场流通换手率均值（%）")
    margin_balance = Column(DECIMAL(20, 2), comment="两融余额（元）")
    margin_net_buy = Column(DECIMAL(20, 2), comment="两融净买入（融资买入-偿还，元）")
    north_net = Column(DECIMAL(16, 2), comment="北向净买入（万元）")
    sh_pct = Column(DECIMAL(10, 4), comment="上证指数涨跌幅（%）")
    divergence = Column(DECIMAL(10, 4), comment="背离值（涨跌中位数-上证涨幅，百分点）")
