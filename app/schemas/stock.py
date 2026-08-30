"""个股接口的请求/响应模型。"""
from typing import List, Optional

from pydantic import BaseModel


class SearchItem(BaseModel):
    ts_code: str
    name: Optional[str] = None
    industry: Optional[str] = None


class StockInfo(BaseModel):
    ts_code: str
    name: Optional[str] = None
    industry: Optional[str] = None
    market: Optional[str] = None
    list_date: Optional[str] = None


class Bar(BaseModel):
    d: str  # 交易日 YYYY-MM-DD
    o: float
    h: float
    l: float
    c: float
    v: Optional[float] = None  # 成交量（手）
    amount: Optional[float] = None  # 成交额（千元）
    pct: Optional[float] = None  # 涨跌幅 %（不受复权影响）


class Latest(BaseModel):
    trade_date: str
    close: float
    pct: Optional[float] = None


class DailyResponse(BaseModel):
    info: StockInfo
    latest: Optional[Latest] = None
    bars: List[Bar]
