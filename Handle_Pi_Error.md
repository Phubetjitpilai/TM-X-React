# Handle_Pi_Error — จัดการกรณีคำสั่งจาก Backend ไปไม่ถึง Pi

> ตกลงกัน 7 ส.ค. 2569 · แยกจาก `PLAN_criteria_and_multigroup.md` เพราะทำได้ทันที
> ไม่ต้องรอ schema / `GM` / ฟอร์มหลายกลุ่ม

---

## ปัญหาที่แก้

ตอนนี้ทุกความผิดพลาดบนเส้น **Backend → Pi** เงียบสนิท

```python
except Exception as exc:
    log.warning("Agent start notify failed: %s", exc)     # main.py:667
```

ผู้ใช้ไม่เห็นอะไรเลย หน้าเว็บขึ้นว่าเริ่มวัดแล้วตามปกติ แล้วอีก ~15 วิถึงพลิกเป็น
`timeout` ซึ่ง**ชี้ผิดสาเหตุ** — คำว่า timeout แปลว่า "Pi ตายไปแล้ว" ทั้งที่ความจริง
อาจเป็นแค่ IP ผิดหรือข้อมูลที่กรอกไม่ผ่าน ผู้ใช้จะไปไล่หาสาย LAN แทนที่จะดูข้อมูลที่กรอก

**เป้าหมายไม่ใช่ "จัดการทุก error ให้ครบ" แต่คือ "อย่าให้ระบบโกหก"**
ระบบที่พังแล้วบอกว่าพัง ดีบั๊กได้เสมอ ต่อให้ error handling ไม่สวย

---

## พื้นฐานที่ต้องเข้าใจก่อน — ทำไมแยกสาเหตุได้

HTTP **ไม่ใช่ทางเลือกแทน TCP** แต่ **วิ่งอยู่บน TCP** เหมือนรถเมล์วิ่งบนถนน

```
เส้นทาง               ชั้นบน        ชั้นล่าง
─────────────────────────────────────────────
Frontend ↔ Backend    SSE  →  HTTP  →  TCP
Backend  ↔ Pi                 HTTP  →  TCP      ← เอกสารนี้พูดถึงเส้นนี้
Pi       ↔ TM-X                        TCP      ← ไม่มีชั้นบนเลย (KEYENCE ออกแบบเอง)
TM-X     → PC                 FTP   →  TCP
```

ตอน Backend ยิง `POST /command` สิ่งที่เกิดขึ้นจริงมี 4 ขั้น

```
① เปิด TCP ไปที่ <AGENT_HOST>:<AGENT_PORT>       (handshake)
② ส่งไบต์ HTTP request ลงบนสายที่เพิ่งเปิด
③ รอไบต์ HTTP response กลับมาบนสายเดิม
④ อ่าน status code
```

**แต่ละกรณีพังคนละขั้น `httpx` จึงโยน exception คนละคลาสให้** ไม่ใช่ "ไม่ตอบ"
เหมือนกันหมดอย่างที่ดูเผินๆ

| พังขั้นไหน | `httpx` โยน | เกิดเร็วแค่ไหน | แปลว่า |
|---|---|---|---|
| ① ไม่มีใครฟังพอร์ตนั้น | `ConnectError` | **ทันที** (โดน RST) | เครื่องอยู่ แต่สคริปต์ไม่ได้รัน |
| ① ไม่มีใครอยู่ที่ IP นั้น | `ConnectTimeout` | ครบ connect timeout | IP ผิด / เครื่องดับ / สายหลุด |
| ③ ต่อติดแล้วแต่เงียบ | `ReadTimeout` | ครบ read timeout | Pi มีชีวิต แต่ค้าง |
| ④ ตอบกลับมาแล้ว | **ไม่ throw** | ทันที | ดู `resp.status_code` เอา |

"เปิด TCP ได้" มีความหมายชัดเจนมาก — แปลว่ามีโปรเซสเปิดฟังพอร์ตนั้นอยู่จริงและ
OS ตอบรับแล้ว **คนละเรื่องกับ "ต่อไม่ติดเลย"**

---

# ส่วนที่ 1 — ทำเลย (จำเป็น)

## 1.1 ตัด Pause / Resume ออกทั้งระบบ

**เหตุผล: ตอนนี้มันโกหก** `send_command.py` ไม่เคยรองรับ `pause` เลย

```python
Backend: UPDATE state='paused' → POST /command {"action":"pause"}
Pi:      if start ... elif stop ...        ← ไม่ตรงสักอัน
         return {"status":"ok"}            ← ตอบ ok ทั้งที่ไม่ได้ทำอะไร
```

