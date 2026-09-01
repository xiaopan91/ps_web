"""tushare 数据同步：交易日历 / 股票信息 / 日线 / 复权 / 每日指标 /
两融 / 北向 / 指数 / 市场情绪聚合。

用法（项目根目录，激活 venv 后）：
    python scripts/sync_data.py cal                        # 交易日历（首次一次）
    python scripts/sync_data.py basic                      # 股票基本信息（偶尔刷新）
    python scripts/sync_data.py index                      # 13 只指数日线（范围式）
    python scripts/sync_data.py hsgt                       # 北向资金（范围式）
    python scripts/sync_data.py backfill --start 20160101  # 回补逐日数据（4接口/日）
    python scripts/sync_data.py update                     # 每日增量（收盘后跑，全量）
    python scripts/sync_data.py sentiment                  # 重算市场情绪表

特点：逐日数据先删后插幂等；限流自适应重试；落库行数校验。
"""
import argparse
import sys
import time
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import tushare as ts
from sqlalchemy import text

from app.config import TUSHARE_TOKEN
from app.database import Base, engine
from app.grid_engine import DEFAULT_ETFS
import app.models  # noqa: F401  # 导入以注册模型

SLEEP = 0.25  # 每次 API 调用后的间隔（秒），可由 --sleep 覆盖
_pro = None

DAILY_COLS = ["ts_code", "trade_date", "open", "high", "low", "close",
              "pre_close", "change", "pct_chg", "vol", "amount"]
ADJ_COLS = ["ts_code", "trade_date", "adj_factor"]
BASIC_DAILY_COLS = ["ts_code", "trade_date", "turnover_rate", "turnover_rate_f",
                    "volume_ratio", "pe", "circ_mv", "total_mv"]
MARGIN_COLS = ["trade_date", "exchange_id", "rzye", "rzmre", "rzche",
               "rqye", "rzrqye"]

INDICES = [  # 13 只核心/风格指数
    ("000001.SH", "上证指数"), ("399001.SZ", "深证成指"), ("000300.SH", "沪深300"),
    ("000905.SH", "中证500"), ("000852.SH", "中证1000"), ("399303.SZ", "国证2000"),
    ("000016.SH", "上证50"), ("000688.SH", "科创50"), ("399006.SZ", "创业板指"),
    ("399673.SZ", "创业板50"), ("399005.SZ", "中小100"), ("000015.SH", "上证红利"),
    ("399102.SZ", "创业板综"),
]

# 涨跌停幅度判定（ST 主板 5%），用于情绪计算
LIMIT_RATE_SQL = """
  CASE
    WHEN d.ts_code LIKE '%.BJ' THEN 0.30
    WHEN d.ts_code LIKE '30%' OR d.ts_code LIKE '68%' THEN 0.20
    WHEN b.name LIKE '%ST%' THEN 0.05
    ELSE 0.10
  END
"""


def get_pro():
    global _pro
    if _pro is None:
        if not TUSHARE_TOKEN:
            sys.exit("[错误] 请先在 .env 填写 TUSHARE_TOKEN")
        _pro = ts.pro_api(TUSHARE_TOKEN)
    return _pro


def call_with_retry(desc, max_tries=5, **params):
    """带重试的 tushare 接口调用；限流错误按 65s 等待（接口按分钟限频）。"""
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


def _delete_insert(table, df, where_sql, params):
    with engine.begin() as conn:
        conn.execute(text(f"DELETE FROM {table} WHERE {where_sql}"), params)
        df.to_sql(table, con=conn, if_exists="append", index=False,
                  chunksize=1000, method="multi")
        return conn.execute(text(f"SELECT COUNT(*) FROM {table} WHERE {where_sql}"),
                            params).scalar()


def _delete_insert_range(table, df, code):
    """按代码 + 拉取区间删除后插入（增量同步安全版：绝不触碰区间外历史）。"""
    lo, hi = df["trade_date"].min(), df["trade_date"].max()
    with engine.begin() as conn:
        conn.execute(text(
            f"DELETE FROM {table} WHERE ts_code = :c AND trade_date BETWEEN :lo AND :hi"),
            {"c": code, "lo": lo, "hi": hi})
        df.to_sql(table, con=conn, if_exists="append", index=False,
                  chunksize=1000, method="multi")
        return conn.execute(text(
            f"SELECT COUNT(*) FROM {table} WHERE ts_code = :c "
            "AND trade_date BETWEEN :lo AND :hi"),
            {"c": code, "lo": lo, "hi": hi}).scalar()


