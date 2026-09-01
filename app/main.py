"""FastAPI 入口：挂载 API 路由、静态资源、首页。"""
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.routers import health, index_quotes, pvfactor, sentiment, stock, strategy, tasks
from app.task_runner import cleanup_orphans, scheduler_loop

ROOT_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = ROOT_DIR / "templates"
STATIC_DIR = ROOT_DIR / "static"


@asynccontextmanager
async def lifespan(app):
    """启动时：建任务表、清理孤儿运行记录、起调度线程。"""
    cleanup_orphans()
    threading.Thread(target=scheduler_loop, daemon=True,
                     name="task-scheduler").start()
    yield


app = FastAPI(title="ps_web", description="个人综合 Web 应用（远期以股票交易系统为主）",
              lifespan=lifespan)

# API 路由（后续新模块在这里追加 include_router）
app.include_router(health.router)
app.include_router(stock.router)
app.include_router(index_quotes.router)
app.include_router(sentiment.router)
app.include_router(strategy.router)
app.include_router(tasks.router)
app.include_router(pvfactor.router)

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


@app.get("/predict/pvfactor", include_in_schema=False)
def pvfactor_redirect(request: Request):
    """旧地址重定向到 /stockpredict/pvscore。"""
    return RedirectResponse("/stockpredict/pvscore", status_code=307)


@app.get("/stockpredict", include_in_schema=False)
def stockpredict_page():
    """个股预测容器页。"""
    return FileResponse(TEMPLATES_DIR / "stockpredict.html")


@app.get("/stockpredict/rank", include_in_schema=False)
def pvfactor_rank_page():
    """量价因子排名页（任意日期全市场排序）。"""
    return FileResponse(TEMPLATES_DIR / "rank.html")


@app.get("/stockpredict/pvscore", include_in_schema=False)
def pvfactor_page():
    """量价综合分回测页（净值/滚动IC）。"""
    return FileResponse(TEMPLATES_DIR / "pvfactor.html")


@app.get("/index", include_in_schema=False)
def index_quotes_page():
    """指数行情页。"""
    return FileResponse(TEMPLATES_DIR / "index_quotes.html")


@app.get("/strategy", include_in_schema=False)
def strategy_page():
    """买卖策略容器页。"""
    return FileResponse(TEMPLATES_DIR / "strategy.html")


@app.get("/strategy/grid", include_in_schema=False)
def grid_lab_page():
    """网格交易实验室。"""
    return FileResponse(TEMPLATES_DIR / "grid_lab.html")


@app.get("/tasks", include_in_schema=False)
def tasks_page():
    """任务中心。"""
    return FileResponse(TEMPLATES_DIR / "tasks.html")