**หน้าเว็บขึ้น paused แต่เครื่องยังวัดต่อ** และค่าที่วัดได้ยังถูกบันทึกลง DB ปกติ
เพราะ `create_measurement` ไม่เช็ค state ของ session

> ไม่เคยเจอตอนเทสต์เพราะ `mockup.py` รองรับ pause/resume ครบ — เจอเฉพาะกับเครื่องจริง

เป็นข้อเดียวในเอกสารนี้ที่ **ลบโค้ดออก ไม่ได้เพิ่ม**

### จุดที่ต้องแก้ใน `main.py` — 8 จุด

| บรรทัด | แก้อะไร |
|---|---|
| `1059-1085` | ลบ `/api/session/pause` ทั้งก้อน |
| `1087-1113` | ลบ `/api/session/resume` ทั้งก้อน |
| `1046-1056` | ลบ `_notify_agent()` (เหลือแต่ `_notify_agent_start`) |
| `386` | restore queue ตอน startup → `state = 'running'` |
| `754` | เช็ค session ซ้อนก่อน Start → `state = 'running'` |
| `1143` | heartbeat UPDATE → `state = 'running'` |
| `1697` | `_block_if_session_running` → `state = 'running'` |
| `1137-1140` | ลบคอมเมนต์เรื่อง "รับ heartbeat ตอน paused" |

### ที่อื่น

- `mysql-init/init.sql` — เอา `paused` ออกจาก state เหลือ `idle`/`running`/`stopped`/`timeout`
- `Frontend/index.html` — ลบปุ่ม Pause + handler ของ SSE `session_paused` / `session_resumed`
- `Backend-pc_station/mockup.py` — ลบ pause/resume จะได้ไม่หลงเทสต์ฟีเจอร์ที่ไม่มีแล้ว
- `CLAUDE.md` — Known Issues ข้อ "`send_command.py` ไม่รองรับ pause/resume" ตกไป

### ผลพลอยได้

ตรรกะ state เหลือ 4 ค่า และ `heartbeat_checker` ไม่ต้องมีข้อยกเว้นเรื่อง paused อีก

## 1.2 Pi ต้องปฏิเสธ action ที่ไม่รู้จัก

`send_command(Pi).py:482` — ตอนนี้ตกท้ายไปที่ `return {"status": "ok"}` เสมอ

```python
@http_app.post("/command")
async def command(req: CommandRequest):
    if req.action == "start":
        ...
    elif req.action == "stop":
        ...
    else:
        raise HTTPException(400, f"ไม่รู้จัก action '{req.action}'")   # ← เพิ่ม
    return {"status": "ok", "action": req.action}
```

บรรทัดเดียว เปลี่ยน "โกหกเงียบๆ" เป็น popup ที่บอกความจริง — และกันไม่ให้เกิดเรื่อง
แบบ Pause ซ้ำอีกในอนาคตเวลามีใครเพิ่ม action ใหม่ฝั่ง backend แล้วลืมทำฝั่ง Pi

## 1.3 กด Start ไม่ติด — เคลียร์ให้สะอาด

ตอนที่ `_notify_agent_start()` (`main.py:632`) พัง สถานะที่ค้างอยู่คือ
DB มี session `running` · `session_queues` มีคิวในหน่วยความจำ · `queue_state` เขียนลง DB แล้ว

```python
async def _notify_agent_start(session_id, ...) -> None:
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(f"{AGENT_BASE_URL}/command", json={...},
                                     timeout=httpx.Timeout(connect=3.0, read=10.0))
        if resp.status_code != 200:
            _fail_start(session_id, f"Pi ปฏิเสธคำสั่ง: {resp.text}")
    except Exception as exc:
        _fail_start(session_id, f"สั่งงาน Pi ไม่สำเร็จ: {exc}")


def _fail_start(session_id: int, msg: str):
    session_queues.pop(session_id, None)                       # ①
    # UPDATE sessions SET state='stopped' WHERE session_id=%s   ②
    raise HTTPException(502, msg)                              # ③
```

**① `session_queues.pop()` — ลืมง่ายที่สุด** เป็น dict ในหน่วยความจำล้วนๆ
ไม่มีใครมาเก็บกวาดให้ กด Start ไม่ติด 20 ครั้งก็ค้าง 20 คิว

**② อย่าทิ้ง `running` ไว้** ไม่งั้นต้องรอ `heartbeat_checker` มาเก็บกวาดใน 15 วิ
แล้วขึ้นเป็น `timeout` ซึ่งชี้ผิดสาเหตุ

