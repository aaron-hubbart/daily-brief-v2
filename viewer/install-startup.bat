@echo off
setlocal enabledelayedexpansion

echo Daily Brief Viewer — Startup Installer
echo ========================================
echo.

:: Auto-detect Python location
set "PYTHON_EXE="
set "PYTHONW_EXE="

:: Try common locations in order
for /f "delims=" %%i in ('where python 2^>nul') do (
    if not defined PYTHON_EXE set "PYTHON_EXE=%%i"
)
:: Try py launcher if python not on PATH
if not defined PYTHON_EXE (
    for /f "delims=" %%i in ('where py 2^>nul') do (
        if not defined PYTHON_EXE set "PYTHON_EXE=%%i"
    )
)
:: Try common install locations
if not defined PYTHON_EXE (
    for %%d in (
        "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
        "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
        "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
        "%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
        "C:\Python313\python.exe"
        "C:\Python312\python.exe"
        "C:\Python311\python.exe"
    ) do (
        if not defined PYTHON_EXE if exist %%d set "PYTHON_EXE=%%~d"
    )
)
if not defined PYTHON_EXE (
    echo ERROR: Python not found. Install from https://python.org
    pause
    exit /b 1
)
echo Python found: %PYTHON_EXE%

:: Derive pythonw.exe from same directory as python.exe
for %%i in ("%PYTHON_EXE%") do set "PYTHON_DIR=%%~dpi"
set "PYTHONW_EXE=%PYTHON_DIR%pythonw.exe"
if not exist "%PYTHONW_EXE%" (
    echo WARNING: pythonw.exe not found, falling back to python.exe
    set "PYTHONW_EXE=%PYTHON_EXE%"
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
"%PYTHON_EXE%" "%SCRIPT_DIR%\patch_task_xml.py" "%TEMP%\db_task.xml" "%TEMP%\db_task_fixed.xml" 2>&1

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
