# แผนลบ `client_uuid` ออกจากระบบ

> เอกสารนี้เขียนไว้ล่วงหน้า **ยังไม่ได้ลงมือทำ** — เปิดอ่านตอนตัดสินใจแล้วว่าจะลบจริง
> เขียนเมื่อ 23 ส.ค. 2569

---

## สรุปสั้น

`client_uuid` เป็น **idempotency key** ที่ใส่ไว้กันบันทึกซ้ำตอน retry
กลไกฝั่งรับ (backend) ทำงานได้ครบ **แต่ไม่มีผู้ส่งคนไหนสร้างคีย์ที่ใช้ได้จริง**
จึงเป็น dead code ที่ไม่เคยเข้าเงื่อนไขเลยสักครั้ง

---

## ทำไมถึงเป็น dead code

**① ไม่มีผู้ส่งคนไหนมี retry**

`Recieve_tm-x.py` ยิง `POST /api/measurements` **ครั้งเดียว** ไม่มีลูปลองใหม่
เน็ตกระตุก/timeout → `report("BACKEND_REJECT")` แล้ว `return` ทันที

**② คีย์ที่ส่งมาเป็นค่าสุ่ม**

```python
"client_uuid": str(uuid.uuid4()),     # Recieve_tm-x.py:284  · mockup.py:209
```

`uuid4()` สุ่มใหม่ทุกครั้งที่เรียก — ต่อให้ยิงซ้ำจริง backend ก็มองว่าเป็นคนละ
การวัด กันอะไรไม่ได้เลยโดยนิยาม

**③ ทางเดียวที่ใช้คีย์คงที่ยังไม่ได้เปิดใช้งาน**

`Pi.py:593` ใช้ `f"pi-{session_id}-{piece}"` ซึ่งเป็นคีย์คงที่ที่ถูกต้อง
แต่อยู่ใน `post_measurement_from_pi()` ของฟีเจอร์ "รับค่าจาก Pi" ที่ยัง
ไม่ได้ต่อสายให้ครบ (ยังไม่มี `POST /api/session/accept` ที่หน้าเว็บเรียกจริง)

---

## ⚠ อ่านก่อนตัดสินใจลบ — 3 ข้อ

**① ถ้าจะใส่ retry เมื่อไหร่ ต้องมีคีย์กลับมาทันที**

ปัญหาที่ยังเปิดอยู่ตอนนี้: เน็ตกระตุกตอน `post_to_backend` แล้วค่าเข้า DB
สำเร็จแต่ response หาย → `Recieve` `return` ก่อนอัปโหลดรูป → **แถวนั้นไม่มีรูป
ถาวร** (ไฟล์ค้างในโฟลเดอร์พักแล้วโดนล้างตอน session จบ)

ทางแก้ที่ถูกคือใส่ retry — **แต่ retry ที่ไม่มีคีย์คงที่จะสร้างข้อมูลซ้ำแทน**
สองอย่างนี้ต้องมาคู่กันเสมอ

**② ฟีเจอร์ "รับค่าจาก Pi" ใช้คีย์นี้อยู่**

`Pi.py` มี `post_measurement_from_pi()` เขียนไว้แล้ว ถ้าลบคอลัมน์ต้องแก้ตรงนั้นด้วย
(หรือลบทั้งฟีเจอร์)

**③ ทางเลือกที่ถูกกว่าการลบ**

เปลี่ยน **1 บรรทัด** ให้เป็นคีย์คงที่ แล้วมันจะกลายเป็นของที่ใช้ได้จริงทันที
โดยไม่ต้อง migration:

```python
# Recieve_tm-x.py — ts_key มาจาก _image_ts_key() ที่แกะจากชื่อไฟล์รูปอยู่แล้ว
"client_uuid": f"rx-{session_id}-{ts_key}",   # แทน str(uuid.uuid4())
```

`ts_key` = `"260731_172842"` มาจาก TM-X ไม่ซ้ำกันและคำนวณซ้ำได้เสมอ

**เทียบต้นทุน**

| | จำนวนจุดที่แตะ | ต้อง migration DB |
|---|---|---|
| ลบทิ้ง | 6 จุด | ✓ |
| แก้ให้ใช้ได้ | 1 จุด | ✗ |

---

## สิ่งที่ `client_uuid` กันได้ / กันไม่ได้ (ถ้าเปลี่ยนเป็นคีย์คงที่แล้ว)

