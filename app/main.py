"""FastAPI 入口：挂载 API 路由、静态资源、首页。"""
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.routers import health, stock

ROOT_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = ROOT_DIR / "templates"
STATIC_DIR = ROOT_DIR / "static"

app = FastAPI(title="ps_web", description="个人综合 Web 应用（远期以股票交易系统为主）")

# API 路由（后续新模块在这里追加 include_router）
app.include_router(health.router)
app.include_router(stock.router)

# 静态资源：/static/css/... /static/js/... /static/vendor/...
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def index():
    """首页：返回 Vue 单页（免编译，直接由后端托管）。"""
    return FileResponse(TEMPLATES_DIR / "index.html")


@app.get("/stock", include_in_schema=False)
def stock_page():
    """个股展示页。"""
    return FileResponse(TEMPLATES_DIR / "stock.html")
