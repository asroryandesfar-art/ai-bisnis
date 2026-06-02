@echo off
setlocal
cd /d "%~dp0"

REM Force UTF-8 so console logs don't crash on Unicode
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

REM If the API is already running on 8000, don't start a duplicate server.
powershell -NoProfile -Command "try { $r = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/health' -TimeoutSec 3; if ($r.status) { exit 0 } else { exit 1 } } catch { exit 1 }"
if %ERRORLEVEL%==0 (
  echo BotNesia API sudah berjalan di http://127.0.0.1:8000
  echo Health:    http://127.0.0.1:8000/health
  echo Dashboard: http://127.0.0.1:8000/dashboard
  echo.
  echo Tidak menjalankan server baru agar port 8000 tidak bentrok.
  echo Tutup server lama dulu kalau kamu memang ingin restart manual.
  pause >nul
  exit /b 0
)

echo Starting BotNesia API...
echo (auto pilih port: 8000, 8001, 8002, 8010)
echo.
python run_server.py

echo.
echo Server stopped. Press any key to close.
pause >nul
