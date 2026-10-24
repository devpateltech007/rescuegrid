@echo off
cd /d "%~dp0.."
if not exist .git git init -b main > data\runtime\git.txt 2>&1
git add -A >> data\runtime\git.txt 2>&1
echo --- staged files containing secrets markers (should be empty): >> data\runtime\git.txt
git grep --cached -l -e "AWS_SECRET_ACCESS_KEY=[A-Za-z0-9/+]" -e "ASIA[A-Z0-9]\{16\}" >> data\runtime\git.txt 2>&1
echo --- status: >> data\runtime\git.txt
git status --short >> data\runtime\git.txt 2>&1
