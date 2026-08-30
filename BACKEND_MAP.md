# แผนที่ Backend — `routers/session.py` กับ `shared.py`

เอกสารนี้ตอบคำถามเดียว: **"ถ้าจะแก้เรื่องนี้ ต้องไปที่บรรทัดไหน"**

เลขบรรทัดอ้างจากไฟล์ ณ วันที่เขียน — ถ้าแก้โค้ดแล้วเลขเลื่อน ให้ค้นจากชื่อฟังก์ชันแทน

---

## สรุปใน 30 วินาที

| ไฟล์ | เปรียบเหมือน | มีอะไร |
|---|---|---|
| `shared.py` (1,565 บรรทัด) | **คลังของกลาง** | เครื่องมือที่ทุกคนใช้ร่วมกัน — ต่อ DB, ส่ง SSE, ค่าจาก `.env`, แบบฟอร์มข้อมูล, เกณฑ์ตัดสิน OK/NG |
| `routers/session.py` (1,104 บรรทัด) | **ห้องควบคุมการวัด** | ทุกอย่างที่เกี่ยวกับ "รอบการวัด 1 รอบ" — เริ่ม หยุด รายงานสถานะ กู้สถานการณ์ |

**`shared.py` ไม่มีตรรกะธุรกิจ** มันคือกล่องเครื่องมือ · ตรรกะจริงอยู่ใน router

---

# ส่วนที่ 1 — `routers/session.py`

แบ่งได้ 4 กลุ่มตามหน้าที่

---

## กลุ่ม A · ท่อสื่อสารกับหน้าเว็บและ Pi

### `sse_stream()` — บรรทัด 18 · `GET /api/stream`

ท่อทางเดียวจาก backend ไปหน้าเว็บ

หน้าเว็บเปิดสายนี้ค้างไว้ตลอด แล้ว backend ยัดข้อมูลลงไปเมื่อมีอะไรเกิดขึ้น (ผ่าน `push_event` ใน `shared.py`)

**ทำงานยังไง** — แต่ละแท็บที่เปิดอยู่จะได้ `asyncio.Queue` ของตัวเอง ใส่ไว้ในลิสต์ `subscribers` แล้วฟังก์ชันนี้วนรอของจากคิว

```python
event = await asyncio.wait_for(queue.get(), timeout=25)
```

ถ้าเงียบครบ 25 วิ จะส่ง `ping` เปล่าๆ ออกไป **เพื่อไม่ให้เบราว์เซอร์หรือ proxy ตัดสายที่ไม่มีข้อมูล**

> ⚠ ตัวเลข 25 นี้คือ "ช่วงเวลาที่เบราว์เซอร์อาจยังไม่รู้ว่า backend ตายแล้ว" — เกี่ยวกับป้ายสถานะบนแถบบน

### `get_ui_config()` — บรรทัด 47 · `GET /api/config`

ส่งค่าจาก `.env` บางตัวให้หน้าเว็บ (เบราว์เซอร์อ่านไฟล์ `.env` เองไม่ได้)

ไม่แตะ DB เลย จึงไม่มีทางตอบ 503 · **ห้ามใส่รหัสผ่านหรือ path ในเครื่องลงไปเด็ดขาด** เพราะระบบยังไม่มี auth

### `get_session_state()` — บรรทัด 69 · `GET /api/session/state`

**endpoint ที่ถูกเรียกบ่อยที่สุดในระบบ และแบกงานมากที่สุด**

คืน session ล่าสุด 1 แถว พร้อมของแถมอีก 4 อย่าง — `queue_state`, `pi_status`, `trigger_ready`, `manual_trigger`

**ใครใช้บ้าง**

| ผู้เรียก | เอาไปทำอะไร | ถี่ |
|---|---|---|
| หน้าเว็บ | สถานะ session · แถบคิว · สถิติ · ชิป Pi · ป้าย DB | 1–4 วิ |
| `Data-receiver.py` | ถามว่ามี session running อยู่ไหม ก่อนรับค่า | ทุกไฟล์ที่ได้รับ |
| `Pi.py` | ดูว่า `measured_count` ขยับหรือยัง | 0.4 วิ |

**หัวใจของมันคือ SQL บรรทัด 143**

```sql
SELECT session_id, state, target_count, measured_count,
       queue_state, last_seen, started_at, ended_at
FROM sessions ORDER BY session_id DESC LIMIT 1
```

> ⚠ **ไม่มี `WHERE`** — คืน session ล่าสุดเสมอ ต่อให้จบไปเป็นเดือน
> นี่คือสาเหตุที่แถบคิวเก่าโผล่กลับมาตอนเปิดหน้าเว็บวันถัดไป
> ถ้าจะแก้ ต้องคิดถึงผู้เรียกทั้ง 3 กลุ่มพร้อมกัน เพราะบางคนต้องการของเก่าจริงๆ

**ทางออก 3 ทาง ต้องใส่ `pi_status` ให้ครบทุกทาง** — มี session / ไม่มี session เลย / ต่อ DB ไม่ติด ถ้าตกหล่นทางไหน หน้าเว็บจะได้ `undefined` แล้วชิป Pi กลายเป็น "ไม่ทราบ"

### `heartbeat()` — บรรทัด 1051 · `POST /api/heartbeat`

Pi ยิงเข้ามาทุก 5 วิ เพื่อบอกว่า "ยังอยู่"