**③ ต้อง `raise` ก่อนบรรทัด `push_event("session_started", ...)`** (`main.py:860`)
ไม่งั้นหน้าเว็บทุกเครื่องจะเข้าโหมดวัดพร้อมกันทั้งที่ไม่มีอะไรเกิดขึ้น
และการ `raise` ทำให้ `fetch` ฝั่งเว็บพัง → UI แสดง popup แทนที่จะแสดงหน้าจอวัดงานปลอมๆ

### ทำไม `timeout` ต้องแยก 2 ค่า

`timeout=10` ตัวเดียวแบบตอนนี้ใช้ร่วมกันทุกขั้น — กรณี IP ผิดจะกินไป 10 วิเต็ม
ทั้งที่รู้ผลได้ตั้งแต่ 3 วิ `connect` สั้นได้เพราะอยู่วง LAN เดียวกัน (ปกติต่อติดใน ~10 ms)
ส่วน `read` ต้องเผื่อให้ Pi ประมวลผล

### อาการที่ผู้ใช้เห็น

```
Pi ปกติ      กด Start → เสร็จใน < 0.5 วิ
Pi ไม่ตอบ    กด Start → ค้าง 3 หรือ 10 วิ → popup บอกสาเหตุ
```

ถ้ารู้สึกว่ากด Start แล้วค้าง **ให้จับเวลา** — ~3 วิ = หา Pi ไม่เจอ · ~10 วิ = Pi ค้าง
· ต่ำกว่านั้นและไม่มี popup = ไม่ใช่เรื่อง Pi (น่าจะเป็น DB)

## 1.4 กด Stop ไม่ติด — **อันตรายกว่า Start มาก**

```
Start ไม่ติด → ไม่มีอะไรเกิดขึ้น
Stop  ไม่ติด → เครื่องยังเดินอยู่ ยังยิง T1 ยังส่งค่าเข้ามา
               ทั้งที่ DB บอกว่า stopped ไปแล้ว (backend UPDATE ก่อนแจ้ง Pi)
```

**ข้อความต้องคนละเรื่องกับ Start — ห้ามขึ้นว่า "หยุดแล้ว"**

```
⚠️ สั่งหยุดไม่ถึงเครื่อง — เครื่องอาจยังวัดอยู่
   ระบบทำเครื่องหมายว่าหยุดแล้ว แต่ยืนยันกับ Pi ไม่ได้
   ให้ไปตรวจที่หน้าเครื่อง หรือปิด send_command.py บน Pi
```

**ไม่ต้อง rollback state กลับเป็น `running`** — ปล่อยเป็น `stopped` ตามเดิม
แล้วให้ `should_stop` (ข้อ 2.1) เป็นตัวไล่ตามเก็บ ถ้ายังไม่ได้ทำข้อนั้น ผู้ใช้ต้อง
ไปจัดการที่เครื่องเอง ซึ่งข้อความข้างบนบอกไว้แล้ว

## 1.5 ล็อก Export ตอนกำลังวัด

`_block_if_session_running()` (`main.py:1685`) ถูกเรียกแค่ 5 จุด — ล้วนเป็นการ
**เขียน** ทั้งหมด

```
update_part · delete_part · update_measurement · delete_measurement · restore_deleted
```

**Export ไม่มีใครกันเลย** ทั้ง backend และหน้าเว็บ

```python
_block_if_session_running(cur, "Export")
```

ใส่ใน `export_csv` (`:3677`) · `export_xlsx` (`:3788`) · `export_report_preview` (`:3756`)

### ทำไมถึงคุ้ม

`main.py` ใช้ **pymysql (sync) ข้างใน `async def`** — endpoint ที่เป็น `async def`
แต่ไม่มี `await` เลยมีถึง **56 ตัว** ทั้งหมดบล็อก event loop ระหว่างทำงาน

ตัวที่หนักพอจะเป็นปัญหาจริงมีแค่ export (เพดาน `REPORT_MAX_ROWS` = 20,000 แถว)

```
มีคนกด Export XLSX ระหว่างวัด ใช้ 20 วิ
   → event loop ค้าง → heartbeat ของ Pi เข้าไม่ได้ 4 รอบติด
   → loop คลาย → checker เห็น last_seen เก่า 20 วิ
   → session ที่วัดอยู่ดีๆ กลายเป็น timeout ทั้งที่ Pi ปกติทุกอย่าง
```

ล็อก Export 3 บรรทัดปิดช่องนี้ได้หมด **ไม่ต้องไปแก้ 56 endpoint**

> Export ทำไว้ให้ช่างหน้าเครื่องใช้เท่านั้น การล็อกระหว่างวัดจึงไม่กระทบใคร

