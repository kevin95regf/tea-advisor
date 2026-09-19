@echo off
setlocal
title 中医食性助手 - 终端
cd /d "%~dp0"

if not exist "core\.venv\Scripts\python.exe" (
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
echo   中医食性助手 - 终端版
echo ============================================================
echo   直接输入你吃了什么，例如：
echo       中午吃了碗麻辣烫，还喝了杯冰可乐
echo.
echo   命令： :e 看示例   :c yang_deficiency 换体质   :q 退出
echo.
echo   每次提问约 13-18 秒，会真实调用模型（约 1 分钱/次）。
echo   想零成本试：另开窗口运行
echo       core\.venv\Scripts\python.exe ui\terminal\chat.py --offline
echo ============================================================
echo.

"core\.venv\Scripts\python.exe" ui\terminal\chat.py

echo.
echo 已退出。
pause
