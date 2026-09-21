"""个股数据接口：搜索 + 日线（含复权）+ 分析指标。"""
from datetime import date, timedelta

import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import engine, get_db
from app.schemas.stock import DailyResponse, SearchItem, StockInfo

router = APIRouter(prefix="/api/stock", tags=["stock"])

# range 预设对应的天数（自然日，足够覆盖对应交易天数）
RANGE_DAYS = {"3m": 95, "6m": 185, "1y": 370, "3y": 1100}
ADJUSTS = ("none", "qfq", "hfq")


def _series(s: pd.Series, ndigits: int = 4) -> list:
    """数值列转 JSON 数组，NaN→None。"""
    return [None if pd.isna(v) else round(float(v), ndigits) for v in s]


@router.get("/search", response_model=list[SearchItem])
def search(q: str = Query(min_length=1), db: Session = Depends(get_db)):
    """按名称/代码模糊搜索在市股票。"""
    rows = db.execute(
        text(
            "SELECT ts_code, name, industry FROM stock_basic "
            "WHERE name LIKE :p OR ts_code LIKE :p OR symbol LIKE :p "
            "ORDER BY ts_code LIMIT 20"
        ),
        {"p": f"%{q}%"},
    ).fetchall()
    return [{"ts_code": r[0], "name": r[1], "industry": r[2]} for r in rows]


@router.get("/daily", response_model=DailyResponse)
def daily(
    code: str,
    range: str = "1y",
    adjust: str = "qfq",
    db: Session = Depends(get_db),
):
    """个股日线。adjust: none 不复权 / qfq 前复权（锚定最新价）/ hfq 后复权。"""
    if range not in RANGE_DAYS and range != "all":
        raise HTTPException(400, f"range 取值: {list(RANGE_DAYS) + ['all']}")
    if adjust not in ADJUSTS:
        raise HTTPException(400, f"adjust 取值: {list(ADJUSTS)}")

    info_row = db.execute(
        text(
            "SELECT ts_code, name, industry, market, list_date "
            "FROM stock_basic WHERE ts_code = :c"
        ),
        {"c": code},
    ).fetchone()
    if not info_row:
        raise HTTPException(404, f"未知股票代码: {code}")

    start = (
        date(1990, 1, 1)
        if range == "all"
        else date.today() - timedelta(days=RANGE_DAYS[range])
    )
    rows = db.execute(
        text(
            "SELECT d.trade_date, d.open, d.high, d.low, d.close, d.vol, "
            "       d.amount, d.pct_chg, a.adj_factor "
            "FROM daily_bar d LEFT JOIN adj_factor a "
            "  ON a.ts_code = d.ts_code AND a.trade_date = d.trade_date "
            "WHERE d.ts_code = :c AND d.trade_date >= :s "
            "ORDER BY d.trade_date"
        ),
        {"c": code, "s": start},
    ).fetchall()

    # 前复权锚点：最新可用复权因子
    latest_adj = None
    for r in rows:
        if r.adj_factor is not None:
            latest_adj = float(r.adj_factor)

    bars = []
    for r in rows:
        adj = float(r.adj_factor) if r.adj_factor is not None else None
        if adjust == "none" or adj is None or latest_adj in (None, 0):
            factor = 1.0
        elif adjust == "hfq":
            factor = adj
        else:  # qfq
            factor = adj / latest_adj
        bars.append(
            {
                "d": r.trade_date.isoformat(),
                "o": float(r.open) * factor,
                "h": float(r.high) * factor,
                "l": float(r.low) * factor,
                "c": float(r.close) * factor,
                "v": float(r.vol) if r.vol is not None else None,
                "amount": float(r.amount) if r.amount is not None else None,
                "pct": float(r.pct_chg) if r.pct_chg is not None else None,
            }
        )

    latest = None
    if bars:
        last = bars[-1]
        latest = {
            "trade_date": last["d"],
            "close": last["c"],
            "pct": last["pct"],
        }

    return {
        "info": {
            "ts_code": info_row[0],
            "name": info_row[1],
            "industry": info_row[2],
            "market": info_row[3],
            "list_date": info_row[4].isoformat() if info_row[4] else None,
        },
        "latest": latest,
        "bars": bars,
    }


