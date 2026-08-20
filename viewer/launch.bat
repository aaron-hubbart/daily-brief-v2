@echo off
cd /d "%~dp0"
python server.py
if errorlevel 1 (
    echo.
    echo Python not found. Install from https://python.org and try again.
    pause
)