ทำ 2 อย่าง — เรียก `mark_pi_seen()` (จำเวลาล่าสุด) และอัปเดต `sessions.last_seen` เพื่อไม่ให้ `heartbeat_checker` มา mark session เป็น timeout

---

## กลุ่ม B · เริ่มการวัด

### `start_session()` — บรรทัด 555 · `POST /api/session/start`

**ฟังก์ชันที่ซับซ้อนที่สุดในไฟล์** เรียกตัวช่วย 6 ตัว ทำงานเป็น 4 ขั้น

```
1) แปลง payload → ลิสต์กลุ่ม        _parse_entry_groups()
   คลี่ ALPL ทุกกลุ่ม → คิวเส้นเดียว  _flatten_groups()
   ตรวจทีละกลุ่ม (ไม่เขียน DB)       _validate_group()
   เช็คว่าทุกกลุ่มใช้ Template เดียวกัน   ← ถ้าไม่ ปฏิเสธทันที (บรรทัด 641)

1.5) ประกอบ payload ที่จะส่งให้ Pi     _build_groups()
     ⚠ ทำ "ก่อน" insert โดยตั้งใจ — ถ้าเกณฑ์ 2 ฝั่งไม่ตรง จะ raise
       ตรงนี้แล้วไม่มี session ผีค้างใน DB

2) INSERT INTO sessions (state='running', target_count, measured_count=0)

3) สร้าง queue_state → เก็บใน session_queues (memory) + UPDATE ลง DB

4) ยิง POST /command ไปหา Pi          _notify_agent_start()
   แล้ว broadcast SSE `session_started`
```

**สิ่งที่ต้องรู้ก่อนแก้**

- **ไม่มีการเขียน Part ลง DB ที่นี่เลยทุกโหมด** — แค่ตรวจแล้วเก็บ config ไว้ใน `queue_state` ให้ `create_measurement` สร้าง Part พร้อม measurement ของชิ้นนั้นทีละชิ้น ผลคือกด Start แล้ว Stop ทันที = ไม่มีอะไรเกิดใน DB
- ใช้ **MySQL named lock** `tmx_start_session` ครอบขั้นที่ 1–2 (ปล่อยที่บรรทัด 669) กันคนกด Start พร้อมกัน 2 เครื่อง
- **ทุกกลุ่มต้องใช้ Template เดียวกัน** เพราะ Pi ส่ง `PW` ครั้งเดียวตอนเริ่ม การสลับ `PW` กลางคิวยังไม่ได้ทำ

### ตัวช่วยของ `start_session`

| ฟังก์ชัน | บรรทัด | ทำอะไร |
|---|---|---|
| `_parse_entry_groups()` | 425 | แปลง payload ให้เป็น "ลิสต์ของกลุ่ม" เสมอ ไม่ว่าหน้าเว็บส่งมารูปแบบไหน |
| `_flatten_groups()` | 450 | คลี่ ALPL ทุกกลุ่มเป็นคิวเส้นเดียว + สร้าง `group_of[i]` = ชิ้นที่ i อยู่กลุ่มไหน |
| `_validate_group()` | 483 | ตรวจ 1 กลุ่มให้ครบ **โดยไม่เขียน DB** คืนชื่อ Template |
| `_criteria_from_config()` | 181 | เกณฑ์ของกลุ่ม — อ่านจาก **config ที่ผู้ใช้กรอก** ไม่ใช่จากแถว Part ใน DB |
| `_limits_of()` | 159 | แปลง nominal/tolerance → **ขอบเขตสำเร็จรูป** (`x_lo`/`x_hi`/`y_lo`/`y_hi`/`offset_max`) |
| `_build_groups()` | 209 | ประกอบฟิลด์ `groups` ที่แนบไปกับ `/command` |
| `_notify_agent_start()` | 259 | ยิง `POST /command` ไปที่ `AGENT_HOST:AGENT_PORT` |
| `_fail_start()` | 365 | ถ้าสั่ง Pi ไม่สำเร็จ → ล้าง session ที่เพิ่งสร้าง แล้วโยน 502 |

**ทำไมต้องแปลงเป็น "ขอบเขตสำเร็จรูป" (`_limits_of`)**

Backend บวก/ลบค่าเผื่อทศนิยม (`_TOL_EPS`) ให้เสร็จก่อนส่ง Pi จึงเทียบ `x_lo <= x <= x_hi` ตรงๆ ได้เลย **ไม่ต้องลอกกฎเรื่องค่าเผื่อไปไว้อีกฝั่ง** — ถ้าส่ง nominal/tol ดิบไป กฎจะมี 2 ชุดที่ต้องคอยทำให้ตรงกันตลอดไป

`offset_max: null` = โหมดนี้ไม่ตรวจ offset (IPM) · **จงใจไม่ส่ง `measure_type` ไปด้วย** เพื่อไม่ให้กฎเรื่องโหมดไปงอกที่ฝั่ง Pi

---

## กลุ่ม C · หยุดการวัด

### `stop_session()` — บรรทัด 725 · `POST /api/session/stop`

กด Stop บนหน้าเว็บ → อัปเดต DB เป็น `stopped` → ล้าง `session_queues` ในหน่วยความจำ → สั่ง Pi ให้หยุด → broadcast SSE

**ถ้าสั่ง Pi ไม่สำเร็จก็ยังหยุด session ใน DB อยู่ดี** แล้วแนบ `agent_error` กลับไปให้หน้าเว็บเด้งเตือนว่า "เครื่องอาจยังวัดต่อ — ไปดูที่เครื่อง"

