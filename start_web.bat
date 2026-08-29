@echo off
setlocal
cd /d "%~dp0"

rem CsDemoAnalyzer Web 一键启动（双击或命令行）。
rem 用法: start_web.bat [restart]
rem   restart = 先结束已运行实例再启动。改了代码后旧进程不会自动加载新代码，
rem             看到"功能没变化"时用 restart 即可。
rem 服务已运行且未指定 restart 时只打开浏览器，不重复起进程。
rem 等待用 ping 实现（不依赖 timeout.exe，避免 PATH 遮蔽问题）。

set PY=D:\Program Files\Python311\python.exe
set PORT=8000

if not exist "%PY%" (
  echo [CSA] 未找到 Python: %PY%
  pause
  exit /b 1
)

set MODE=%~1
set RUNNING=0
netstat -ano | findstr /R /C:":%PORT% .*LISTENING" >nul 2>&1
if not errorlevel 1 set RUNNING=1

set KILL=0
if /i "%MODE%"=="restart" set KILL=1

rem 已在运行且非 restart：直接开浏览器走人
if "%RUNNING%"=="1" if not "%KILL%"=="1" (
  echo [CSA] 服务已在运行，直接打开浏览器...
  echo [CSA] 改了代码想加载新版本？运行: start_web.bat restart
  start "" http://127.0.0.1:%PORT%
  ping -n 3 127.0.0.1 >nul
  exit /b 0
)

rem 结束端口上的旧实例（restart 或端口被占时）
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":%PORT% .*LISTENING"') do (
  echo [CSA] 结束旧进程 PID=%%P
  taskkill /PID %%P /T /F >nul 2>&1
)
if "%RUNNING%"=="1" ping -n 3 127.0.0.1 >nul

if not exist output mkdir output

echo [CSA] 正在启动 CsDemoAnalyzer Web 服务（最小化窗口，日志见 output\web_server.log）...
start "CSA Web" /MIN cmd /c ""%PY%" -m uvicorn cs_analyzer.web.app:app --host 127.0.0.1 --port %PORT% --log-level info > output\web_server.log 2>&1"

rem 等待端口就绪（最多 ~75 秒；冷启动导入 pandas/numpy 可能偏慢）
set /a tries=0
:wait
ping -n 2 127.0.0.1 >nul
netstat -ano | findstr /R /C:":%PORT% .*LISTENING" >nul 2>&1
if not errorlevel 1 goto up
set /a tries+=1
if %tries% lss 60 goto wait

echo [CSA] 启动超时——日志最后 15 行:
powershell -NoProfile -Command "Get-Content output\web_server.log -Tail 15" 2>nul
echo [CSA] 常见原因: 端口被占用 / 依赖缺失。完整日志: output\web_server.log
pause
exit /b 1

:up
echo [CSA] 服务已启动: http://127.0.0.1:%PORT%
start "" http://127.0.0.1:%PORT%
ping -n 3 127.0.0.1 >nul
exit /b 0
