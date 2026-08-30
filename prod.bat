@echo off
title ps_web production console
cd /d "%~dp0"
set NSSM=%~dp0tools\nssm.exe
set LOGFILE=%~dp0logs\service.log

:menu
cls
echo ============================================
echo    ps_web PRODUCTION console
echo ============================================
sc query ps_web | findstr RUNNING >nul 2>&1
if errorlevel 1 (set STS=STOPPED) else (set STS=RUNNING)
echo    service : %STS%
echo    local   : http://127.0.0.1:8000
powershell -NoProfile -Command "$ip=(Get-NetIPAddress -AddressFamily IPv4 | Where-Object {$_.IPAddress -match '^(192\.168\.|10\.|172\.(1[6-9]|2[0-9]|3[01])\.)'} | Select-Object -First 1).IPAddress; if($ip){Write-Host ('    LAN     : http://'+$ip+':8000')}"
echo --------------------------------------------
echo   [1] start service          (UAC prompt)
echo   [2] stop service           (UAC prompt)
echo   [3] restart service        (UAC prompt, use after code changes)
echo   [4] show last 50 log lines
echo   [5] show last 200 log lines
echo   [6] open app in browser
echo   [7] health check
echo   [q] quit
echo.
set "CHOICE="
set /p CHOICE=select:
if not defined CHOICE goto menu
if "%CHOICE%"=="1" goto svc_start
if "%CHOICE%"=="2" goto svc_stop
if "%CHOICE%"=="3" goto svc_restart
if "%CHOICE%"=="4" goto log50
if "%CHOICE%"=="5" goto log200
if "%CHOICE%"=="6" goto browser
if "%CHOICE%"=="7" goto health
if /i "%CHOICE%"=="q" exit /b 0
goto menu

:svc_start
call :elevate start
echo done.
pause
goto menu

:svc_stop
call :elevate stop
echo done.
pause
goto menu

:svc_restart
call :elevate restart
echo done.
pause
goto menu

:log50
call :showlog 50
goto menu

:log200
call :showlog 200
goto menu

:showlog
if not exist "%LOGFILE%" (
    echo [INFO] no log file yet: %LOGFILE%
) else (
    powershell -NoProfile -Command "Get-Content -LiteralPath '%LOGFILE%' -Tail %1"
)
echo.
pause
goto :eof

:browser
start http://127.0.0.1:8000
goto menu

:health
%SystemRoot%\System32\curl.exe -s -m 5 http://127.0.0.1:8000/api/health
echo.
echo (empty means service not responding)
pause
goto menu

:elevate
rem %1 = start|stop|restart, each triggers one UAC confirmation
powershell -NoProfile -Command "Start-Process -FilePath '%NSSM%' -ArgumentList '%1','ps_web' -Verb RunAs -Wait"
goto :eof
