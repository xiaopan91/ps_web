@echo off
chcp 65001 >nul
title ps_web 开发服务
cd /d "%~dp0"

echo ============================================
echo    ps_web 一键启动
echo ============================================

rem ---- 1. 检查虚拟环境 ----
if not exist ".venv\Scripts\python.exe" (
    echo [错误] 未找到虚拟环境 .venv
    echo        请先在项目目录执行:
    echo            python -m venv .venv
    echo            .venv\Scripts\python -m pip install -r requirements.txt
    pause
    exit /b 1
)
echo [OK] 虚拟环境就绪

rem ---- 2. 检查 MySQL 服务（停了就试着拉起）----
sc query MySQL80 | findstr RUNNING >nul 2>&1
if errorlevel 1 (
    echo [信息] MySQL80 未运行，尝试启动...
    net start MySQL80 >nul 2>&1
    sc query MySQL80 | findstr RUNNING >nul 2>&1
    if errorlevel 1 (
        echo [警告] MySQL80 启动失败，多半是权限不够
        echo        请右键以管理员身份运行本脚本。Web 仍会启动，但页面上数据库是红灯。
    ) else (
        echo [OK] MySQL80 已启动
    )
) else (
    echo [OK] MySQL80 运行中
)

rem ---- 3. 服务已在跑就只开浏览器 ----
netstat -ano | findstr :8000 | findstr LISTENING >nul 2>&1
if not errorlevel 1 (
    echo [信息] 端口 8000 已有服务在跑，直接打开浏览器
    start http://127.0.0.1:8000
    %SystemRoot%\System32\timeout.exe /t 2 >nul
    exit /b 0
)

rem ---- 4. 后台小助手：等服务可连接后自动开浏览器 ----
start "" /min powershell -NoProfile -WindowStyle Hidden -Command "for($i=0;$i -lt 40;$i++){try{$c=New-Object Net.Sockets.TcpClient;$c.Connect('127.0.0.1',8000);$c.Close();Start-Process 'http://127.0.0.1:8000';break}catch{Start-Sleep 1}}"

rem ---- 5. 前台启动开发服务器（本窗口即日志窗口，Ctrl+C 停止）----
echo [OK] 启动开发服务器：http://127.0.0.1:8000
".venv\Scripts\python.exe" run.py

echo.
echo [信息] 服务已停止
pause
