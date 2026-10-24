@echo off
rem Unit/integration tests (no AWS calls) -> data\runtime\pytest.txt
cd /d "%~dp0.."
if not exist data\runtime mkdir data\runtime
.venv\Scripts\python.exe -m pytest backend\tests -q -p no:cacheprovider > data\runtime\pytest.txt 2>&1
echo EXIT %ERRORLEVEL% >> data\runtime\pytest.txt
