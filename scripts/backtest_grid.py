"""网格交易回测 CLI（引擎在 app/grid_engine.py）。

用法：
    python scripts/backtest_grid.py --code 510300.SH --start 20160101
    python scripts/backtest_grid.py --code 510300.SH --start 20160101 --scan
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.grid_engine import GridBacktest  # noqa: E402


def report(bt, r):
    m = r["metrics"]
    print(f"\n===== 网格回测 {bt.code} {bt.start}~{bt.end} =====")
    print(f"参数: 格距 {bt.g*100:.0f}% × 上下各 {bt.n} 格 | "
          f"初始 {bt.cash0:,.0f} | 每格 {bt.per_grid:,.0f}")
    print(f"网格:   总收益 {m['total_ret']*100:7.2f}% | 年化 "
          f"{m['ann_ret']*100:7.2f}% | 最大回撤 {m['max_dd']*100:6.2f}%")
    print(f"持有:   总收益 {m['bh_ret']*100:7.2f}%")
    print(f"交易:   买 {m['n_buys']} 次 / 卖 {m['n_sells']} 次 | "
          f"配对胜率 {(m['win_rate'] or 0)*100:.0f}%")
    print(f"期末:   现金 {m['final_cash']:,.0f} + 份额 {m['final_shares']}")


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
                row.append(bt.run()["metrics"]["ann_ret"] * 100)
            print(f"{p:>4}%  " + "".join(f"{v:>9.1f}" for v in row))
        return

    bt = GridBacktest(args.code, args.start, args.end, args.grid_pct,
                      args.n_grids, args.cash)
    r = bt.run()
    report(bt, r)
    if args.csv and r["trades"]:
        import pandas as pd
        pd.DataFrame(r["trades"]).to_csv(args.csv, index=False,
                                         encoding="utf-8-sig")
        print(f"交易明细已写入 {args.csv}")


if __name__ == "__main__":
    main()
