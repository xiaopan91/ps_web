"""网格交易回测器（等比对称网格，日线级）。

规则：
- 后复权价格上画格线 L_k = base × (1+g)^k，k ∈ [-N, +N]
- 收盘价移动导致每下穿一条格线买入一格、每上穿一条格线卖出一格，
  成交价 = 格线价（模拟网格限价单）；跳空穿越多格全部成交
- 每格资金 = 初始资金 ÷ N；份额按 100 股/份取整
- 边界：满 N 格后不再买（单边跌满仓）、清零后不再卖（单边涨空仓）
- 日线数据一天只有净方向，买卖不会同日发生 → 天然满足 T+1
- 费用：佣金双边万2.5（最低5元）+ 卖出印花税千1（仅个股，ETF 免）

用法：
    python scripts/backtest_grid.py --code 510300.SH --start 20160101
    python scripts/backtest_grid.py --code 510300.SH --start 20160101 --scan
"""
import argparse
import math
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
from sqlalchemy import text

from app.database import engine


def is_etf(code: str) -> bool:
    return (code.endswith(".SH") and code[:2] in ("51", "56", "58")) or \
           (code.endswith(".SZ") and code.startswith("15"))


class GridBacktest:
    def __init__(self, code, start, end=None, grid_pct=5.0, n_grids=10,
                 cash=100000.0, fee_rate=2.5e-4, min_fee=5.0, stamp_tax=1e-3):
        self.code = code
        self.start = start
        self.end = end or date.today().isoformat()
        self.g = grid_pct / 100.0
        self.n = n_grids
        self.cash0 = cash
        self.fee_rate = fee_rate
        self.min_fee = min_fee
        self.stamp_tax = 0.0 if is_etf(code) else stamp_tax
        self.per_grid = cash / n_grids

    def load(self):
        table = "fund_daily" if is_etf(self.code) else "daily_bar"
        df = pd.read_sql(text(f"""
            SELECT t.trade_date, t.close, a.adj_factor
            FROM {table} t LEFT JOIN adj_factor a
              ON a.ts_code = t.ts_code AND a.trade_date = t.trade_date
            WHERE t.ts_code = :c AND t.trade_date BETWEEN :s AND :e
            ORDER BY t.trade_date
        """), engine, params={"c": self.code, "s": self.start, "e": self.end})
        if df.empty:
            sys.exit(f"[错误] {self.code} 在 {self.start}~{self.end} 无数据"
                     f"（ETF 先运行 sync_data.py etf）")
        df["adj_factor"] = df["adj_factor"].astype(float).ffill().bfill()
        df["px"] = df["close"].astype(float) * df["adj_factor"]  # 后复权价
        df["trade_date"] = df["trade_date"].astype(str)
        return df

    def grid_pos(self, p):
        """价格所在格区间下标 k（价格 ∈ [L_k, L_{k+1})）。"""
        return math.floor(math.log(p / self.base) / math.log(1 + self.g) + 1e-9)

    def run(self, verbose=False):
        df = self.load()
        self.base = df["px"].iloc[0]

        cash = self.cash0
        shares = 0
        trades = []
        equity, dates = [], []

        prev_k = self.grid_pos(df["px"].iloc[0])
        # 持仓槽位：格线序号 -> 该格买入份额。下穿未持有的线买入一格；
        # 上穿 L_m 时卖出在 L_{m-1} 买入的那格（卖线恒比买线高一格，往返赚一格间距）
        held = {}
        for _, row in df.iterrows():
            d, px, adj = row["trade_date"], row["px"], row["adj_factor"]
            k = self.grid_pos(px)

            if k < prev_k:  # 下穿格线 m ∈ [k+1, prev_k]：未持有的买入
                for m in range(prev_k, k, -1):
                    if m in held or len(held) >= self.n or cash <= 0:
                        continue
                    line = self.base * (1 + self.g) ** m
                    qty = self._grid_qty_at(line)
                    if qty == 0 or cash < qty * line:
                        qty = min(qty, int(cash / line / 100) * 100)
                    if qty <= 0 or cash < qty * line:
                        continue
                    fee = max(qty * line * self.fee_rate, self.min_fee)
                    cash -= qty * line + fee
                    shares += qty
                    held[m] = qty
                    trades.append((d, "买", line / adj, qty, fee))
            elif k > prev_k:  # 上穿格线 m ∈ [prev_k+1, k]：卖出 m-1 格的持仓
                for m in range(prev_k + 1, k + 1):
                    j = m - 1
                    if j not in held:
                        continue
                    buy_line = self.base * (1 + self.g) ** j
                    line = self.base * (1 + self.g) ** m
                    qty = held.pop(j)
                    fee = max(qty * line * self.fee_rate, self.min_fee) \
                          + qty * line * self.stamp_tax
                    cash += qty * line - fee
                    shares -= qty
                    trades.append((d, "卖", line / adj, qty, fee,
                                   (line - buy_line) * qty))
            prev_k = k

            prev_k = k
            equity.append(cash + shares * px)
            dates.append(d)

        eq = pd.Series(equity, index=dates)
        bh = self.cash0 * df["px"] / df["px"].iloc[0]  # 买入持有
        tdf = pd.DataFrame(trades,
                           columns=["date", "side", "price", "qty", "fee", "pnl"]
                           ) if trades else pd.DataFrame(
                           columns=["date", "side", "price", "qty", "fee", "pnl"])
        sells = tdf[tdf["side"] == "卖"] if not tdf.empty else tdf
        wins = (sells["pnl"] > 0).sum() if not sells.empty else 0

        result = {
            "equity": eq, "bh": bh, "trades": tdf,
            "total_ret": eq.iloc[-1] / self.cash0 - 1,
            "bh_ret": bh.iloc[-1] / self.cash0 - 1,
            "ann_ret": (eq.iloc[-1] / self.cash0) ** (252 / len(eq)) - 1,
            "max_dd": (eq / eq.cummax() - 1).min(),
            "n_trades": int((tdf["side"] == "买").sum()) if not tdf.empty else 0,
            "n_sells": int((tdf["side"] == "卖").sum()) if not tdf.empty else 0,
            "win_rate": wins / len(sells) if len(sells) else None,
            "final_cash": cash, "final_shares": shares,
        }
        if verbose:
            self._report(result)
        return result

    def _grid_qty_at(self, line):
        return int(self.per_grid / line / 100) * 100

    def _report(self, r):
        print(f"\n===== 网格回测 {self.code} {self.start}~{self.end} =====")
        print(f"参数: 格距 {self.g*100:.0f}% × 上下各 {self.n} 格 | "
              f"初始 {self.cash0:,.0f} | 每格 {self.per_grid:,.0f}")
        print(f"网格:   总收益 {r['total_ret']*100:7.2f}% | 年化 "
              f"{r['ann_ret']*100:7.2f}% | 最大回撤 {r['max_dd']*100:6.2f}%")
        print(f"持有:   总收益 {r['bh_ret']*100:7.2f}%")
        print(f"交易:   买 {r['n_trades']} 次 / 卖 {r['n_sells']} 次 | "
              f"配对胜率 {(r['win_rate'] or 0)*100:.0f}%")
        print(f"期末:   现金 {r['final_cash']:,.0f} + 份额 {r['final_shares']}")


