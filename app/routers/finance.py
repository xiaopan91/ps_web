"""个人理财接口 v2：标的级持仓体系。

层级：大模块（低/中/高风险）→ 小模块 → 标的（可关联库内行情）。
核心语义：
- 当前余额 = 标的最新一条 fin_balance 的 amount（无记录 = 0）
- 移仓自动调整双方余额并留痕；跨小模块移仓对该小模块是"外部流"
- IRR = 余额法近似 XIRR（外部现金流 = 相邻余额增量 − 期间移仓净转入，
  最新余额为终值回收；市场盈亏与投入混算，属近似口径）
"""
from datetime import date, datetime

import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

from app.database import engine
from app.models.finance import MODULES, PRESET_SUB_MODULE
from app.pa_engine import xirr
from app.routers.index_quotes import INDEX_NAMES
from scripts.sync_data import THEME_INDICES

router = APIRouter(prefix="/api/fin", tags=["finance"])

INDEX_ALL = {**INDEX_NAMES, **{c: n for c, n in THEME_INDICES}}   # 13 核心 + 23 主题

DEBT_CATEGORIES = {"负债"}   # v1 遗留常量（fin_snapshot 表仍在库）


def _parse_d(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


@router.get("/search_asset")
def search_asset(q: str):
    """统一搜索库内资产：股票 / 基金(ETF) / 指数。返回可关联的 type+code+name。"""
    like = f"%{q.strip()}%"
    if not q.strip():
        return []
    out = []
    stk = pd.read_sql(text(
        "SELECT ts_code, name FROM stock_basic "
        "WHERE name LIKE :p OR ts_code LIKE :p ORDER BY ts_code LIMIT 8"),
        engine, params={"p": like})
    out += [{"asset_type": "股票", "ts_code": r.ts_code, "name": r.name}
            for r in stk.itertuples()]
    fnd = pd.read_sql(text(
        "SELECT ts_code, name FROM fund_basic "
        "WHERE name LIKE :p OR ts_code LIKE :p ORDER BY ts_code LIMIT 8"),
        engine, params={"p": like})
    out += [{"asset_type": "ETF", "ts_code": r.ts_code, "name": r.name}
            for r in fnd.itertuples()]
    for code, name in INDEX_ALL.items():
        if q.strip() in code or q.strip() in name:
            out.append({"asset_type": "指数", "ts_code": code, "name": name})
    return out[:15]


def _clean(v):
    return None if v is None or (isinstance(v, float) and not np.isfinite(v)) else round(float(v), 2)


def _latest_balances() -> dict:
    """每个标的的当前余额 {item_id: {amount, date}}（同日多条取最新 id）。"""
    df = pd.read_sql(text(
        "SELECT b.item_id, b.amount, b.date FROM fin_balance b "
        "JOIN (SELECT item_id, MAX(id) AS mid FROM fin_balance GROUP BY item_id) t "
        "  ON t.item_id = b.item_id AND t.mid = b.id"), engine)
    return {int(r.item_id): {"amount": float(r.amount), "date": str(r.date)}
            for r in df.itertuples()}


def _items_full() -> list[dict]:
    items = pd.read_sql(text(
        "SELECT id, module, sub, name, asset_type, ts_code, note FROM fin_item "
        "ORDER BY module, sub, id"), engine)
    bal = _latest_balances()
    # 最新行情快照（股票= daily_bar；ETF= fund_daily；指数= index_daily）
    # fund_daily 无 pct_chg 列，统一取最近两日收盘价算涨跌
    quotes = {}
    for table, typ in (("daily_bar", "股票"), ("fund_daily", "ETF"), ("index_daily", "指数")):
        q = pd.read_sql(text(
            f"SELECT ts_code, trade_date, close FROM {table} "
            f"WHERE trade_date IN (SELECT trade_date FROM ("
            f"SELECT DISTINCT trade_date FROM {table} ORDER BY trade_date DESC LIMIT 2) x)"), engine)
        q["close"] = pd.to_numeric(q["close"], errors="coerce")
        if q.empty:
            continue
        q = q.sort_values("trade_date")
        last = q.groupby("ts_code")["close"].last()
        prev = q.groupby("ts_code")["close"].nth(-2)
        for ts, close in last.items():
            p = prev.get(ts)
            pct = (float(close) / float(p) - 1) * 100 if pd.notna(p) and float(p) != 0 else None
            quotes[(typ, ts)] = (float(close), None if pct is None else round(pct, 2))
    out = []
    for r in items.itertuples():
        b = bal.get(r.id, {})
        q = quotes.get((r.asset_type, r.ts_code)) if r.ts_code else None
        out.append({
            "id": int(r.id), "module": r.module, "sub": r.sub, "name": r.name,
            "asset_type": r.asset_type, "ts_code": r.ts_code, "note": r.note,
            "amount": _clean(b.get("amount")), "balance_date": b.get("date"),
            "quote_close": q[0] if q else None, "quote_pct": q[1] if q else None,
        })
    return out


# --------------------------------------------------------------- 标的 CRUD

class ItemIn(BaseModel):
    module: str
    sub: str
    name: str
    asset_type: str = "其他"
    ts_code: str | None = None
    note: str = ""


@router.get("/items")
def list_items():
    return _items_full()


@router.post("/items")
def add_item(body: ItemIn):
    if body.module not in MODULES:
        raise HTTPException(400, f"大模块须为 {MODULES}")
    if not body.name.strip() or not body.sub.strip():
        raise HTTPException(400, "小模块与标的名不能为空")
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO fin_item (module, sub, name, asset_type, ts_code, note, created_at) "
            "VALUES (:m, :s, :n, :t, :c, :note, :at)"),
            {"m": body.module, "s": body.sub.strip(), "n": body.name.strip(),
             "t": body.asset_type, "c": body.ts_code, "note": body.note.strip() or None,
             "at": datetime.now()})
    return {"ok": True}


