@echo off
chcp 65001 >nul
title Markdown 阅读器 - 本地服务器
color 0A

echo ========================================
echo   📖 Markdown 阅读器 一键启动
echo ========================================
echo.
echo 正在启动本地 HTTP 服务器...
echo.

cd /d "%~dp0"

REM 尝试用 Python 启动 HTTP 服务器
where python >nul 2>&1
if %errorlevel%==0 (
    echo ✅ 检测到 Python，启动服务器中...
    echo.
    echo 服务器地址: http://localhost:8000
    echo.
    echo 按 Ctrl+C 停止服务器
    echo ========================================
    echo.
    start "" "http://localhost:8000/index.html"
    python -m http.server 8000
    goto :eof
)

REM 尝试用 Python3
where python3 >nul 2>&1
if %errorlevel%==0 (
    echo ✅ 检测到 Python3，启动服务器中...
    echo.
    echo 服务器地址: http://localhost:8000
    echo.
    echo 按 Ctrl+C 停止服务器
    echo ========================================
    echo.
    start "" "http://localhost:8000/index.html"
    python3 -m http.server 8000
    goto :eof
)

REM 尝试用 Node.js
where node >nul 2>&1
if %errorlevel%==0 (
    echo ✅ 检测到 Node.js，启动服务器中...
    echo.
    echo 服务器地址: http://localhost:8000
    echo.
    echo 按 Ctrl+C 停止服务器
    echo ========================================
    echo.
    start "" "http://localhost:8000/index.html"
    npx serve -l 8000 .
    goto :eof
)

REM 都没找到
echo.
echo ❌ 未检测到 Python 或 Node.js
echo.
echo 请先安装其中一个：
echo.
echo   Python:  https://www.python.org/downloads/
echo   Node.js: https://nodejs.org/
echo.
echo 安装后重新运行本脚本即可。
echo.
pause
