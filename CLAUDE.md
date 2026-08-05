# TM-X Measurement System

ระบบอัตโนมัติสำหรับตรวจวัดมิติ (Dimensional Inspection) ของชิ้นงาน ALPL (IPM) ที่ใช้จัดแนว IC Lead กับ Contact Pin บนเครื่องทดสอบ 2 แพลตฟอร์ม (HT9046, HT9046MX) โดยมาแทนที่กระบวนการแมนนวลที่ทำผ่าน KEYENCE TM-X5065 Vision Controller เดิม


โปรเจกต์นี้เป็นทั้งระบบใช้งานจริงในห้อง PM Kit ของ Analog Devices (ADI) Thailand และเป็นผลงาน Capstone ของนักศึกษาฝึกงาน

---

## สถาปัตยกรรมระบบ

```
┌──────────────┐   HTTP (REST)    ┌──────────────────┐   SSE (server→client)   ┌──────────────┐
│   Frontend   │ ───────────────▶ │  Backend-server    │ ─────────────────────▶ │  Operator     │
│ (React SPA)  │ ◀─── SSE ─────── │     (FastAPI)      │                         │  Browser      │
└──────────────┘                  └──────────────────┘
                                          │
                                  MySQL   │  (dev: Docker · หน้างานจริง: ลงเครื่องตรง)
                                  (data)  │
                                          ▼
                                   ┌──────────────┐
                                   │   MySQL DB   │
                                   └──────────────┘
                                          ▲
                                          │ HTTP (POST /api/measurements, heartbeat)
                                          │
                                   ┌────────────────────────────┐        TCP (R0/PW/T1/S0)         ┌─────────────────┐
                                   │ send_command.py (บน Pi)      │ ───────────────────────────────▶ │ KEYENCE TM-X5065 │
                                   │  รับ start/stop จาก Backend   │                                  │   + MCU (Serial) │
                                   └────────────────────────────┘                                  └─────────────────┘
                                                                                                            │
                                   ┌────────────────────────────┐        FTP (ค่า .txt + รูป)                 │
                                   │ Recieve_tm-x.py (บน PC)      │ ◀───────────────────────────────────────────┘
                                   │  POST ค่า+รูป เข้า Backend     │
                                   └────────────────────────────┘
```

**แยกหน้าที่ชัดเจน 2 สคริปต์ (สถาปัตยกรรมที่ใช้จริง)**

| สคริปต์ | รันที่ | หน้าที่ |
|---|---|---|
| `send_command.py` | Raspberry Pi | รับ start/stop จาก Backend → สั่ง TM-X ผ่าน TCP (`R0` → `PW,1,<template>` → `T1` ต่อชิ้น → `S0`) **ไม่เห็นค่า/รูปเลย** |
| `Recieve_tm-x.py` | PC (เครื่องเดียวกับ Backend) | เปิด FTP server รอรับค่า+รูปที่ TM-X ส่งตรงมา → ถาม Backend ว่า session ไหน running → POST ค่า + อัปโหลดรูป |

Pi ไม่ยุ่งกับรูป/ค่าที่วัดได้แล้ว (TM-X ส่งตรงเข้า PC) — ต่างจาก `agent.py` เดิม
ที่ Pi เปิด FTP server ของตัวเองรับรูปแล้วส่งต่อให้ PC อีกทอด

- **Frontend → Backend**: HTTP request ปกติ (POST /api/session/start, /api/session/stop ฯลฯ)
- **Backend → Frontend**: Server-Sent Events (SSE) ทางเดียว ผ่าน `/api/stream`
- **Backend → Pi**: `POST /command` ไปที่ `AGENT_HOST:AGENT_PORT` (action: `start`/`stop` พร้อม `session_id`, `template_name`, `target_count`, `number_alpl`)
- **Pi → Backend**: heartbeat ผ่าน `POST /api/heartbeat` ทุก 5 วิ (แนบ `session_id` ปัจจุบัน กัน `heartbeat_checker` mark session เป็น timeout)
- **Pi → TM-X**: TCP `192.168.10.11:8600` — `R0` (reset) → `PW,1,<template>` (โหลดโปรแกรมวัด) → `T1` ต่อชิ้น (ผ่าน connection ใหม่แยกทุกครั้ง) → `S0` ตอนจบ
- **TM-X → PC**: FTP — TM-X เขียนไฟล์ `.txt` ต่อท้ายเรื่อยๆ (บรรทัดละ 1 ค่า รูปแบบ `+0005.017,+0005.029`) แล้วส่งรูปตามมาในคอนเนกชันเดียวกัน `Recieve_tm-x.py` จับคู่ "รูปที่เพิ่งได้" กับ "บรรทัดล่าสุดของ .txt"
- **PC → Backend**: `POST /api/measurements` แล้วอัปโหลดรูปต่อที่ `POST /api/measurements/{id}/image-upload` (multipart)
- **รูปภาพ (image storage)**: **เลิกใช้ MinIO แล้ว** — `Recieve_tm-x.py` พักไฟล์ที่ `TEMP_IMAGE_DIR` (`Store_image_temporary/`) บน PC แล้วอัปโหลดเข้า Backend (คนละ process แต่เครื่องเดียวกัน) → Backend แปลงเป็น `.jpg` ด้วย Pillow เซฟลง `ALPL_IMAGE_DIR` แยกโฟลเดอร์ตามวันที่วัด (DD-MM-YYYY พ.ศ.) แล้วอัปเดต `measurements.image_path` เสิร์ฟผ่าน static mount `/media/alpl` — ไฟล์ temp ถูกลบทิ้งเสมอไม่ว่าอัปโหลดสำเร็จหรือไม่

---

## โครงสร้างโปรเจกต์

