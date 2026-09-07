@echo off

set PYTHONUNBUFFERED=1
set PYTHONIOENCODING=utf-8
set ROOT=%~dp0

REM `>>` ไม่สร้างโฟลเดอร์ให้เอง — ถ้าไม่มีจะ error แล้วเงียบไปเลย
if not exist "%ROOT%logs" mkdir "%ROOT%logs"

cd /d "%ROOT%Backend-server"
"%ROOT%.venv\Scripts\python.exe" -u main_split.py >> "%ROOT%logs\backend.log" 2>&1
