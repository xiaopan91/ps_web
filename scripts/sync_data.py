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
import numpy as np
import tushare as ts
from sqlalchemy import bindparam, text

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
                    "volume_ratio", "pe", "pe_ttm", "circ_mv", "total_mv"]
MARGIN_COLS = ["trade_date", "exchange_id", "rzye", "rzmre", "rzche",
               "rqye", "rzrqye"]
FINA_COLS = ["ts_code", "ann_date", "end_date", "update_flag", "eps", "bps",
             "roe", "grossprofit_margin", "netprofit_margin", "debt_to_assets",
             "or_yoy", "netprofit_yoy"]

# 主题指数预置清单（中证/国证，2026-09 逐个验证过日线+成分可得性）
THEME_INDICES = [
    ("931743.CSI", "半导体设备"), ("931071.CSI", "半导体"), ("H30184.CSI", "全指半导体"),
    ("931865.CSI", "芯片产业"), ("931494.CSI", "消费电子"), ("930850.CSI", "云计算"),
    ("930713.CSI", "人工智能"), ("930790.CSI", "机器人"), ("931151.CSI", "光伏产业"),
    ("399976.SZ", "新能源车"), ("931642.CSI", "中证新能"), ("931643.CSI", "中证电池"),
    ("399997.SZ", "白酒"), ("399989.SZ", "医疗"), ("399975.SZ", "证券公司"),
    ("399986.SZ", "银行"), ("399967.SZ", "军工"), ("930901.CSI", "动漫游戏"),
    ("399998.SZ", "煤炭"), ("399440.SZ", "钢铁"), ("399395.SZ", "有色"),
    ("930651.CSI", "中证全指房地产"), ("931009.CSI", "中证全指家电"),
]

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
    recompute_pv_rank()
    recompute_industry()
    recompute_board()


# ---------------------------------------------------------------- 情绪计算

