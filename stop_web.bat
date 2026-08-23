@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

rem CsDemoAnalyzer Web 服务一键关闭：按端口找到进程并结束。

set PORT=8000
set FOUND=0

for /f "tokens=5" %%P in ('netstat -ano ^| findstr /C:":%PORT%" ^| findstr /C:"LISTENING"') do (
  set FOUND=1
  echo [CSA] 结束进程 PID=%%P
  taskkill /PID %%P /T /F >nul 2>&1
)

if !FOUND!==0 (
  echo [CSA] 服务未在运行。
) else (
  echo [CSA] 服务已关闭。
)
ping -n 3 127.0.0.1 >nul
exit /b 0