---

# ส่วนที่ 2 — ไว้ทีหลัง (ยังไม่เคยเกิดจริง)

> ทำเมื่อเจอปัญหาจริง อย่าทำล่วงหน้า

## 2.1 heartbeat สั่งให้ Pi หยุด (`should_stop`)

**ปิดได้ 3 เคสพร้อมกันด้วยกลไกเดียว**

```
① กด Stop แล้วคำสั่งไปไม่ถึง Pi        → Pi วัดต่อ
② Start ได้ ReadTimeout แต่ Pi เริ่มไปแล้ว → Pi วัดต่อโดย DB บอก stopped
③ heartbeat_checker mark timeout ไปแล้ว   → Pi ไม่รู้เรื่อง วัดต่อ
```

ข้อมูลมีอยู่แล้ว แค่ตอนนี้ทิ้งไปเฉยๆ — `heartbeat()` ตอบ `{"ok": True}` เสมอ

**ฝั่ง Backend** (`main.py:1121`)

```python
@app.post("/api/heartbeat")
async def heartbeat(req: HeartbeatRequest):
    if req.session_id is None:
        return {"ok": True}
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute("SELECT state FROM sessions WHERE session_id=%s", (req.session_id,))
            row = cur.fetchone()
            if row is None or row["state"] != "running":
                return {"ok": True, "should_stop": True}        # ← ของใหม่
            cur.execute("UPDATE sessions SET last_seen=NOW() WHERE session_id=%s",
                        (req.session_id,))
    finally:
        db.close()
    return {"ok": True}
```

**ฝั่ง Pi** — `heartbeat_loop()` อ่าน response ที่เมื่อก่อนโยนทิ้ง

```python
r = httpx.post(f"{BACKEND_URL}/api/heartbeat",
               json={"session_id": current_session_id}, timeout=5)
if r.json().get("should_stop") and is_running:
    print("⏹ backend แจ้งว่า session นี้ปิดไปแล้ว — หยุดวัด")
    is_running = False        # ลูปหลุดเอง → finally ส่ง S0 + ปิด socket
```

ตั้ง `is_running = False` จาก thread อื่นเป็น pattern เดียวกับที่ handler ของ `stop`
ทำอยู่แล้ว ไม่มีอะไรใหม่ และปิดช่องได้ภายใน 5 วิโดยไม่ต้องเพิ่มช่องทางสื่อสารใหม่เลย

> ⚠️ **ห้ามใช้ `cur.rowcount` ของ `UPDATE` เดิมมาตัดสินแทน `SELECT`**
> pymysql คืนจำนวนแถวที่ **เปลี่ยนจริง** ไม่ใช่แถวที่ match — ถ้า heartbeat 2 ครั้ง
> มาในวินาทีเดียวกัน `NOW()` ได้ค่าเท่าเดิม MySQL คืน `0` แล้ว Pi จะโดนสั่งหยุด
> ทั้งที่ session ปกติดี

## 2.2 แยกข้อความ error เป็น 3 แบบ

ข้อ 1.3 ใช้ `except Exception` ก้อนเดียวแล้วโชว์ `{exc}` ซึ่งพอใช้ได้ เพราะข้อความ
ของ exception บอกอยู่แล้วว่าเป็น `ConnectError` หรือ `ReadTimeout`

ถ้าอยากให้ข้อความอ่านง่ายขึ้นสำหรับผู้ใช้ทั่วไปค่อยแยกทีหลัง

```python
except httpx.ConnectError:      # ⚠ ต้องมาก่อน — คนละสายกับ TimeoutException
    "ติดต่อเครื่อง Pi ไม่ได้ ({AGENT_HOST}:{AGENT_PORT})\n"
    "ตรวจ: send_command.py รันอยู่ไหม · สาย LAN · IP ของ Pi เปลี่ยนหรือเปล่า"
except httpx.ConnectTimeout:    # ⚠ ต้องมาก่อน TimeoutException (เป็นลูกของมัน)
    "หาเครื่อง Pi ไม่เจอที่ {AGENT_HOST} — ตรวจ IP หรือสาย LAN"
except httpx.TimeoutException:  # เหลือแค่ ReadTimeout
    "Pi ไม่ตอบภายใน 10 วินาที — อาจติดคำสั่งเดิมค้างอยู่ ลองรีสตาร์ท send_command.py"
```

