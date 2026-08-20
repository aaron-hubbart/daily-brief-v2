@echo off
echo Removing Daily Brief Viewer from startup...

schtasks /delete /tn "DailyBriefViewer" /f >nul 2>&1
if errorlevel 1 (
    echo Task not found or already removed.
) else (
    echo Startup task removed.
)

:: Stop running instance via PID file if available
if exist "%~dp0.server.pid" (
    set /p PID=<"%~dp0.server.pid"
    taskkill /pid %PID% /f >nul 2>&1
    del "%~dp0.server.pid" >nul 2>&1
    echo Server stopped.
) else (
    for /f "tokens=5" %%p in ('netstat -ano 2^>nul ^| findstr ":8765 " ^| findstr "LISTENING"') do (
        taskkill /pid %%p /f >nul 2>&1
        echo Server stopped.
    )
)

echo Done.
pause