```
TM-X_Project/
├── Backend-server/              # FastAPI backend (Single Source of Truth)
│   ├── main.py
│   └── requirements.txt
├── Backend-pc_station/          # สคริปต์ฝั่งหน้างาน — 2 ตัวแรกคือของจริงที่ใช้งาน ที่เหลือเป็น legacy
│   ├── send_command.py          # ✅ ของจริง รันบน Pi — รับ start/stop จาก Backend แล้วสั่ง TM-X ผ่าน TCP
│   ├── Recieve_tm-x.py          # ✅ ของจริง รันบน PC — FTP server รับค่า+รูปจาก TM-X แล้ว POST เข้า Backend
│   ├── mockup.py                # โหมด mock (สุ่มค่า) สำหรับเทสต์ไม่มีฮาร์ดแวร์ — รองรับ pause/resume ด้วย
│   ├── requirements.txt         # dependency ของทั้ง 3 ตัวข้างบน (รวม pyftpdlib)
│   ├── agent.py                 # ⚠ legacy — สถาปัตยกรรมเก่าที่ Pi เปิด FTP รับรูปเองแล้วส่งต่อ PC (ไม่ใช้แล้ว)
│   └── tcp.py, ftp.py           # ⚠ legacy — สคริปต์ทดสอบเดี่ยวๆ เหลือไว้อ้างอิง
├── Frontend/                    # Web Dashboard สำหรับ Operator (ของเดิม ยังใช้งานจริงอยู่ — ดูหัวข้อ Frontend)
│   ├── index.html               # หน้าหลัก: Live Telemetry, Part Entry, Session Control (Start/Pause/Stop)
│   ├── edit.html                # Database Editor (Parts/Measurements/Lookup Tables CRUD)
│   ├── export.html              # Wizard 3 ขั้นของทุกรูปแบบ — ?format=csv|pdf|excel
│   ├── report-template.html     # ตัวแก้ผังรายงานแบบสเปรดชีต (ใช้กับ PDF/Excel)
│   └── test.html                # ⚠ mockup เก่า ไม่ได้ใช้แล้ว
├── Frontend-react/              # โปรเจกต์ React ใหม่ (Vite+TS+Router+TanStack Query) — กำลังย้ายมาแทน Frontend/ ทีละหน้า ยังไม่ deploy จริง (ดู Frontend-react/README.md)
├── DEPLOY.md                    # ขั้นตอนติดตั้งบนเครื่อง PC หน้างาน (MySQL ลงตรง ไม่ใช้ Docker)
├── sql-tools/                   # สคริปต์ SQL ที่ "รันเองด้วยมือ" เท่านั้น (migration/diagnose)
│   │                            # ⚠ ห้ามเอาไปไว้ใน mysql-init/ เด็ดขาด — ดูหมายเหตุใต้ตาราง
│   ├── add_measurement_indexes.sql  # เพิ่ม INDEX ให้ DB เก่า (DB ใหม่ได้จาก init.sql อยู่แล้ว)
│   ├── migrate_export_template.sql  # เพิ่มคอลัมน์ kind/layout_json ให้ DB เก่าที่สร้างไว้ก่อน
│   ├── migrate_report_kind.sql      # แปลงเทมเพลตเก่า kind='report' → 'pdf'
│   └── diagnose_start_blockers.sql  # ไล่หาว่า ALPL ตัวไหนกด Start ไม่ได้เพราะติดข้อไหน
├── mysql-init/                  # ⚠ mount เป็น docker-entrypoint-initdb.d — ทุกไฟล์ .sql
│   │                            # ในนี้ถูกรันอัตโนมัติเรียงตามตัวอักษรตอน container เกิดใหม่
│   ├── init.sql                 # Schema + INDEX (auto-run ตอน container เกิดใหม่ / หน้างานต้อง import เอง)
│   └── insert.sql                # Seed ข้อมูลตั้งต้นของตาราง lookup (operator/owner/handler/vendor/package_size)
├── image_ALPL/                  # แหล่งภาพอ้างอิงของแต่ละ ALPL (ใช้เทียบ/แสดงผล)
├── Store_image_temporary/       # โฟลเดอร์พักภาพชั่วคราว **บน PC** (Recieve_tm-x.py) ก่อนอัปโหลดเข้า Backend แล้วลบทิ้ง
├── ALPL/                        # ที่เก็บรูปถาวรบนเครื่อง PC (Backend) แยกโฟลเดอร์ย่อยตามวันที่วัด (DD-MM-YYYY พ.ศ.) — สร้างอัตโนมัติโดย main.py (ดู ALPL_IMAGE_DIR)
├── TM-X_simulation/             # ⚠ legacy — ตัวจำลอง TM-X ที่เขียนไว้ตอนยังไม่รู้โปรโตคอลจริง
│   │                            #   ใช้คำสั่ง LOAD_TEMPLATE/MEASURE_CMD ซึ่งไม่ตรงกับของจริง
│   │                            #   (R0/PW/T1/S0) และไม่ push ไฟล์ออกทาง FTP — ไม่ได้ใช้แล้ว
│   ├── tm-x.py
│   └── requirements.txt
├── docker-compose.yml           # ใช้จริงตอน dev (MySQL) — service `minio` เป็น legacy เลิกใช้แล้วแต่ยังไม่ได้ลบ
└── .env                         # Config กลาง (DB, Agent, TM-X, Heartbeat, โฟลเดอร์พักภาพชั่วคราว)
```

---

## Tech Stack

