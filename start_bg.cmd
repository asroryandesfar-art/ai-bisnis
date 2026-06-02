@echo off
setlocal
cd /d "%~dp0"

REM Background runner for BotNesia API (writes logs to files)
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

for /f %%I in ('powershell -NoProfile -Command "try { $r = Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/health -TimeoutSec 2; if ($r.StatusCode -eq 200) { 'RUNNING' } } catch { }"') do set "BOTNESIA_STATUS=%%I"

if /I "%BOTNESIA_STATUS%"=="RUNNING" (
  echo BotNesia API already running on http://127.0.0.1:8000
  echo - Health:    http://127.0.0.1:8000/health
  echo - Dashboard: http://127.0.0.1:8000/dashboard
  exit /b 0
)

if exist run_server.out.log del /f /q run_server.out.log
if exist run_server.err.log del /f /q run_server.err.log

python run_server.py 1> run_server.out.log 2> run_server.err.log
