@echo off
setlocal enabledelayedexpansion

echo Daily Brief Viewer — Startup Installer
echo ========================================
echo.

:: Hardcoded Python location (found via Get-ChildItem)
set "PYTHON_DIR=C:\Users\AaronHubbart\AppData\Local\Programs\Python\Python312"
set "PYTHONW_EXE=%PYTHON_DIR%\pythonw.exe"
set "PYTHON_EXE=%PYTHON_DIR%\python.exe"

:: Verify pythonw exists, fall back to python if not
if not exist "%PYTHONW_EXE%" (
    echo WARNING: pythonw.exe not found at %PYTHONW_EXE%
    if exist "%PYTHON_EXE%" (
        echo Falling back to python.exe
        set "PYTHONW_EXE=%PYTHON_EXE%"
    ) else (
        echo ERROR: Neither python.exe nor pythonw.exe found in %PYTHON_DIR%
        pause
        exit /b 1
    )
)
echo Using: %PYTHONW_EXE%

:: Resolve the folder this script lives in
set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
set "SERVER_SCRIPT=%SCRIPT_DIR%\server.py"
set "VBS_LAUNCHER=%SCRIPT_DIR%\run-silent.vbs"
set "TASK_NAME=DailyBriefViewer"

if not exist "%SERVER_SCRIPT%" (
    echo ERROR: server.py not found in %SCRIPT_DIR%
    echo Make sure install-startup.bat is in the same folder as server.py.
    pause
    exit /b 1
)
echo Server script: %SERVER_SCRIPT%

:: Write VBS with fully explicit paths — no PATH dependency at runtime
echo.
echo Creating silent launcher...
> "%VBS_LAUNCHER%" (
    echo Dim oShell
    echo Set oShell = CreateObject("WScript.Shell"^)
    echo oShell.Run """!PYTHONW_EXE!"" ""!SERVER_SCRIPT!"" --no-browser", 0, False
)
echo.
echo run-silent.vbs contents:
type "%VBS_LAUNCHER%"
echo.

:: Remove old task
schtasks /delete /tn "%TASK_NAME%" /f >nul 2>&1

:: Create task
schtasks /create ^
  /tn "%TASK_NAME%" ^
  /tr "wscript.exe \"%VBS_LAUNCHER%\"" ^
  /sc ONLOGON ^
  /delay 0000:15 ^
  /f >nul 2>&1

if errorlevel 1 (
    echo ERROR: Could not register startup task.
    echo Right-click install-startup.bat and choose "Run as administrator".
    pause
    exit /b 1
)
echo Startup task registered.

:: Patch battery/power settings via XML
echo Patching power settings...
schtasks /query /tn "%TASK_NAME%" /xml > "%TEMP%\db_task.xml" 2>nul
"%PYTHON_EXE%" -c "
import sys
try:
    with open(r'%TEMP%\db_task.xml', 'r', encoding='utf-16') as f:
        xml = f.read()
    xml = xml.replace('<DisallowStartIfOnBatteries>true</DisallowStartIfOnBatteries>', '<DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>')
    xml = xml.replace('<StopIfGoingOnBatteries>true</StopIfGoingOnBatteries>', '<StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>')
    with open(r'%TEMP%\db_task_fixed.xml', 'w', encoding='utf-16') as f:
        f.write(xml)
    print('Power settings patched.')
except Exception as e:
    print('Could not patch power settings:', e)
    sys.exit(1)
" 2>&1

if not errorlevel 1 (
    schtasks /delete /tn "%TASK_NAME%" /f >nul 2>&1
    schtasks /create /tn "%TASK_NAME%" /xml "%TEMP%\db_task_fixed.xml" /f >nul 2>&1
    if errorlevel 1 echo Note: XML re-import failed, task kept without power patch.
)

:: Kill any running instance
echo.
echo Stopping any existing server...
if exist "%SCRIPT_DIR%\.server.pid" (
    set /p OLD_PID=<"%SCRIPT_DIR%\.server.pid"
    taskkill /pid !OLD_PID! /f >nul 2>&1
    del "%SCRIPT_DIR%\.server.pid" >nul 2>&1
)
for /f "tokens=5" %%p in ('netstat -ano 2^>nul ^| findstr ":8765 " ^| findstr "LISTENING"') do (
    taskkill /pid %%p /f >nul 2>&1
)

:: Start it now
echo Starting server...
wscript.exe "%VBS_LAUNCHER%"
timeout /t 3 /nobreak >nul

netstat -ano 2>nul | findstr ":8765 " | findstr "LISTENING" >nul
if errorlevel 1 (
    echo.
    echo Server not detected on port 8765.
    echo Testing directly -- a console window will appear briefly:
    "%PYTHON_EXE%" "%SERVER_SCRIPT%" --no-browser &
    timeout /t 3 /nobreak >nul
    netstat -ano 2>nul | findstr ":8765 " | findstr "LISTENING" >nul
    if errorlevel 1 (
        echo Still not running. Check server.py for errors.
    ) else (
        echo Server is running via direct launch at http://localhost:8765
        start "" http://localhost:8765
    )
) else (
    echo Server is running at http://localhost:8765
    start "" http://localhost:8765
)

echo.
echo Done. Viewer auto-starts on every login.
echo To remove: run uninstall-startup.bat
echo.
pause
