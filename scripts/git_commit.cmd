@echo off
cd /d "%~dp0.."
git rm -r --cached -q frontend/tsconfig.tsbuildinfo >nul 2>&1
git add -A
git -c user.name="RESCUEGRID 3D" -c user.email="rescuegrid3d@localhost" commit -q -m "RESCUEGRID 3D: Helene Swannanoa reconnaissance twin, Bedrock hazard pipeline, routing, EC2 deploy" > data\runtime\gitcommit.txt 2>&1
git log --oneline -n 3 >> data\runtime\gitcommit.txt 2>&1
git ls-files | findstr /i "secrets aws.cmd .env" >> data\runtime\gitcommit.txt 2>&1
echo COMMIT_DONE >> data\runtime\gitcommit.txt
