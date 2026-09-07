@echo off
REM ── ตัวสั่ง TM-X ผ่าน TCP (Pi.py) ────────────────────────────────────────
REM
REM  ⚠⚠ **ไฟล์นี้ควรรันบน Raspberry Pi ไม่ใช่บนเครื่อง PC**
REM     ที่รันบน PC ได้ตอนนี้เพราะยังทดสอบเครื่องเดียว (`AGENT_HOST=127.0.0.1`)
REM     พอแยกเครื่องจริงต้อง **ลบ Task ของไฟล์นี้ออกจาก PC** แล้วไปตั้งบน Pi แทน
REM     ไม่งั้นจะมี 2 ตัวแย่งกันฟัง AGENT_PORT และแย่งกันคุย TM-X
REM
REM  ⚠ ห้ามใช้ `start` — ดูเหตุผลเต็มใน run-backend.bat

set PYTHONUNBUFFERED=1
set PYTHONIOENCODING=utf-8
set ROOT=%~dp0

if not exist "%ROOT%logs" mkdir "%ROOT%logs"

cd /d "%ROOT%Backend-pc_station"
"%ROOT%.venv\Scripts\python.exe" -u Pi.py >> "%ROOT%logs\pi.log" 2>&1
