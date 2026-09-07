@echo off
REM ── Image Server สำหรับ Power BI (server_image.py, พอร์ต 8080) ───────────
REM  ⚠ ห้ามใช้ `start` — ดูเหตุผลเต็มใน run-backend.bat

set PYTHONUNBUFFERED=1
set PYTHONIOENCODING=utf-8
set ROOT=%~dp0

if not exist "%ROOT%logs" mkdir "%ROOT%logs"

cd /d "%ROOT%Backend-server"
"%ROOT%.venv\Scripts\python.exe" -u server_image.py >> "%ROOT%logs\image.log" 2>&1