| Layer | Tools |
|---|---|
| Backend | Python 3.11, FastAPI, Pydantic, httpx, pymysql, pandas, sse-starlette, python-dotenv |
| Database | MySQL 8.0 — **dev: รันผ่าน Docker** (`docker compose up`, port 3307) · **หน้างานจริง: ลงเครื่องตรงเป็น Windows Service** (port 3306) ดู `DEPLOY.md` |
| Image Storage | ดีไซน์สรุปแล้ว (เลิกใช้ MinIO) — ไฟล์จริงบนดิสก์ 2 จุด: `Store_image_temporary/` พักชั่วคราวบน Agent/Pi, `ALPL_IMAGE_DIR` (`ALPL/`) เก็บถาวรบน PC แยกโฟลเดอร์ตามวันที่วัด (DD-MM-YYYY พ.ศ.) ส่งข้ามเครื่องด้วย HTTP multipart upload — Backend แปลงไฟล์ต้นทาง (ปกติ .bmp) เป็น .jpg เสมอด้วย Pillow ก่อนเซฟ |
| Frontend | React (Vite) + React Router (SPA) + TanStack Query (react-query) — กำลังย้ายจาก Vanilla JS เดิม (ดูหัวข้อ "Frontend Framework Migration") |
| Realtime | Server-Sent Events (SSE) |
| Hardware (เป้าหมาย ยังไม่ต่อจริง) | KEYENCE TM-X5065 (TCP), FTP สำหรับภาพ, MCU ผ่าน Serial |
| Infra | dev ใช้ Docker เฉพาะ MySQL · หน้างานไม่มี container เลย (MySQL เป็น Windows Service, backend เป็น process uvicorn ตัวเดียว) — เหตุผลที่ไม่ใช้ Docker หน้างานอยู่ใน `DEPLOY.md` |
| Export | openpyxl (.xlsx) · PDF ใช้ตัวพิมพ์ของเบราว์เซอร์ (`window.print()` + `@media print`) ไม่ได้สร้างฝั่ง server |
| Reporting (แยกจากระบบนี้) | Power BI (DAX, ตาราง `combined_3_fixed`) |

**สำคัญ**: ต้องใช้ Python 3.11 เท่านั้น (3.14 ใช้ไม่ได้กับ dependency บางตัว)

---

> ⚠ **ห้ามวางสคริปต์ SQL อื่นใน `mysql-init/` นอกจาก `init.sql` กับ `insert.sql`**
> โฟลเดอร์นี้ถูก mount เป็น `docker-entrypoint-initdb.d` — MySQL รันไฟล์ `.sql` **ทุกไฟล์**
> ในนั้นเรียงตามตัวอักษรตอน container เกิดใหม่ และ entrypoint ใช้ `set -e` ดังนั้นถ้าไฟล์ไหน
> error ไฟล์ถัดไปจะไม่ถูกรันเลย ตัวอย่างที่เคยเกิดจริง: ไฟล์ชื่อขึ้นต้นด้วย `d` (diagnose)
> เรียงมาก่อน `init.sql` แล้ว SELECT จากตารางที่ยังไม่มี → `ERROR 1146` → `init.sql`/`insert.sql`
> ไม่ถูกรัน → ฐานข้อมูลว่างเปล่า หน้าเว็บขึ้น "โหลด ... ไม่สำเร็จ" ทุกช่อง
> สคริปต์ migration/diagnose ให้เก็บที่ `sql-tools/` แล้วรันเองด้วยมือ

## Database Schema (`mysql-init/init.sql`)

3 ตาราง ความสัมพันธ์: `parts (1) → (N) sessions (1) → (N) measurements`

- **`parts`**: PK = `number_alpl` (1 ALPL = 1 vendor/handler/package เสมอ) **ไม่ได้เก็บ nominal/tolerance เอง** — ผูกกับ `package_size` ผ่าน `package_size_id` แทน
- **`package_size`**: เก็บ `nominal_x`, `nominal_y` และ tolerance **ตัวเดียวใช้ร่วมกันทั้งแกน X/Y** (`upper_tol`, `lower_tol` — ไม่ได้แยกราย axis) พร้อม `template_name` (โปรแกรมวัดของ TM-X ที่ผูกกับขนาด package นี้)
- **`sessions`**: 1 รอบการวัด state = `idle | running | stopped | timeout`, มี `target_count`/`measured_count` ใช้เช็คว่าวัดครบหรือยัง
- **`measurements`**: ผลวัดแต่ละชิ้น มี `value_x`, `value_y`, `result` (OK/NG), `measure_type` (IPM/New/Rework/Manual), `image_path` (relative path ใต้ `ALPL_IMAGE_DIR` บนเครื่อง PC เช่น `"22-07-2569/203_22-07-2569.jpg"` — แยกโฟลเดอร์ตามวันที่วัด (พ.ศ.) ไม่ใช่ตาม package_size แล้ว เสิร์ฟผ่าน static mount `/media/alpl` — หมายเหตุ: ชื่อไฟล์ใช้แค่ `number_alpl` + วันที่ ไม่มี `measurement_id` ปน จึงเขียนทับกันได้ถ้ามีมากกว่า 1 การวัดของ ALPL เดียวกันในวันเดียวกัน (ตั้งใจ — เก็บแค่รูปล่าสุดของวันนั้น))
  - หมายเหตุ (อัปเดต): คอลัมน์ operator **ไม่ใช่ `Oparetor` (VARCHAR สะกดผิด) แบบเดิมแล้ว** — ตอนนี้เป็น `operator_id` (FK ไปตาราง `operator` ที่เก็บ `operator_name`) เอกสารเดิมพูดถึง `Oparetor` เพราะเป็นข้อมูลเก่าก่อน migrate ตอนนี้ล้าสมัยแล้ว

---

## Backend (`Backend-server/main.py`)

