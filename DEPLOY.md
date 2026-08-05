# การติดตั้งบนเครื่อง PC หน้างาน (ห้อง PM Kit)

เอกสารนี้ใช้ตอนย้ายระบบจากเครื่อง dev ไปลงเครื่องจริง

**สรุปสั้น**: เครื่อง dev ใช้ MySQL ผ่าน Docker · เครื่องหน้างาน **ลง MySQL ตรงเป็น
Windows Service ไม่ใช้ Docker**

---

## ทำไมหน้างานไม่ใช้ Docker

| เหตุผล | รายละเอียด |
|---|---|
| **เปิดเครื่องแล้วต้องขึ้นเอง** | MySQL ที่ลงตรงเป็น Windows Service เริ่มทำงานตอนบูตทันที ไม่ต้องมีคนล็อกอิน · Docker Desktop ต้องรอให้มีคนล็อกอินเข้า Windows ก่อน — ไฟดับกลางคืนแล้วเครื่องรีบูต ระบบจะไม่ขึ้นจนกว่าจะมีคนมาเปิด |
| **ลิขสิทธิ์** | Docker Desktop ต้องซื้อ licence สำหรับองค์กรที่มีพนักงานเกิน 250 คน — ADI เข้าเกณฑ์ ต้องเช็คกับ IT ก่อน |
| **ความเร็ว** | Docker Desktop บน Windows รัน MySQL อยู่ใน WSL2 การอ่านเขียนดิสก์ต้องข้ามขอบ VM |
| **คนดูแลต่อ** | วิศวกรทดสอบเปิด `services.msc` ดูสถานะได้ · คนที่ใช้ `docker ps` เป็นมีน้อยกว่า |
| **Backup** | MySQL ลงตรงเก็บข้อมูลเป็นโฟลเดอร์ปกติ ชี้โปรแกรม backup ไปได้เลย · Docker volume อยู่ในดิสก์เสมือนของ WSL2 ต้อง export ก่อน |

---

## ขั้นตอนติดตั้ง

### 1. ลง MySQL 8.0

ดาวน์โหลด MySQL Installer เลือก **Server only** ตอนติดตั้งให้ติ๊ก
**"Configure MySQL Server as a Windows Service"** และ **"Start the MySQL Server at
System Startup"**

### 2. ⚠ ตั้ง timezone — ข้อนี้ลืมไม่ได้

เครื่อง dev บังคับ timezone ไว้ที่ `docker-compose.yml` (`--default-time-zone=+07:00`)
พอลง MySQL ตรงแล้วไม่มีใครตั้งให้ **`timestamp` ที่บันทึกจะเพี้ยนไป 7 ชั่วโมงทันที**
(เคยเกิดมาแล้วรอบหนึ่งตอนใช้ Docker แรกๆ)

แก้ที่ `my.ini` (ปกติอยู่ที่ `C:\ProgramData\MySQL\MySQL Server 8.0\my.ini`):

```ini
[mysqld]
default-time-zone = '+07:00'
```

แล้วรีสตาร์ท service:

```powershell
Restart-Service MySQL80
```

ตรวจว่าได้จริง — ต้องได้เวลาไทย ไม่ใช่ UTC:

```sql
SELECT NOW(), @@global.time_zone;
```

### 3. สร้าง database + user

```sql
CREATE DATABASE tmx_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'pc_user'@'localhost' IDENTIFIED BY '<ตั้งรหัสใหม่ ห้ามใช้ของ dev>';
GRANT ALL PRIVILEGES ON tmx_db.* TO 'pc_user'@'localhost';
FLUSH PRIVILEGES;
```

### 4. Import schema + ข้อมูลตั้งต้น

`init.sql` **ไม่ auto-run** แล้ว (นั่นเป็นความสามารถของ Docker image) ต้อง import เอง
และต้องเรียงตามนี้เท่านั้น เพราะ `insert.sql` อ้างตารางที่ `init.sql` สร้าง:

```powershell
mysql -upc_user -p tmx_db < mysql-init\init.sql
mysql -upc_user -p tmx_db < mysql-init\insert.sql
```

`init.sql` มี INDEX ของตาราง `measurements` อยู่แล้ว **ไม่ต้องรันอะไรใน `sql-tools/`
เพิ่ม** (โฟลเดอร์นั้นมีไว้อัปเกรด DB ที่มีข้อมูลอยู่แล้วเท่านั้น)