@router.get("/metrics")
def metrics(
    code: str,
    range: str = "1y",
    db: Session = Depends(get_db),
):
    """个股分析指标：换手/量比/PE/市值 + 振幅/ATR/60日位置 + 相对沪深300强弱。

    rolling 列（pos60/atr）需 60 日预热，窗口向前多取 60 个交易日，返回前裁掉。
    """
    if range not in RANGE_DAYS and range != "all":
        raise HTTPException(400, f"range 取值: {list(RANGE_DAYS) + ['all']}")

    # 交易日历（降序）：自然日窗口 → 交易日索引，再前推 60 日预热
    with engine.connect() as conn:
        cal = [r[0] for r in conn.execute(text(
            "SELECT cal_date FROM trade_cal WHERE exchange='SSE' AND is_open=1 "
            "AND cal_date <= CURDATE() ORDER BY cal_date DESC"))]
    if range == "all":
        start = cal[-1]
    else:
        natural_start = date.today() - timedelta(days=RANGE_DAYS[range])
        idx = next((i for i, d in enumerate(cal) if d < natural_start), len(cal) - 1)
        start = cal[min(len(cal) - 1, idx + 60)]

    df = pd.read_sql(text(
        "SELECT d.trade_date, d.high, d.low, d.close, d.pre_close, d.pct_chg, "
        "       a.adj_factor, b.turnover_rate_f, b.volume_ratio, b.pe, b.pe_ttm, "
        "       b.circ_mv, b.total_mv "
        "FROM daily_bar d "
        "LEFT JOIN adj_factor a ON a.ts_code = d.ts_code AND a.trade_date = d.trade_date "
        "LEFT JOIN daily_basic b ON b.ts_code = d.ts_code AND b.trade_date = d.trade_date "
        "WHERE d.ts_code = :c AND d.trade_date >= :s ORDER BY d.trade_date"),
        engine, params={"c": code, "s": start})
    if df.empty:
        raise HTTPException(404, f"{code} 无行情数据")
    num_cols = ("high", "low", "close", "pre_close", "pct_chg", "adj_factor",
                "turnover_rate_f", "volume_ratio", "pe", "pe_ttm", "circ_mv", "total_mv")
    for c in num_cols:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    # 前复权（锚定窗口内最新因子，与 /daily 口径一致）
    latest_adj = df["adj_factor"].dropna().iloc[-1] if df["adj_factor"].notna().any() else None
    if latest_adj in (None, 0) or pd.isna(latest_adj):
        df["close_qfq"] = df["close"]
    else:
        df["close_qfq"] = df["close"] * df["adj_factor"].fillna(latest_adj) / latest_adj

    # 波动与位置
    df["amp"] = (df["high"] - df["low"]) / df["pre_close"] * 100
    tr = np.maximum.reduce([
        df["high"] - df["low"],
        (df["high"] - df["pre_close"]).abs(),
        (df["low"] - df["pre_close"]).abs(),
    ])
    df["atr_pct20"] = pd.Series(tr, index=df.index).rolling(20).mean() / df["close"] * 100
    low60 = df["low"].rolling(60).min()
    high60 = df["high"].rolling(60).max()
    df["pos60"] = (df["close"] - low60) / (high60 - low60) * 100

    # 相对沪深300：两侧各归一到窗口首日，比值 = 相对强弱（>1 跑赢）
    bench = pd.read_sql(text(
        "SELECT trade_date, close FROM index_daily "
        "WHERE ts_code = '000300.SH' AND trade_date >= :s"),
        engine, params={"s": start})
    bench_map = dict(zip(bench["trade_date"].astype(str),
                         pd.to_numeric(bench["close"], errors="coerce")))
    dates_all = df["trade_date"].astype(str).tolist()

    # 52 周区间/年化波动 用全窗口算（裁剪前）
    last250 = df.tail(250)
    high_52w = float(last250["high"].max())
    low_52w = float(last250["low"].min())
    year = date.today().year
    # YTD 跨区间固定：去年收盘（未入窗口，单独查一行）对比最新收盘，
    # 用 close×adj_factor（后复权比值，锚定因子相消），忽略窗口选择
    ytd = None
    year_base = db.execute(
        text(
            "SELECT d.close, a.adj_factor FROM daily_bar d "
            "LEFT JOIN adj_factor a ON a.ts_code = d.ts_code AND a.trade_date = d.trade_date "
            "WHERE d.ts_code = :c AND d.trade_date < :y "
            "ORDER BY d.trade_date DESC LIMIT 1"
        ),
        {"c": code, "y": f"{year}-01-01"},
    ).fetchone()
    last_raw = df.iloc[-1]
    if year_base and year_base[0] is not None and pd.notna(last_raw["close"]):
        base_px = float(year_base[0]) * (float(year_base[1]) if year_base[1] is not None else 1.0)
        last_px = float(last_raw["close"]) * (
            float(last_raw["adj_factor"]) if pd.notna(last_raw["adj_factor"]) else 1.0)
        if base_px:
            ytd = (last_px / base_px - 1) * 100
    ann_vol = float(df["pct_chg"].std() * np.sqrt(244)) if df["pct_chg"].count() > 2 else None

    # PE-TTM 历史分位：当前值在自身历史（2016 起）与近 5 年中的位置，
    # 仅统计盈利期（pe_ttm > 0），亏损期不参与分位
    pe_ttm_last = df["pe_ttm"].iloc[-1]
    pe_pct = pe_pct5 = None
    if pd.notna(pe_ttm_last) and pe_ttm_last > 0:
        dist = db.execute(
            text(
                "SELECT COUNT(pe_ttm) AS n_all, SUM(pe_ttm <= :v) AS n_le, "
                "       SUM(CASE WHEN trade_date >= :d5 THEN 1 ELSE 0 END) AS n5_all, "
                "       SUM(CASE WHEN trade_date >= :d5 AND pe_ttm <= :v THEN 1 ELSE 0 END) AS n5_le "
                "FROM daily_basic WHERE ts_code = :c AND pe_ttm > 0"
            ),
            {"c": code, "v": float(pe_ttm_last),
             "d5": date.today() - timedelta(days=1825)},
        ).fetchone()
        if dist[0]:
            pe_pct = round(float(dist[1] or 0) / float(dist[0]) * 100, 1)
        if dist[2]:
            pe_pct5 = round(float(dist[3] or 0) / float(dist[2]) * 100, 1)

    # 裁掉预热段，RS 在裁剪后归一（首日 = 1.0）；历史不足 60 日则不裁（滚动列为 NULL）
    c_qfq = df["close_qfq"].reset_index(drop=True)
    trim = 60 if len(df) > 60 else 0
    df = df.iloc[trim:].reset_index(drop=True)
    dates = df["trade_date"].astype(str).tolist()
    rs = pd.Series([None] * len(df), index=df.index, dtype=float)
    bench_series = pd.Series([bench_map.get(d) for d in dates], dtype=float)
    if bench_series.count() >= 2 and c_qfq.iloc[trim:].count() >= 2:
        b0 = bench_series.dropna().iloc[0]
        s0 = c_qfq.iloc[trim:].dropna().iloc[0]
        rs = (c_qfq / s0) / (bench_series / b0)

    last = df.iloc[-1]
    stats = {
        "date": dates[-1] if dates else None,
        "turnover_f": None if pd.isna(last["turnover_rate_f"]) else round(float(last["turnover_rate_f"]), 2),
        "volume_ratio": None if pd.isna(last["volume_ratio"]) else round(float(last["volume_ratio"]), 2),
        "pe": None if pd.isna(last["pe_ttm"]) else round(float(last["pe_ttm"]), 2),
        "pe_pct": pe_pct,
        "pe_pct5": pe_pct5,
        "circ_mv": None if pd.isna(last["circ_mv"]) else round(float(last["circ_mv"]) / 1e4, 2),
        "total_mv": None if pd.isna(last["total_mv"]) else round(float(last["total_mv"]) / 1e4, 2),
        "high_52w": round(high_52w, 2),
        "low_52w": round(low_52w, 2),
        "ytd": None if ytd is None else round(ytd, 2),
        "ann_vol": None if ann_vol is None or not np.isfinite(ann_vol) else round(ann_vol, 2),
        "amp20": None if pd.isna(df["amp"].tail(20).mean()) else round(float(df["amp"].tail(20).mean()), 2),
        "atr20": None if pd.isna(df["atr_pct20"].iloc[-1]) else round(float(df["atr_pct20"].iloc[-1]), 2),
        "pos60": None if pd.isna(last["pos60"]) else round(float(last["pos60"]), 1),
        "n_days": len(dates),
    }
    return {
        "dates": dates,
        "close_qfq": _series(df["close_qfq"]),
        "rs": _series(rs, 3),
        "turnover_f": _series(df["turnover_rate_f"], 3),
        "volume_ratio": _series(df["volume_ratio"], 3),
        "pe": _series(df["pe_ttm"], 2),
        "circ_mv": _series(df["circ_mv"] / 1e4, 2),
        "total_mv": _series(df["total_mv"] / 1e4, 2),
        "amp": _series(df["amp"], 3),
        "atr_pct20": _series(df["atr_pct20"], 3),
        "pos60": _series(df["pos60"], 1),
        "stats": stats,
    }