รันด้วย:
```bash
cd Backend-server
pip install -r requirements.txt
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

หลักการออกแบบที่สำคัญ (ต้องเข้าใจก่อนแก้โค้ด):

1. **FastAPI คือ Single Source of Truth** — สถานะทั้งหมด (session, measurement) อยู่ที่ backend เท่านั้น Agent ไม่เขียนลง DB ตรงๆ เลย
2. **`session_queues` (in-memory dict)** — เก็บคิว ALPL + ตำแหน่งปัจจุบันของแต่ละ session (โหมด IPM/New) เพราะ schema ตาราง `sessions` เก็บแค่ `number_alpl` ตัวเดียว (ALPL แรกของคิว)
   - **ความเสี่ยงที่รู้อยู่แล้ว**: ถ้า server restart กลางที่ session กำลัง running คิวนี้จะหาย ยังไม่มีการ persist ลง DB
3. **Stop flow ไม่สมมาตร (asymmetry)** — กด Stop จากเว็บ จะอัปเดต DB (`state='stopped'`) + แจ้ง Agent แต่ปุ่ม Stop ทางกายภาพที่ MCU ตอนนี้แค่ flip flag ใน memory ฝั่ง Agent เท่านั้น **ไม่ได้อัปเดต DB** — เป็น gap สถาปัตยกรรมที่ต้อง flag ไว้เวลา present งาน
4. **SSE เป็นทางเดียว** server → client เท่านั้น (`/api/stream`) ฝั่ง frontend ยังคงใช้ HTTP POST ปกติในการส่งคำสั่งไป backend (ไม่ใช่ bidirectional)
5. **MeasurementType: IPM vs New**
   - `IPM`: ALPL ลงทะเบียนไว้แล้วใน `parts` → query หา `template_name` อย่างเดียว ไม่ insert part ใหม่
   - `New`: ลงทะเบียน part ใหม่ + วัดในรอบเดียว → ต้อง insert `parts` ก่อน insert `sessions` เสมอ (เพราะมี FOREIGN KEY)
6. **Agent ไม่รู้ว่ากำลังวัด ALPL ตัวไหนในคิว** — แค่ส่ง `value_x`/`value_y` มาเรื่อยๆ Backend เป็นคนจับคู่ ALPL จากตำแหน่งใน `session_queues` เอง (ยกเว้น manual session แบบเก่าที่ไม่มี entry ใน `session_queues` จะใช้ `req.number_alpl` ที่ Agent ส่งมาตรงๆ)
7. **Heartbeat checker** (background task) — ตรวจทุก `HEARTBEAT_INTERVAL` วินาที ถ้า session ไหน `state='running'` แต่ `last_seen` เก่ากว่า `HEARTBEAT_TIMEOUT` → เปลี่ยนเป็น `timeout` และ broadcast ผ่าน SSE

### Endpoint หลัก
- `GET /api/stream` — SSE stream
- `GET /api/session/state`, `POST /api/session/start`, `POST /api/session/stop`
- `POST /api/heartbeat`
- `GET/POST/PATCH/DELETE /api/parts`, `/api/parts/{id}`
- `GET/POST/PATCH/DELETE /api/measurements`, `/api/measurements/{id}`, `PATCH /api/measurements/{id}/image`
- `POST /api/measurements/{id}/image-upload` — รับไฟล์รูป (multipart, `UploadFile`) จาก Agent แปลงเป็น `.jpg` ด้วย Pillow แล้วเซฟลง `ALPL_IMAGE_DIR/<DD-MM-YYYY พ.ศ.>/<number_alpl>_<DD-MM-YYYY พ.ศ.>.jpg` แล้วอัปเดต `measurements.image_path` เป็น relative path + broadcast SSE event `image_updated`
- `GET /api/image-url/{measurement_id}` — คืน `{"url": "/media/alpl/<image_path>"}` จริงแล้ว (ไม่ใช่ stub อีกต่อไป) หรือ 404 ถ้ายังไม่มีรูป ส่วน `POST /api/upload-url` เดิม (MinIO presigned URL) ถูกลบออกจากโค้ดไปแล้ว ไม่มีอยู่อีกต่อไป
- `GET /api/export/csv` — export พร้อม filter (ใช้ filter ชุดเดียวกับ `list_measurements`)
- `GET /api/export/columns?kind=csv|pdf|excel` — catalog คอลัมน์ที่ลากใส่เทมเพลตได้
- `GET /api/export/templates?kind=...`, CRUD + `/duplicate` — เทมเพลตแยก 3 ชนิด
- `GET /api/export/report-preview?export_template_id=&full=0|1` — คลี่ผัง + ข้อมูลจริงเป็นตาราง 2 มิติ
- `GET /api/export/xlsx` — สร้างไฟล์ .xlsx จากผังรายงาน (openpyxl)

### Export / รายงาน — สิ่งที่ต้องรู้ก่อนแก้
1. **`_render_report` เป็นตัวกลางตัวเดียว** ของทั้ง preview / Excel / PDF — แก้ที่นี่ที่เดียว
   ไม่งั้นสิ่งที่เห็นบนจอกับไฟล์ที่ได้จะเพี้ยนกันเงียบๆ (PDF ใช้ตัวพิมพ์ของเบราว์เซอร์
   วาดจาก HTML ก้อนเดียวกับ preview ไม่ได้สร้าง PDF ฝั่ง server)
2. **`kind` มี 3 ค่า**: `csv` / `pdf` / `excel` — ห้ามเช็คแบบ `kind == "report"` อีก
   (`report` เป็นชื่อเก่าสมัยที่ PDF กับ Excel ใช้ลิสต์ร่วมกัน) ทุกอย่างที่ไม่ใช่ `csv`
   ถือเป็นรายงานหมด เคยพลาดตรงนี้แล้วบันทึกเทมเพลตไม่ได้เพราะไปตกเส้นทางของ CSV
3. **`latest_only` ต้องกรองข้างในด้วย** — subquery ของ "เอาเฉพาะการวัดล่าสุด" ใช้ WHERE
   ชุดเดียวกับ query หลัก ถ้าเผลอเอา WHERE ออกจะกลายเป็น "ล่าสุดของทั้งตาราง" แล้ว
   ALPL ที่ถูกวัดซ้ำนอกช่วงที่กรองจะหายไปจากรายงานทั้งตัวโดยไม่มีอะไรเตือน
4. **ค่าวันที่ปลายช่วงถูกครอบเต็มวันที่ backend** (`_day_end`) — ส่ง `2026-07-30` มาเฉยๆ ได้
5. **`variants` บนเซลล์ข้อมูล** = หน้าตาแยกตามค่า (Result: OK เขียว / NG แดง) ผูกกับ
   *ฟิลด์* ไม่ใช่ตำแหน่ง ลากย้ายบล็อกแล้วต้องติดไปด้วย (ดู `moveFieldBlock`)

---

## สคริปต์หน้างาน (`Backend-pc_station/`)

### `send_command.py` — รันบน Raspberry Pi

```bash
cd Backend-pc_station
pip install -r requirements.txt
python send_command.py          # ฟัง POST /command ที่ port 9998 (= AGENT_PORT)
```

- รับ `POST /command` จาก Backend (action `start`/`stop`) พร้อม `session_id`,
  `template_name`, `target_count`, `number_alpl`
- ต่อ TCP ไป TM-X (`TMX_HOST`/`TMX_PORT` จาก `.env`) แล้วส่งตามลำดับ:
  `R0` (reset) → `PW,1,<template>` (โหลดโปรแกรมวัด, zero-pad 3 หลัก) →
  วนต่อชิ้นจนครบ `target_count`: รอ `input()` แล้วส่ง `T1` → `S0` ตอนจบ
- **`T1` ส่งผ่าน connection ใหม่แยกทุกครั้ง** ไม่ใช้ตัวที่ค้างไว้ส่ง R0/PW/S0
  (ทดสอบกับฮาร์ดแวร์จริงแล้วว่าต้องทำแบบนี้ — ดู `trigger_sensor()`)
- **ไม่เห็นค่า/รูปที่วัดได้เลย** — ไม่มี FTP server บน Pi อีกต่อไป
- heartbeat ทุก 5 วิ พร้อม `session_id` ปัจจุบัน (กัน `heartbeat_checker` ฝั่ง
  backend mark session เป็น timeout แล้วหน้าเว็บโดน reset กลางคัน)

### `Recieve_tm-x.py` — รันบน PC (เครื่องเดียวกับ Backend)

```bash
cd Backend-pc_station
python Recieve_tm-x.py          # เปิด FTP server ที่ AGENT_FTP_PORT (default 21)
```

- เปิด FTP server รอรับของจาก TM-X — **TM-X ส่งตรงมาที่ PC ไม่ผ่าน Pi**
- TM-X ทำ 2 สเต็ปใน 1 คอนเนกชัน: เขียนไฟล์ `.txt` ผลวัด **ต่อท้ายเรื่อยๆ**
  (บรรทัดละ 1 ค่า รูปแบบ `+0005.017,+0005.029` = value_x,value_y) แล้วส่งรูปตามมา
  → `on_file_received` จำ path ของ `.txt` ไว้ พอได้ไฟล์ที่นามสกุลเป็นรูป จึงอ่าน
  **บรรทัดล่าสุด** ของ `.txt` มาจับคู่กับรูปนั้น
- ถาม Backend ก่อนทุกครั้งว่ามี session ไหน `running` อยู่ (`GET /api/session/state`)
  — **ถ้าไม่มี จะทิ้งค่า+รูปนั้นไปเลย** (กันแปะผิด session ตอน TM-X ส่งมาช้า
  หลัง session จบไปแล้ว)
- `number_alpl` ที่ส่งไปไม่จำเป็นต้องตรงเป๊ะ — session แบบคิว (IPM/New/Rework)
  ฝั่ง `main.py` เพิกเฉยค่านี้แล้วใช้ตำแหน่งในคิวของตัวเองแทน

### ข้อจำกัดของสถาปัตยกรรมนี้ที่ต้องรู้

- **Pi ไม่รู้ว่าชิ้นไหนพลาด** — ส่ง `T1` แล้ววนไปชิ้นถัดไปทันที ไม่มี retry
  แบบ `arm_and_capture()` ของ `agent.py` เดิม ถ้า TM-X พลาดรอบไหน (ไม่ส่งค่า/รูป
  มาที่ PC) `measured_count` จะไม่ครบ `target_count` แล้ว session ค้างที่
  `running` — ต้องกด Stop เองจากเว็บ
- **`send_command.py` ไม่รองรับ `pause`/`resume`** — backend ยิง action นี้ไป
  แต่ `/command` รู้จักแค่ `start`/`stop` คำสั่งจึงถูกกลืนเงียบๆ (ดู Known Issues)
- **`input()` บล็อก thread** — กด Stop จากเว็บแล้ว `S0` ถูกยิงไป TM-X ทันที แต่
  loop จะยังไม่หลุดจนกว่าจะเคาะ Enter ที่เทอร์มินัลอีกครั้ง (จะหายไปเองตอนต่อ
  MCU จริงเพราะไม่ต้องใช้ `input()` แล้ว)
- **ไม่เช็ค response ของ `R0`/`PW`** — ถ้า TM-X ตอบ error (เช่นไม่มีโปรแกรม
  หมายเลขนั้น) โค้ดเดินหน้าวัดต่อทั้ง session โดยไม่มีใครรู้

### `mockup.py` — เทสต์โดยไม่มีฮาร์ดแวร์

สุ่มค่า `value_x`/`value_y` ตาม nominal/tolerance จริงของ ALPL นั้น (จึงได้ OK/NG
ที่สมจริง) และ **รองรับ `pause`/`resume` ครบ** ต่างจาก `send_command.py`


---

## Frontend (`Frontend/`)

> **สถานะ**: ย้ายครบทั้ง 3 หน้าแล้ว (ยังไม่ verify การ build/รันจริงครบ 100%) — โปรเจกต์ React ใหม่อยู่ที่ `Frontend-react/` (Vite + TypeScript + React Router + TanStack Query) **Export และ Edit ใช้งานได้จริงแล้ว** (Parts/Measurements CRUD ครบ, ล็อกตอน session running, value_x/value_y แก้ไม่ได้) **Dashboard (Home) ย้ายมาแล้วเช่นกัน** (Session Control, Live Telemetry ผ่าน SSE, Part Entry 3 โหมด IPM/New/Rework, Stats, ตาราง Measurements + Report modal) — หมายเหตุ: ปุ่ม Save กับ Start ของ Part Entry เดิมที่แยกกัน 2 ขั้นตอน ถูกรวมเป็นปุ่มเดียว "▶ Start" เพื่อลดความซับซ้อนของ UI (ดูรายละเอียดใน `PartEntry.tsx`) ไฟล์ .html เดิมด้านล่างนี้**ยังเป็นของจริงที่ใช้งานอยู่** (`main.py` ยังเสิร์ฟจาก `Frontend/` เดิม ไม่ใช่ `Frontend-react/`) จนกว่าจะทดสอบ React ฝั่งนี้จนมั่นใจแล้วค่อยสลับ static mount ดูแผนที่หัวข้อ "Frontend Framework Migration" ท้ายหัวข้อนี้

ปัจจุบัน (ก่อนย้าย) — Single-file vanilla JS ทุกหน้า ธีมสว่าง (light theme)

- **`index.html`** — Dashboard หลัก: Live Telemetry (รับผ่าน SSE), Part Entry modal (เลือกโหมด IPM/New แล้วกด Start), Camera Preview, System Diagnostics, Stats card (scope เฉพาะ session ปัจจุบัน)
- **`edit.html`** — Database Editor จัดการตาราง Parts/Measurements (Add/Edit/Delete ผ่าน modal forms)
- **`export.html`** — หน้า export ข้อมูลเป็น CSV (ปัจจุบันเป็นแค่ placeholder "Coming soon" — logic ฝั่ง backend `/api/export/csv` ทำงานได้จริงแล้ว แต่ยังไม่มีหน้าเว็บเรียกใช้)

### Frontend Framework Migration (แผนที่ตกลงกันไว้)

- **เครื่องมือที่เลือก**: React + Vite (build tool, ไม่ใช้ Next.js เพราะไม่ต้องการ server-side rendering) + TanStack Query (react-query) สำหรับดึง/cache/refetch ข้อมูลจาก backend แทนการเขียน fetch + loading/error state เอง
- **เหตุผลที่ย้าย**: โค้ด vanilla JS เดิมยาวเกินไป (`index.html` ~2,552 บรรทัด) และมีโค้ดซ้ำระหว่าง `index.html`/`edit.html` หลายจุด (fetch dropdown operators/vendors/handlers/owners/package-sizes ซ้ำกันคนละชุด, pattern "fetch แล้วต้อง refetch เองหลัง save/delete" ซ้ำทุกตาราง)
- **ลำดับการย้าย** (ทีละหน้า ไม่ทำพร้อมกันหมด): `export.html` ก่อน (ยังเป็นแค่ placeholder เสี่ยงน้อยสุด ใช้ทดสอบ toolchain + ถือโอกาสสร้างหน้า export ที่เรียก `/api/export/csv` จริง) → `edit.html` (CRUD ตรงไปตรงมา ฝึก pattern) → `index.html` (ซับซ้อนสุด ย้ายท้ายสุด)
- **shared code ที่ควรทำเป็น hook/component กลางตั้งแต่แรก**: `useLookups()` (ดึง operators/owners/vendors/handlers/package-sizes ครั้งเดียวใช้ทุกหน้า), `useSSE()` (เชื่อม `/api/stream`), `<Pagination>` / `<Modal>` / `<ConfirmDialog>` / `<Toast>`
- **การ deploy ไม่เปลี่ยนสถาปัตยกรรม**: `npm run build` ได้โฟลเดอร์ `Frontend/dist/` แล้วเปลี่ยน static mount ท้าย `main.py` (`app.mount("/", StaticFiles(directory=_frontend_dir, html=True))`) ให้ชี้ไปที่ `Frontend/dist` แทน `Frontend/` — backend ยังเป็น process เดียว (uvicorn) เหมือนเดิม เครื่อง PC หน้างานไม่ต้องมี Node.js ติดตั้ง (Node ใช้แค่ตอน dev/build บนเครื่องที่เขียนโค้ด)
- **ระหว่าง dev**: ต้องรัน 2 อย่างพร้อมกัน — `uvicorn main:app` (port 8000, API) และ `npm run dev` (Vite dev server, port 5173, หน้า React ที่กำลังแก้) — เรียกข้าม port ได้เพราะ `main.py` เปิด CORS `allow_origins=["*"]` ไว้แล้ว
- **ตัดสินใจแล้ว**: ใช้ **SPA เดียว + React Router** (`react-router-dom`) แทนการแยก build หลายหน้าแบบเดิม — route `/` (Dashboard), `/edit` (Database Editor), `/export` (Export) อยู่ใน React app เดียวกัน แชร์ layout/topbar เดียวกันได้ทันที ไม่ต้อง copy topbar markup ซ้ำ 3 ไฟล์แบบ index.html/edit.html/export.html เดิม

---

## Environment Variables (`.env`)

| ตัวแปร | ใช้ที่ | คำอธิบาย |
|---|---|---|
| `DB_HOST`, `DB_USER`, `DB_PASSWORD`, `DB_NAME`, `DB_PORT` | Backend | การเชื่อมต่อ MySQL — **`DB_PORT=3307` ตอน dev (Docker map ออกมา) · `3306` ตอนลงหน้างาน** |
| `BACKEND_URL` | Agent | URL ของ Backend (สำหรับ Agent ยิง measurement/heartbeat กลับ) — ถ้า Agent อยู่คนละเครื่อง (เช่น Raspberry Pi) ต้องเปลี่ยนเป็น IP ของเครื่อง PC ที่รัน Backend |
| `AGENT_HOST` | Backend | ที่อยู่ของเครื่องที่ Agent รันอยู่ (ทิศตรงข้ามกับ `BACKEND_URL`) — default `localhost` (เทสต์เครื่องเดียวได้ปกติ) เปลี่ยนเป็น IP ของ Raspberry Pi เมื่อแยกเครื่องจริง |
| `AGENT_PORT` | Backend, Agent | Port ที่ Agent HTTP server ฟังอยู่ |
| `SERIAL_PORT`, `SERIAL_BAUD` | Agent | การเชื่อมต่อ MCU ผ่าน Serial (ยังไม่ใช้จริง) |
| `TMX_HOST`, `TMX_PORT` | Agent | TCP ของ TM-X Controller (ต่อจริงแล้วที่ `192.168.10.11:8600`) |
| `TEMP_IMAGE_DIR` | `Recieve_tm-x.py` (**PC**) | โฟลเดอร์พักภาพชั่วคราวหลัง FTP รับจาก TM-X มา ก่อนอัปโหลดต่อให้ Backend แล้วลบทิ้ง (default `./Store_image_temporary`) |
| `ALPL_IMAGE_DIR` | Backend (PC) | ที่เก็บรูปถาวร แยกโฟลเดอร์ย่อยตามวันที่วัด (DD-MM-YYYY พ.ศ.) อัตโนมัติ (default `TM-X_Project/ALPL/`) — ไฟล์ต้นทางถูกแปลงเป็น `.jpg` เสมอ (Pillow) |
| `AGENT_FTP_HOST`, `AGENT_FTP_PORT` | `Recieve_tm-x.py` (**PC**) | ที่อยู่/พอร์ตของ FTP server ที่รอรับค่า+รูปจาก TM-X — **ตอนนี้ใช้ `21`** (Windows bind พอร์ตต่ำได้ไม่ต้องเป็น admin ต่างจาก Linux) ถ้าพอร์ต 21 ถูก IIS FTP หรือโปรแกรมอื่นจองอยู่ต้องปิดตัวนั้นก่อน · `agent.py` เดิมใช้ `2121` เพราะรันบน Linux (Pi) |
| `AGENT_FTP_USER`, `AGENT_FTP_PASS` | `Recieve_tm-x.py` (**PC**) | บัญชีที่ TM-X ใช้ล็อกอินเข้า FTP server บน PC — ต้องตั้งให้ตรงกับที่ตั้งไว้ในตัว TM-X เอง |
| `AGENT_IMAGE_WAIT_TIMEOUT` | Agent (Pi) | เวลารอรูปสูงสุดหลัง trigger (วินาที) ก่อนจะยอมวัดต่อโดยไม่มีรูป |
| `HEARTBEAT_INTERVAL`, `HEARTBEAT_TIMEOUT` | Backend, Agent | ความถี่ heartbeat / timeout threshold |
| `MEASURE_TIMEOUT`, `MEASURE_POLL_INTERVAL` | `send_command.py` (Pi) | รอค่าการวัดกลับมาสูงสุดกี่วินาทีหลังยิง `T1` (default 15) และถี่แค่ไหนที่ถาม backend ว่า `measured_count` ขยับยัง (default 0.4) — ครบเวลาแล้วไม่ขยับจะเด้งถามผู้ใช้บนหน้าเว็บ |
| `CORS_ORIGINS` | Backend | รายการ origin ที่ยอมให้เรียก API (คั่นด้วยคอมมา) — ค่าเริ่มต้นเปิดเฉพาะ localhost:8000 กับ Vite dev :5173 ใส่ `*` ถ้าอยากได้พฤติกรรมเดิม |
| `REPORT_MAX_ROWS` | Backend | เพดานจำนวนแถวของรายงาน PDF/Excel (default 20000) เกินแล้วปฏิเสธพร้อมบอกให้กรองก่อน |

> หมายเหตุ: ตัวแปร `MINIO_*` ทั้งหมดถูกถอดออกจากโค้ดแล้ว (เลิกใช้ MinIO) — ถ้าเห็นใน `.env` เก่าที่ยังไม่ได้อัปเดต ลบทิ้งได้เลย ไม่มีโค้ดจุดไหนอ่านค่านี้อีกต่อไป

> **อย่า commit `.env` จริงขึ้น repo** — ไฟล์ตัวอย่างควรเป็น `.env.example` ที่ไม่มีรหัสผ่านจริง

---

## วิธีรันทั้งระบบ (Local Dev)

```bash
# 1. รัน MySQL ผ่าน Docker (dev ใช้วิธีนี้ — หน้างานจริงลง MySQL ตรง ดู DEPLOY.md)
#    init.sql + insert.sql ถูกรันให้อัตโนมัติ "เฉพาะตอน volume ว่างเปล่าครั้งแรก"
docker compose up -d
#    ⚠ `docker compose down -v` ลบ volume = ข้อมูลการวัดหายทั้งหมด ใช้เฉพาะตอน
#      ตั้งใจจะเริ่มใหม่จากศูนย์เท่านั้น (สั่ง `down` เฉยๆ ไม่ลบข้อมูล)