### `_notify_agent_action()` — บรรทัด 790

ยิงคำสั่งสั้นๆ (`stop` / `continue`) ไปหา Pi คืนข้อความ error ถ้าไม่สำเร็จ **ไม่ raise** — เพราะผู้เรียกต้องทำงานต่อให้จบไม่ว่า Pi จะตอบหรือไม่

### `session_event()` — บรรทัด 836 · `POST /api/session/event`

รับรายงานสาเหตุจาก `Data-receiver.py` (เช่น "หาไฟล์ .txt ไม่เจอ") แล้วส่งต่อให้หน้าเว็บผ่าน SSE

---

## กลุ่ม D · กู้สถานการณ์ตอนวัดพลาด

4 ฟังก์ชันนี้ทำงานเป็นชุดเดียวกัน อ่านรวมกันถึงจะเข้าใจ

```
Pi ยิง T1 → รอค่าจนหมดเวลา (MEASURE_TIMEOUT) → ยังไม่มา
   ↓
POST /api/measure-timeout        report_measure_timeout()   บรรทัด 861
   ↓ backend เก็บคำถามไว้ใน measure_timeouts + broadcast SSE
   ↓
หน้าเว็บเด้ง modal ถามผู้ใช้ (ปิดไม่ได้ มีนับถอยหลัง)
   ↓
ผู้ใช้เลือก 1 ใน 3
   ├─ "ลองใหม่"          → POST /api/session/retry    retry_session()   บรรทัด 926
   ├─ "รับค่าจาก Pi"     → POST /api/session/accept   accept_session()  บรรทัด 1005
   └─ "หยุด"             → POST /api/session/stop     (เส้นทางเดียวกับปุ่ม Stop ทุกประการ)
   ↓
backend ยิง POST /command ไปหา Pi (action: retry / accept / stop)
   ↓
Pi ที่ค้างรออยู่ตื่นขึ้นมาทำงานต่อ
```

> ⚠ **Pi ไม่ได้ poll รอคำตอบ** — มันค้างรออยู่ที่ `threading.Event` ในตัวเอง
> (`Pi.py:586` → `_answer_event.wait(ASK_USER_TIMEOUT)`) แล้ว backend เป็นฝ่าย
> ยิง `POST /command` ไปปลุก (`Pi.py:134-148`)
>
> **ไม่มี `GET /api/measure-timeout/{session_id}` อยู่จริงในโค้ด** — มีแค่ `POST`
> ที่บรรทัด 860 · `CLAUDE.md` เขียนว่ามี GET ตัวนี้ แต่ตกรุ่นไปแล้ว

**`accept_session()` คืออะไร** — กรณีที่ TM-X วัดสำเร็จแล้วจริง แต่ค่าไม่ถึง DB (Data-receiver ส่งไม่ถึง) ชิ้นงานถูก MCU คัดออกไปแล้ว **ไม่มีอะไรให้วัดใหม่** Pi จึงเอาค่าที่อ่านจาก `GM` ไว้แล้วมา POST เข้า `/api/measurements` เอง โดยไม่มีรูป

> ⚠ นี่เป็น **ทางเดียวที่ Pi เขียนผลวัดลง DB** — ปกติเป็นหน้าที่ของ `Data-receiver.py`
> Pi เช็ค `measured_count` ซ้ำก่อน POST เพราะค่าอาจมาถึงระหว่างที่ modal เปิดรออยู่
> **การเช็คนั้นคือด่านเดียวที่กันแถวซ้ำทั้งระบบ** (ไม่มี `client_uuid` แล้ว)

### `manual_trigger()` — บรรทัด 972 · `POST /api/session/trigger`

ปุ่มจำลองสัญญาณทริกเกอร์บนหน้าเว็บ ใช้ระหว่างที่ยังไม่ได้ต่อ MCU จริง — เปิด/ปิดด้วย `ALLOW_MANUAL_TRIGGER` ใน `.env`

---

# ส่วนที่ 2 — `shared.py`

แบ่งได้ 9 กลุ่ม

---

## กลุ่ม 1 · ต่อฐานข้อมูล

### `get_db()` — บรรทัด 457

**เปิด connection ใหม่ทุก request ไม่มี pool โดยตั้งใจ** — ระบบนี้อยู่บน PC เครื่องเดียว มีผู้ใช้จริงคนเดียว ความเรียบง่ายคุ้มกว่าความซับซ้อนของ pool

ทำ 2 อย่างที่สำคัญ

**① แปลง error ให้เป็น 503** — ถ้า MySQL ล่ม `pymysql.connect()` จะโยน `OperationalError` ซึ่ง FastAPI ไม่รู้จัก → หลุดเป็น 500 ดิบที่**ไม่มี CORS header** ทำให้หน้าเว็บอ่าน error ไม่ได้เลย จับไว้ที่นี่ที่เดียวแล้วโยน `HTTPException(503)` แทน

**② circuit breaker** — `connect_timeout=3` เป็นราคาที่จ่าย **ต่อ request** ไม่ใช่ต่อเหตุการณ์ MySQL ดับทีเดียวแต่ทุก endpoint ต้องรอครบ 3 วิของตัวเอง เปิดหน้าเว็บครั้งเดียวยิงสิบกว่า request → กองสะสมจนเว็บเหมือนค้าง ตัว breaker จำไว้ว่า "เพิ่งต่อไม่ติด" แล้วปฏิเสธทันทีในช่วง `DB_BREAKER_COOLDOWN`

