@echo off
chcp 65001 >nul
title Markdown Reader
cd /d "%~dp0"
echo.
echo ========================================
echo   Markdown Reader - Local Server Launch
echo ========================================
echo.

set "PORT=8000"
set "LAUNCHED=0"

REM Try Python
where python >nul 2>&1
if %errorlevel%==0 (
    echo [OK] Python found. Starting server...
    echo.
    echo Server: http://localhost:%PORT%/index.html
    echo Press Ctrl+C to stop.
    echo ========================================
    echo.
    start "" "http://localhost:%PORT%/index.html"
    python -m http.server %PORT%
    set "LAUNCHED=1"
    goto :eof
)

REM Try Python3
where python3 >nul 2>&1
if %errorlevel%==0 (
    echo [OK] Python3 found. Starting server...
    echo.
    echo Server: http://localhost:%PORT%/index.html
    echo Press Ctrl+C to stop.
    echo ========================================
    echo.
    start "" "http://localhost:%PORT%/index.html"
    python3 -m http.server %PORT%
    set "LAUNCHED=1"
    goto :eof
)

REM Try Node.js
where node >nul 2>&1
if %errorlevel%==0 (
    echo [OK] Node.js found. Starting server...
    echo.
    echo Server: http://localhost:%PORT%/index.html
    echo Press Ctrl+C to stop.
    echo ========================================
    echo.
    start "" "http://localhost:%PORT%/index.html"
    npx --yes serve -l %PORT% .
    set "LAUNCHED=1"
    goto :eof
)

REM Nothing found
echo.
echo [ERROR] No Python or Node.js found!
echo.
echo Please install one of these:
echo.
echo   Python:  https://www.python.org/downloads/
echo   Node.js: https://nodejs.org/
echo.
echo After install, run this file again.
echo.
pause