# 2. รัน Backend (terminal ที่ 1)
cd Backend-server
pip install -r requirements.txt
uvicorn main:app --reload --host 0.0.0.0 --port 8000
#    --reload ใช้ได้เฉพาะตอน dev — ห้ามใส่ตอนใช้งานจริง เพราะมันจ้องดูไฟล์แล้ว
#    รีสตาร์ทเอง ทำให้ SSE ของทุกเครื่องที่เปิดอยู่หลุดพร้อมกัน

# 3. สคริปต์หน้างาน — ของจริงต้องรัน 2 ตัวคนละเครื่อง
cd Backend-pc_station
pip install -r requirements.txt

#    3a. บน Raspberry Pi (terminal ที่ 2) — สั่ง TM-X ผ่าน TCP
python send_command.py

#    3b. บน PC เครื่องเดียวกับ Backend (terminal ที่ 3) — รับค่า+รูปจาก TM-X
python Recieve_tm-x.py

#    หรือถ้ายังไม่มีฮาร์ดแวร์ ใช้ตัวเดียวจบ (สุ่มค่าแทน + รองรับ pause/resume)
python mockup.py

# 4. รัน Frontend
# ก่อนย้าย React เสร็จ: เปิดไฟล์ Frontend/index.html ผ่าน browser โดยตรง (หรือให้
# backend เสิร์ฟผ่าน StaticFiles mount ที่มีอยู่แล้วที่ localhost:8000)
# หลังย้าย React เสร็จ: cd Frontend && npm install && npm run dev (terminal ที่ 3
# แยกจาก backend ระหว่าง dev — ดูหัวข้อ Frontend Framework Migration)
```

ตรวจ Python version ก่อนเสมอ: ต้องเป็น **3.11**

---

## Known Issues / งานที่เหลือ

- [ ] `session_queues` ไม่ persist ลง DB — หายเมื่อ server restart กลาง session
- [ ] Stop flow ไม่สมมาตร — ปุ่มกายภาพไม่อัปเดต DB เหมือนปุ่มบนเว็บ
- [x] ~~`edit.html` เป็น frontend-only mockup~~ — เรียก API จริงครบแล้ว (Parts/Measurements/Lookup Tables CRUD)
- [x] ~~topbar navigation ยังไม่ครบ~~ — ครบทั้ง 4 หน้า จัดกลางพร้อมไฮไลต์หน้าปัจจุบัน
- [ ] ยังไม่มี auth เลย — ใครเข้าถึง API ได้ก็สั่ง Start/Stop/ลบข้อมูลได้ (จำกัดด้วย `CORS_ORIGINS` ได้ระดับหนึ่ง แต่ไม่ใช่การยืนยันตัวตน)
- [ ] `Frontend/test.html` เป็น mockup เก่าที่ไม่ได้ใช้แล้ว ยังไม่ได้ลบ
- [x] ~~Pi ไม่รู้ว่าชิ้นไหนพลาด~~ — `send_command.py` รอยืนยันว่า `measured_count` ขยับจริงหลังยิง `T1` (poll `/api/session/state`) ถ้าครบ `MEASURE_TIMEOUT` แล้วไม่ขยับ จะแจ้ง `POST /api/measure-timeout` → backend broadcast SSE `measure_timeout` → หน้าเว็บเด้ง modal ถามว่า "วัดชิ้นถัดไป / หยุดการวัด" → Pi poll `GET /api/measure-timeout/{session_id}` รอคำตอบ (เลือกหยุด = เดินเส้นทางเดียวกับปุ่ม Stop ทุกประการ)
- [ ] Trigger วัดแต่ละชิ้นใน `send_command.py` ยังจำลองด้วยการกด Enter ที่ terminal แทนสัญญาณ trigger จริงจาก MCU — รอต่อ MCU ผ่าน Serial จริง
- [ ] **`send_command.py` ไม่รองรับ `pause`/`resume`** — backend ยิง action นี้ไปแต่ `/command` รู้จักแค่ `start`/`stop` คำสั่งถูกกลืนเงียบๆ แล้วตอบ `{"status":"ok"}` กลับมา → **กด Pause บนเว็บแต่เครื่องจริงยังวัดต่อ** (`mockup.py` รองรับครบ จึงไม่เจอตอนเทสต์)
- [ ] `POST /api/measurements` ไม่เช็คสถานะ session — ค่าที่ TM-X ส่งมาช้าหลังกด Pause/Stop ยังถูกบันทึกลง DB (`Recieve_tm-x.py` เช็คแค่ว่ามี session `running` อยู่ไหมตอนที่ได้รูป ไม่ใช่ตอนที่ backend รับ)
- [ ] `send_command.py` ไม่เช็ค response ของ `R0`/`PW` — TM-X ตอบ error ก็เดินหน้าวัดต่อทั้ง session
- [ ] Power BI dashboard (`combined_3_fixed`) พัฒนาแยกขนานไปกับ Web Frontend
- [ ] Frontend ย้ายจาก Vanilla JS ไปเป็น React + Vite + TanStack Query ที่ `Frontend-react/` ครบทั้ง 3 หน้าแล้ว (Export, Edit, Dashboard) — ยังไม่ได้ตัดสลับ static mount ใน `main.py` ให้ชี้มาที่นี่ (ยังเสิร์ฟจาก `Frontend/` เดิมอยู่) รอทดสอบผ่านหน้าจอจริงให้ครบทุก flow ก่อน (โดยเฉพาะ Dashboard ที่ซับซ้อนสุด — Part Entry 3 โหมด, SSE) โค้ด Dashboard/Edit เขียนโดยยังไม่เคยผ่าน `npm run build` จริงเช่นกัน (ดูหัวข้อ Frontend Framework Migration)

---

## Conventions สำหรับแก้โค้ด

- คอมเมนต์ในโค้ดเขียนเป็นภาษาไทย ให้คงสไตล์นี้ต่อเวลาแก้ไฟล์เดิม
- คอลัมน์ operator ถูก migrate จาก `Oparetor` (VARCHAR สะกดผิด) ไปเป็น `operator_id` (FK ไปตาราง `operator`) เรียบร้อยแล้ว — ห้าม migrate กลับไปเป็น VARCHAR ตรงๆ โดยไม่คุยกันก่อน
- Tolerance เก็บที่ตาราง `package_size` เป็นค่าเดียวใช้ร่วมกันทั้งแกน X/Y (`upper_tol`, `lower_tol`) — **ไม่ได้แยกราย axis และไม่ได้เก็บที่ `parts`** ห้ามย้ายกลับไปเก็บที่ `parts` หรือแยกเป็น per-axis (`upper_tol_x`/`upper_tol_y` ฯลฯ) โดยไม่คุยกันก่อน
- **Frontend เดิม** (ไฟล์ .html ที่ยังไม่ย้าย — ดูสถานะที่หัวข้อ Frontend): ให้คงเป็น single HTML file ต่อหน้า ห้าม split เป็นหลาย JS/CSS file
- **Frontend ที่ย้ายเป็น React แล้ว**: แยกเป็น component ตามปกติของ React ได้เลย (ไม่ต้องยัดรวมไฟล์เดียวแบบเดิม) ใช้ TanStack Query จัดการ data fetching/cache/invalidate แทนการเขียน fetch + state เอง — ดูรายละเอียดที่หัวข้อ "Frontend Framework Migration"
- ก่อนแก้ตรรกะ session/queue ใน `main.py` ให้อ่าน docstring ภาษาไทยในฟังก์ชันที่เกี่ยวข้องก่อนเสมอ (อธิบายเหตุผลเชิงสถาปัตยกรรมไว้ละเอียด)