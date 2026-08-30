"""生产入口：由 NSSM 服务调用（scripts/install_service.bat）。

与 run.py 的区别：
- 监听 0.0.0.0（局域网可访问），端口 8000
- 不带 --reload（那是开发特性，生产环境反而碍事）
- use_colors=False：服务日志落盘，不能有 ANSI 转义字节
"""
import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app", host="0.0.0.0", port=8000, reload=False, use_colors=False
    )
