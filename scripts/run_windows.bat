@echo off
chcp 65001 >nul
cd /d "%~dp0\..\backend"
if not exist .venv\Scripts\python.exe (
  echo Avval scripts\setup_windows.bat ni ishga tushiring.
  pause & exit /b 1
)
start "" /min cmd /c "timeout /t 4 >nul & start http://127.0.0.1:8000"
.venv\Scripts\python.exe run.py %*
pause