> ⚠ `autocommit=True` (บรรทัด 48) — **ทุกคำสั่ง SQL คอมมิตทันทีทีละตัว ไม่มี transaction**
> ฟังก์ชันไหนที่เขียนหลาย statement ติดกันจึงหยุดกลางคันแล้วเหลือสภาพครึ่งๆ ได้
> (ดู `create_measurement` ใน `measurements.py` — 4 การเขียนเรียงกัน)

---

## กลุ่ม 2 · ส่งข้อมูลไปหน้าเว็บ

### `push_event()` — บรรทัด 442

ตัวเดียวที่ยิง SSE ออกไป — ใส่ payload เดียวกันลงในคิวของทุกแท็บที่เปิดอยู่ (ลิสต์ `subscribers`)

```python
push_event("measurement", {...})   # ทุกแท็บได้พร้อมกัน
```

**ชื่อ event ต้องตรงกับลิสต์ `EVENT_NAMES` ใน `useSSE.ts` ฝั่ง React** — ถ้าเพิ่ม event ใหม่ที่นี่แต่ลืมเพิ่มที่นั่น หน้าเว็บจะทิ้งมันเงียบๆ ไม่มี error ให้เห็น

---

## กลุ่ม 3 · วงจรชีวิตของแอป

### `lifespan()` — บรรทัด 608

ทำงานตอน FastAPI เริ่มและตอนปิด · เริ่ม background task ทั้งหมดที่นี่

```python
await _reload_session_queues()   # ต้องเสร็จ "ก่อน" รับ request ตัวแรก
yield                            # ← ระหว่าง yield คือช่วงที่แอปทำงานปกติ
```

### `_reload_session_queues()` — บรรทัด 520

กู้ `session_queues` กลับเข้า memory จากคอลัมน์ `sessions.queue_state`

**ทำไมต้องมี** — `session_queues` เป็น dict ใน memory ล้วนๆ ถ้า backend restart กลาง session คิวจะหายหมด แล้วชิ้นที่เหลือจะถูกบันทึกใต้ ALPL ผิดตัว

> ⚠ ต้อง `await` ให้เสร็จก่อน `yield` **ห้ามทำเป็น fire-and-forget** ไม่งั้น request แรกอาจเข้ามาก่อนที่คิวจะกู้เสร็จ

### `heartbeat_checker()` — บรรทัด 562

วนทุก `HEARTBEAT_INTERVAL` วิ — ถ้า session ไหน `running` แต่ `last_seen` เก่ากว่า `HEARTBEAT_TIMEOUT` จะเปลี่ยนเป็น `timeout` + ล้างคิว + broadcast SSE

### `_deleted_purge_loop()` — บรรทัด 695

ล้างถังขยะที่เกิน `DELETED_RETENTION_DAYS` — ทำทันทีตอนเริ่ม แล้ววนวันละครั้ง

---

## กลุ่ม 4 · สถานะของ Pi

| ฟังก์ชัน | บรรทัด | ทำอะไร |
|---|---|---|
| `mark_pi_seen()` | 624 | จำว่า "เพิ่งเห็น Pi เดี๋ยวนี้" — เรียกจาก `/api/heartbeat` ทุกครั้ง |
| `read_pi_status()` | 655 | คืน `True` / `False` / **`None`** |
| `read_trigger_ready()` | 677 | ตอนนี้ยิงทริกเกอร์ได้ไหม — ใช้เปิด/ปิดปุ่มบนหน้าเว็บ |

> ⚠ `read_pi_status()` มี **3 ค่า ไม่ใช่ 2**
> `True` = ได้ heartbeat ภายในเกณฑ์ · `False` = เงียบเกินเกณฑ์ · `None` = **ไม่ทราบ** (backend เพิ่ง restart ยังไม่เคยได้ heartbeat เลย)
> **ห้ามยุบ `None` รวมกับ `False`** — "รู้ว่าตาย" กับ "เราไม่รู้" คนละเรื่องกันตอนไล่หาสาเหตุ
>
> ต่างจาก `read_trigger_ready()` ที่ยุบเหลือ 2 ค่าตั้งแต่ฝั่ง backend เพราะปุ่มมีแค่ "กดได้" กับ "กดไม่ได้" และ "ไม่รู้" ต้องแปลว่ากดไม่ได้เสมอ

---

## กลุ่ม 5 · เกณฑ์ตัดสิน OK/NG

**3 ฟังก์ชันนี้เป็นทางเดียวที่ควรใช้** ห้ามเขียนกฎเทียบค่าขึ้นมาใหม่ที่อื่น

| ฟังก์ชัน | บรรทัด | ทำอะไร |
|---|---|---|
| `_load_criteria()` | 134 | ดึง nominal/tolerance ที่จะใช้ตัดสิน **ตามโหมดที่กำลังวัด** |
| `_within_tolerance()` | 97 | ค่าแกนหนึ่งอยู่ในช่วง `nominal − lower_tol .. nominal + upper_tol` ไหม |
| `_offset_limit()` | 123 | เพดาน offset ที่ต้องตรวจจริง — `None` = ไม่นับเป็นเกณฑ์ |

**กฎที่ต้องจำ — เกณฑ์มาจากคนละตารางตามโหมด**