**ลำดับ `except` สำคัญ** — `ConnectTimeout` เป็นลูกของ `TimeoutException`
ถ้าเขียน `except httpx.TimeoutException` ไว้บนสุดจะกลืน `ConnectTimeout` ไปด้วย
แล้วข้อความจะบอกว่า "Pi ค้าง" ทั้งที่จริงคือ "หา Pi ไม่เจอ" — ชี้ผิดทางเลย

## 2.3 เปลี่ยน `async def` → `def`

ถ้าล็อก Export แล้ว (ข้อ 1.5) ยังเจอ session ตายเองโดยไม่มีสาเหตุ ค่อยกลับมาดูข้อนี้

FastAPI รัน endpoint ที่เป็น `def` ธรรมดา **ใน threadpool แยก** event loop จึงว่าง
รับ request อื่นต่อได้ ทั้ง 56 ตัวไม่มี `await` อยู่แล้ว จึงเปลี่ยนได้ตรงๆ ไม่ต้อง
แก้อะไรข้างใน

```python
async def export_xlsx(...):     →     def export_xlsx(...):
```

## 2.4 `create_measurement` ปฏิเสธ session ที่ไม่ได้ running

ค่าที่ TM-X ส่งมาช้าหลังกด Stop ยังถูกบันทึกลง DB อยู่ (Known Issue เดิมใน `CLAUDE.md`)

---

# ภาคผนวก — heartbeat timeout ทำงานยังไง

`heartbeat_checker()` (`main.py:405`) วนทุก `HEARTBEAT_INTERVAL` (5 วิ)
เจอ session ที่ `state='running'` แต่ `last_seen` เก่ากว่า `HEARTBEAT_TIMEOUT` (15 วิ)
แล้วทำ 5 อย่าง

```python
UPDATE sessions SET state='timeout', ended_at=NOW()   # ① ปิด session
session_queues.pop(sid)                                # ② ทิ้งคิว — กู้ไม่ได้
measure_timeouts.pop(sid)                              # ③ ทิ้งคำถามที่ค้างอยู่
log.warning(...)                                       # ④
await push_event("session_timeout", {...})             # ⑤ แจ้งทุกหน้าเว็บ
```

**เวลาจริงคือ 15-20 วิ ไม่ใช่ 15 เป๊ะ** เพราะ checker ตื่นทุก 5 วิ

**ข้อ ② กู้ไม่ได้** — `_reload_session_queues()` ตอน server บูตกู้เฉพาะ session ที่
`state='running'` ตัวที่เป็น `timeout` แล้วไม่ถูกกู้ ถ้า Pi ฟื้นกลับมาแล้ว POST ค่าเข้ามา
`create_measurement` จะหา `session_queues` ไม่เจอ → ตอบ `409` ทิ้งค่านั้นไป
(**ค่าถูกทิ้งดีกว่าถูกแปะผิด ALPL** — `409` ตัวนั้นใส่ไว้เพื่อกรณีนี้โดยเฉพาะ)

ALPL ที่วัดไปแล้วก่อน timeout อยู่ใน DB ครบ ส่วนที่เหลือในคิวหายไป ต้องกด Start ใหม่

## สาเหตุที่ heartbeat ขาดได้จริง (ทุกเครื่องอยู่บน LAN เดียวกัน ไม่มีอินเทอร์เน็ตเกี่ยว)

| สาเหตุ | ควรทำยังไง |
|---|---|
| สาย LAN หลุด / switch ดับ | **timeout ทำงานถูกแล้ว** ไม่ใช่บั๊ก |
| Pi ค้าง / SD พัง | **timeout ทำงานถูกแล้ว** |
| IP เปลี่ยน (DHCP) | ตั้ง static IP หรือ DHCP reservation ให้ทั้ง PC และ Pi |
| Backend รีสตาร์ท (`--reload`) | อย่าใช้ `--reload` ตอนใช้งานจริง |
| **Backend บล็อก event loop** | **ล็อก Export (ข้อ 1.5)** |

---

# ลำดับการทำ

| # | งาน | ขนาด |
|---|---|---|
| 1 | ตัด Pause / Resume (1.1) | ลบโค้ด |
| 2 | Pi ปฏิเสธ action ที่ไม่รู้จัก (1.2) | 1 บรรทัด |
| 3 | ล็อก Export (1.5) | 3 บรรทัด |
| 4 | Start ไม่ติด — เคลียร์ + popup (1.3) | ~15 บรรทัด |
| 5 | Stop ไม่ติด — ข้อความเตือน (1.4) | ~5 บรรทัด |
| — | **ส่วนที่ 2 รอไว้ก่อน** | |

ข้อ 1-3 ทำได้ภายในไม่กี่นาทีและปิดเคส "ระบบโกหก" ไปแล้วครึ่งหนึ่ง
