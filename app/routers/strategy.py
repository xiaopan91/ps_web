"""买卖策略接口：网格交易回测。"""
from fastapi import APIRouter, HTTPException, Query

from app.grid_engine import GridBacktest

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