def main():
    parser = argparse.ArgumentParser(description="网格交易回测")
    parser.add_argument("--code", required=True, help="标的代码，如 510300.SH")
    parser.add_argument("--start", required=True, help="开始日期 YYYYMMDD")
    parser.add_argument("--end", default=None)
    parser.add_argument("--grid-pct", type=float, default=5.0, help="格距百分比")
    parser.add_argument("--n-grids", type=int, default=10, help="上下各几格")
    parser.add_argument("--cash", type=float, default=100000)
    parser.add_argument("--scan", action="store_true", help="参数扫描热力图")
    parser.add_argument("--csv", default=None, help="交易明细输出 CSV 路径")
    args = parser.parse_args()

    if args.scan:
        print(f"\n参数扫描 {args.code}（年化收益 %，行=格距，列=格数）")
        pcts = [2, 3, 4, 5, 6, 8, 10]
        grids = [5, 8, 10, 15, 20]
        print("      " + "".join(f"{g:>8}格" for g in grids))
        for p in pcts:
            row = []
            for g in grids:
                bt = GridBacktest(args.code, args.start, args.end, p, g, args.cash)
                row.append(bt.run()["ann_ret"] * 100)
            print(f"{p:>4}%  " + "".join(f"{v:>9.1f}" for v in row))
        return

    bt = GridBacktest(args.code, args.start, args.end, args.grid_pct,
                      args.n_grids, args.cash)
    r = bt.run(verbose=True)
    if args.csv and not r["trades"].empty:
        r["trades"].to_csv(args.csv, index=False, encoding="utf-8-sig")
        print(f"交易明细已写入 {args.csv}")


if __name__ == "__main__":
    main()
