@echo off
REM ── เปิดทุกอย่างของ TM-X ในไฟล์เดียว ─────────────────────────────────────
REM
REM  ⚠⚠ **ต้องเป็น `start /B cmd /c "..."` เท่านั้น** ห้ามเขียนแบบใดแบบหนึ่งนี้
REM
REM     start "" python.exe -u x.py >> log 2>&1      ← log ว่างเปล่า!
REM        `>>` ผูกกับตัว `start` ไม่ใช่กับ python · python ได้ console ใหม่
REM        แล้วพิมพ์ลงที่นั่นแทน (เจอมาแล้ว: python รัน 8 ตัวแต่ log ไม่มีอะไรเลย)
REM
REM     python.exe -u x.py >> log 2>&1               ← ค้างที่ตัวแรก
REM        ไม่มี `start` แปลว่ารอจนกว่า python จะจบ ซึ่งไม่มีวันจบ
REM        บรรทัดที่ 2-4 จึงไม่เคยถูกเรียก
REM
REM     `start /B cmd /c "..."` แก้ทั้งสองอย่างพร้อมกัน:
REM        /B      = ไม่เปิดหน้าต่างใหม่ (Operator จะไม่เห็นและเผลอปิดไม่ได้)
REM        cmd /c  = ให้ cmd ตัวในเป็นคนตีความ `>>` จึงผูกกับ python จริง ๆ
REM
REM  ⚠ `%~dp0` = โฟลเดอร์ที่ไฟล์นี้วางอยู่ (มี \ ปิดท้ายให้แล้ว) — ก๊อปไปเครื่อง
REM    ไหนก็ทำงานได้โดยไม่ต้องแก้ ขอแค่วางไว้ที่รากของโปรเจกต์ (ระดับเดียวกับ .venv)

set PYTHONUNBUFFERED=1
set PYTHONIOENCODING=utf-8
set ROOT=%~dp0
set PY=%ROOT%.venv\Scripts\python.exe

REM `>>` ไม่สร้างโฟลเดอร์ให้เอง — ไม่มีแล้วจะ error เงียบ ๆ
if not exist "%ROOT%logs" mkdir "%ROOT%logs"

cd /d "%ROOT%Backend-server"
start /B cmd /c ""%PY%" -u main_split.py    >> "%ROOT%logs\backend.log"  2>&1"
start /B cmd /c ""%PY%" -u Data-receiver.py >> "%ROOT%logs\receiver.log" 2>&1"
start /B cmd /c ""%PY%" -u server_image.py  >> "%ROOT%logs\image.log"    2>&1"

REM ⚠ Pi.py ควรรันบน Raspberry Pi ไม่ใช่ PC — ที่รันตรงนี้ได้เพราะยังทดสอบ
REM   เครื่องเดียว (AGENT_HOST=127.0.0.1) · พอแยกเครื่องจริงให้ลบ 2 บรรทัดล่าง
REM   ทิ้ง ไม่งั้นจะมี 2 ตัวแย่งกันฟัง AGENT_PORT และแย่งกันคุย TM-X
cd /d "%ROOT%Backend-pc_station"
start /B cmd /c ""%PY%" -u Pi.py            >> "%ROOT%logs\pi.log"       2>&1"

echo เปิดครบ 4 ตัวแล้ว — ดู log ที่ %ROOT%logs\
