"""tushare 数据同步：交易日历 + 全市场 A 股日线 + 复权因子。

用法（项目根目录，激活 venv 后）：
    python scripts/sync_data.py cal                        # 1) 先同步交易日历
    python scripts/sync_data.py backfill --start 20160101  # 2) 回补历史（近10年）
    python scripts/sync_data.py update                     # 3) 之后每天增量

特点：按交易日批量拉全市场；逐日幂等（先删后插，重跑无害）；
限流+失败重试；逐日落库行数校验（防接口截断）。
"""
import argparse
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import tushare as ts
from sqlalchemy import text

from app.config import TUSHARE_TOKEN
from app.database import Base, engine
import app.models  # noqa: F401  # 导入以注册模型

SLEEP = 0.25  # 每次 API 调用后的间隔（秒），可由 --sleep 覆盖
_pro = None

DAILY_COLS = ["ts_code", "trade_date", "open", "high", "low", "close",
              "pre_close", "change", "pct_chg", "vol", "amount"]
ADJ_COLS = ["ts_code", "trade_date", "adj_factor"]


def get_pro():
    global _pro
    if _pro is None:
        if not TUSHARE_TOKEN:
            sys.exit("[错误] 请先在 .env 填写 TUSHARE_TOKEN")
        _pro = ts.pro_api(TUSHARE_TOKEN)
    return _pro


def call_with_retry(desc, max_tries=5, **params):
    """带重试的 tushare 接口调用；遇到限流按 65s 等待（接口按分钟限频）。"""
    func_name = params.pop("func")
    func = getattr(get_pro(), func_name)
    for attempt in range(1, max_tries + 1):
        try:
            df = func(**params)
            time.sleep(SLEEP)
            return df
        except Exception as exc:
            rate_limited = "超限" in str(exc)
            wait = 65 if rate_limited else 5 * attempt
            if attempt == max_tries:
                sys.exit(f"[错误] {desc} 重试耗尽（{exc}），终止")
            print(f"    [重试] {desc} 失败: {exc}，{wait}s 后重试 {attempt}/{max_tries - 1}")
            time.sleep(wait)


def to_date(s):
    return pd.to_datetime(s, format="%Y%m%d").date()


def sync_cal():
    """同步上交所交易日历（4年一段，整表幂等重建；接口限流 1次/分钟 由重试自适应）。"""
    print("[1] 同步交易日历（trade_cal 限流 1次/分钟，分段间隔约 65s）...")
    frames = []
    for y0 in range(2015, 2028, 4):
        y1 = min(y0 + 3, 2027)
        if y0 > 2015:  # 首次调用后，主动等待避开限流
            print(f"    等待 65s（接口限流）...")
            time.sleep(65)
        df = call_with_retry(f"trade_cal {y0}-{y1}", func="trade_cal", exchange="SSE",
                             start_date=f"{y0}0101", end_date=f"{y1}1231")
        frames.append(df)
        print(f"    {y0}-{y1}: {len(df)} 行")
    cal = pd.concat(frames, ignore_index=True)
    cal = cal[["exchange", "cal_date", "is_open"]]
    cal["cal_date"] = cal["cal_date"].map(to_date)
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM trade_cal WHERE exchange = 'SSE'"))
        cal.to_sql("trade_cal", con=conn, if_exists="append", index=False,
                   chunksize=1000, method="multi")
        n = conn.execute(text(
            "SELECT COUNT(*) FROM trade_cal WHERE exchange='SSE' AND is_open=1"
        )).scalar()
    print(f"[OK] 日历共 {len(cal)} 天，其中交易日 {n} 天")


def open_dates(start: date, end: date):
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT cal_date FROM trade_cal WHERE exchange='SSE' AND is_open=1 "
            "AND cal_date BETWEEN :s AND :e ORDER BY cal_date"
        ), {"s": start, "e": end}).fetchall()
    if not rows:
        sys.exit("[错误] 没有可用的交易日，请先运行: python scripts/sync_data.py cal")
    return [r[0] for r in rows]


