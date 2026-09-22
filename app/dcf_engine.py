"""DCF 估值引擎：两阶段 FCFE 折现 + CAPM 折现率 + 敏感性矩阵 + 隐含增长反推。

口径说明：
- 现金流用 tushare fina_indicator.fcfe（股权自由现金流，单位元），年报口径；
  取数规则与回测因子不同——每报告期取 fcfe 非空的最新版本行（2023 后原始
  披露行该字段为空，"最早公告"规则会取到空值）
- 折现率 Re = rf + β×ERP（CAPM）；β 由个股对沪深300 周收益回归自算
- 选 FCFE 而非 FCFF：fcfe 直接对应股权价值，无需净债务数据（balance 未接）
- 已知局限：金融股 fcfe 恒空（不适用）；负基数会显著失真（页面强制警告）
"""
import numpy as np
import pandas as pd
from sqlalchemy import text

from app.database import engine


def _fcfe_annual(code: str) -> pd.DataFrame:
    """年报 FCFE 序列：每报告期取最新公告版本，返回 end_date/fcfe（元）。"""
    df = pd.read_sql(text(
        "SELECT end_date, ann_date, fcfe FROM fina_indicator "
        "WHERE ts_code = :c AND fcfe IS NOT NULL "
        "AND CAST(end_date AS CHAR) LIKE '%-12-31' ORDER BY ann_date"),
        engine, params={"c": code})
    df["end_date"] = pd.to_datetime(df["end_date"]).dt.date
    df["fcfe"] = pd.to_numeric(df["fcfe"], errors="coerce")
    return df.dropna(subset=["fcfe"]).drop_duplicates(subset=["end_date"], keep="last")


def _total_share(code: str) -> float | None:
    """最新总股本（股）。"""
    with engine.connect() as conn:
        v = conn.execute(text(
            "SELECT total_share FROM daily_basic WHERE ts_code = :c "
            "AND total_share IS NOT NULL ORDER BY trade_date DESC LIMIT 1"),
            {"c": code}).scalar()
    return None if v is None else float(v) * 1e4   # 万股 → 股


def _latest_price(code: str) -> float | None:
    with engine.connect() as conn:
        v = conn.execute(text(
            "SELECT close FROM daily_bar WHERE ts_code = :c "
            "ORDER BY trade_date DESC LIMIT 1"), {"c": code}).scalar()
    return None if v is None else float(v)


def beta_r2(code: str, window: int = 750):
    """β 与 R²：个股日涨跌幅对沪深300，近 window 个交易日按周复利采样回归。

    β 截断到 [0.3, 3.0]（回归噪声防护）；返回 (beta, r2)，样本不足返回 (None, None)。
    """
    stk = pd.read_sql(text(
        "SELECT trade_date, pct_chg FROM daily_bar WHERE ts_code = :c "
        "ORDER BY trade_date"), engine, params={"c": code})
    mkt = pd.read_sql(text(
        "SELECT trade_date, pct_chg FROM index_daily WHERE ts_code = '000300.SH' "
        "ORDER BY trade_date"), engine)
    m = stk.merge(mkt, on="trade_date", suffixes=("_s", "_m")).tail(window)
    if len(m) < 250:
        return None, None
    wk = pd.to_datetime(m["trade_date"]).dt.strftime("%G-%V")
    gs = m.groupby(wk)["pct_chg_s"].apply(lambda x: ((1 + x / 100).prod() - 1) * 100)
    gm = m.groupby(wk)["pct_chg_m"].apply(lambda x: ((1 + x / 100).prod() - 1) * 100)
    if len(gs) < 50 or gm.var() == 0:
        return None, None
    beta = float(gs.cov(gm) / gm.var())
    beta = min(3.0, max(0.3, beta))
    return round(beta, 2), round(float(gs.corr(gm) ** 2), 2)


def two_stage(base: float, g1: float, g: float, re: float, years: int = 5):
    """两阶段 FCFE 折现，返回股权价值（元）。re <= g 时返回 None。"""
    if re <= g:
        return None
    t = np.arange(1, years + 1)
    fcfe_t = base * (1 + g1) ** t
    pv_stage1 = (fcfe_t / (1 + re) ** t).sum()
    tv = fcfe_t[-1] * (1 + g) / (re - g)
    return float(pv_stage1 + tv / (1 + re) ** years)


