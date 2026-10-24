@echo off
rem Type-check and build the frontend into frontend\dist (served by FastAPI).
cd /d "%~dp0..\frontend"
if not exist node_modules call npm install --no-audit --no-fund
call npx tsc -p tsconfig.json --noEmit || exit /b 1
call npx vite build || exit /b 1
echo FRONTEND_BUILD_OK
