@echo off
setlocal enabledelayedexpansion
rem ===========================================================================
rem  BasketBuddy - ONE-TIME laptop setup.
rem  Run this ONCE on a new machine, then use localrun.bat to start the app.
rem
rem  It mirrors localrun.bat's Python choice (Anaconda if present, else a venv),
rem  installs the backend deps INTO that interpreter, downloads the CloakBrowser
rem  stealth browser, installs the frontend deps, and checks your API keys.
rem ===========================================================================

echo.
echo ============================================
echo   BasketBuddy - one-time laptop setup
echo ============================================
echo.

set "ROOT=%~dp0"
set "BACKEND=%ROOT%backend"
set "FRONTEND=%ROOT%frontend"

rem --- 1. Pick the SAME Python localrun.bat will use -------------------------
set "PYTHON="
if exist "%USERPROFILE%\anaconda3\python.exe"  set "PYTHON=%USERPROFILE%\anaconda3\python.exe"
if not defined PYTHON if exist "%USERPROFILE%\miniconda3\python.exe" set "PYTHON=%USERPROFILE%\miniconda3\python.exe"

if not defined PYTHON (
    echo [setup] No Anaconda/Miniconda found - creating a virtual environment instead.
    set "VENV=%BACKEND%\.venv"
    set "VENV_PY=!VENV!\Scripts\python.exe"
    if not exist "!VENV_PY!" (
        set "BASEPY="
        py -3 --version >nul 2>&1 && set "BASEPY=py -3"
        if not defined BASEPY ( where python >nul 2>&1 && set "BASEPY=python" )
        if not defined BASEPY (
            echo ERROR: No Python 3 found. Install it from https://www.python.org/downloads/
            echo        ^(tick "Add python.exe to PATH"^) and re-run this script.
            pause & exit /b 1
        )
        echo [setup] Creating venv at !VENV! ...
        !BASEPY! -m venv "!VENV!" || (echo ERROR: Failed to create the venv. & pause & exit /b 1)
    )
    set "PYTHON=!VENV_PY!"
    set "USING_VENV=1"
)
echo [setup] Using Python: !PYTHON!
echo.

rem --- 2. Backend Python dependencies ---------------------------------------
echo [setup] Installing backend dependencies (this can take a few minutes)...
"!PYTHON!" -m pip install --upgrade pip
"!PYTHON!" -m pip install -r "%BACKEND%\requirements.txt" || (echo ERROR: pip install failed. & pause & exit /b 1)
rem mark the venv as provisioned so localrun.bat does not reinstall
if defined USING_VENV echo installed> "%BACKEND%\.venv\.deps_installed"
echo.

rem --- 3. CloakBrowser stealth Chromium (~500MB, per-machine, one-time) ------
echo [setup] Downloading the CloakBrowser stealth browser (~500MB, one-time)...
"!PYTHON!" -m cloakbrowser install
"!PYTHON!" -m cloakbrowser info >nul 2>&1 && (echo [setup] CloakBrowser ready.) || (echo [setup] WARNING: CloakBrowser browser not installed - Walmart/Target pricing will be unavailable until 'python -m cloakbrowser install' succeeds.)
echo.

rem --- 4. Frontend dependencies ---------------------------------------------
where node >nul 2>&1
if %errorlevel%==0 (
    echo [setup] Installing frontend dependencies...
    pushd "%FRONTEND%"
    call npm install
    popd
) else (
    echo [setup] WARNING: Node.js not found. Install it from https://nodejs.org
    echo        then run "npm install" inside the frontend folder.
)
echo.

rem --- 5. Verify secrets present --------------------------------------------
if exist "%BACKEND%\config.env" (
    echo [setup] config.env found - API keys present.
) else (
    echo [setup] WARNING: backend\config.env is missing.
    echo        Copy it from the source laptop or most stores will be skipped.
)

echo.
echo ============================================
echo   Setup complete.  Start the app with:
echo        localrun.bat
echo ============================================
echo.
pause