# ---------------------------------------------------------------- 基础同步

def sync_basic():
    """同步在市股票基本信息（整表先删后插）。"""
    print("[1] 同步股票基本信息 stock_basic ...")
    df = call_with_retry("stock_basic", func="stock_basic", exchange="",
                         list_status="L",
                         fields="ts_code,symbol,name,area,industry,market,list_date")
    df["list_date"] = df["list_date"].map(
        lambda s: pd.to_datetime(s, format="%Y%m%d").date() if s else None)
    n = _delete_insert("stock_basic", df, "1=1", {})
    print(f"[OK] 共 {n} 只在市股票")


def sync_cal():
    """同步上交所交易日历（4年一段；接口限流由重试自适应）。"""
    print("[1] 同步交易日历（trade_cal 限流严格，分段间隔约 65s）...")
    frames = []
    for y0 in range(2015, 2028, 4):
        y1 = min(y0 + 3, 2027)
        if y0 > 2015:
            print("    等待 65s（接口限流）...")
            time.sleep(65)
        df = call_with_retry(f"trade_cal {y0}-{y1}", func="trade_cal", exchange="SSE",
                             start_date=f"{y0}0101", end_date=f"{y1}1231")
        frames.append(df)
        print(f"    {y0}-{y1}: {len(df)} 行")
    cal = pd.concat(frames, ignore_index=True)[["exchange", "cal_date", "is_open"]]
    cal["cal_date"] = cal["cal_date"].map(to_date)
    n = _delete_insert("trade_cal", cal, "exchange = 'SSE'", {})
    print(f"[OK] 日历共 {n} 天")


def sync_index(full=False):
    """同步 13 只指数日线（逐指数 4 年分段，自增补差；full=True 强制从 2015 全量）。"""
    print(f"[index] 同步 {len(INDICES)} 只指数日线{'（强制全量）' if full else ''} ...")
    total_new = 0
    for code, name in INDICES:
        with engine.connect() as conn:
            mx = conn.execute(text(
                "SELECT MAX(trade_date) FROM index_daily WHERE ts_code = :c"
            ), {"c": code}).scalar()
        start = date(2015, 1, 1) if full else \
            ((mx + timedelta(days=1)) if mx else date(2015, 1, 1))
        if start > date.today():
            print(f"  {name} {code}: 已最新")
            continue
        frames = []
        y0 = start.year
        while y0 <= date.today().year:
            y1 = min(y0 + 3, date.today().year)
            s = max(start, date(y0, 1, 1)).strftime("%Y%m%d")
            e = min(date(y1, 12, 31), date.today()).strftime("%Y%m%d")
            if s <= e:
                df = call_with_retry(f"index_daily {code} {y0}", func="index_daily",
                                     ts_code=code, start_date=s, end_date=e)
                frames.append(df)
            y0 += 4
        if not frames:
            print(f"  {name} {code}: 无新数据")
            continue
        df = pd.concat(frames, ignore_index=True)
        df = df[["ts_code", "trade_date", "open", "high", "low", "close",
                 "pct_chg", "vol", "amount"]]
        df["trade_date"] = df["trade_date"].map(to_date)
        n = _delete_insert_range("index_daily", df, code)
        total_new += len(df)
        print(f"  {name} {code}: +{len(df)} 行（区间内 {n}）")
    print(f"[OK] 指数共新增 {total_new} 行")




