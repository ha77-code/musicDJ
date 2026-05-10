@echo off
chcp 65001 >nul
title Music DJ
cd /d "%~dp0"

echo.
echo ========================================
echo         Music DJ - Starting...
echo ========================================
echo.

set PYTHON=
set NODE=

:: -- Find Python --
if exist "C:\anaconda3\python.exe" (
    set PYTHON=C:\anaconda3\python.exe
)
if not defined PYTHON (
    where python >nul 2>&1
    if %errorlevel% equ 0 set PYTHON=python
)
if not defined PYTHON (
    echo [ERROR] Python not found. Please install Python 3.10+
    pause
    exit /b 1
)
echo [OK] Python: %PYTHON%

:: -- Find Node.js --
where node >nul 2>&1
if %errorlevel% neq 0 (
    echo [WARN] Node.js not found - Netease API unavailable
) else (
    echo [OK] Node.js found
)

:: -- Install Python deps --
%PYTHON% -c "import flask" 2>nul
if %errorlevel% neq 0 (
    echo [INFO] Installing Python dependencies...
    %PYTHON% -m pip install flask requests mutagen pycryptodome --quiet 2>nul
)

:: -- Kill existing processes on our ports --
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8765" ^| findstr "LISTENING" 2^>nul') do (
    taskkill /f /pid %%a >nul 2>&1
)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":3000" ^| findstr "LISTENING" 2^>nul') do (
    taskkill /f /pid %%a >nul 2>&1
)

:: -- Start NeteaseCloudMusicApi (:3000) --
where node >nul 2>&1
if %errorlevel% equ 0 (
    echo [START] NeteaseCloudMusicApi on port 3000...
    cd /d "%~dp0NeteaseCloudMusicApi\api-enhanced-main"
    start "NeteaseAPI" /min cmd /c "node app.js"
    cd /d "%~dp0"
    timeout /t 3 /nobreak >nul
)

:: -- Start Flask Backend (:8765) --
echo [START] Music DJ Backend on http://localhost:8765
start /b "" %PYTHON% backend\dj_server.py >nul 2>&1

:: -- Wait and open browser --
timeout /t 2 /nobreak >nul
echo [OPEN] Launching browser...
start http://localhost:8765

echo.
echo ========================================
echo   Music DJ is running!
echo   Flask     : http://localhost:8765
echo   Netease API: http://localhost:3000
echo.
echo   Close this window to stop all servers.
echo ========================================
echo.
pause >nul

:: -- Cleanup --
echo [STOP] Shutting down...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8765" ^| findstr "LISTENING" 2^>nul') do (
    taskkill /f /pid %%a >nul 2>&1
)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":3000" ^| findstr "LISTENING" 2^>nul') do (
    taskkill /f /pid %%a >nul 2>&1
)
echo [DONE] All servers stopped.