> ⚠ `init.sql` ขึ้นต้นด้วย `DROP TABLE IF EXISTS` ทุกตาราง — **ห้ามรันซ้ำหลังจากมี
> ข้อมูลจริงแล้ว ข้อมูลจะหายหมด**

### 5. ⚠ แก้ `.env`

```ini
DB_HOST=127.0.0.1
DB_PORT=3306          # เปลี่ยนจาก 3307 ของ Docker
DB_USER=pc_user
DB_PASSWORD=<รหัสที่ตั้งในข้อ 3>
DB_NAME=tmx_db
```

### 6. ลง Python 3.11 + dependency

ต้องเป็น **3.11 เท่านั้น** (3.14 ใช้กับ dependency บางตัวไม่ได้)

```powershell
cd Backend-server
pip install -r requirements.txt
```

### 7. รัน backend

```powershell
uvicorn main:app --host 0.0.0.0 --port 8000
```

`--host 0.0.0.0` จำเป็นถ้าจะให้เครื่องอื่นในวงเข้าดูได้
**ห้ามใส่ `--reload`** ตอนใช้งานจริง — มันจ้องดูไฟล์แล้วรีสตาร์ทเอง ทำให้ SSE
ของทุกเครื่องหลุดพร้อมกัน

### 8. เปิด Firewall

```powershell
New-NetFirewallRule -DisplayName "TM-X Web 8000" -Direction Inbound `
  -Protocol TCP -LocalPort 8000 -Action Allow -Profile Any
```

---

## ตั้งค่า `.env` — 2 ระยะ

ทุกอย่างที่เป็น IP/พอร์ตอ่านจาก `.env` ทั้งหมด ไม่มี hardcode ในโค้ดแล้ว
ย้ายเครื่องจึงแก้ที่ไฟล์เดียว ไม่ต้องแตะโค้ด

### ระยะที่ 1 — ทุกอย่างอยู่บนแล็ปท็อปเครื่องเดียว (เทสต์กับ TM-X จริง)

```ini
BACKEND_URL=http://localhost:8000     # send_command/Recieve ยิงกลับ Backend
AGENT_HOST=localhost                  # Backend ยิง /command ไปหา send_command
AGENT_PORT=9998
TMX_HOST=192.168.10.11                # IP จริงของ TM-X Controller
TMX_PORT=8600
AGENT_FTP_HOST=0.0.0.0                # FTP server รอรับจาก TM-X (ฟังทุก interface)
AGENT_FTP_PORT=21
```

รัน 3 อย่างบนแล็ปท็อป: `uvicorn main:app` + `send_command.py` + `Recieve_tm-x.py`

> แล็ปท็อปต้องอยู่วงเดียวกับ TM-X และ **ต้องตั้งค่าใน TM-X ให้ส่ง FTP มาที่ IP
> ของแล็ปท็อป** (ไม่ใช่ IP ของ PC เดิม) พร้อมบัญชีตรงกับ `AGENT_FTP_USER/PASS`

### ระยะที่ 2 — แยกเครื่อง (Pi + PC หน้างาน)

สมมุติ PC = `192.168.10.20`, Pi = `192.168.10.30`

| ไฟล์ `.env` ที่ | คีย์ | ค่า |
|---|---|---|
| **บน Pi** | `BACKEND_URL` | `http://192.168.10.20:8000` |
| | `AGENT_PORT` | `9998` (พอร์ตที่ตัวเองเปิดรอ) |
| | `TMX_HOST` / `TMX_PORT` | `192.168.10.11` / `8600` |
| **บน PC** | `AGENT_HOST` | `192.168.10.30` ← IP ของ Pi |
| | `AGENT_PORT` | `9998` (ต้องตรงกับที่ Pi เปิด) |
| | `AGENT_FTP_HOST` / `AGENT_FTP_PORT` | `0.0.0.0` / `21` |
| | `BACKEND_URL` | `http://localhost:8000` |

**ต้องเปลี่ยนที่ตัว TM-X ด้วย** — ตั้งปลายทาง FTP เป็น IP ของ PC (`192.168.10.20`)

### จุดที่คนมักลืม

