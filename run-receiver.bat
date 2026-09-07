@echo off
REM ── FTP server รับค่า+รูปจาก TM-X (Data-receiver.py) ─────────────────────
REM  ⚠ ห้ามใช้ `start` — ดูเหตุผลเต็มใน run-backend.bat

set PYTHONUNBUFFERED=1
set PYTHONIOENCODING=utf-8
set ROOT=%~dp0

if not exist "%ROOT%logs" mkdir "%ROOT%logs"

cd /d "%ROOT%Backend-server"
"%ROOT%.venv\Scripts\python.exe" -u Data-receiver.py >> "%ROOT%logs\receiver.log" 2>&1
