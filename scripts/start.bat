@echo off
chcp 65001 >nul
cd /d "%~dp0.."
echo === PBC 智能管理工作站 启动 ===
"C:\Users\caca\.workbuddy\binaries\python\envs\default\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
pause