def implied_g(base: float, g1: float, re: float, equity_value: float,
              years: int = 5, lo: float = -0.05):
    """反推当前市值隐含的永续增长率。无解/超界时返回 None。"""
    hi = re - 0.001
    v_hi = two_stage(base, g1, hi, re, years)
    if v_hi is None or v_hi < equity_value:
        return None                     # 永续增速贴满折现率仍撑不起现价
    v_lo = two_stage(base, g1, lo, re, years)
    if v_lo is not None and v_lo > equity_value:
        return None                     # 下界仍有富余 → 隐含增长为负且超界
    for _ in range(80):
        mid = (lo + hi) / 2
        v = two_stage(base, g1, mid, re, years)
        if v is None or v < equity_value:
            lo = mid
        else:
            hi = mid
    return round((lo + hi) / 2 * 100, 2)


def compute_dcf(code: str, rf: float = 2.5, erp: float = 6.0,
                g1: float | None = None, g: float = 2.5,
                base_mode: str = "avg3", base_override: float | None = None):
    """DCF 主入口。所有百分比参数以百分数传入（如 9 表示 9%）。"""
    ann = _fcfe_annual(code)
    annual = [{"year": d.year, "fcfe": round(v / 1e8, 2)}
              for d, v in zip(ann["end_date"], ann["fcfe"])][-10:]
    if len(ann) < 2:
        return {"applicable": False,
                "reason": "无 FCFE 数据（金融股或上市过短），DCF 不适用"}

    warnings = []
    annual_vals = ann[ann["end_date"].map(lambda d: d.month == 12)]["fcfe"]
    if len(annual_vals) >= 3:
        base_map = {
            "avg3": float(annual_vals.tail(3).mean()),
            "latest": float(annual_vals.iloc[-1]),
        }
    else:
        base_map = {"latest": float(annual_vals.iloc[-1])}
        warnings.append("年报不足 3 期，基数降级为最新年报")
    base_map["manual"] = base_override if base_override else None
    if base_mode not in base_map or base_map.get(base_mode) is None:
        base_mode = "latest" if "latest" in base_map else list(base_map)[0]
    base = base_map[base_mode]
    if base <= 0:
        warnings.append(f"FCFE 基数为负（{base/1e8:.1f} 亿），DCF 结果严重失真，仅供参考")

    # g1 默认：近 3 年年报 FCFE 复合增速，截断 [0%, 20%]
    if g1 is None and len(annual_vals) >= 3:
        first = annual_vals.iloc[-3]
        g1 = (0 if first <= 0 else
              min(20.0, max(0.0, ((annual_vals.iloc[-1] / first) ** (1 / 2) - 1) * 100)))
    if g1 is None:
        g1 = 10.0

    beta, r2 = beta_r2(code)
    if beta is None:
        beta = 1.0
        warnings.append("上市时间不足，β 无法回归，按 1.0 处理")
    if r2 is not None and r2 < 0.2:
        warnings.append(f"β 回归 R² 仅 {r2}，β 可靠性低")
    re = rf + beta * erp
    if re <= g / 100 + 0.001:
        warnings.append("折现率 Re ≤ 永续增速，参数无效，请调整")
        return {"applicable": False, "reason": "Re ≤ 永续增速（参数无效）",
                "beta": beta, "r2": r2, "re": round(re * 100, 2), "warnings": warnings}

    share = _total_share(code)
    price = _latest_price(code)
    equity = two_stage(base, g1 / 100, g / 100, re / 100)
    per_share = None if (equity is None or not share) else round(equity / share, 2)
    premium = (None if (per_share is None or not price)
               else round((price / per_share - 1) * 100, 1))

    # 敏感性矩阵：Re ±2pp（步进 1pp）× 永续 g 0~4%（步进 1pp）
    re_levels = [round(re - 2 + i, 1) for i in range(5)]
    g_levels = [0.0, 1.0, 2.0, 3.0, 4.0]
    matrix = []
    for re_l in re_levels:
        row = []
        for g_l in g_levels:
            eq = two_stage(base, g1 / 100, g_l / 100, re_l / 100)
            if eq is None or not share:
                row.append(None)
                continue
            ps = eq / share
            prem = None if not price else round((price / ps - 1) * 100, 0)
            row.append({"ps": round(ps, 2), "prem": prem})
        matrix.append({"re": re_l, "g": g_levels, "values": row})

    implied = None
    if equity is not None and share and price:
        implied = implied_g(base, g1 / 100, re / 100, price * share)

    return {
        "applicable": True,
        "code": code,
        "beta": beta, "r2": r2,
        "rf": rf, "erp": erp, "re": round(re, 2),
        "g1": g1, "g": g,
        "base_mode": base_mode, "base_fcfe": round(base / 1e8, 2),  # 亿元
        "share_yi": round(share / 1e8, 2) if share else None,        # 亿股
        "price": price,
        "per_share": per_share,
        "premium": premium,
        "implied_g": implied,
        "annual": annual,
        "matrix": matrix, "re_levels": re_levels, "g_levels": g_levels,
        "warnings": warnings,
    }
