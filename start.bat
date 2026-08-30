@echo off
title ps_web dev server
cd /d "%~dp0"

echo ============================================
echo    ps_web one-click launcher
echo ============================================

rem ---- 1. check venv ----
if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] venv not found: .venv
    echo         run these first:
    echo             python -m venv .venv
    echo             .venv\Scripts\python -m pip install -r requirements.txt
    echo Press any key to exit...
    pause >nul
    exit /b 1
)
echo [OK] venv ready

rem ---- 2. check MySQL service, start it if stopped ----
sc query MySQL80 | findstr RUNNING >nul 2>&1
if errorlevel 1 (
    echo [INFO] MySQL80 not running, trying to start...
    net start MySQL80 >nul 2>&1
    sc query MySQL80 | findstr RUNNING >nul 2>&1
    if errorlevel 1 (
        echo [WARN] MySQL80 start failed - probably no permission
        echo        Right-click the script and "Run as administrator".
        echo        Web will still start, but DB shows red on the page.
    ) else (
        echo [OK] MySQL80 started
    )
) else (
    echo [OK] MySQL80 running
)

rem ---- 3. already running? just open browser ----
netstat -ano | findstr :8000 | findstr LISTENING >nul 2>&1
if not errorlevel 1 (
    echo [INFO] port 8000 already in use, opening browser only
    start http://127.0.0.1:8000
    %SystemRoot%\System32\timeout.exe /t 2 >nul
    exit /b 0
)

rem ---- 4. background helper: open browser once server is reachable ----
start "" /min powershell -NoProfile -WindowStyle Hidden -Command "for($i=0;$i -lt 40;$i++){try{$c=New-Object Net.Sockets.TcpClient;$c.Connect('127.0.0.1',8000);$c.Close();Start-Process 'http://127.0.0.1:8000';break}catch{Start-Sleep 1}}"

rem ---- 5. start dev server in foreground (this window = log window, Ctrl+C to stop) ----
echo [OK] starting dev server: http://127.0.0.1:8000
".venv\Scripts\python.exe" run.py

echo.
echo [INFO] server stopped
echo Press any key to exit...
pause >nul