def sync_etf(codes=None, full=False):
    """同步 ETF 信息与日线。codes 为空用默认清单；full=True 强制从 2015 全量。
    复权因子写入 adj_factor 表（结构与个股一致、代码空间不冲突，回测统一读取）。"""
    print("[etf] 同步基金基本信息 fund_basic ...")
    df = call_with_retry("fund_basic", func="fund_basic", market="E",
                         fields="ts_code,name,management,fund_type,list_date,market")
    df = df[["ts_code", "name", "management", "fund_type", "list_date", "market"]]
    df["list_date"] = df["list_date"].map(
        lambda s: pd.to_datetime(s, format="%Y%m%d").date() if s else None)
    n = _delete_insert("fund_basic", df, "1=1", {})
    print(f"[OK] 共 {n} 只 ETF")

    targets = codes if codes else [c for c, _ in DEFAULT_ETFS]
    print(f"[etf] 同步 {len(targets)} 只 ETF 日线（4年分段，自增补差）...")
    for code in targets:
        # fund_daily
        with engine.connect() as conn:
            mx = conn.execute(text(
                "SELECT MAX(trade_date) FROM fund_daily WHERE ts_code = :c"
            ), {"c": code}).scalar()
        start = date(2015, 1, 1) if full else \
            ((mx + timedelta(days=1)) if mx else date(2015, 1, 1))
        if start > date.today():
            print(f"  {code} fund_daily: 已最新")
        else:
            frames = []
            y0 = start.year
            while y0 <= date.today().year:
                y1 = min(y0 + 3, date.today().year)
                s = max(start, date(y0, 1, 1)).strftime("%Y%m%d")
                e = min(date(y1, 12, 31), date.today()).strftime("%Y%m%d")
                if s <= e:
                    frames.append(call_with_retry(f"fund_daily {code} {y0}",
                                                  func="fund_daily", ts_code=code,
                                                  start_date=s, end_date=e))
                y0 += 4
            if frames:
                df = pd.concat(frames, ignore_index=True)
                df = df[["ts_code", "trade_date", "open", "high", "low",
                         "close", "vol", "amount"]]
                df["trade_date"] = df["trade_date"].map(to_date)
                cnt = _delete_insert_range("fund_daily", df, code)
                print(f"  {code} fund_daily: +{len(df)} 行（区间内 {cnt}）")

        # fund_adj → adj_factor 表（区间内重建）
        with engine.connect() as conn:
            mx = conn.execute(text(
                "SELECT MAX(trade_date) FROM adj_factor WHERE ts_code = :c"
            ), {"c": code}).scalar()
        start = date(2015, 1, 1) if full else \
            ((mx + timedelta(days=1)) if mx else date(2015, 1, 1))
        if start > date.today():
            continue
        frames = []
        y0 = start.year
        while y0 <= date.today().year:
            y1 = min(y0 + 3, date.today().year)
            s = max(start, date(y0, 1, 1)).strftime("%Y%m%d")
            e = min(date(y1, 12, 31), date.today()).strftime("%Y%m%d")
            if s <= e:
                frames.append(call_with_retry(f"fund_adj {code} {y0}",
                                              func="fund_adj", ts_code=code,
                                              start_date=s, end_date=e))
            y0 += 4
        if frames:
            df = pd.concat(frames, ignore_index=True)[["ts_code", "trade_date",
                                                       "adj_factor"]]
            df["trade_date"] = df["trade_date"].map(to_date)
            lo, hi = df["trade_date"].min(), df["trade_date"].max()
            with engine.begin() as conn:
                conn.execute(text(
                    "DELETE FROM adj_factor WHERE ts_code = :c "
                    "AND trade_date BETWEEN :lo AND :hi"),
                    {"c": code, "lo": lo, "hi": hi})
                df.to_sql("adj_factor", con=conn, if_exists="append", index=False,
                          chunksize=1000, method="multi")
            print(f"  {code} adj_factor: {len(df)} 行（区间内重建）")


