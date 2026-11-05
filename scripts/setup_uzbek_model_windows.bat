@echo off
chcp 65001 >nul
cd /d "%~dp0\..\backend"
if not exist .venv\Scripts\python.exe (
  echo Avval scripts\setup_windows.bat ni ishga tushiring.
  pause & exit /b 1
)
.venv\Scripts\python.exe setup_uzbek_model.py %*
pause
