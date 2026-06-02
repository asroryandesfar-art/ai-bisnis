@echo off
setlocal
cd /d "%~dp0"

set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

echo Running schema.sql into your DATABASE_URL...
python init_db.py
echo.
pause