| โหมด | ใช้ตารางไหน | เอา offset มาตัดสินไหม |
|---|---|---|
| IPM | `package_size` | **ไม่** |
| New / Rework | `part_number` | **ใช่** |

> ⚠ **ห้ามเรียก `_offset_ok(offset, row["offset_tol"])` ตรงๆ** เพราะจะหลุดเงื่อนไขเรื่องโหมด แล้ว DB กับ Pi จะตัดสินไม่ตรงกัน

**`_TOL_EPS` (บรรทัด 95)** = ค่าเผื่อความคลาดเคลื่อนของเลขทศนิยม เพราะคอมพิวเตอร์เก็บ `0.1 + 0.2` ได้ไม่ตรงเป๊ะ ค่าที่อยู่ขอบสเปกพอดีจึงอาจถูกตัดสินผิดถ้าไม่เผื่อไว้

---

## กลุ่ม 6 · ประวัติการแก้ไข และถังขยะ

| ฟังก์ชัน | บรรทัด | ทำอะไร |
|---|---|---|
| `log_edit()` | 265 | **ตัวเดียวที่เขียนตาราง `edit_history`** |
| `_history_changes()` | 226 | เทียบก่อน/หลัง คืน `[{field, before, after}]` |
| `_history_value()` | 222 | แปลง `Decimal`/`datetime`/`timedelta` ให้ `json.dumps` รับได้ |
| `_archive_before_delete()` | 318 | เก็บข้อมูลที่กำลังจะลบไว้เป็นไฟล์ JSON ใน `Deleted/` |
| `_purge_old_deleted()` | 1410 | ลบโฟลเดอร์ที่เก่ากว่ากำหนด คืนจำนวนที่ลบ |
| `_json_safe()` | 201 | แปลงค่าจาก DB ให้ `json.dumps` ได้ |

---

## กลุ่ม 7 · แบบฟอร์มข้อมูล (Pydantic)

คลาสพวกนี้คือ **กติกาว่า request ที่ส่งเข้ามาต้องมีอะไรบ้าง** ถ้าไม่ครบ FastAPI ปฏิเสธให้เองด้วย 422 โดยที่โค้ดเราไม่ต้องเขียนเช็ค

| คลาส | บรรทัด | ใช้กับ |
|---|---|---|
| `MeasurementCreate` | 1059 | `POST /api/measurements` |
| `PartCreate` | 955 | สร้าง Part |
| `PartsCheckRequest` | 985 | `POST /api/parts/check` |
| `PackageSizeCreate/Update` | 827 / 836 | ตาราง `package_size` |
| `PartNumberCreate/Update` | 851 / 862 | ตาราง `part_number` |
| `LookupCreate/Update` | 819 / 822 | ตาราง lookup ทั่วไป |
| `StopSessionRequest` | 711 | `POST /api/session/stop` |
| `MeasureTimeoutRequest` | 783 | `POST /api/measure-timeout` |
| `SessionEventRequest` | 788 | `POST /api/session/event` |
| `HeartbeatRequest` | 806 | `POST /api/heartbeat` |
| `ImageUpdate` | 1077 | `PATCH .../image` |
| `ExportTemplateBody` | 1308 | เทมเพลตรายงาน |

> ⚠ **`MeasurementCreate` ไม่มีฟิลด์ `result`** — คำตัดสิน OK/NG ที่ Pi คำนวณไว้ส่งเข้ามาไม่ได้ backend คำนวณใหม่เองเสมอด้วย `_judge()` ใน `measurements.py`
> (ฝั่ง Pi ตัดสินเองเพื่อสั่ง MCU คัดแยกโดยไม่ต้องรอเน็ต — คนละวัตถุประสงค์กัน)

---

## กลุ่ม 8 · SQL สำเร็จรูป และตัวช่วยรายงาน

| ตัวแปร/ฟังก์ชัน | บรรทัด | ทำอะไร |
|---|---|---|
| `PARTS_SELECT` | 872 | SQL กลางของตาราง Parts |
| `MEASUREMENTS_SELECT` | 1042 | SQL กลางของตาราง Measurements |
| `EXPORT_SELECT` | 1109 | SQL กลางของการ export |
| `_lookup_id()` | 901 | แปลงชื่อจาก dropdown → id |
| `_insert_part_row()` | 1000 | Insert 1 แถวลง `parts_specifications` |
| `_block_if_session_running()` | 919 | ปฏิเสธการแก้/ลบ Part ระหว่างที่กำลังวัดอยู่ |
| `_axis_state()` | 1157 | แกนนี้ OK หรือ NG (ใช้ในรายงาน) |
| `_offset_state()` | 1170 | offset ของแถวนี้ผ่านไหม |
| `_tolerance_spec()` | 1186 | สเปกขนาดชิ้นงานย่อบรรทัดเดียว |
| `_fmt_timestamp()` | 1136 | จัดรูปแบบวันเวลาตามที่ผู้ใช้ติ๊ก |
| `_day_start()` / `_day_end()` | 1330 / 1320 | ครอบช่วงวันที่ให้เต็มวัน |
| `export_filters_dep()` | 1338 | รวม filter ที่ preview กับ csv ใช้ร่วมกัน |
| `_thai_date_str()` | 184 | `DD-MM-YYYY` ปี พ.ศ. |

> ⚠ **ห้ามใส่ `_block_if_session_running()` ใน `/api/parts/check`** เพราะเป็นการอ่านอย่างเดียวและต้องใช้ได้ก่อนเริ่มวัด

