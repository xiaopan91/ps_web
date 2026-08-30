"""集中读取配置：从项目根目录的 .env 加载，敏感信息不进代码、不进 git。"""
import os
from pathlib import Path

from dotenv import load_dotenv

# .env 放在项目根目录（本文件的上两级）
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
DB_PORT = int(os.getenv("DB_PORT", "3306"))
DB_USER = os.getenv("DB_USER", "ps_web_user")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_NAME = os.getenv("DB_NAME", "ps_web")

# tushare 数据源（https://tushare.pro 注册获取）
TUSHARE_TOKEN = os.getenv("TUSHARE_TOKEN", "")

# SQLAlchemy 连接串（PyMySQL 驱动，utf8mb4 支持中文和 emoji）
SQLALCHEMY_DATABASE_URL = (
    f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    "?charset=utf8mb4"
)