@router.delete("/items/{item_id}")
def del_item(item_id: int):
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM fin_balance WHERE item_id = :i"), {"i": item_id})
        conn.execute(text("DELETE FROM fin_transfer WHERE from_item = :i OR to_item = :i"),
                     {"i": item_id})
        n = conn.execute(text("DELETE FROM fin_item WHERE id = :i"), {"i": item_id}).rowcount
    if not n:
        raise HTTPException(404, "标的不存在")
    return {"ok": True}


# --------------------------------------------------------------- 余额

class BalanceIn(BaseModel):
    item_id: int
    date: str
    amount: float
    note: str = ""


@router.get("/balances")
def list_balances(item_id: int | None = None):
    where, params = "", {"i": item_id} if item_id else {}
    if item_id:
        where = "WHERE b.item_id = :i"
    df = pd.read_sql(text(
        f"SELECT b.id, b.item_id, i.name, i.sub, i.module, b.date, b.amount, b.note "
        f"FROM fin_balance b JOIN fin_item i ON i.id = b.item_id {where} "
        f"ORDER BY b.date DESC, b.id DESC"), engine, params=params)
    return [{"id": int(r.id), "item_id": int(r.item_id), "name": r.name,
             "sub": r.sub, "module": r.module,
             "date": str(r.date), "amount": _clean(r.amount), "note": r.note or ""}
            for r in df.itertuples()]


@router.post("/balances")
def add_balance(body: BalanceIn):
    if body.item_id is None:
        raise HTTPException(400, "item_id 必填")
    with engine.begin() as conn:
        exists = conn.execute(text("SELECT 1 FROM fin_item WHERE id = :i"),
                              {"i": body.item_id}).scalar()
        if not exists:
            raise HTTPException(404, "标的不存在")
        conn.execute(text(
            "INSERT INTO fin_balance (item_id, date, amount, note, created_at) "
            "VALUES (:i, :d, :a, :n, :t)"),
            {"i": body.item_id, "d": _parse_d(body.date), "a": round(body.amount, 2),
             "n": body.note.strip() or None, "t": datetime.now()})
    return {"ok": True}


@router.delete("/balances/{bid}")
def del_balance(bid: int):
    with engine.begin() as conn:
        n = conn.execute(text("DELETE FROM fin_balance WHERE id = :i"), {"i": bid}).rowcount
    if not n:
        raise HTTPException(404, "记录不存在")
    return {"ok": True}


# --------------------------------------------------------------- 移仓

class TransferIn(BaseModel):
    date: str
    from_item: int
    to_item: int
    amount: float
    note: str = ""


@router.post("/transfers")
def add_transfer(body: TransferIn):
    if body.from_item == body.to_item:
        raise HTTPException(400, "移仓双方不能是同一标的")
    if body.amount <= 0:
        raise HTTPException(400, "移仓金额必须大于 0")
    bal = _latest_balances()
    src = bal.get(body.from_item, {}).get("amount", 0.0)
    if body.amount > src:
        raise HTTPException(400, f"转出金额超过转出标的当前余额（{src:.2f}）")
    d = _parse_d(body.date)
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO fin_transfer (date, from_item, to_item, amount, note, created_at) "
            "VALUES (:d, :f, :t, :a, :n, :at)"),
            {"d": d, "f": body.from_item, "t": body.to_item,
             "a": round(body.amount, 2), "n": body.note.strip() or None,
             "at": datetime.now()})
        # 自动调整双方余额（写入移仓日的新余额记录）
        for item_id, delta in ((body.from_item, -body.amount), (body.to_item, body.amount)):
            cur = bal.get(item_id, {}).get("amount", 0.0)
            conn.execute(text(
                "INSERT INTO fin_balance (item_id, date, amount, note, created_at) "
                "VALUES (:i, :d, :a, :n, :t)"),
                {"i": item_id, "d": d, "a": round(cur + delta, 2),
                 "n": f"移仓自动调整（{'转出' if delta < 0 else '转入'}）", "t": datetime.now()})
    return {"ok": True}


