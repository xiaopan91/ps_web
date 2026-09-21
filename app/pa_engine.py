"""定投回测引擎：等额定投(DCA) / 等价值定投(VA) / 一次性买入(lump)。

纯函数、无 IO，输入日线收盘价序列，输出逐期与逐日账户序列及指标。
口径纪律：
- VA 目标路径 V(t) = C×t（线性，与 DCA 每期预算 C 同节奏，保证公平对比）
  或增长型 V(t) = C×t×(1+g)^((t-1)/12)（g 为路径年增速）；
- VA 每期交易额 = 目标路径 − 持仓市值，正买负卖（可关卖出），
  单期买入上限 k×C（Edleson 补丁，防深熊资金需求失控）；
- 卖出所得现金停留在账户内（零收益），期末账户 = 持仓市值 + 现金；
- 三策略现金流时点不同，收益对比以 XIRR 年化为准。
"""
import math
from datetime import date


def sample_period_idx(dates: list, freq: str) -> list:
    """返回每期首个交易日在日线数组中的下标。freq: month / week。"""
    if freq not in ("month", "week"):
        raise ValueError("freq 取值: month / week")
    seen, idx = set(), []
    for i, d in enumerate(dates):
        key = (d.year, d.month) if freq == "month" else d.isocalendar()[:2]
        if key not in seen:
            seen.add(key)
            idx.append(i)
    return idx


def xirr(flows: list) -> float | None:
    """年化内部收益率。flows: [(date, amount)]，投入为负、期末回收为正。

    二分法解 NPV=0；现金流无符号变化（全损或异常）时返回 None。
    """
    if len(flows) < 2:
        return None
    t0 = flows[0][0]

    def npv(rate):
        return sum(a / (1 + rate) ** ((d - t0).days / 365.0) for d, a in flows)

    lo, hi = -0.95, 20.0
    f_lo, f_hi = npv(lo), npv(hi)
    if f_lo == 0:
        return lo
    if f_lo * f_hi > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        f_mid = npv(mid)
        if abs(f_mid) < 1e-9:
            return mid
        if f_lo * f_mid < 0:
            hi = mid
        else:
            lo, f_lo = mid, f_mid
    return (lo + hi) / 2


def max_decline_pp(series: list) -> float:
    """序列自峰顶的最大回落幅度（百分点，正数）。用于收益率序列的回撤口径：
    收益率序列可正可负，按比值算回撤会在负值/小峰值区间失真。"""
    peak, mdd = -math.inf, 0.0
    for v in series:
        if v > peak:
            peak = v
        if peak - v > mdd:
            mdd = peak - v
    return round(mdd, 2)


def _simulate(closes: list, pidx: list, mode: str, amount: float,
              path_type: str = "linear", growth: float = 0.0,
              allow_sell: bool = True, max_k: float = 3.0) -> list[dict]:
    """逐期模拟。返回每期 {i, date, price, invest, contributed, shares, cash}。"""
    n = len(pidx)
    shares = cash = contributed = 0.0
    rows = []
    for j, i in enumerate(pidx, start=1):
        p = closes[i]
        if mode == "dca":
            trade = amount
        elif mode == "va":
            path = amount * j
            if path_type == "growth":
                path *= (1 + growth) ** ((j - 1) / 12.0)
            trade = path - shares * p
            if trade > 0 and max_k > 0:
                trade = min(trade, max_k * amount)
            if trade < 0 and not allow_sell:
                trade = 0.0
        elif mode == "lump":
            trade = amount * n if j == 1 else 0.0
        else:
            raise ValueError(f"未知定投模式: {mode}")
        if trade > 0:
            shares += trade / p
            contributed += trade
        elif trade < 0:
            shares += trade / p        # trade 为负即卖出
            cash -= trade
        rows.append({"i": i, "date": None, "price": round(p, 2),
                     "invest": round(trade, 2), "contributed": round(contributed, 2),
                     "shares": round(shares, 4), "cash": round(cash, 2)})
    return rows


def _strategy_result(dates: list, closes: list, pidx: list, rows: list[dict]) -> dict:
    """把逐期记录扩展为逐日账户序列并计算指标。"""
    # 期与期之间份额/现金不变，按日展开账户总值
    acc_daily, contrib_daily = [], []
    for j, r in enumerate(rows):
        lo = r["i"]
        hi = rows[j + 1]["i"] if j + 1 < len(rows) else len(closes)
        for i in range(lo, hi):
            acc_daily.append(round(r["shares"] * closes[i] + r["cash"], 2))
            contrib_daily.append(r["contributed"])
    if not acc_daily:
        return None

    total_in = sum(r["invest"] for r in rows if r["invest"] > 0)
    total_sold = sum(-r["invest"] for r in rows if r["invest"] < 0)
    n_sells = sum(1 for r in rows if r["invest"] < 0)
    buy_amount = total_in
    buy_shares = sum(r["invest"] / closes[r["i"]] for r in rows if r["invest"] > 0)
    final_account = acc_daily[-1]
    profit = final_account - total_in
    flows = [(dates[r["i"]], -r["invest"]) for r in rows if r["invest"] > 0]
    flows.append((dates[-1], final_account))
    rate = xirr(flows)
    # 回撤对「收益率序列」算（账户/累计投入 − 1）：持续投入会掩盖账户回撤
    ret_series = [round((a / c - 1) * 100, 2) for a, c in
                  zip(acc_daily, contrib_daily) if c > 0]

    return {
        "metrics": {
            "total_in": round(total_in, 2),
            "final_account": round(final_account, 2),
            "profit": round(profit, 2),
            "profit_pct": round(profit / total_in * 100, 2) if total_in else None,
            "xirr": round(rate * 100, 2) if rate is not None else None,
            "max_dd": max_decline_pp(ret_series),
            "avg_cost": round(buy_amount / buy_shares, 2) if buy_shares else None,
            "end_price": round(closes[-1], 2),
            "max_single_inject": round(max((r["invest"] for r in rows), default=0), 2),
            "total_sold": round(total_sold, 2),
            "n_sells": n_sells,
        },
        # 逐日序列（图用）
        "account": acc_daily,
        "contributed": contrib_daily,
        # 逐期序列（投入柱状图用）
        "p_dates": [dates[r["i"]] for r in rows],
        "p_invest": [round(r["invest"], 2) for r in rows],
    }


def backtest_all(dates: list, closes: list, freq: str = "month",
                 amount: float = 2000.0, path_type: str = "linear",
                 growth: float = 0.0, allow_sell: bool = True,
                 max_k: float = 3.0) -> dict:
    """三策略一起跑，输入全日线，输出各自逐日/逐期序列与指标。"""
    if len(dates) != len(closes) or not dates:
        raise ValueError("dates/closes 长度不一致或为空")
    pidx = sample_period_idx(dates, freq)
    if len(pidx) < 2:
        raise ValueError("样本期数不足（至少 2 期）")
    out = {"n_periods": len(pidx),
           "first": dates[pidx[0]].isoformat(), "last": dates[-1].isoformat()}
    for mode, name in (("dca", "dca"), ("va", "va"), ("lump", "lump")):
        rows = _simulate(closes, pidx, mode, amount, path_type, growth,
                         allow_sell, max_k)
        for r in rows:
            r["date"] = dates[r["i"]].isoformat()
        out[name] = _strategy_result(dates, closes, pidx, rows)
    return out