def recompute_pv_rank(full=False):
    """重建量价综合分个股日表（全量或增量）。

    增量规则：凡 daily_bar 里存在而 pv_rank 缺失的交易日都（重）算，
    并把前一交易日的 next_ret 回填（新交易日到来后才能知道）。
    """
    print("[pvrank] 重建量价综合分排名 ...")
    t0 = time.time()
    if full:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM pv_rank"))
    with engine.connect() as conn:
        dates = [r[0] for r in conn.execute(text(
            "SELECT DISTINCT trade_date FROM daily_bar ORDER BY trade_date"))]
        have = {str(r[0]) for r in conn.execute(text(
            "SELECT DISTINCT trade_date FROM pv_rank"))}
    if not dates:
        sys.exit("[错误] daily_bar 无数据")
    # 历史最早 60 个交易日滚动窗口不足、因子恒为 NaN，pv_rank 永不覆盖；
    # 必须按历史位置排除（对 dates 切片而非对 todo 切片），否则 todo[0]
    # 永远卡在 2016-01-04，把取数窗口和删除范围拖成全表
    WARM = 60
    todo = [d for d in dates[WARM:] if str(d) not in have]
    if not todo:
        print("[OK] pv_rank 已最新")
        return
    first = todo[0]
    i = dates.index(first)
    j = dates.index(todo[-1])
    # 因子需要 20 日滚动 + 缓冲，取数窗口从第一个待算日往前 60 个交易日；
    # 末尾多取一天（次日的次日收益列用）。todo 可能不连续（如散缺），不能按
    # i + len(todo) 推末尾，必须用 todo[-1] 的真实位置
    lookback = dates[max(0, i - 60):j + 2]
    print(f"[pvrank] 待算 {len(todo)} 个交易日（{todo[0]} ~ {todo[-1]}），"
          f"取数窗口 {lookback[0]} ~ {lookback[-1]}")

    df = pd.read_sql(text(
        "SELECT d.ts_code, d.trade_date, d.close, d.pct_chg, d.vol, d.high, d.low, "
        "       d.amount, b2.turnover_rate_f "
        "FROM daily_bar d LEFT JOIN daily_basic b2 "
        "  ON b2.ts_code = d.ts_code AND b2.trade_date = d.trade_date "
        "WHERE d.trade_date BETWEEN :s AND :e ORDER BY d.ts_code, d.trade_date"),
        engine, params={"s": lookback[0], "e": lookback[-1]})
    for c in ("close", "pct_chg", "vol", "high", "low", "amount", "turnover_rate_f"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["trade_date"] = df["trade_date"].astype(str)
    df["abs_ret"] = df["pct_chg"].abs()
    df["sign1"] = np.sign(df["pct_chg"])
    df["next_ret"] = df.groupby("ts_code")["pct_chg"].shift(-1)
    g = df.groupby("ts_code", sort=False)
    df["vol_ma5"] = g["vol"].transform(lambda x: x.rolling(5).mean())
    df["pv_sync_d"] = df["sign1"] * (df["vol"] / df["vol_ma5"] - 1)
    df["pv_sync20"] = g["pv_sync_d"].transform(lambda x: x.rolling(20).mean())
    df["illiq_d"] = df["abs_ret"] / df["amount"].replace(0, np.nan) * 1e9
    df["amihud3"] = g["illiq_d"].transform(lambda x: x.rolling(3).mean())
    df["amt_ma5"] = g["amount"].transform(lambda x: x.rolling(5).mean())
    df["amt_ma20"] = g["amount"].transform(lambda x: x.rolling(20).mean())
    df["ret_10"] = g["close"].pct_change(10, fill_method=None)
    df["vw_mom10"] = df["ret_10"] * (df["amt_ma5"] / df["amt_ma20"] - 1)

    todo_s = {str(d) for d in todo}
    cur = df[df["trade_date"].isin(todo_s)].dropna(
        subset=["pv_sync20", "amihud3", "vw_mom10"]).copy()
    signs = {"pv_sync20": -1, "amihud3": +1, "vw_mom10": -1, "turnover_rate_f": -1}
    cur["score"] = sum(
        sg * cur.groupby("trade_date")[col].rank(pct=True)
        for col, sg in signs.items()) / len(signs)
    out = cur[["ts_code", "trade_date", "score", "pct_chg", "next_ret"]].copy()
    out["pct_chg"] = out["pct_chg"].astype(float)
    out["next_ret"] = out["next_ret"].astype(float)
    out["trade_date"] = pd.to_datetime(out["trade_date"]).dt.date
    # 只删本次真正写出的交易日。todo 里因子不足的日子（dropna 剔除）不会进 out，
    # 若按 [todo 首, todo 末] 区间删，一次空增量就会清掉整张表（本次 0 行事故根因）
    n = len(out)
    del_dates = sorted(set(out["trade_date"]))
    with engine.begin() as conn:
        for k in range(0, len(del_dates), 500):
            conn.execute(
                text("DELETE FROM pv_rank WHERE trade_date IN :ds")
                .bindparams(bindparam("ds", expanding=True)),
                {"ds": del_dates[k:k + 500]})
        if n:
            out.to_sql("pv_rank", con=conn, if_exists="append", index=False,
                       chunksize=1000, method="multi")

    # 回填前一交易日的 next_ret（新交易日到来后才能知道）
    if i > 0:
        prev = dates[i - 1]
        first_rows = df[df["trade_date"] == str(first)][["ts_code", "pct_chg"]] \
            .rename(columns={"pct_chg": "next_ret"})
        from sqlalchemy.dialects.mysql import insert as mysql_insert
        from app.models.pv_rank import PvRank
        stmt = mysql_insert(PvRank.__table__).values([
            {"ts_code": r.ts_code, "trade_date": prev, "score": None,
             "pct_chg": None,
             "next_ret": None if pd.isna(r.next_ret) else round(float(r.next_ret), 4)}
            for r in first_rows.itertuples()])
        stmt = stmt.on_duplicate_key_update(next_ret=stmt.inserted.next_ret)
        with engine.begin() as conn:
            conn.execute(stmt)
        print(f"[pvrank] 已回填 {prev} 的次日收益")
    print(f"[OK] pv_rank 覆盖至 {todo[-1]}，本次 {n:,} 行，用时 {time.time()-t0:.0f}s")


def sync_fina(start_period="20160331"):
    """同步财务指标（tushare fina_indicator，单股全历史逐只拉取）。

    当前积分档不支持按报告期批量（fina_indicator_vip 需 5000 分），
    只能逐只调用。三个坑：
    - 必须显式传 start_date/end_date（不带日期只返回最近 100 行）
    - 单次调用硬上限 100 行，命中即按公告日窗口对半递归拆分
    - update_flag 不能当版本选择器：多数报告期只有 '1' 没有 '0'，
      全版本入库，由查询端按「每期最早公告日」取数（防前视以公告日为准）
    按股票先删后插，幂等。
    """
    import app.models  # noqa: F401  注册 ORM 模型，确保 fina_indicator 表存在
    print("[fina] 同步财务指标（按个股全历史）...")
    t0 = time.time()
    Base.metadata.create_all(engine)

    start = date(int(start_period[:4]), int(start_period[4:6]), int(start_period[6:8]))
    start_s, end_s = start.strftime("%Y%m%d"), date.today().strftime("%Y%m%d")
    with engine.connect() as conn:
        codes = [r[0] for r in conn.execute(text(
            "SELECT ts_code FROM stock_basic ORDER BY ts_code"))]
    if not codes:
        sys.exit("[错误] stock_basic 为空，请先运行: python scripts/sync_data.py basic")

    def fetch_window(c, s_dt, e_dt, depth=0):
        df = call_with_retry(f"fina_indicator {c}", func="fina_indicator", ts_code=c,
                             start_date=s_dt, end_date=e_dt,
                             fields=",".join(FINA_COLS))
        if df is None or len(df) < 100 or depth >= 4:
            return df
        mid = pd.to_datetime(s_dt) + (pd.to_datetime(e_dt) - pd.to_datetime(s_dt)) / 2
        left = fetch_window(c, s_dt, mid.strftime("%Y%m%d"), depth + 1)
        right = fetch_window(c, (mid + pd.Timedelta(days=1)).strftime("%Y%m%d"),
                             e_dt, depth + 1)
        parts = [d for d in (left, right) if d is not None and not d.empty]
        return pd.concat(parts, ignore_index=True) if parts else None

    done = 0
    for i, c in enumerate(codes, 1):
        df = fetch_window(c, start_s, end_s)
        if df is not None and not df.empty:
            df = df[FINA_COLS].copy()
            for col in ("ann_date", "end_date"):
                df[col] = pd.to_datetime(df[col], format="%Y%m%d", errors="coerce").dt.date
            df = df.dropna(subset=["end_date"])
            df = df[df["end_date"] >= start]
            df = df.drop_duplicates(subset=["ts_code", "end_date", "update_flag"])
            if not df.empty:
                _delete_insert("fina_indicator", df, "ts_code = :c", {"c": c})
                done += 1
        if i % 250 == 0 or i == len(codes):
            print(f"  进度 {i}/{len(codes)}（已入库 {done} 只）"
                  f"已用 {(time.time()-t0)/60:.1f}min")
    print(f"[OK] 财务指标完成 {done} 只，用时 {(time.time()-t0)/60:.1f} 分钟")


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


# ---------------------------------------------------------------- 行业聚合

def recompute_industry(full=False):
    """聚合行业日频指标（自建行业指数，按 (industry, trade_date) 先删后插）。"""
    import app.models  # noqa: F401  注册 ORM 模型，确保 industry_daily 表存在
    print("[industry] 聚合行业日频指标 ...")
    t0 = time.time()
    Base.metadata.create_all(engine)

    with engine.connect() as conn:
        if not full:
            have = conn.execute(text(
                "SELECT MAX(trade_date) FROM industry_daily")).scalar()
        else:
            have = None
    start = have if have else date(2016, 1, 1)

    df = pd.read_sql(text(
        "SELECT d.trade_date, b.industry, d.pct_chg, d.close, d.pre_close, "
        "       d.amount, b2.turnover_rate_f, b2.circ_mv "
        "FROM daily_bar d "
        "LEFT JOIN stock_basic b ON b.ts_code = d.ts_code "
        "LEFT JOIN daily_basic b2 ON b2.ts_code = d.ts_code AND b2.trade_date = d.trade_date "
        "WHERE d.trade_date >= :s AND b.industry IS NOT NULL"),
        engine, params={"s": start})
    if df.empty:
        print("[OK] 无新增数据")
        return
    for c in ("pct_chg", "close", "pre_close", "amount", "turnover_rate_f", "circ_mv"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    # 个股日收益用 close/pre_close 复算（pct_chg 缺失行仍可参与等权均值）
    df["ret"] = np.where((df["close"] > 0) & (df["pre_close"] > 0),
                         (df["close"] / df["pre_close"] - 1) * 100, np.nan)
    df["up"] = (df["ret"] > 0).astype("float64")
    df.loc[df["ret"].isna(), "up"] = np.nan
    df["down"] = (df["ret"] < 0).astype("float64")
    df.loc[df["ret"].isna(), "down"] = np.nan
    df["circ_mv"] = df["circ_mv"] / 1e4          # 万元 → 亿元
    df["amount"] = df["amount"] / 1e5            # 千元 → 亿元
    df["mv_w"] = df["circ_mv"] * df["ret"]       # 市值加权收益的分子

    g = df.groupby(["industry", "trade_date"], sort=False)
    out = pd.DataFrame({
        "n_stocks": g["ret"].count(),
        "up_count": g["up"].sum(),
        "down_count": g["down"].sum(),
        "ret_eq": g["ret"].mean(),
        "ret_cap_num": g["mv_w"].sum(),
        "cap_w": g["circ_mv"].sum(),
        "amount": g["amount"].sum(),
        "turnover_med": g["turnover_rate_f"].median(),
        "circ_mv": g["circ_mv"].sum(),
    }).reset_index()
    # 市值加权收益：ret 已是百分数，Σ(市值×ret%)/Σ(市值) 即加权百分数
    out["ret_cap"] = np.where(out["cap_w"] > 0,
                              out["ret_cap_num"] / out["cap_w"], np.nan)
    day_amount = out.groupby("trade_date")["amount"].transform("sum")
    out["amount_share"] = np.where(day_amount > 0, out["amount"] / day_amount * 100, np.nan)

    out["trade_date"] = pd.to_datetime(out["trade_date"]).dt.date
    cols = ["industry", "trade_date", "n_stocks", "up_count", "down_count",
            "ret_eq", "ret_cap", "amount", "amount_share", "turnover_med", "circ_mv"]
    out = out[cols]
    n = _delete_insert("industry_daily", out,
                       "trade_date >= :s", {"s": out["trade_date"].min()})
    print(f"[OK] 行业聚合 {out['industry'].nunique()} 个行业 "
          f"{out['trade_date'].min()} ~ {out['trade_date'].max()}，共 {n:,} 行，"
          f"用时 {time.time()-t0:.0f}s")


# ---------------------------------------------------------------- 板块体系

def backfill_dbasic(start: date):
    """逐日重拉 daily_basic 全市场（补 pe_ttm 等新增列的历史）。

    按日先删后插幂等；一次调用返回当日全市场约 5500 行。
    """
    import app.models  # noqa: F401  注册 ORM 模型
    Base.metadata.create_all(engine)
    print(f"[dbasic] 逐日重拉 daily_basic（{start} 起）...")
    t0 = time.time()
    days = open_dates(start, date.today())
    for i, d in enumerate(days, 1):
        df = call_with_retry(f"daily_basic {d:%Y%m%d}", func="daily_basic",
                             trade_date=f"{d:%Y%m%d}")
        if df is not None and not df.empty:
            df = df[BASIC_DAILY_COLS].copy()
            df = df.dropna(subset=["turnover_rate_f"])   # 与既有入库口径一致
            df["trade_date"] = df["trade_date"].map(to_date)
            _delete_insert("daily_basic", df, "trade_date = :d", {"d": d})
        if i % 100 == 0 or i == len(days):
            print(f"  进度 {i}/{len(days)}，已用 {(time.time()-t0)/60:.1f}min")
    print(f"[OK] daily_basic 回补完成 {len(days)} 天，用时 {(time.time()-t0)/60:.1f} 分钟")


def sync_board():
    """重建板块目录与成分：申万 L1/L2/L3（当前成分）+ 主题指数（最新月末快照）。"""
    import calendar

    import app.models  # noqa: F401  注册 ORM 模型
    print("[board] 重建板块目录与成分 ...")
    t0 = time.time()
    Base.metadata.create_all(engine)
    today = date.today()

    groups, members = [], []
    # 申万分类 + 成分（is_new=Y 当前成分）
    cls = call_with_retry("index_classify SW2021", func="index_classify", src="SW2021")
    for r in cls.itertuples():
        if r.level in ("L1", "L2", "L3") and str(r.is_pub) == "1":
            groups.append({"board_code": r.index_code,
                           "board_type": f"sw_{r.level.lower()}",
                           "board_name": r.industry_name})
    mem = call_with_retry("index_member_all", func="index_member_all")
    mem = mem[mem["is_new"] == "Y"]
    for r in mem.itertuples():
        for code in (r.l1_code, r.l2_code, r.l3_code):
            if isinstance(code, str) and code:
                members.append({"board_code": code, "ts_code": r.ts_code})
    n_sw_mem = len(members)

    # 主题指数：最新月末的成分快照
    eom = date(today.year, today.month, 1) - timedelta(days=1)
    eom = date(eom.year, eom.month, calendar.monthrange(eom.year, eom.month)[1])
    for code, name in THEME_INDICES:
        groups.append({"board_code": code, "board_type": "theme", "board_name": name})
        w = call_with_retry(f"index_weight {code}", func="index_weight",
                            index_code=code, trade_date=f"{eom:%Y%m%d}")
        if w is None or w.empty:
            print(f"  [警告] {code} {name} 成分为空，跳过")
            continue
        for r in w.itertuples():
            members.append({"board_code": code, "ts_code": r.con_code})

    groups_df = pd.DataFrame(groups).drop_duplicates(subset=["board_code"])
    members_df = pd.DataFrame(members).drop_duplicates()
    members_df = members_df[members_df["board_code"].isin(set(groups_df["board_code"]))]
    n1 = _delete_insert("board_group", groups_df, "1=1", {})
    n2 = _delete_insert("board_member", members_df, "1=1", {})
    print(f"[OK] 板块目录 {n1} 个（申万 {n1 - len(THEME_INDICES)} + 主题 {len(THEME_INDICES)}），"
          f"成分 {n2:,} 条（申万 {n_sw_mem:,}），用时 {time.time()-t0:.0f}s")


def sync_index_ext():
    """同步主题指数官方日线进 index_daily 表（增量）。"""
    print("[index_ext] 同步主题指数日线 ...")
    t0 = time.time()
    for code, name in THEME_INDICES:
        with engine.connect() as conn:
            last = conn.execute(text(
                "SELECT MAX(trade_date) FROM index_daily WHERE ts_code = :c"),
                {"c": code}).scalar()
        start = (last + timedelta(days=1)).strftime("%Y%m%d") if last else "20150101"
        df = call_with_retry(f"index_daily {code}", func="index_daily", ts_code=code,
                             start_date=start, end_date=f"{date.today():%Y%m%d}")
        if df is None or df.empty:
            print(f"  {code} {name}: 无新增")
            continue
        df = df[["ts_code", "trade_date", "open", "high", "low", "close",
                 "pct_chg", "vol", "amount"]].copy()
        df["trade_date"] = df["trade_date"].map(to_date)
        n = _delete_insert("index_daily", df, "ts_code = :c AND trade_date >= :s",
                           {"c": code, "s": df["trade_date"].min()})
        print(f"  {code} {name}: +{n} 行（{df['trade_date'].min()} 起）")
    print(f"[OK] 主题指数日线完成，用时 {time.time()-t0:.0f}s")


def recompute_board(full=False):
    """聚合板块日频指标：申万自建聚合；theme 的 ret 字段回填官方指数涨跌幅。"""
    import app.models  # noqa: F401  注册 ORM 模型
    print("[board_daily] 聚合板块日频指标 ...")
    t0 = time.time()
    Base.metadata.create_all(engine)

    with engine.connect() as conn:
        have = None if full else conn.execute(
            text("SELECT MAX(trade_date) FROM board_daily")).scalar()
    start = have if have else date(2016, 1, 1)

    mem = pd.read_sql(text("SELECT board_code, ts_code FROM board_member"), engine)
    if mem.empty:
        print("[警告] board_member 为空，请先运行 sync_data.py board")
        return
    df = pd.read_sql(text(
        "SELECT d.trade_date, d.ts_code, d.close, d.pre_close, d.amount, "
        "       b2.turnover_rate_f, b2.circ_mv "
        "FROM daily_bar d "
        "LEFT JOIN daily_basic b2 ON b2.ts_code = d.ts_code AND b2.trade_date = d.trade_date "
        "WHERE d.trade_date >= :s"), engine, params={"s": start})
    df = df.merge(mem, on="ts_code", how="inner")  # 一股属多板块（L1+L2+L3+主题）→ 行数膨胀
    for c in ("close", "pre_close", "amount", "turnover_rate_f", "circ_mv"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["ret"] = np.where((df["close"] > 0) & (df["pre_close"] > 0),
                         (df["close"] / df["pre_close"] - 1) * 100, np.nan)
    df["up"] = (df["ret"] > 0).astype("float64")
    df.loc[df["ret"].isna(), "up"] = np.nan
    df["down"] = (df["ret"] < 0).astype("float64")
    df.loc[df["ret"].isna(), "down"] = np.nan
    df["circ_mv"] = df["circ_mv"] / 1e4
    df["amount"] = df["amount"] / 1e5
    df["mv_w"] = df["circ_mv"] * df["ret"]

    g = df.groupby(["board_code", "trade_date"], sort=False)
    out = pd.DataFrame({
        "n_stocks": g["ret"].count(),
        "up_count": g["up"].sum(),
        "down_count": g["down"].sum(),
        "ret_eq": g["ret"].mean(),
        "ret_cap_num": g["mv_w"].sum(),
        "cap_w": g["circ_mv"].sum(),
        "amount": g["amount"].sum(),
        "turnover_med": g["turnover_rate_f"].median(),
        "circ_mv": g["circ_mv"].sum(),
    }).reset_index()
    out["ret_cap"] = np.where(out["cap_w"] > 0,
                              out["ret_cap_num"] / out["cap_w"], np.nan)
    day_amount = out.groupby("trade_date")["amount"].transform("sum")
    out["amount_share"] = np.where(day_amount > 0, out["amount"] / day_amount * 100, np.nan)

    # theme 板块的 ret 字段回填官方指数涨跌幅（权威口径）
    theme_ret = pd.read_sql(
        text("SELECT ts_code AS board_code, trade_date, pct_chg FROM index_daily "
             "WHERE ts_code IN :cs").bindparams(bindparam("cs", expanding=True)),
        engine, params={"cs": [c for c, _ in THEME_INDICES]})
    if not theme_ret.empty:
        theme_ret["pct_chg"] = pd.to_numeric(theme_ret["pct_chg"], errors="coerce")
        theme_ret["trade_date"] = pd.to_datetime(theme_ret["trade_date"]).dt.date
        out = out.merge(theme_ret, on=["board_code", "trade_date"], how="left")
        m = out["pct_chg"].notna()
        out.loc[m, "ret_eq"] = out.loc[m, "pct_chg"]
        out.loc[m, "ret_cap"] = out.loc[m, "pct_chg"]
        out = out.drop(columns=["pct_chg"])

    out["trade_date"] = pd.to_datetime(out["trade_date"]).dt.date
    cols = ["board_code", "trade_date", "n_stocks", "up_count", "down_count",
            "ret_eq", "ret_cap", "amount", "amount_share", "turnover_med", "circ_mv"]
    out = out[cols]
    n = _delete_insert("board_daily", out, "trade_date >= :s",
                       {"s": out["trade_date"].min()})
    print(f"[OK] 板块聚合 {out['board_code'].nunique()} 个板块 "
          f"{out['trade_date'].min()} ~ {out['trade_date'].max()}，共 {n:,} 行，"
          f"用时 {time.time()-t0:.0f}s")


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
    p_pv = with_common(sub.add_parser("pvrank", help="重建量价综合分排名表"))
    p_pv.add_argument("--full", action="store_true", help="全量重建（默认增量）")
    p_fina = with_common(sub.add_parser("fina", help="同步财务指标（季频，按报告期）"))
    p_fina.add_argument("--start", default="20160331",
                        help="起始报告期 YYYYMMDD（季度末，默认 2016Q1）")
    p_ind = with_common(sub.add_parser("industry", help="聚合行业日频指标（自建行业指数）"))
    p_ind.add_argument("--full", action="store_true", help="全量重建（默认增量）")
    with_common(sub.add_parser("board", help="重建板块目录与成分（申万层级 + 主题指数）"))
    with_common(sub.add_parser("index_ext", help="同步主题指数官方日线（增量）"))
    p_db = with_common(sub.add_parser("dbasic", help="逐日重拉 daily_basic（补 pe_ttm 等新增列）"))
    p_db.add_argument("--start", default="20160101", help="开始日期 YYYYMMDD")

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
    elif args.cmd == "pvrank":
        recompute_pv_rank(full=args.full)
    elif args.cmd == "fina":
        sync_fina(args.start)
    elif args.cmd == "industry":
        recompute_industry(full=args.full)
    elif args.cmd == "board":
        sync_board()
    elif args.cmd == "index_ext":
        sync_index_ext()
    elif args.cmd == "dbasic":
        backfill_dbasic(date(int(args.start[:4]), int(args.start[4:6]), int(args.start[6:8])))
    else:
        {"cal": sync_cal, "basic": sync_basic,
         "index": lambda: sync_index(full=args.full),
         "hsgt": sync_hsgt,
         "etf": lambda: sync_etf(args.codes.split(",") if args.codes else None,
                                 full=args.full)
         }[args.cmd]()


if __name__ == "__main__":
    main()
