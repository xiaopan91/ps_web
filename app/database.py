"""SQLAlchemy 数据库引擎与会话。"""
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import SQLALCHEMY_DATABASE_URL

# pool_pre_ping：取连接前先探活，避免 MySQL 闲置断开后报错
engine = create_engine(SQLALCHEMY_DATABASE_URL, pool_pre_ping=True, pool_recycle=3600)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

# 所有 ORM 模型都继承 Base
Base = declarative_base()


def get_db():
    """FastAPI 依赖：每个请求一个会话，用完自动关闭。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
