@echo off
setlocal

for %%P in (8000 8001 8002 8010) do (
  curl -sS -m 2 http://127.0.0.1:%%P/health >nul 2>&1
  if not errorlevel 1 (
    start "" "http://127.0.0.1:%%P/dashboard"
    exit /b 0
  )
)

start "" "http://127.0.0.1:8000/dashboard"
