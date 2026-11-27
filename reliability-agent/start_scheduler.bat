@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHON=python"
if exist ".venv\Scripts\python.exe" set "PYTHON=.venv\Scripts\python.exe"
"%PYTHON%" -m reliability_agent --config config.yaml schedule %*
exit /b %errorlevel%
