@echo off
rem Start the RESCUEGRID 3D backend locally (Windows). AWS credentials are read from
rem .secrets\aws.cmd if present (git-ignored), otherwise from your environment / AWS profile.
cd /d "%~dp0"
if exist .secrets\aws.cmd call .secrets\aws.cmd
.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 %*
