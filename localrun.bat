@echo off
setlocal enabledelayedexpansion
if "%1"=="--backend" goto :backend

echo.
echo   Starting BasketBuddy [LOCAL MODE]...
echo   Backend  --^>  http://localhost:8002   (this machine)
echo   Frontend --^>  http://localhost:8081
echo.

rem --- free port 8002 if something is already listening ---
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8002 " ^| findstr "LISTENING"') do taskkill /f /pid %%a >nul 2>&1

rem --- launch the backend in its own window ---
start "BasketBuddy Backend" cmd /k ""%~f0" --backend"

rem --- frontend: make sure Node deps exist, then start Expo ---
cd /d "%~dp0frontend"
where node >nul 2>&1 || (echo ERROR: Node.js not found. Install it from https://nodejs.org and re-run. & pause & exit /b 1)
if not exist "node_modules" (
    echo Installing frontend dependencies ^(first run only, can take a few minutes^)...
    call npm install
)
set "EXPO_PUBLIC_API_TARGET=local"
call npx expo start -c
goto :eof


:backend
rem ===========================================================================
rem  Backend launcher.
rem  Prefers Anaconda if it's installed; otherwise creates a standard Python
rem  venv and installs requirements automatically (first run only). This makes
rem  the script portable to any Windows machine, conda or not.
rem ===========================================================================
set "ROOT=%~dp0"
set "BACKEND=%ROOT%backend"

rem --- 1. Use Anaconda / Miniconda if it's present ---
set "PYTHON="
if exist "%USERPROFILE%\anaconda3\python.exe" set "PYTHON=%USERPROFILE%\anaconda3\python.exe"
if not defined PYTHON if exist "%USERPROFILE%\miniconda3\python.exe" set "PYTHON=%USERPROFILE%\miniconda3\python.exe"
if not defined PYTHON if exist "C:\Users\laksh\anaconda3\python.exe" set "PYTHON=C:\Users\laksh\anaconda3\python.exe"

rem --- 2. No conda → set up a standard virtual environment ---
if not defined PYTHON (
    echo [backend] No Anaconda found - using a standard Python venv instead.
    set "VENV=%BACKEND%\.venv"
    set "VENV_PY=!VENV!\Scripts\python.exe"

    if not exist "!VENV_PY!" (
        echo [backend] Locating a base Python to build the venv...
        set "BASEPY="
        py -3 --version >nul 2>&1 && set "BASEPY=py -3"
        if not defined BASEPY (
            where python >nul 2>&1 && set "BASEPY=python"
        )
        if not defined BASEPY (
            echo ERROR: No Python 3 found on this machine.
            echo Install it from https://www.python.org/downloads/ ^(tick "Add python.exe to PATH"^) and re-run.
            pause & exit /b 1
        )
        echo [backend] Creating venv at !VENV! ...
        !BASEPY! -m venv "!VENV!" || (echo ERROR: Failed to create the virtual environment. & pause & exit /b 1)
    )

    set "PYTHON=!VENV_PY!"

    rem --- install requirements once; sentinel avoids reinstalling every launch ---
    if not exist "!VENV!\.deps_installed" (
        echo [backend] Installing Python dependencies ^(first run only, can take a few minutes^)...
        "!PYTHON!" -m pip install --upgrade pip
        "!PYTHON!" -m pip install -r "%BACKEND%\requirements.txt" || (echo ERROR: pip install failed. & pause & exit /b 1)
        echo installed> "!VENV!\.deps_installed"
    )
)

rem --- 3. Run the server ---
set "PYTHONPATH=%BACKEND%\aldi;%BACKEND%"
set "PYTHONIOENCODING=utf-8"
cd /d "%BACKEND%"
if exist "aldi\.aldi_session.json" del "aldi\.aldi_session.json"
echo [backend] Using Python: !PYTHON!
echo [backend] Running on http://localhost:8002
set PORT=8002
"!PYTHON!" server.py
goto :eof
