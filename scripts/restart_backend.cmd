@echo off
rem Stop whatever listens on :8000, then start the backend with output in data\runtime\server.log
cd /d "%~dp0.."
for /f "tokens=5" %%a in ('netstat -ano ^| findstr /r /c:":8000 .*LISTENING"') do taskkill /PID %%a /F >nul 2>&1
if not exist data\runtime mkdir data\runtime
if exist .secrets\aws.cmd call .secrets\aws.cmd
start "rescuegrid-backend" /b .venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 > data\runtime\server.log 2>&1
