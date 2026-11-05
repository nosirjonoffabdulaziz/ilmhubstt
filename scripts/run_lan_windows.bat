@echo off
chcp 65001 >nul
cd /d "%~dp0\..\backend"
if not exist .venv\Scripts\python.exe (
  echo Avval scripts\setup_windows.bat ni ishga tushiring.
  pause & exit /b 1
)
echo Telefon kompyuter bilan BIR Wi-Fi tarmog'ida bo'lishi kerak.
echo Agar telefon ochilmasa, Windows Firewall'da 8000-portni oching (administrator CMD):
echo   netsh advfirewall firewall add rule name="ilmhubstt" dir=in action=allow protocol=TCP localport=8000 profile=private
echo Tarmoqqa ochiq bo'lgani uchun .env faylida APP_ACCESS_KEY ni o'rnatish tavsiya etiladi.
echo.
.venv\Scripts\python.exe run.py --lan
pause
