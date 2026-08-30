"""健康检查接口：验证后端存活与数据库连通性。"""
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
def health(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception as exc:  # 连不上时返回具体原因，方便排查
        db_status = f"error: {exc}"
    return {"status": "ok", "database": db_status}
