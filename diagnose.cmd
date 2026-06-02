@echo off
setlocal
cd /d "%~dp0"

echo === BotNesia Diagnose ===
echo Folder: %CD%
echo.

echo [1/5] Python version
python --version
echo.

echo [2/5] Import check
python -c "import main; print('import main: OK')"
if errorlevel 1 (
  echo Import failed. Press any key to close.
  pause >nul
  exit /b 1
)
echo.

echo [3/5] Port usage (8000/8001/8002/8010)
netstat -ano | findstr :8000
netstat -ano | findstr :8001
netstat -ano | findstr :8002
netstat -ano | findstr :8010
echo.

echo [4/5] Start server (close window to stop)
echo If you see "Starting BotNesia API on http://127.0.0.1:PORT", open:
echo   http://127.0.0.1:PORT/health
echo.
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
python run_server.py

echo.
echo [5/5] After server stops, last port status:
netstat -ano | findstr :8000
echo.
echo Done. Press any key to close.
pause >nul