| สถานการณ์ | กันได้ไหม |
|---|---|
| ผู้ส่งคนเดิมยิงซ้ำ (retry · กดปุ่มรัว · timeout แล้วลองใหม่) | ✓ |
| TM-X อัปโหลดไฟล์เดิมซ้ำ | ✓ ถ้าใช้คีย์แบบ `ts_key` |
| **Pi กับ Recieve ต่างคนต่างส่งค่าของชิ้นเดียวกัน** | **✗** — คนละสูตรคีย์ |

เคสสุดท้ายต้องแก้ที่ backend แทน (เทียบ `measured_count` ตอน `/api/session/accept`)
ไม่ใช่หน้าที่ของ `client_uuid`

---

## ขั้นตอนการลบ (ถ้าตัดสินใจแล้วว่าจะลบจริง)

ทำตามลำดับนี้เท่านั้น — **โค้ดก่อน แล้วค่อย DB** ไม่งั้นจะมีช่วงที่ INSERT อ้าง
คอลัมน์ที่ไม่มีอยู่แล้ว → `OperationalError 1054` → **บันทึกผลการวัดไม่ได้ทั้งระบบ**
(เคยเกิดมาแล้วตอนถอดคอลัมน์ฝั่ง GH — ดู `sql-tools/migrate_offset_op.sql`)

### 1) ฝั่งผู้ส่ง — เอาออกจาก payload

| ไฟล์ | บรรทัด | ทำอะไร |
|---|---|---|
| `Backend-server/Recieve_tm-x.py` | 284 | ลบ `"client_uuid": str(uuid.uuid4()),` |
| `Backend-pc_station/mockup.py` | 209 | ลบบรรทัดเดียวกัน |
| `Backend-pc_station/mockup.py` | 188 | ลบบรรทัดใน docstring ที่อธิบายมัน |
| `Backend-pc_station/Pi.py` | 593 | ลบออกจาก `post_measurement_from_pi()` |
| `Backend-pc_station/Pi.py` | 572 | ลบย่อหน้าเตือนใน docstring |
| `Backend-pc_station/Pi.py` | 744 | แก้คอมเมนต์ที่อ้างถึงมัน |

⚠ ถ้าลบจาก `Recieve` แต่ลืม `mockup.py` จะไม่ error (Pydantic เมิน field เกิน
เงียบ ๆ) แต่จะเหลือของตกค้างที่ทำให้คนอ่านโค้ดสับสน — **เช็คด้วย grep ให้ครบ**

### 2) Model — `Backend-server/shared.py:1044`

```python
client_uuid: Optional[str] = None      # ← ลบบรรทัดนี้
```

### 3) ตรรกะเช็คซ้ำ — `Backend-server/routers/measurements.py`

- **บรรทัด 247-272** — ลบบล็อก `if req.client_uuid:` ทั้งก้อน (SELECT หาซ้ำ +
  `return {"status": "duplicate_ignored"}`)
- **บรรทัด 337** — เอา `client_uuid` ออกจากรายชื่อคอลัมน์ของ `INSERT`
- **บรรทัด 338** — **ลด `%s` ลง 1 ตัว** ⚠ ลืมข้อนี้จะได้ `not enough arguments
  for format string` (เคยพลาดมาแล้วตอนถอด `offset_pos_gh`)
- **บรรทัด 343** — เอา `req.client_uuid` ออกจาก tuple ค่า
- **บรรทัด 345-347** — พิจารณาว่าจะเก็บ `except pymysql.IntegrityError` ไว้ไหม
  ตอนนี้ข้อความบอกว่า "duplicate client_uuid" ซึ่งจะไม่จริงอีกต่อไป
  ถ้าเก็บไว้ให้แก้ข้อความ ถ้าไม่มี UNIQUE อื่นในตารางแล้วก็ลบ `except` ทิ้งได้

**ตรวจก่อนไปขั้นถัดไป** — จำนวนคอลัมน์ · จำนวน `%s` · จำนวนค่าใน tuple
ต้องเท่ากันทั้ง 3 อย่าง

### 4) Schema สำหรับ DB ใหม่ — `mysql-init/init.sql`

- **บรรทัด 156** — ลบคอมเมนต์อธิบาย `client_uuid`
- **บรรทัด 170** — ลบ `client_uuid VARCHAR(36) NULL UNIQUE,`

### 5) Migration สำหรับ DB ที่มีข้อมูลแล้ว

⚠⚠ `mysql-init/` รันให้ **เฉพาะตอน data directory ว่างเปล่า** (container เกิดใหม่
ครั้งแรก) เท่านั้น — DB ที่ใช้อยู่จะไม่ถูกแตะเลย **ต้องเขียนสคริปต์รันเองด้วยมือ**

