@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0\.."
echo ==========================================================
echo   ilmhubstt - o'rnatish (Windows)
echo ==========================================================

rem faster-whisper uchun Python 3.12 / 3.11 / 3.13 tavsiya etiladi (3.14 hali to'liq qo'llanmaydi)
set PY=
for %%V in (3.12 3.11 3.13 3.10) do (
  if not defined PY (
    py -%%V -c "import sys" >nul 2>nul && set PY=py -%%V
  )
)
if not defined PY (
  echo [XATO] Python 3.10-3.13 topilmadi.
  echo        O'rnating:  winget install --id Python.Python.3.12 -e
  echo        So'ng VS Code'ni yopib qayta oching va bu faylni qayta ishga tushiring.
  pause & exit /b 1
)
echo Python: %PY%

where ffmpeg >nul 2>nul
if errorlevel 1 (
  echo [XATO] FFmpeg topilmadi. O'rnating:  winget install --id Gyan.FFmpeg -e
  echo        So'ng VS Code'ni yopib qayta oching va bu faylni qayta ishga tushiring.
  pause & exit /b 1
)

if exist backend\.venv\Scripts\python.exe (
  backend\.venv\Scripts\python.exe -c "import sys; assert sys.version_info < (3,14)" >nul 2>nul || (
    echo Eski .venv Python 3.14 bilan yaratilgan - qayta yaratiladi...
    rmdir /s /q backend\.venv
  )
)
if not exist backend\.venv (
  echo Virtual muhit yaratilmoqda...
  %PY% -m venv backend\.venv || (echo [XATO] venv yaratilmadi & pause & exit /b 1)
)
echo Kutubxonalar o'rnatilmoqda (bir necha daqiqa)...
backend\.venv\Scripts\python.exe -m pip install --upgrade pip
backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt || (echo [XATO] pip install muvaffaqiyatsiz & pause & exit /b 1)
backend\.venv\Scripts\python.exe -c "import faster_whisper, ctranslate2; print('[OK] faster-whisper', faster_whisper.__version__)" || (echo [XATO] faster-whisper import bo'lmadi & pause & exit /b 1)

if not exist .env copy .env.example .env >nul
echo.
echo [OK] O'rnatish tugadi. Ishga tushirish: scripts\run_windows.bat
echo      Birinchi transkripsiyada model internetdan yuklanadi (0.5-1.6 GB).
pause
