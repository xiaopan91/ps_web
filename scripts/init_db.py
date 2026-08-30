"""用 root 账号创建应用数据库和专用账号（只需运行一次）。

用法：
  1. 把 .env 里的 MYSQL_ROOT_PASSWORD 和 DB_PASSWORD 填好
  2. 激活虚拟环境后运行：python scripts/init_db.py
  3. 成功后把 .env 里的 MYSQL_ROOT_PASSWORD 一行删掉
"""
import os
import sys
from pathlib import Path

import pymysql
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
DB_PORT = int(os.getenv("DB_PORT", "3306"))
DB_NAME = os.getenv("DB_NAME", "ps_web")
DB_USER = os.getenv("DB_USER", "ps_web_user")
ROOT_PASSWORD = os.getenv("MYSQL_ROOT_PASSWORD", "")
APP_PASSWORD = os.getenv("DB_PASSWORD", "")

if not ROOT_PASSWORD or not APP_PASSWORD:
    sys.exit("请先在 .env 中填写 MYSQL_ROOT_PASSWORD 和 DB_PASSWORD")

conn = pymysql.connect(host=DB_HOST, port=DB_PORT, user="root", password=ROOT_PASSWORD)
try:
    with conn.cursor() as cur:
        cur.execute(
            f"CREATE DATABASE IF NOT EXISTS `{DB_NAME}` "
            "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
        )
        # localhost 和 127.0.0.1 各建一份，兼容服务端域名解析开关的两种状态
        for host in ("localhost", "127.0.0.1"):
            cur.execute(
                f"CREATE USER IF NOT EXISTS '{DB_USER}'@'{host}' IDENTIFIED BY %s",
                (APP_PASSWORD,),
            )
            # 重复运行时同步密码
            cur.execute(
                f"ALTER USER '{DB_USER}'@'{host}' IDENTIFIED BY %s", (APP_PASSWORD,)
            )
            cur.execute(f"GRANT ALL PRIVILEGES ON `{DB_NAME}`.* TO '{DB_USER}'@'{host}'")
        cur.execute("FLUSH PRIVILEGES")
    conn.commit()
    print(f"完成：数据库 {DB_NAME} 与账号 {DB_USER} 已就绪")
finally:
    conn.close()