# --------------------------------------------------------------- 目标配置

class TargetIn(BaseModel):
    targets: dict[str, float]   # {小模块: 目标%}


@router.get("/targets")
def list_targets():
    df = pd.read_sql(text("SELECT sub, target_pct FROM fin_target"), engine)
    return {r.sub: float(r.target_pct) for r in df.itertuples()}


@router.put("/targets")
def save_targets(body: TargetIn):
    with engine.begin() as conn:
        for sub, pct in body.targets.items():
            conn.execute(text(
                "INSERT INTO fin_target (sub, target_pct, updated_at) VALUES (:s, :p, :t) "
                "ON DUPLICATE KEY UPDATE target_pct = :p, updated_at = :t"),
                {"s": sub, "p": round(pct, 2), "t": datetime.now()})
    return {"ok": True}


# --------------------------------------------------------------- 总览聚合

@router.get("/portfolio")
def portfolio():
    """总览：总资产、标的明细（含最新行情）、小模块聚合（余额/目标/调仓差额）。"""
    items = _items_full()
    targets = list_targets()
    total = sum(i["amount"] or 0 for i in items)

    subs = {}
    for i in items:
        s = subs.setdefault(i["sub"], {"module": i["module"], "sub": i["sub"],
                                       "balance": 0.0, "count": 0})
        s["balance"] += i["amount"] or 0
        s["count"] += 1
    # 无标的的小模块也展示（预置 + 已设目标），便于先定目标配置、后建仓
    for sub in (set(PRESET_SUB_MODULE) | set(targets)) - set(subs):
        subs[sub] = {"module": PRESET_SUB_MODULE.get(sub, "其他"), "sub": sub,
                     "balance": 0.0, "count": 0}
    for s in subs.values():
        t = targets.get(s["sub"], 0.0)
        s["target_pct"] = t
        s["target_amt"] = round(total * t / 100, 2)
        s["diff"] = round(s["target_amt"] - s["balance"], 2)
    # 大模块顺序（低→中→高）优先，同模块内余额降序
    _order = {m: i for i, m in enumerate(MODULES)}
    sub_rows = sorted(subs.values(),
                      key=lambda x: (_order.get(x["module"], 99), -x["balance"]))

    modules = {}
    for s in sub_rows:
        m = modules.setdefault(s["module"], {"module": s["module"], "balance": 0.0})
        m["balance"] += s["balance"]

    return {"total": round(total, 2), "items": items, "subs": sub_rows,
            "modules": [modules[m] for m in MODULES if m in modules]
                       + [modules[m] for m in sorted(modules) if m not in MODULES],
            "targets_sum": round(sum(targets.values()), 2)}


# --------------------------------------------------------------- 小模块详情

@router.get("/sub/{sub_name}")
def sub_detail(sub_name: str):
    """小模块详情页数据：概览 + 标的（含行情与 XIRR）+ 余额历史。"""
    all_items = _items_full()
    items = [i for i in all_items if i["sub"] == sub_name]
    targets = list_targets()
    module = items[0]["module"] if items else PRESET_SUB_MODULE.get(sub_name)
    if module is None and sub_name not in targets:
        raise HTTPException(404, f"未知小模块: {sub_name}")

    total = sum(i["amount"] or 0 for i in all_items)
    balance = sum(i["amount"] or 0 for i in items)
    t = targets.get(sub_name, 0.0)
    xirr_map = {x["item_id"]: x["xirr"] for x in irr()["items"]}
    for i in items:
        i["xirr"] = xirr_map.get(i["id"])

    hist = pd.read_sql(text(
        "SELECT b.item_id, i.name, b.date, b.amount FROM fin_balance b "
        "JOIN fin_item i ON i.id = b.item_id WHERE i.sub = :s "
        "ORDER BY b.date, b.id LIMIT 2000"), engine, params={"s": sub_name})
    history = [{"item_id": int(r.item_id), "name": r.name, "date": str(r.date),
                "amount": _clean(r.amount)} for r in hist.itertuples()]

    return {"module": module or "其他", "sub": sub_name,
            "balance": round(balance, 2), "count": len(items),
            "target_pct": t, "target_amt": round(total * t / 100, 2),
            "diff": round(total * t / 100 - balance, 2),
            "items": items, "history": history}