- `AGENT_HOST` (บน PC) กับ `BACKEND_URL` (บน Pi) เป็นคนละทิศทางกัน ต้องตั้งทั้งคู่
- `AGENT_PORT` ต้องตรงกันทั้งสองเครื่อง — Backend ยิงไปพอร์ตนี้ / Pi เปิดฟังพอร์ตนี้
- Firewall ของ PC ต้องเปิด **8000** (เว็บ+API) และ **21 + 60000-60100** (FTP passive)
- Firewall ของ Pi ต้องเปิด **9998**
- ถ้า TM-X อยู่คนละวงกับ PC/Pi ต้องจัดการ routing เอง — `send_command.py` ต่อ TM-X
  จาก Pi เท่านั้น ส่วน TM-X ต้อง push FTP ไปถึง PC ได้ด้วย

---

## ยังไม่ได้ทำ (ถ้าจะให้ระบบขึ้นเองตอนบูต)

MySQL ขึ้นเองแล้วในฐานะ Windows Service แต่ **backend (uvicorn) ยังไม่ขึ้นเอง**
ตอนนี้ต้องมีคนเปิด PowerShell รันเอง ทางเลือกที่ทำได้:

- **Task Scheduler** — สร้าง task แบบ "At startup" + "Run whether user is logged on
  or not" วิธีนี้ง่ายสุด ไม่ต้องลงอะไรเพิ่ม
- **NSSM** — ห่อ uvicorn เป็น Windows Service จริงๆ ได้ทั้ง auto-restart ตอน crash
  และดูสถานะใน `services.msc` เหมือน MySQL

---

## ตรวจหลังติดตั้ง

| เช็ค | คำสั่ง / วิธี | ต้องได้ |
|---|---|---|
| MySQL เป็น service และ auto-start | `Get-Service MySQL80` | Status `Running`, StartType `Automatic` |
| timezone ถูก | `SELECT NOW();` | ตรงกับเวลาบนนาฬิกาเครื่อง |
| ตารางครบ | `SHOW TABLES;` | 11 ตาราง |
| INDEX ครบ | `SHOW INDEX FROM measurements;` | มี `idx_meas_timestamp`, `idx_meas_alpl_ts`, `idx_meas_session_result` |
| ข้อมูลตั้งต้นเข้า | `SELECT COUNT(*) FROM package_size;` | 22 แถว |
| backend ต่อ DB ได้ | เปิด `http://localhost:8000` | หน้า Home ขึ้น ป้ายมุมขวาเป็น 🟢 Online |
| เครื่องอื่นเข้าได้ | เปิด `http://<IP เครื่องนี้>:8000` จากอีกเครื่อง | หน้าเว็บขึ้นปกติ |
| **ทดสอบไฟดับ** | รีสตาร์ทเครื่องโดยไม่ล็อกอิน แล้วลองเข้าจากอีกเครื่อง | หน้าเว็บต้องขึ้นเอง |

ข้อสุดท้ายคือข้อที่คนมักข้าม แต่เป็นเหตุผลหลักที่เลือกไม่ใช้ Docker ตั้งแต่ต้น
ถ้ายังไม่ได้ทำข้อ "ยังไม่ได้ทำ" ข้างบน ข้อนี้จะไม่ผ่าน

---

## ข้อจำกัดที่ต้องรู้ก่อนส่งมอบ

- **ไม่มีระบบล็อกอิน** — ใครในวงที่รู้ IP เข้าได้และสั่ง Start/Stop/ลบข้อมูลได้ทั้งหมด
- **ไม่มีการกันคนแย่งกันคุม** — สองคนกด Start พร้อมกันจากคนละเครื่องยังไม่มีอะไรกันไว้
- **`send_command.py` ยังไม่รองรับ Pause/Resume** — กด Pause บนเว็บแล้วเครื่องจริงยังวัดต่อ (`/command` รู้จักแค่ start/stop)
- **ไม่มี retry ต่อชิ้น** — ถ้า TM-X พลาดรอบไหน `measured_count` ไม่ครบ `target_count` แล้ว session ค้าง ต้องกด Stop เอง
- **ปุ่ม Stop ที่ MCU ไม่อัปเดต DB** — กดปุ่มจริงหน้าเครื่องแล้ว DB ยังเป็น `running`