สร้าง `sql-tools/drop_client_uuid.sql` โดยยืมโครงจาก `sql-tools/drop_gh_columns.sql`
(มี stored procedure + `IF EXISTS` guard ให้รันซ้ำได้ เพราะ MySQL 8.0 ไม่มี
`DROP COLUMN IF EXISTS`)

```sql
-- ลบ UNIQUE index ก่อน แล้วค่อยลบคอลัมน์
IF EXISTS (SELECT 1 FROM information_schema.STATISTICS
           WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'measurements'
             AND COLUMN_NAME = 'client_uuid') THEN
  ALTER TABLE measurements DROP INDEX client_uuid;
END IF;

IF EXISTS (SELECT 1 FROM information_schema.COLUMNS
           WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'measurements'
             AND COLUMN_NAME = 'client_uuid') THEN
  ALTER TABLE measurements DROP COLUMN client_uuid;
END IF;
```

ปิดท้ายด้วย `SELECT` แสดง **ทุกคอลัมน์ของตาราง** ไม่ใช่เฉพาะที่คาดว่าจะเปลี่ยน —
เคยพลาดมาแล้วตอน `drop_gh_columns.sql` ที่ตรวจเฉพาะ `%gh%` แล้วไม่มี output
เลยเข้าใจผิดว่า "สำเร็จ" ทั้งที่ความจริงคือ "ไม่มีอะไรให้ทำ" (DB เป็น schema
คนละรุ่นกันอยู่) กว่าจะรู้ก็ไล่ผิดทางไป 3 รอบ

**วิธีรัน (dev)**

```powershell
Get-Content -Raw -Encoding utf8 sql-tools\drop_client_uuid.sql |
  docker exec -i tm-x_project-mysql-1 mysql -u root -prootpassword --default-character-set=utf8mb4 tmx_db
```

⚠ เช็คชื่อ container ก่อนยิง — มี 2 stack (`tm-x_project-mysql-1` กับ
`tm-xreact-mysql-1`) เคยยิงผิดตัวมาแล้ว

### 6) เอกสาร

- `CLAUDE.md` — ส่วน Database Schema ถ้ามีการพูดถึง
- `IMPROVEMENT_PLAN.md` — มีการอ้าง `client_uuid = ts_key + เลข 10 หลัก`
  ในบันทึกแผนเดิม ให้ปรับหรือลบตามที่ตัดสินใจ

---

## ตรวจหลังทำเสร็จ

```bash
# 1. ไม่เหลือ client_uuid ที่ไหนแล้ว (ยกเว้นไฟล์นี้)
grep -rn "client_uuid" --include=*.py --include=*.sql --include=*.ts --include=*.tsx .

# 2. INSERT นับ 3 อย่างตรงกัน
#    จำนวนคอลัมน์ = จำนวน %s = จำนวนค่าใน tuple

# 3. DB ไม่เหลือคอลัมน์
docker exec -i tm-x_project-mysql-1 mysql -u root -prootpassword tmx_db -e "DESCRIBE measurements;"

# 4. รันจริง — วัด 1 ชิ้นด้วย mockup แล้วต้องได้ 200 ไม่ใช่ 500
```

**ทดสอบให้ครบ 3 ทาง** ไม่ใช่แค่ทางปกติ:

- วัดสำเร็จปกติ → บันทึกได้
- `MOCK_MODE=recieve` → modal เด้ง → กด "รับค่าจาก Pi" → บันทึกได้ (ถ้ายังเก็บ
  ฟีเจอร์นี้ไว้)
- กด Stop กลางคัน → ไม่มี error ค้าง

---

## ถ้าไม่ลบ — สิ่งที่ควรทำแทน

ต้นทุนของการปล่อยไว้เฉย ๆ คือ `VARCHAR(36)` ต่อแถว กับโค้ด ~25 บรรทัดที่ไม่เคย
ทำงาน — ถูกกว่าค่าแรงในการลบ

**แต่ความเสียหายที่แท้จริงคือความเข้าใจผิด** — คนอ่านโค้ดเจอ `client_uuid` แล้ว
คิดว่า "กันซ้ำไว้แล้ว" → ใส่ retry อย่างสบายใจ → ได้ข้อมูลซ้ำทันที

ถ้าเลือกไม่ลบ **อย่างน้อยต้องเติมคอมเมนต์ให้ชัด** ที่ `shared.py:1044` และจุดที่
`Recieve` สร้าง uuid ว่า:

> กลไกฝั่งรับพร้อมแล้ว แต่ผู้ส่งยังใช้ `uuid4()` สุ่ม จึงยังกันอะไรไม่ได้จริง —
> ถ้าจะใส่ retry ต้องเปลี่ยนเป็นคีย์คงที่ก่อน (ดู `Delete_client_uuid.md`)
