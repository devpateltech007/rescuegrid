@echo off
rem Usage: scripts\aws_showcase.cmd [setup^|report^|teardown]   (default: report)
cd /d "%~dp0.."
if exist .secrets\aws.cmd call .secrets\aws.cmd
set PYTHONIOENCODING=utf-8
.venv\Scripts\python.exe scripts\deploy\aws_showcase.py %*
