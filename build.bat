@echo off
chcp 65001 >nul
cd /d %~dp0
if not exist .venv\Scripts\python.exe (
  echo 未找到虚拟环境，请先按 README 初始化项目
  pause & exit /b 1
)
.venv\Scripts\python -m pip show pyinstaller >nul 2>&1 || .venv\Scripts\python -m pip install pyinstaller
.venv\Scripts\python -m PyInstaller --noconfirm drawing-manager.spec || (echo 打包失败 & pause & exit /b 1)
copy /y stop_server.bat "dist\drawing-manager\停止服务.bat" >nul
powershell -NoProfile -Command "Compress-Archive -Path 'dist\drawing-manager\*' -DestinationPath 'dist\drawing-manager-绿色版.zip' -Force"
echo.
echo 打包完成: dist\drawing-manager-绿色版.zip （解压给同事，双击 DrawingManager.exe 即用）
pause
