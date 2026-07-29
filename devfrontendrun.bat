@echo off
rem ---------------------------------------------------------------------------
rem  DEVELOPER FRONTEND: fully static, edit-easy copy of the app.
rem  Zero backend, zero network calls — every screen runs on baked-in mock
rem  data (developerFrontEnd/mocks/demoMealPlan.ts). Safe to restyle freely;
rem  nothing here touches the real frontend/ or any live backend.
rem  See developerFrontEnd/README.md for details.
rem ---------------------------------------------------------------------------

echo.
echo   Starting BasketBuddy [DEVELOPER FRONTEND - static demo]...
echo   Backend  --^>  none (static mock data only)
echo   Frontend --^>  http://localhost:8090
echo.

cd /d "%~dp0developerFrontEnd"
where node >nul 2>&1 || (echo ERROR: Node.js not found. Install it from https://nodejs.org and re-run. & pause & exit /b 1)
if not exist "node_modules" (
    echo Installing developerFrontEnd dependencies ^(first run only, can take a few minutes^)...
    call npm install
)
call npx expo start -c --port 8090
goto :eof
