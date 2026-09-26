@echo off
chcp 65001 >nul
rem 停止图纸管理服务（占用 8000 端口的进程）
for /f "tokens=5" %%p in ('netstat -ano ^| findstr /c:":8000" ^| findstr /c:"LISTENING"') do taskkill /PID %%p /F >nul 2>&1
echo 服务已停止（如无提示说明本来就没在运行）
pause