---

## กลุ่ม 9 · ค่าจาก `.env`

| ตัวแปร | บรรทัด | คุม |
|---|---|---|
| `DB_CONFIG` | 39 | การต่อ MySQL |
| `DB_BREAKER_COOLDOWN` | 78 | circuit breaker พักกี่วิ |
| `ALPL_IMAGE_DIR` | 90 | ที่เก็บรูปถาวร |
| `_TOL_EPS` | 95 | ค่าเผื่อทศนิยม |
| `DELETED_DIR` / `_RETENTION_DAYS` | 194 / 199 | ถังขยะ |
| `AGENT_HOST` / `AGENT_PORT` / `AGENT_BASE_URL` | 391–395 | ที่อยู่ของ Pi |
| `UI_POLL_INTERVAL` | 403 | หน้าเว็บ poll ถี่แค่ไหน |
| `PI_ONLINE_TIMEOUT` | 408 | Pi เงียบกี่วิถึงนับว่าออฟไลน์ |
| `HEARTBEAT_INTERVAL` / `_TIMEOUT` | 426 / 428 | heartbeat |
| `CORS_ORIGINS` | 434 | origin ที่ยอมให้เรียก API |
| `REPORT_MAX_ROWS` / `REPORT_PREVIEW_LIMIT` | 1381 / 1379 | เพดานแถวรายงาน |
| `ALLOW_MANUAL_TRIGGER` | 1388 | เปิดปุ่มจำลองทริกเกอร์ไหม |

> ⚠ **ตัวเลขในโค้ดคือค่า fallback ไม่ใช่ค่าที่ใช้จริง** — ต้องไปดู `.env` เสมอก่อนสรุปว่าอะไรถูกอะไรผิด

---

# ส่วนที่ 3 — ใคร poll อะไร และเอาไปทำอะไร

`/api/session/state` (`session.py:69`) ถูกยิงจาก **7 ที่ที่ไม่รู้จักกัน** — ตารางนี้ไล่ทีละตัว

---

## ① `Pi.py:239` `get_measured_count()` — ถี่ที่สุดในระบบ

**ถี่** ทุก **0.4 วิ** (`MEASURE_POLL_INTERVAL` ใน `.env`) เฉพาะช่วงที่รอค่าหลังยิง `T1` แต่ละชิ้น

**ทำอะไร** — Pi ยิง `T1` ให้ TM-X วัดแล้ว **ไม่มีทางรู้เลยว่าค่าไปถึง DB หรือยัง** เพราะคนส่งค่าคือ `Data-receiver.py` ที่อยู่คนละเครื่อง Pi จึงต้องคอยถาม backend ว่า `measured_count` ขยับหรือยัง

```python
# Pi.py:540  wait_for_measurement()
while time.time() < deadline:
    if not is_running: return True          # ผู้ใช้กด Stop ระหว่างรอ
    count_after = get_measured_count(session_id)
    if count_after > count_before: return True   # ✅ ค่าถึง DB แล้ว วัดชิ้นต่อไปได้
    time.sleep(MEASURE_POLL_INTERVAL)
return False                                 # ❌ ครบ 15 วิ (MEASURE_TIMEOUT) แล้วไม่ขยับ
```

คืน `False` เมื่อไหร่ → เข้าสู่ผัง "กู้สถานการณ์" ในกลุ่ม D

**ทำไมต้องถี่ขนาดนี้** — ทุก 0.4 วิที่ช้าไปคือเวลาที่คนหน้างานยืนรอเปล่าๆ ก่อนวัดชิ้นถัดไป · และมันยิงเฉพาะช่วงรอ ไม่ได้ยิงตลอดเวลา

> ⚠ `get_measured_count()` เช็ค `data["session_id"] != session_id` แล้วคืน `None`
> ป้องกันการอ่านตัวนับของ session อื่นมาใช้ — จำเป็นเพราะ endpoint นี้คืน
> session ล่าสุดเสมอ ไม่ได้คืนตัวที่ Pi ถามหา

---

## ② `Pi.py:813` — เช็คตอนจบ session

**ถี่** ครั้งเดียวตอนหลุดออกจาก loop การวัด

**ทำอะไร** — ถามว่า session นี้ยังเป็น `running` อยู่ไหม ถ้าใช่แปลว่า **จบก่อนครบจำนวน** (ไม่ใช่จบเพราะวัดครบ) แล้วรายงานสาเหตุกลับไป

> ⚠ ห้ามส่ง `reason` เป็น `None` — `session.py` เช็ค `if req.reason:` ถ้าเป็น `None`
> จะไม่เขียนอะไรลง DB เลย หน้าเว็บขึ้น `STOPPED` เปล่าๆ โดยไม่บอกว่าทำไม

---

## ③ `useSessionState.ts:80` — ตัวหลักของหน้าเว็บ

**ถี่** 1 วิตอน `running` · 4 วิตอนอื่น

**ทำอะไร** — เป็นแหล่งข้อมูลของ **4 อย่างบนหน้าจอ**

| ได้อะไร | เอาไปโชว์ที่ไหน |
|---|---|
| `dbOffline` (จาก HTTP 503) | ป้าย Server/Database บนแถบบน (`Layout.tsx`) |
| `piStatus` | ชิป Raspberry Pi ใน Session Control |
| `triggerReady` | เปิด/ปิดปุ่ม ⚡ Trigger |
| `manualTrigger` | แสดง/ซ่อนปุ่มนั้น |

