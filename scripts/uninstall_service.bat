@echo off
title ps_web service uninstaller
rem Remove the ps_web service and its firewall rule. Run as Administrator.

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

echo [1/3] stopping service ...
"%NSSM%" stop ps_web

echo [2/3] removing firewall rule ...
netsh advfirewall firewall delete rule name="ps_web 8000" >nul 2>&1

echo [3/3] removing service ...
"%NSSM%" remove ps_web confirm

echo [DONE] service removed.
echo Press any key to exit...
pause >nul