def sync_hsgt():
    """同步沪深港通资金流向（按年分段——接口单次约 300 行上限，自增补差）。"""
    print("[hsgt] 同步北向资金（按年分段）...")
    frames = []
    y0 = 2014
    while y0 <= date.today().year:
        s = f"{y0}0101"
        e = min(date(y0, 12, 31), date.today()).strftime("%Y%m%d")
        df = call_with_retry(f"hsgt {y0}", func="moneyflow_hsgt",
                             start_date=s, end_date=e)
        with engine.connect() as conn:
            expect = conn.execute(text(
                "SELECT COUNT(*) FROM trade_cal WHERE exchange='SSE' AND is_open=1 "
                "AND cal_date BETWEEN :s AND :e"),
                {"s": f"{y0}-01-01", "e": e[:4] + "-" + e[4:6] + "-" + e[6:]}
            ).scalar()
        if expect and len(df) and len(df) < expect - 15:
            print(f"  [警告] {y0} 年返回 {len(df)} 行 < 交易日 {expect}，可能仍被截断"
                  f"（少量缺口为港股通休市，属正常）")
        frames.append(df)
        print(f"  {y0}: {len(df)} 行")
        y0 += 1
    df = pd.concat(frames, ignore_index=True)
    df = df[["trade_date", "north_money", "south_money", "hgt", "sgt"]]
    for c in ("north_money", "south_money", "hgt", "sgt"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["trade_date"] = df["trade_date"].map(to_date)
    df = df.dropna(subset=["trade_date"]).drop_duplicates("trade_date")
    n = _delete_insert("hsgt_flow", df, "1=1", {})
    print(f"[OK] 北向共 {n} 日")


# ---------------------------------------------------------------- 逐日同步

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
    """同步单个交易日的日线/复权/每日指标/两融（各表先删后插，幂等）。"""
    ds = d.strftime("%Y%m%d")
    counts = {}

    specs = [
        ("daily_bar", "daily", DAILY_COLS, "close", "trade_date"),
        ("adj_factor", "adj_factor", ADJ_COLS, "adj_factor", "trade_date"),
        ("daily_basic", "daily_basic", BASIC_DAILY_COLS, "turnover_rate_f", "trade_date"),
    ]
    for table, func, cols, dropna_col, _ in specs:
        df = call_with_retry(f"{func} {ds}", func=func, trade_date=ds)
        if df is None or df.empty:
            continue
        df = df[cols].dropna(subset=[dropna_col])
        df["trade_date"] = df["trade_date"].map(to_date)
        cnt = _delete_insert(table, df, "trade_date = :d", {"d": d})
        if cnt != len(df):
            print(f"  [警告] {ds} {table}: 期望 {len(df)} 行，实际 {cnt} 行！")
        counts[table] = cnt

    # 两融（每交易所一行，不带 ts_code 维度）
    df = call_with_retry(f"margin {ds}", func="margin", trade_date=ds)
    if df is not None and not df.empty:
        df = df[MARGIN_COLS].dropna(subset=["rzye"])
        df["trade_date"] = df["trade_date"].map(to_date)
        cnt = _delete_insert("margin_daily", df, "trade_date = :d", {"d": d})
        counts["margin_daily"] = cnt
    return counts


def run_dates(dates, label):
    total = len(dates)
    print(f"[{label}] 共 {total} 个交易日：{dates[0]} ~ {dates[-1]}")
    t0 = time.time()
    for i, d in enumerate(dates, 1):
        sync_one_day(d)
        step = 1 if total <= 50 else 50
        if i % step == 0 or i == total:
            elapsed = time.time() - t0
            eta = elapsed / i * (total - i)
            print(f"  进度 {i}/{total}（{d}）已用 {elapsed/60:.1f}min "
                  f"预计剩余 {eta/60:.1f}min")
    print(f"[OK] {label} 完成，用时 {(time.time()-t0)/60:.1f} 分钟")


def cmd_backfill(args):
    start = date(int(args.start[:4]), int(args.start[4:6]), int(args.start[6:8]))
    end = date.today() if not args.end else date(
        int(args.end[:4]), int(args.end[4:6]), int(args.end[6:8]))
    run_dates(open_dates(start, end), "回补")


def cmd_update(args):
    with engine.connect() as conn:
        maxd = conn.execute(text("SELECT MAX(trade_date) FROM daily_bar")).scalar()
        mind = conn.execute(text("SELECT MIN(trade_date) FROM daily_bar")).scalar()
    if maxd is None:
        sys.exit("[错误] 库里还没有日线数据，请先运行 backfill")

    # 空洞自愈：已覆盖区间内缺失的交易日（防中间断档，补上）
    with engine.connect() as conn:
        holes = [r[0] for r in conn.execute(text(
            "SELECT t.cal_date FROM trade_cal t "
            "WHERE t.exchange='SSE' AND t.is_open=1 AND t.cal_date BETWEEN :lo AND :hi "
            "AND NOT EXISTS (SELECT 1 FROM daily_bar d WHERE d.trade_date = t.cal_date) "
            "ORDER BY t.cal_date"), {"lo": mind, "hi": maxd})]
    if holes:
        print(f"[体检] 发现 {len(holes)} 个缺失交易日，先补洞: {holes[0]} ~ {holes[-1]}")
        run_dates(holes, "补洞")
    else:
        print("[体检] 已覆盖区间无缺口")

    dates = open_dates(maxd, date.today())
    dates = dates[1:] if dates and dates[0] == maxd else dates
    if dates:
        run_dates(dates, "增量")
    else:
        print("[INFO] 日线已最新")
    sync_index()
    recompute_sentiment()


# ---------------------------------------------------------------- 情绪计算

def recompute_sentiment(start=None):
    """从底层数据表聚合重算 market_sentiment（start 仅限定落库范围）。"""
    print("[sentiment] 聚合市场情绪 ...")
    t0 = time.time()

    with engine.connect() as conn:
        # 1) 广度 / 量能 / 均值 / 离散度（纯 SQL 聚合，全历史）
        agg = pd.read_sql(text("""
            SELECT trade_date,
                   SUM(pct_chg > 0) AS up_count, SUM(pct_chg < 0) AS down_count,
                   SUM(pct_chg = 0) AS flat_count,
                   SUM(CAST(amount AS DOUBLE)) * 1000 AS total_amount,
                   AVG(CAST(pct_chg AS DOUBLE)) AS mean_pct,
                   STDDEV_POP(CAST(pct_chg AS DOUBLE)) AS std_pct
            FROM daily_bar GROUP BY trade_date ORDER BY trade_date
        """), conn)

        # 2) 涨跌停家数（按板块/ST 阈值自算）
        lu = pd.read_sql(text(f"""
            SELECT trade_date,
                   SUM(close >= ROUND(pre_close * (1 + {LIMIT_RATE_SQL}), 2) - 0.0001) AS limit_up,
                   SUM(close <= ROUND(pre_close * (1 - {LIMIT_RATE_SQL}), 2) + 0.0001) AS limit_down
            FROM daily_bar d LEFT JOIN stock_basic b ON b.ts_code = d.ts_code
            GROUP BY trade_date ORDER BY trade_date
        """), conn)

        # 3) 中位数（pandas 算，SQL 无 MEDIAN）
        med = pd.read_sql(text(
            "SELECT trade_date, CAST(pct_chg AS DOUBLE) AS pct FROM daily_bar"
        ), conn)
        median_pct = med.groupby("trade_date")["pct"].median().rename("median_pct")
        del med

        # 4) 连板高度（近两年窗口，pandas run-length）
        streak_max = None
        try:
            since = (date.today() - timedelta(days=730)).strftime("%Y-%m-%d")
            lu_flag = pd.read_sql(text(f"""
                SELECT d.ts_code, d.trade_date,
                       (d.close >= ROUND(d.pre_close * (1 + {LIMIT_RATE_SQL}), 2) - 0.0001) AS is_lu
                FROM daily_bar d LEFT JOIN stock_basic b ON b.ts_code = d.ts_code
                WHERE d.trade_date >= :s
            """), conn, params={"s": since})
            if len(lu_flag):
                lu_flag["is_lu"] = lu_flag["is_lu"].fillna(False).astype(bool)
                lu_flag = lu_flag.sort_values(["ts_code", "trade_date"])
                # 连板 run-length：涨停状态变化处开新组，组内 cumcount 即连板天数
                prev = lu_flag.groupby("ts_code")["is_lu"].shift(fill_value=False)
                lu_flag["grp"] = (lu_flag["is_lu"] != prev).groupby(
                    lu_flag["ts_code"]).cumsum()
                lu_flag["streak"] = lu_flag.groupby(
                    ["ts_code", "grp"]).cumcount() + 1
                lu_flag.loc[~lu_flag["is_lu"], "streak"] = 0
                streak_max = lu_flag[lu_flag["streak"] > 0].groupby(
                    "trade_date")["streak"].max().rename("max_streak")
            del lu_flag
        except Exception as exc:
            print(f"  [警告] 连板计算失败（置空）: {exc}")

        # 5) 换手 / 两融 / 北向 / 上证
        to = pd.read_sql(text(
            "SELECT trade_date, AVG(CAST(turnover_rate_f AS DOUBLE)) AS avg_turnover_f "
            "FROM daily_basic GROUP BY trade_date"), conn)
        mg = pd.read_sql(text(
            "SELECT trade_date, SUM(CAST(rzye AS DOUBLE)) AS margin_balance, "
            "SUM(CAST(rzmre AS DOUBLE)) - SUM(CAST(rzche AS DOUBLE)) AS margin_net_buy "
            "FROM margin_daily GROUP BY trade_date"), conn)
        nh = pd.read_sql(text(
            "SELECT trade_date, CAST(north_money AS DOUBLE) AS north_net "
            "FROM hsgt_flow"), conn)
        sh = pd.read_sql(text(
            "SELECT trade_date, CAST(pct_chg AS DOUBLE) AS sh_pct "
            "FROM index_daily WHERE ts_code = '000001.SH'"), conn)

    df = (agg.set_index("trade_date")
             .join(lu.set_index("trade_date"))
             .join(median_pct)
             .join(to.set_index("trade_date"))
             .join(mg.set_index("trade_date"))
             .join(nh.set_index("trade_date"))
             .join(sh.set_index("trade_date")))
    if streak_max is not None:
        df = df.join(streak_max)
    df["max_streak"] = df.get("max_streak")

    # 量能比 = 5日均额 / 20日均额；背离 = 中位数 - 上证
    df["amount_ratio"] = (df["total_amount"].rolling(5).mean()
                          / df["total_amount"].rolling(20).mean())
    df["divergence"] = df["median_pct"] - df["sh_pct"]

    df = df.reset_index().rename(columns={"index": "trade_date"})
    if start:
        df = df[df["trade_date"] >= start]

    n = _delete_insert("market_sentiment", df,
                       "trade_date >= :s" if start else "1=1",
                       {"s": start} if start else {})
    print(f"[OK] 情绪表 {n} 日，用时 {time.time()-t0:.0f}s")


def main():
    global SLEEP
    parser = argparse.ArgumentParser(description="tushare A股数据同步")
    sub = parser.add_subparsers(dest="cmd", required=True)

    def with_common(p):
        p.add_argument("--sleep", type=float, default=0.25, help="API 调用间隔秒数")
        return p

    with_common(sub.add_parser("cal", help="同步交易日历（首次必跑）"))
    with_common(sub.add_parser("basic", help="同步股票基本信息"))
    p_index = with_common(sub.add_parser("index", help="同步 13 只指数日线"))
    p_index.add_argument("--full", action="store_true",
                         help="忽略断点，从 2015 强制全量重拉")
    with_common(sub.add_parser("hsgt", help="同步北向资金"))
    p_etf = with_common(sub.add_parser("etf", help="同步 ETF 信息与常用标的日线"))
    p_etf.add_argument("--full", action="store_true",
                       help="忽略断点，从 2015 强制全量重拉")
    p_etf.add_argument("--codes", default=None,
                       help="逗号分隔的 ETF 代码，默认常用网格标的清单")

    p_backfill = with_common(sub.add_parser("backfill", help="回补历史（日线/复权/指标/两融）"))
    p_backfill.add_argument("--start", required=True, help="开始日期 YYYYMMDD")
    p_backfill.add_argument("--end", default=None, help="结束日期，默认今天")

    with_common(sub.add_parser("update", help="每日增量同步（全量）"))
    p_sent = with_common(sub.add_parser("sentiment", help="重算市场情绪表"))
    p_sent.add_argument("--start", default=None, help="仅重算该日期起（YYYYMMDD）")

    args = parser.parse_args()

    SLEEP = args.sleep
    Base.metadata.create_all(engine)  # 幂等建表

    if args.cmd == "backfill":
        cmd_backfill(args)
    elif args.cmd == "update":
        cmd_update(args)
    elif args.cmd == "sentiment":
        s = (date(int(args.start[:4]), int(args.start[4:6]), int(args.start[6:8]))
             if args.start else None)
        recompute_sentiment(s)
    else:
        {"cal": sync_cal, "basic": sync_basic,
         "index": lambda: sync_index(full=args.full),
         "hsgt": sync_hsgt,
         "etf": lambda: sync_etf(args.codes.split(",") if args.codes else None,
                                 full=args.full)
         }[args.cmd]()


if __name__ == "__main__":
    main()
