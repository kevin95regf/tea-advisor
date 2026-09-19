@echo off
setlocal
title 中医食性助手 - Web
cd /d "%~dp0core"

if not exist ".venv\Scripts\python.exe" (
  echo.
  echo [错误] 找不到虚拟环境 core\.venv\Scripts\python.exe
  echo.
  echo 请先安装依赖（在 core 目录下执行，用 python -m 是因为 venv 的 pip.exe
  echo 在目录改名后会失效）：
  echo     python -m venv .venv
  echo     .venv\Scripts\python.exe -m pip install -e ".[dev,web]"
  echo.
  pause
  exit /b 1
)

echo.
echo ============================================================
echo   中医食性助手 - 本地 Web 界面
echo ============================================================
echo   浏览器打开： http://127.0.0.1:8000
echo   停止服务：   在本窗口按 Ctrl+C
echo.
echo   本服务只绑定 127.0.0.1，同局域网的其他设备访问不到。
echo   界面顶部有「测试指引」，第一次用请先看它。
echo ============================================================
echo.

rem 延迟 4 秒再开浏览器，等 uvicorn 起来，否则会看到连接失败。
rem 设 TA_NO_BROWSER=1 可跳过开浏览器（自动化测试用）。
if not "%TA_NO_BROWSER%"=="1" (
  start "" /min cmd /c "timeout /t 4 /nobreak >nul & start http://127.0.0.1:8000"
)

".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000

echo.
echo 服务已停止。
pause
