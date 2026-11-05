@echo off
chcp 65001 >nul
echo ==========================================================
echo   ilmhubstt - lokal AI muharrir (Ollama) o'rnatish
echo ==========================================================
where ollama >nul 2>nul
if errorlevel 1 (
  echo Ollama o'rnatilmoqda...
  winget install --id Ollama.Ollama -e --accept-source-agreements --accept-package-agreements
  if errorlevel 1 (
    echo [XATO] Ollama o'rnatilmadi. Qo'lda yuklab oling: https://ollama.com/download
    pause & exit /b 1
  )
  set "PATH=%LOCALAPPDATA%\Programs\Ollama;%PATH%"
)
set MODEL=%1
if "%MODEL%"=="" set MODEL=gemma3:12b
echo.
echo Model yuklanmoqda: %MODEL%  (gemma3:12b ~8 GB, gemma3:4b ~3 GB)
echo Kuchsiz kompyuter yoki 8 GB dan kam video xotira bo'lsa:  setup_ai_editor_windows.bat gemma3:4b
ollama pull %MODEL% || (echo [XATO] model yuklanmadi & pause & exit /b 1)
echo.
echo Sinov:
ollama run %MODEL% "Faqat tuzatilgan matnni yoz: khafsizligini tamillash dogrisida" 
echo.
if not "%MODEL%"=="gemma3:12b" (
  echo DIQQAT: .env faylida OLLAMA_MODEL=%MODEL% deb yozing.
)
echo [OK] Tayyor. ilmhubstt serverini qayta ishga tushiring.
pause