def sync_one_day(d):
    """同步单个交易日的日线与复权因子（先删后插，幂等）。"""
    ds = d.strftime("%Y%m%d")
    n_daily = n_adj = 0
    for table, cols, dropna_col in (("daily_bar", DAILY_COLS, "close"),
                                    ("adj_factor", ADJ_COLS, "adj_factor")):
        func = "daily" if table == "daily_bar" else "adj_factor"
        df = call_with_retry(f"{func} {ds}", func=func, trade_date=ds)
        if df is None or df.empty:
            print(f"  {ds} {table}: 接口无数据（可能尚未生成），跳过")
            continue
        df = df[cols].dropna(subset=[dropna_col])
        df["trade_date"] = df["trade_date"].map(to_date)
        with engine.begin() as conn:
            conn.execute(text(f"DELETE FROM {table} WHERE trade_date = :d"), {"d": d})
            df.to_sql(table, con=conn, if_exists="append", index=False,
                      chunksize=1000, method="multi")
            cnt = conn.execute(text(
                f"SELECT COUNT(*) FROM {table} WHERE trade_date = :d"
            ), {"d": d}).scalar()
        if cnt != len(df):
            print(f"  [警告] {ds} {table}: 期望 {len(df)} 行，实际落库 {cnt} 行！")
        if table == "daily_bar":
            n_daily = cnt
        else:
            n_adj = cnt
    return n_daily, n_adj


def run_dates(dates, label):
    total = len(dates)
    print(f"[{label}] 共 {total} 个交易日：{dates[0]} ~ {dates[-1]}")
    t0 = time.time()
    for i, d in enumerate(dates, 1):
        n_daily, n_adj = sync_one_day(d)
        step = 1 if total <= 50 else 50
        if i % step == 0 or i == total:
            elapsed = time.time() - t0
            eta = elapsed / i * (total - i)
            print(f"  进度 {i}/{total}（{d}，日线 {n_daily} 行）"
                  f" 已用 {elapsed/60:.1f}min 预计剩余 {eta/60:.1f}min")
    print(f"[OK] {label} 完成，用时 {(time.time()-t0)/60:.1f} 分钟")


def cmd_backfill(args):
    start = date(int(args.start[:4]), int(args.start[4:6]), int(args.start[6:8]))
    end = date.today() if not args.end else date(
        int(args.end[:4]), int(args.end[4:6]), int(args.end[6:8]))
    run_dates(open_dates(start, end), "回补")


def cmd_update(args):
    with engine.connect() as conn:
        maxd = conn.execute(text("SELECT MAX(trade_date) FROM daily_bar")).scalar()
    if maxd is None:
        sys.exit("[错误] 库里还没有日线数据，请先运行 backfill")
    dates = open_dates(maxd, date.today())
    if not dates:
        print("[OK] 已是最新，无需要同步的交易日")
        return
    dates = dates[1:] if dates[0] == maxd else dates  # 跳过已完成当天
    if not dates:
        print("[OK] 已是最新，无需要同步的交易日")
        return
    run_dates(dates, "增量")


def main():
    global SLEEP
    parser = argparse.ArgumentParser(description="tushare A股数据同步")
    sub = parser.add_subparsers(dest="cmd", required=True)

    def with_common(p):
        p.add_argument("--sleep", type=float, default=0.25, help="API 调用间隔秒数")
        return p

    with_common(sub.add_parser("cal", help="同步交易日历（首次必跑）"))

    p_backfill = with_common(sub.add_parser("backfill", help="回补历史日线"))
    p_backfill.add_argument("--start", required=True, help="开始日期 YYYYMMDD")
    p_backfill.add_argument("--end", default=None, help="结束日期，默认今天")

    with_common(sub.add_parser("update", help="增量同步到最新"))

    args = parser.parse_args()

    SLEEP = args.sleep
    Base.metadata.create_all(engine)  # 幂等建表

    {"cal": lambda: sync_cal(),
     "backfill": lambda: cmd_backfill(args),
     "update": lambda: cmd_update(args)}[args.cmd]()


if __name__ == "__main__":
    main()