# --------------------------------------------------------------- 历史与 IRR

@router.get("/history")
def history(limit: int = 500):
    """余额与移仓事件流（倒序），供历史列表与下钻。"""
    bal = pd.read_sql(text(
        "SELECT b.id, b.item_id, i.name, i.sub, i.module, b.date, b.amount, b.note "
        "FROM fin_balance b JOIN fin_item i ON i.id = b.item_id "
        "ORDER BY b.date DESC, b.id DESC LIMIT :l"), engine, params={"l": limit})
    tr = pd.read_sql(text(
        "SELECT t.id, t.date, f.name AS from_name, t2.name AS to_name, "
        "       f.sub AS from_sub, t2.sub AS to_sub, t.amount, t.note "
        "FROM fin_transfer t "
        "JOIN fin_item f ON f.id = t.from_item "
        "JOIN fin_item t2 ON t2.id = t.to_item "
        "ORDER BY t.date DESC, t.id DESC LIMIT :l"), engine, params={"l": limit})
    balances = [{"kind": "balance", "id": int(r.id), "item_id": int(r.item_id),
                 "name": r.name, "sub": r.sub, "module": r.module,
                 "date": str(r.date), "amount": _clean(r.amount), "note": r.note or ""}
                for r in bal.itertuples()]
    transfers = [{"kind": "transfer", "id": int(r.id), "date": str(r.date),
                  "from_name": r.from_name, "to_name": r.to_name,
                  "from_sub": r.from_sub, "to_sub": r.to_sub,
                  "amount": _clean(r.amount), "note": r.note or ""}
                 for r in tr.itertuples()]
    return {"balances": balances, "transfers": transfers}


@router.get("/irr")
def irr():
    """标的/小模块/大模块 年化收益率（余额法近似 XIRR）。"""
    bal = pd.read_sql(text(
        "SELECT b.item_id, b.date, b.amount, i.name, i.sub, i.module FROM fin_balance b "
        "JOIN fin_item i ON i.id = b.item_id ORDER BY b.date"), engine)
    tr = pd.read_sql(text(
        "SELECT t.date, t.from_item, t.to_item, t.amount FROM fin_transfer t"), engine)
    if bal.empty:
        return {"items": [], "subs": [], "modules": []}
    for c in ("amount",):
        bal[c] = pd.to_numeric(bal[c], errors="coerce")
    tr["amount"] = pd.to_numeric(tr["amount"], errors="coerce")
    tr["date"] = pd.to_datetime(tr["date"]).dt.date
    bal["date"] = pd.to_datetime(bal["date"]).dt.date

    def xirr_of(series: pd.Series) -> float | None:
        """余额序列 → 外部现金流（相邻增量）+ 期末回收 → XIRR。"""
        pts = series[series.notna()]
        if len(pts) < 2:
            return None
        flows = []
        prev_d, prev_v = None, None
        for d, v in pts.items():
            if prev_d is not None:
                delta = float(v) - float(prev_v)
                if abs(delta) > 1e-9:
                    flows.append((d, -delta))
            prev_d, prev_v = d, v
        flows.append((pts.index[-1], float(pts.iloc[-1])))
        rate = xirr(flows)
        return None if rate is None else round(rate * 100, 2)

    out_items, sub_series, mod_series = [], {}, {}
    for item_id, grp in bal.groupby("item_id"):
        s = grp.set_index("date")["amount"]
        name = grp["name"].iloc[0]
        sub, module = grp["sub"].iloc[0], grp["module"].iloc[0]
        rate = xirr_of(s)
        sub_series.setdefault(sub, []).append(s)
        mod_series.setdefault(module, []).append(s)
        out_items.append({"item_id": int(item_id), "name": name, "sub": sub,
                          "module": module, "xirr": rate})

    def agg_xirr(series_list):
        if not series_list:
            return None
        combined = {}
        for s in series_list:
            for d, v in s.items():
                combined[d] = combined.get(d, 0.0) + float(v)
        ser = pd.Series(combined).sort_index()
        return xirr_of(ser)

    out_subs = [{"sub": k, "xirr": agg_xirr(v)} for k, v in sorted(sub_series.items())]
    out_mods = [{"module": k, "xirr": agg_xirr(v)} for k, v in sorted(mod_series.items())]
    return {"items": out_items, "subs": out_subs, "modules": out_mods}
