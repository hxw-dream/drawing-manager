@echo off
cd /d %~dp0
start "" /b cmd /c "timeout /t 2 >nul & start http://127.0.0.1:8000"
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
