"""买卖策略接口：网格交易回测 + 定投回测（等额/等价值/一次性）。"""
import time
from datetime import date

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text

from app.database import engine
from app.grid_engine import GridBacktest
from app.pa_engine import backtest_all
from app.routers.index_quotes import INDEX_NAMES

router = APIRouter(prefix="/api/strategy", tags=["strategy"])


@router.get("/grid/targets")
def grid_targets():
    """网格实验室可选标的（常用 ETF 清单）。"""
    from app.grid_engine import DEFAULT_ETFS
    return [{"ts_code": c, "name": n} for c, n in DEFAULT_ETFS]


@router.get("/grid/backtest")
def grid_backtest(
    code: str,
    start: str = Query(pattern=r"^\d{8}$"),
    end: str = Query(default=None, pattern=r"^\d{8}$"),
    grid_pct: float = Query(default=5.0, ge=0.5, le=50),
    n_grids: int = Query(default=10, ge=2, le=50),
    cash: float = Query(default=100000, gt=0),
    initial_grids: int = Query(default=None, ge=0, le=50),
):
    """运行网格回测，返回净值曲线、指标与交易明细。"""
    start_iso = f"{start[:4]}-{start[4:6]}-{start[6:8]}"
    end_iso = f"{end[:4]}-{end[4:6]}-{end[6:8]}" if end else None
    try:
        bt = GridBacktest(code, start_iso, end_iso, grid_pct, n_grids, cash,
                          initial_grids=initial_grids)
        return bt.run()
    except ValueError as exc:
        raise HTTPException(400, str(exc))


# ---------------------------------------------------------------- 定投回测

_PA_CACHE = {}   # 参数 tuple -> (computed_at, payload)
_TTL = 1800


def _pa_params(
    start: str = Query(default="2016-01-01", pattern=r"^\d{4}-\d{2}-\d{2}$"),
    freq: str = Query(default="month", pattern=r"^(month|week)$"),
    amount: float = Query(default=2000, gt=0, le=1e7),
    path_type: str = Query(default="linear", pattern=r"^(linear|growth)$"),
    growth: float = Query(default=0.0, ge=-0.2, le=0.5),
    allow_sell: int = Query(default=1, ge=0, le=1),
    max_inject_k: float = Query(default=3.0, ge=0, le=20),
):
    return {"start": start, "freq": freq, "amount": amount,
            "path_type": path_type, "growth": growth,
            "allow_sell": bool(allow_sell), "max_inject_k": max_inject_k}


def _load_index_closes(code: str, start: str):
    df = pd.read_sql(text(
        "SELECT trade_date, close FROM index_daily "
        "WHERE ts_code = :c AND trade_date >= :s ORDER BY trade_date"),
        engine, params={"c": code, "s": start})
    if df.empty:
        raise HTTPException(404, f"{code} 在 {start} 之后无指数数据")
    dates = list(pd.to_datetime(df["trade_date"]).dt.date)
    closes = [float(v) for v in pd.to_numeric(df["close"], errors="coerce")]
    return dates, closes


@router.get("/pa/backtest")
def pa_backtest(
    code: str,
    params: dict = Depends(_pa_params),
):
    """单指数定投回测：一次返回 DCA / VA / 一次性买入 三策略。"""
    if code not in INDEX_NAMES:
        raise HTTPException(404, f"未知指数代码: {code}")
    dates, closes = _load_index_closes(code, params["start"])
    try:
        out = backtest_all(dates, closes, freq=params["freq"],
                           amount=params["amount"], path_type=params["path_type"],
                           growth=params["growth"], allow_sell=params["allow_sell"],
                           max_k=params["max_inject_k"])
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"info": {"ts_code": code, "name": INDEX_NAMES[code],
                     "n_periods": out["n_periods"],
                     "first": out["first"], "last": out["last"]},
            "dca": out["dca"], "va": out["va"], "lump": out["lump"],
            "index": {"dates": [d.isoformat() for d in dates],
                      "closes": closes,
                      "nav": [round(c / closes[0], 4) for c in closes]}}


@router.get("/pa/compare")
def pa_compare(params: dict = Depends(_pa_params)):
    """全部 13 只指数的三策略对比矩阵（行内按 XIRR 标最优）。"""
    key = tuple(sorted(params.items()))
    hit = _PA_CACHE.get(key)
    if hit and time.time() - hit[0] < _TTL:
        return hit[1]

    rows = []
    for code, name in INDEX_NAMES.items():
        try:
            dates, closes = _load_index_closes(code, params["start"])
            out = backtest_all(dates, closes, freq=params["freq"],
                               amount=params["amount"], path_type=params["path_type"],
                               growth=params["growth"], allow_sell=params["allow_sell"],
                               max_k=params["max_inject_k"])
        except HTTPException:
            continue
        except ValueError:
            continue
        rows.append({
            "code": code, "name": name, "n_periods": out["n_periods"],
            "first": out["first"], "last": out["last"],
            **{f"{m}_{f}": out[m]["metrics"][f]
               for m in ("dca", "va", "lump")
               for f in ("xirr", "profit_pct", "max_dd", "total_in",
                         "final_account", "max_single_inject", "n_sells")},
        })
    for r in rows:
        xr = {m: r[f"{m}_xirr"] for m in ("dca", "va", "lump")
              if r[f"{m}_xirr"] is not None}
        r["best"] = max(xr, key=xr.get) if xr else None
    payload = {"params": params, "rows": rows}
    if len(_PA_CACHE) > 30:
        _PA_CACHE.pop(next(iter(_PA_CACHE)))
    _PA_CACHE[key] = (time.time(), payload)
    return payload
