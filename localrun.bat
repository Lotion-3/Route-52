@echo off
if "%1"=="--backend" goto :backend

echo.
echo   Starting BasketBuddy [LOCAL MODE]...
echo   Backend  --^>  http://localhost:8002   (this machine)
echo   Frontend --^>  http://localhost:8081
echo.

for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8002 " ^| findstr "LISTENING"') do taskkill /f /pid %%a >nul 2>&1
start "BasketBuddy Backend" cmd /k ""%~f0" --backend"
cd /d "%~dp0frontend"
set "EXPO_PUBLIC_API_TARGET=local"
call npx expo start -c
goto :eof

:backend
set PYTHON=C:\Users\laksh\anaconda3\python.exe
if not exist "%PYTHON%" set PYTHON=C:\Users\laksh\anaconda3\envs\base\python.exe
if not exist "%PYTHON%" (echo ERROR: Cannot find Anaconda Python & pause & exit /b 1)
set "PYTHONPATH=%~dp0backend\aldi;%~dp0backend"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0backend"
if exist "aldi\.aldi_session.json" del "aldi\.aldi_session.json"
echo [backend] Running on http://localhost:8002
set PORT=8002
%PYTHON% server.py
