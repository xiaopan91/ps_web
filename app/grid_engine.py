"""网格交易回测引擎（等比对称网格，日线级）。

规则：
- 后复权价格上画格线 L_k = base × (1+g)^k
- 格线槽位：下穿未持有的线买入一格；上穿 L_m 时卖出在 L_{m-1} 买入的那格
  （卖线恒比买线高一格，每对往返固定赚一格间距）
- 每格资金 = 初始资金 ÷ N；份额按 100 股/份取整；满 N 格停买、清零停卖
- 日线数据一天只有净方向，买卖不会同日发生 → 天然满足 T+1
- 费用：佣金双边万2.5（最低5元）+ 卖出印花税千1（仅个股，ETF 免）
"""
import math

import pandas as pd
from sqlalchemy import text

from app.database import engine


def is_etf(code: str) -> bool:
    return (code.endswith(".SH") and code[:2] in ("51", "56", "58")) or \
           (code.endswith(".SZ") and code.startswith("15"))


# 常用网格标的（sync_data.py etf 子命令与策略页共用）
DEFAULT_ETFS = [
    ("510300.SH", "沪深300ETF"), ("510500.SH", "中证500ETF"),
    ("512880.SH", "证券ETF"), ("518880.SH", "黄金ETF"),
    ("513100.SH", "纳指ETF"), ("159915.SZ", "创业板ETF"),
    ("512690.SH", "酒ETF"), ("515790.SH", "光伏ETF"),
    ("512010.SH", "医药ETF"), ("510880.SH", "红利ETF"),
]


class GridBacktest:
    def __init__(self, code, start, end=None, grid_pct=5.0, n_grids=10,
                 cash=100000.0, fee_rate=2.5e-4, min_fee=5.0, stamp_tax=1e-3,
                 initial_grids=None):
        self.code = code
        self.start = start
        self.end = end or "2099-12-31"
        self.g = grid_pct / 100.0
        self.n = n_grids
        self.cash0 = cash
        self.fee_rate = fee_rate
        self.min_fee = min_fee
        self.stamp_tax = 0.0 if is_etf(code) else stamp_tax
        self.per_grid = cash / n_grids
        # 底仓格数：默认半仓（n//2）；起始日按收盘价建仓占用上方槽位，
        # 上涨逐格止盈、剩余现金作为下方格线子弹。0 = 空仓起步（旧行为）
        self.initial = min(initial_grids if initial_grids is not None
                           else max(n_grids // 2, 0), n_grids)

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
            raise ValueError(f"{self.code} 在 {self.start}~{self.end} 无数据")
        df["adj_factor"] = df["adj_factor"].astype(float).ffill().bfill()
        df["px"] = df["close"].astype(float) * df["adj_factor"]  # 后复权价
        df["trade_date"] = df["trade_date"].astype(str)
        return df

    def grid_pos(self, p):
        """价格所在格区间下标 k（价格 ∈ [L_k, L_{k+1})）。"""
        return math.floor(math.log(p / self.base) / math.log(1 + self.g) + 1e-9)

    def run(self):
        df = self.load()
        self.base = df["px"].iloc[0]

        cash = self.cash0
        shares = 0
        trades = []
        equity, dates = [], []

        prev_k = self.grid_pos(df["px"].iloc[0])
        held = {}  # 格线序号 -> (份额, 实际买入价)

        # 底仓：起始日按收盘价（=基准价）建 initial 格，占用槽位 0..initial-1
        first = df.iloc[0]
        for j in range(self.initial):
            qty = self._grid_qty_at(self.base)
            if qty <= 0 or cash < qty * self.base:
                break
            fee = max(qty * self.base * self.fee_rate, self.min_fee)
            cash -= qty * self.base + fee
            shares += qty
            held[j] = (qty, self.base)
            trades.append({"date": first["trade_date"], "side": "买",
                           "price": round(float(first["close"]), 4),
                           "qty": qty, "fee": round(fee, 2)})

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
                    held[m] = (qty, line)
                    trades.append({"date": d, "side": "买",
                                   "price": round(line / adj, 4),
                                   "qty": qty, "fee": round(fee, 2)})
            elif k > prev_k:  # 上穿格线 m ∈ [prev_k+1, k]：卖出 m-1 格的持仓
                for m in range(prev_k + 1, k + 1):
                    j = m - 1
                    if j not in held:
                        continue
                    qty, buy_px = held.pop(j)
                    line = self.base * (1 + self.g) ** m
                    fee = max(qty * line * self.fee_rate, self.min_fee) \
                          + qty * line * self.stamp_tax
                    cash += qty * line - fee
                    shares -= qty
                    trades.append({"date": d, "side": "卖",
                                   "price": round(line / adj, 4),
                                   "qty": qty, "fee": round(fee, 2),
                                   "pnl": round((line - buy_px) * qty, 2)})
            prev_k = k
            equity.append(cash + shares * px)
            dates.append(d)

        eq = pd.Series(equity, index=dates)
        bh = self.cash0 * df["px"] / df["px"].iloc[0]  # 买入持有
        tdf = pd.DataFrame(trades)
        sells = tdf[tdf["side"] == "卖"] if not tdf.empty else tdf
        wins = int((sells["pnl"] > 0).sum()) if not sells.empty else 0

        # 网格线绘制范围：名义网格 ±N，外扩覆盖价格实际区间（限 ±40 防线太密）
        jlo = min(-self.n, self.grid_pos(df["px"].min()) - 1)
        jhi = max(self.n, self.grid_pos(df["px"].max()) + 1)
        jlo, jhi = max(jlo, -40), min(jhi, 40)

        return {
            "dates": dates,
            "equity": [round(v, 2) for v in eq],
            "bh": [round(v, 2) for v in bh],
            "prices": [round(v, 4) for v in df["close"].astype(float)],
            "adj": [round(v, 6) for v in df["adj_factor"]],
            "base_hfq": self.base,
            "grid_pct": self.g * 100,
            "grid_jrange": [jlo, jhi],
            "trades": trades,
            "metrics": {
                "total_ret": eq.iloc[-1] / self.cash0 - 1,
                "bh_ret": bh.iloc[-1] / self.cash0 - 1,
                "ann_ret": (eq.iloc[-1] / self.cash0) ** (252 / len(eq)) - 1,
                "max_dd": (eq / eq.cummax() - 1).min(),
                "n_buys": int((tdf["side"] == "买").sum()) if not tdf.empty else 0,
                "n_sells": int((tdf["side"] == "卖").sum()) if not tdf.empty else 0,
                "win_rate": wins / len(sells) if len(sells) else None,
                "final_cash": round(cash, 2),
                "final_shares": shares,
            },
        }

    def _grid_qty_at(self, line):
        return int(self.per_grid / line / 100) * 100