@router.get("/funda")
def funda(code: str, range: str = "1y", db: Session = Depends(get_db)):
    """基本面：季频财务指标 + PB 日频历史。

    PB = 未复权收盘价 / bps，bps 按公告日向后对齐（merge_asof backward），
    公告日之前用上一报告期，严格防前视。
    """
    if range not in RANGE_DAYS and range != "all":
        raise HTTPException(400, f"range 取值: {list(RANGE_DAYS) + ['all']}")

    fina = pd.read_sql(text(
        "SELECT end_date, ann_date, eps, bps, roe, grossprofit_margin, "
        "       netprofit_margin, debt_to_assets, or_yoy, netprofit_yoy "
        "FROM fina_indicator WHERE ts_code = :c "
        "AND ann_date IS NOT NULL ORDER BY end_date, ann_date"),
        engine, params={"c": code})
    if fina.empty:
        return {"periods": [], "latest": None, "pb_dates": [], "pb": [],
                "note": "暂无财务数据（fina_indicator 未同步或该股无披露）"}
    num_cols = ("eps", "bps", "roe", "grossprofit_margin", "netprofit_margin",
                "debt_to_assets", "or_yoy", "netprofit_yoy")
    for c in num_cols:
        fina[c] = pd.to_numeric(fina[c], errors="coerce")
    for c in ("end_date", "ann_date"):
        fina[c] = pd.to_datetime(fina[c]).dt.date
    # 每期取最早公告日版本（防前视；update_flag 不能当版本选择器）
    fina = fina.drop_duplicates(subset=["end_date"], keep="first")

    def rnd(v, d=2):
        return None if pd.isna(v) else round(float(v), d)

    last = fina.iloc[-1]
    latest = {
        "end_date": str(last["end_date"]), "ann_date": str(last["ann_date"]),
        "eps": rnd(last["eps"]), "bps": rnd(last["bps"]),
        "roe": rnd(last["roe"]), "grossprofit_margin": rnd(last["grossprofit_margin"]),
        "netprofit_margin": rnd(last["netprofit_margin"]),
        "debt_to_assets": rnd(last["debt_to_assets"]),
        "or_yoy": rnd(last["or_yoy"], 1), "netprofit_yoy": rnd(last["netprofit_yoy"], 1),
    }
    periods = [
        {"end_date": str(r.end_date), "ann_date": str(r.ann_date),
         "or_yoy": rnd(r.or_yoy, 1), "netprofit_yoy": rnd(r.netprofit_yoy, 1),
         "roe": rnd(r.roe)}
        for r in fina.tail(12).itertuples()]

    # PB 日频：窗口内未复权收盘 ÷ 最近已公告 bps
    start = (date(1990, 1, 1) if range == "all"
             else date.today() - timedelta(days=RANGE_DAYS[range]))
    bars = pd.read_sql(text(
        "SELECT trade_date, close FROM daily_bar "
        "WHERE ts_code = :c AND trade_date >= :s ORDER BY trade_date"),
        engine, params={"c": code, "s": start})
    bars["close"] = pd.to_numeric(bars["close"], errors="coerce")
    bps_pts = fina[["ann_date", "bps"]].dropna(subset=["bps"])
    bps_pts = bps_pts[bps_pts["bps"] > 0].sort_values("ann_date")
    pb_dates: list = []
    pb: list = []
    if not bars.empty and not bps_pts.empty:
        left = bars.rename(columns={"trade_date": "key"}).assign(
            key=pd.to_datetime(bars["trade_date"]))
        right = bps_pts.rename(columns={"ann_date": "key"}).assign(
            key=pd.to_datetime(bps_pts["ann_date"]))
        merged = pd.merge_asof(left[["key", "close"]], right[["key", "bps"]],
                               on="key", direction="backward")
        pb_s = merged["close"] / merged["bps"].replace(0, np.nan)
        pb_dates = pd.to_datetime(merged["key"]).dt.strftime("%Y-%m-%d").tolist()
        pb = _series(pb_s)

    return {"periods": periods, "latest": latest,
            "pb_dates": pb_dates, "pb": pb}
