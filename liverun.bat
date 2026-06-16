@echo off
rem ---------------------------------------------------------------------------
rem  LIVE MODE: frontend talks to the deployed Render backend.
rem  No local backend is started — Render is already running the deployed code.
rem  Use localrun.bat instead to test against this machine's backend on :8002.
rem ---------------------------------------------------------------------------

echo.
echo   Starting BasketBuddy [LIVE MODE]...
echo   Backend  --^>  https://route52.onrender.com   (deployed Render)
echo   Frontend --^>  http://localhost:8081
echo.

cd /d "%~dp0frontend"
set "EXPO_PUBLIC_API_TARGET=live"
call npx expo start -c
goto :eof
