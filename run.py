"""开发服务器启动入口：python run.py

等价于：uvicorn app.main:app --reload --port 8000
"""
import uvicorn

if __name__ == "__main__":
    # use_colors=False：不输出 ANSI 颜色码（老式控制台不解析，会显示成方框）
    uvicorn.run(
        "app.main:app", host="127.0.0.1", port=8000, reload=True, use_colors=False
    )