**ทำไมถี่ขึ้นตอน running** — ค่าที่ต้องการความสดที่สุดคือ `triggerReady` ปุ่มต้องสว่างทันทีที่ Pi พร้อมรับสัญญาณ ไม่งั้นคนหน้างานยืนรอโดยไม่รู้ว่าต้องรออีกนานแค่ไหน

**ทำไม `retry: false`** — เส้นนี้ถูกใช้เป็น "เครื่องวัดว่า DB ยังไหวไหม" ด้วย ถ้าปล่อยให้ retry ป้าย Database offline จะขึ้นช้ากว่าความจริงหลายวินาที

TanStack Query dedupe ตาม `queryKey` ให้อยู่แล้ว — `Layout` กับ `DashboardPage` เรียกทั้งคู่แต่ยิงจริงแค่ครั้งเดียว

---

## ④ `DashboardPage:831` `loadSessionState()` — ตัวที่ซ้ำซ้อน

**ถี่** ทุก 5 วิ

**ทำอะไร** — ยิงแล้วส่งผลต่อให้ 2 ฟังก์ชัน

```python
updateSession(d)     # merge เข้า session state + เช็คว่าคิว Part Entry หมดอายุยัง
syncQueueStrip(d)    # วาดแถบคิว ALPL ใหม่จาก queue_state
```

> ⚠ **ตัวนี้กับ ③ ยิง endpoint เดียวกันแต่ไม่รู้จักกัน**
> `loadSessionState()` เป็น `apiGet` ดิบ **ไม่ได้ผ่าน TanStack จึงไม่ถูก dedupe**
> ตอนกำลังวัด หน้า Dashboard จึงยิง `/api/session/state` จาก 2 ทางพร้อมกัน
> แล้วเอาผลไปเขียน state คนละชุด — **มีจังหวะที่สองตัวเห็นข้อมูลคนละเวอร์ชันได้**
> ถ้าจะรื้อ polling ควรยุบให้เหลือทางเดียว

---

## ⑤ `EditPage:276` `checkSessionRunning()` — ล็อกหน้า

**ถี่** ทุก 4 วิ เฉพาะตอนเปิดหน้า Edit

**ทำอะไร** — อ่านแค่ฟิลด์เดียวคือ `state`

```tsx
const d = await apiGet<{ state: string }>("/api/session/state");
setSessionRunning(d.state === "running");
```

ถ้า `running` → ล็อกฟอร์มทั้งหน้าไม่ให้แก้/ลบ Part **เพราะการแก้ config ระหว่างที่เครื่องกำลังวัดอยู่จะทำให้เกณฑ์ตัดสินเปลี่ยนกลางคัน** (ฝั่ง backend มี `_block_if_session_running()` กันอีกชั้นอยู่แล้ว ตัวนี้แค่ทำให้ UI บอกล่วงหน้าแทนที่จะให้กดแล้วเด้ง error)

จับ error แบบเงียบๆ โดยตั้งใจ — poll ล้มเหลวไม่ควรทำให้หน้าใช้งานไม่ได้

---

## ⑥ `Data-receiver.py:136` `get_current_session()` — ด่านก่อนรับค่า

**ถี่** ไม่ใช่ interval — ยิง **ทุกครั้งที่ได้ไฟล์จาก TM-X**

**ทำอะไร** — ถามว่าตอนนี้มี session ไหน `running` อยู่

```python
if data.get("state") == "running":
    return data.get("session_id")
return None      # ← ไม่มี session → ทิ้งค่า+รูปนั้นไปเลย
```

**ทำไมต้องมี** — TM-X ส่งไฟล์ช้ากว่าเวลาจริงได้ ถ้าส่งมาถึงหลัง session จบไปแล้ว ค่านั้นจะถูกแปะเข้า session ผิดตัว ด่านนี้ทิ้งมันทิ้งไปเลย

---

## ⑦ `Data-receiver.py:263` `session_watcher()` — ล้างโฟลเดอร์พัก

**ถี่** ทุก **3 วิ** (`SESSION_POLL_INTERVAL` ฮาร์ดโค้ดไว้ที่บรรทัด 35 ไม่ได้อ่านจาก `.env`)

**ทำอะไร** — เฝ้าดูว่า `session_id` เปลี่ยนหรือ session จบหรือยัง แล้วเรียก `clear_temp_dir()` ล้าง `Store_image_temporary/` ทิ้ง

กันไม่ให้รูปค้างจากรอบก่อนถูกจับคู่ผิดกับค่าของรอบใหม่

---

## ⑧ `updateStats()` `DashboardPage:450` — ตัวเดียวที่ไม่ได้ยิง `/api/session/state`

**ถี่** ทุกครั้งที่ `updateSession()` ถูกเรียก — คือทั้งจาก poll 5 วิ **และ** จาก SSE event ทุกตัว

**ทำอะไร** — ยิง `/api/measurements` **3 คำขอพร้อมกัน** เพื่อนับเลข 3 ตัวบนการ์ด Stats

```tsx
Promise.all([
  apiGet("/api/measurements", { session_id, limit: 1 }),                  // total
  apiGet("/api/measurements", { session_id, result: "OK", limit: 1 }),    // ok
  apiGet("/api/measurements", { session_id, result: "NG", limit: 1 }),    // ng
])
```

ใช้ `limit: 1` เพราะต้องการแค่ฟิลด์ `total` ที่ backend แนบมา ไม่ได้ต้องการตัวข้อมูล

