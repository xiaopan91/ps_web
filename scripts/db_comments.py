"""给已存在的库补齐表/字段注释（依据 app/models 中定义的 comment）。

用法（项目根目录）：
    python scripts/db_comments.py dev      # 开发库
    python scripts/db_comments.py prod     # 生产库
    python scripts/db_comments.py both

原理：从 information_schema 读取各列现有定义（类型/可空/默认值），
仅追加 COMMENT，不改变任何结构；新库直接由 create_all 带出注释。
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine, text  # noqa: E402

import app.models  # noqa: E402,F401  # 注册全部模型
from app.config import DB_HOST, DB_PASSWORD, DB_PORT, DB_USER  # noqa: E402
from app.database import Base  # noqa: E402

TARGETS = {"dev": "ps_web_dev", "prod": "ps_web"}


def apply_comments(dbname: str):
    url = (f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/"
           f"{dbname}?charset=utf8mb4")
    engine = create_engine(url)
    total = 0
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            t0 = time.time()
            rows = conn.execute(text(
                "SELECT COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE, COLUMN_KEY, "
                "EXTRA, COLUMN_DEFAULT FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA = :db AND TABLE_NAME = :t"
            ), {"db": dbname, "t": table.name}).fetchall()
            if not rows:
                print(f"[skip] {dbname}.{table.name} 表不存在")
                continue
            info = {r[0]: r for r in rows}

            mods = []
            n_cols = 0
            for col in table.columns:
                if col.name not in info or not col.comment:
                    continue
                _, ctype, nullable, key, extra, default = info[col.name]
                d = f"`{col.name}` {ctype}"
                if nullable == "NO" or key == "PRI":
                    d += " NOT NULL"
                if default is not None:
                    d += f" DEFAULT '{default}'"
                if extra:
                    d += f" {extra}"
                esc = col.comment.replace("'", "''")
                d += f" COMMENT '{esc}'"
                mods.append(f"MODIFY COLUMN {d}")
                n_cols += 1
            if table.comment:
                mods.append(f"COMMENT='{table.comment}'")
            if not mods:
                continue
            conn.execute(text(f"ALTER TABLE `{table.name}` " + ", ".join(mods)))
            print(f"[ok] {dbname}.{table.name}: {n_cols} 列注释"
                  f"（{time.time()-t0:.1f}s）")
            total += 1
    print(f"[DONE] {dbname} 共 {total} 张表")


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "dev"
    if which == "both":
        for name in ("dev", "prod"):
            apply_comments(TARGETS[name])
    else:
        apply_comments(TARGETS[which])
