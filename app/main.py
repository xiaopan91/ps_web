"""FastAPI 入口：挂载 API 路由、静态资源、首页。"""
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.routers import health, index_quotes, sentiment, stock

ROOT_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = ROOT_DIR / "templates"
STATIC_DIR = ROOT_DIR / "static"

app = FastAPI(title="ps_web", description="个人综合 Web 应用（远期以股票交易系统为主）")

# API 路由（后续新模块在这里追加 include_router）
app.include_router(health.router)
app.include_router(stock.router)
app.include_router(index_quotes.router)
app.include_router(sentiment.router)

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


@app.get("/sentiment", include_in_schema=False)
def sentiment_redirect(request: Request):
    """旧地址重定向到 /predict/sentiment（保留查询参数）。"""
    qs = str(request.query_params)
    return RedirectResponse(f"/predict/sentiment?{qs}" if qs else "/predict/sentiment",
                            status_code=307)


@app.get("/predict", include_in_schema=False)
def predict_page():
    """宏观预测容器页。"""
    return FileResponse(TEMPLATES_DIR / "predict.html")


@app.get("/predict/sentiment", include_in_schema=False)
def sentiment_page():
    """市场情绪页（宏观预测下）。"""
    return FileResponse(TEMPLATES_DIR / "sentiment.html")


@app.get("/index", include_in_schema=False)
def index_quotes_page():
    """指数行情页。"""
    return FileResponse(TEMPLATES_DIR / "index_quotes.html")