**เช็คธง `isTelemetryCleared()` 2 ครั้ง — ก่อนและหลัง `await`** เพราะผู้ใช้อาจกด 🧹 Clear ระหว่างที่ fetch ยังค้างอยู่ ถ้าไม่เช็คซ้ำ response ที่มาถึงทีหลังจะเขียนทับของที่เพิ่งล้าง

> ⚠ **นี่คือตัวที่กินคำขอมากที่สุดต่อรอบ** — 3 คำขอ × ทุก SSE event
> ถ้าจะลดภาระ backend ควรทำเป็น endpoint เดียวที่คืน `{total, ok, ng}` มาทีเดียว
> (`SELECT COUNT(*), SUM(result='OK'), SUM(result='NG')` query เดียวจบ)

---

## สรุปภาระต่อนาที ตอนกำลังวัด 1 เครื่อง 1 แท็บ

| ผู้เรียก | คำขอ/นาที (โดยประมาณ) |
|---|---|
| Pi (ช่วงรอค่า) | ~150 |
| `useSessionState` | ~60 |
| `loadSessionState` | 12 |
| `updateStats` | 36+ (12 รอบ × 3) |
| `Data-receiver` `session_watcher` | 20 |
| **รวม** | **~280 คำขอ/นาที** |

ทุกคำขอเปิด MySQL connection ใหม่ (ไม่มี pool โดยตั้งใจ — ดู `get_db()`) ตัวเลขนี้จึงเป็นเหตุผลที่ `bench_latency.py` มีอยู่

---

# ดัชนี — อยากแก้เรื่องนี้ ไปที่ไหน

| อยากแก้ | ไปที่ |
|---|---|
| แถบคิวเก่าไม่หาย / session ที่จบแล้วยังโผล่ | `session.py:143` (SQL ไม่มี `WHERE`) |
| payload ที่ส่งให้ Pi | `session.py:209` `_build_groups()` |
| เกณฑ์ OK/NG | `shared.py:97-183` (3 ฟังก์ชัน) |
| ให้กลุ่มใช้ Template ต่างกันได้ | `session.py:641` + ฝั่ง Pi ต้องสลับ `PW` ได้ด้วย |
| การจับคู่ ALPL ↔ ผลวัด · transaction | `measurements.py:244-360` (**ไม่ใช่ 2 ไฟล์นี้**) |
| ชิป Pi online/offline | `shared.py:624-694` |
| session หายตอน restart | `shared.py:520` `_reload_session_queues()` |
| เพิ่ม SSE event ใหม่ | `shared.py:442` + `useSSE.ts` `EVENT_NAMES` (**ต้องแก้คู่กัน**) |
| ถังขยะ / ประวัติการแก้ไข | `shared.py:265-386, 1410` |
| SQL ของตาราง/รายงาน | `shared.py:872, 1042, 1109` |

---

# 3 ข้อควรระวังก่อนลงมือแก้

**1 · `session_queues` มีเจ้าของกระจาย 3 ไฟล์ 8 จุด**

```
shared.py:440           ประกาศ
shared.py:520-560       กู้กลับจาก DB ตอน boot
shared.py:602           ลบตอน heartbeat timeout
session.py:693,702      สร้าง + เขียนลง DB ตอน Start
session.py:400,767      ลบตอน Stop
measurements.py:261     อ่านเพื่อหา ALPL
measurements.py:343-346 ขยับ position + เขียนกลับ DB
measurements.py:359     ลบตอนวัดครบ
```

มี **2 ร่างที่ต้องตรงกันตลอดเวลา** — `dict` ใน memory กับคอลัมน์ `queue_state` ใน DB โดยไม่มีใครเป็นเจ้าของการซิงก์ ใครแก้ต้องจำเองว่าต้องเขียนกลับลง DB ด้วย

**2 · `from shared import *` ทำให้หาที่มาของชื่อไม่ได้**

ทุก router ใช้ `from shared import *` ชื่ออย่าง `get_db` `push_event` จึงโผล่มาเฉยๆ โดยไม่มีบรรทัด import บอก — IDE กระโดดไปหานิยามไม่ได้ และเปลี่ยนชื่ออะไรต้องค้นทั้งโปรเจกต์เอง

คำเตือน `⚠ ห้ามประกาศ session_queues ซ้ำในไฟล์นี้` ที่อยู่บนหัวทุก router **มีอยู่เพราะภาษาบังคับให้ไม่ได้** ถ้าเปลี่ยนเป็น import ตรงๆ คำเตือนนั้นจะไม่จำเป็นอีกต่อไป

**3 · คอมเมนต์ในไฟล์นี้เชื่อถือได้สูง แต่ไม่ 100%**

โค้ดชุดนี้เขียนคอมเมนต์อธิบาย *เหตุผล* ไว้ละเอียดมาก และส่วนใหญ่มาจากปัญหาที่เจอจริงหน้างาน — **อ่านก่อนแก้เสมอ** แต่ก็เคยมีที่ตกรุ่น เช่น `CLAUDE.md` ยังเขียนว่า `session_queues` ไม่ persist ทั้งที่ตอนนี้ persist แล้ว

**เชื่อบรรทัดที่รันจริง ไม่ใช่คำอธิบายเหนือมัน — ถ้าสองอย่างขัดกัน นั่นคือบั๊กที่ควรแก้อยู่แล้ว**
