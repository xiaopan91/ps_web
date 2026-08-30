@echo off
title ps_web service installer
rem ============================================
rem   Install ps_web as a Windows service (NSSM)
rem   Run as Administrator!
rem   - auto start on boot
rem   - auto restart 5s after crash
rem   - log to logs\service.log, rotate at 10MB
rem   - firewall rule for LAN access on port 8000
rem ============================================

rem ---- must be admin ----
net session >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Administrator rights required.
    echo         Right-click this file and "Run as administrator".
    echo Press any key to exit...
    pause >nul
    exit /b 1
)

set PROJECT=D:\claude\ps_web
set NSSM=%PROJECT%\tools\nssm.exe
set PY=%PROJECT%\.venv\Scripts\python.exe

if not exist "%NSSM%" (
    echo [ERROR] %NSSM% not found. Download nssm and put it there first.
    echo Press any key to exit...
    pause >nul
    exit /b 1
)
if not exist "%PY%" (
    echo [ERROR] %PY% not found. Create the venv first.
    echo Press any key to exit...
    pause >nul
    exit /b 1
)
if not exist "%PROJECT%\logs" mkdir "%PROJECT%\logs"

echo [1/6] installing service ps_web ...
"%NSSM%" install ps_web "%PY%" "%PROJECT%\run_prod.py"
"%NSSM%" set ps_web AppDirectory "%PROJECT%"

echo [2/6] log to file with rotation ...
"%NSSM%" set ps_web AppStdout "%PROJECT%\logs\service.log"
"%NSSM%" set ps_web AppStderr "%PROJECT%\logs\service.log"
"%NSSM%" set ps_web AppRotateFiles 1
"%NSSM%" set ps_web AppRotateBytes 10485760

echo [3/6] restart on crash after 5s ...
"%NSSM%" set ps_web AppExit Default Restart
"%NSSM%" set ps_web AppRestartDelay 5000

echo [4/6] auto start on boot ...
"%NSSM%" set ps_web Start SERVICE_AUTO_START

echo [5/6] firewall rule for port 8000 ...
netsh advfirewall firewall delete rule name="ps_web 8000" >nul 2>&1
netsh advfirewall firewall add rule name="ps_web 8000" dir=in action=allow protocol=TCP localport=8000 >nul

echo [6/6] starting service ...
"%NSSM%" start ps_web
%SystemRoot%\System32\timeout.exe /t 3 >nul

sc query ps_web | findstr RUNNING >nul 2>&1
if errorlevel 1 (
    echo [WARN] service not running yet - check: nssm status ps_web
) else (
    echo [OK] service ps_web is RUNNING
    echo      local:  http://127.0.0.1:8000
    echo      LAN:    http://^<your-ip^>:8000
)
echo.
echo Press any key to exit...
pause >nul
