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

## 1.3 กด Start ไม่ติด — เคลียร์ให้สะอาด  ✅ **ทำแล้ว 13 ส.ค. 2569**

> **สรุปสิ่งที่ทำจริง** (ต่างจากแผนเดิมเล็กน้อย — ดูรายละเอียดใต้หัวข้อ)
>
> | เคส | ข้อความ | ส่ง `stop` ตามไป |
> |---|---|---|
> | Pi ตอบ 400/500 | `Pi ปฏิเสธคำสั่ง (HTTP 400): …` | ❌ Pi ไม่ได้เริ่ม |
> | `ConnectError` | `ติดต่อโปรแกรมบนเครื่อง Pi ไม่ได้ …` | ❌ ต่อไม่ติด |
> | `ConnectTimeout` | `หาเครื่อง Pi ไม่เจอที่ …` | ❌ ต่อไม่ติด |
> | `ReadTimeout` | `Pi ไม่ตอบภายใน 10 วินาที …` | ✅ **อาจเริ่มไปแล้ว** |
>
> `ReadTimeout` เป็นเคสเดียวที่ต่อติดและส่ง payload ออกไปแล้ว — Pi อาจรับไป
> และกำลังยิง `T1` อยู่ ถ้าปิด session เงียบๆ จะได้สภาพ "DB บอก stopped แต่ Pi
> ยังวัดต่อ" แล้ววนไปเด้ง modal ถามผู้ใช้ทั้งที่หน้าเว็บบอกว่าไม่มี session แล้ว
>
> `_fail_start()` ทำ 4 อย่าง: เคลียร์ `session_queues` · เคลียร์ `measure_timeouts` ·
> `UPDATE state='stopped'` + `last_event='START_FAILED'` · `raise HTTPException(502)`
>
> **ส่วน Stop ทำตรงข้าม** — `_notify_agent_action()` คืนข้อความ error กลับมาแทน
> การ raise เพราะ DB ปิดไปแล้ว การโยน exception จะทำให้ผู้ใช้เข้าใจว่ากดไม่สำเร็จ
> แล้วกดซ้ำ · `stop_session` เอาข้อความไปบันทึกเป็น `last_event='STOP_NOT_DELIVERED'`
> แล้วแนบไปกับ SSE `session_stopped.agent_error` → หน้าเว็บเด้งเตือนว่า
> **"หยุดในระบบแล้ว แต่สั่งเครื่องไม่สำเร็จ — กรุณาไปกดหยุดที่หน้าเครื่อง"**


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
แล้วให้การ**นับ heartbeat ที่ยิงไม่ออก** (ข้อ 2.1) เป็นตัวไล่ตามเก็บ
ถ้ายังไม่ได้ทำข้อนั้น ผู้ใช้ต้องไปจัดการที่เครื่องเอง ซึ่งข้อความข้างบนบอกไว้แล้ว

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

## 2.1 Pi หยุดเองเมื่อขาดการติดต่อ Backend  ✅ **ทำแล้ว 13 ส.ค. 2569**

> อัปเดต 7 ส.ค. 2569 — **เปลี่ยนจากแผนเดิมที่จะทำ `should_stop`** ดูเหตุผลท้ายหัวข้อ
> อัปเดต 13 ส.ค. 2569 — **เปลี่ยนจาก "นับจำนวนครั้ง" เป็น "จับเวลา"** (ของเดิมคำนวณ
> เวลาผิด ดูหัวข้อย่อยข้างล่าง) และทำลงโค้ดจริงแล้วทั้ง `send_command(Pi).py`
> กับ `mockup.py`

เดิม Pi โยนข้อมูลนี้ทิ้งทั้งหมด

```python
except Exception:
    pass          # ← รู้ว่ายิงไม่ออก แล้วก็ลืมทันที ไม่นับ ไม่ log
```

### ดีไซน์ที่ใช้ — สมมาตร ไม่มีใครสั่งใคร

สองฝั่งใช้กติกาเดียวกันคือ **"เวลาตั้งแต่ heartbeat สำเร็จครั้งล่าสุด > `HEARTBEAT_TIMEOUT`"**
แล้วต่างคนต่างหยุดเอง

| ฝั่ง | ตรวจจาก | ทำอะไร |
|---|---|---|
| Backend (`heartbeat_checker`) | `sessions.last_seen` | `state='timeout'` + ทิ้งคิว + แจ้ง SSE |
| Pi (`heartbeat_loop`) | `_hb_last_ok` | `is_running = False` |

**จงใจไม่ให้ Backend ส่งคำสั่ง stop กลับมา** — ตอนที่ heartbeat ขาด Backend ก็ยิง
`/command` มาหา Pi ไม่ถึงอยู่แล้วด้วยเหตุผลเดียวกัน สั่งไปก็เปล่าประโยชน์

### โค้ดที่ลงจริง (`send_command(Pi).py` — แก้ไฟล์เดียว ไม่แตะ Backend)

```python
_hb_last_ok = time.time()

def heartbeat_loop():
    global is_running, _hb_last_ok
    while True:
        try:
            httpx.post(f"{BACKEND_URL}/api/heartbeat",
                       json={"session_id": current_session_id}, timeout=5)
            _hb_last_ok = time.time()
        except Exception:
            pass                  # ไม่ต้องนับ แค่ "ไม่อัปเดตเวลา" ก็พอ

        # เช็คนอก try เสมอ — ต้องทำงานทุกรอบไม่ว่ารอบนี้จะยิงออกหรือไม่
        if is_running and time.time() - _hb_last_ok > HB_TIMEOUT_HINT:
            print(f"⏹ ติดต่อ Backend ไม่ได้เกิน {HB_TIMEOUT_HINT:g} วิ — หยุดวัด")
            is_running = False    # + บอก MCU ให้หยุดด้วย
        time.sleep(HB_INTERVAL)
```

### ทำไมจับเวลา ไม่นับจำนวนครั้ง

แผนเดิมเขียนไว้ว่า `_hb_fail × HB_INTERVAL > HB_TIMEOUT_HINT` (4 × 5 = 20 วิ > 15 วิ)
**ซึ่งคำนวณเวลาจริงผิด** เพราะรอบที่ยิงไม่ออกแบบ `ConnectTimeout` จะกินเวลา
`timeout=5` ไปก่อน แล้วค่อย `sleep(HB_INTERVAL)` อีก

```
รอบที่ยิงออก    :  0 วิ (แทบทันที) + sleep 5      =  5 วิ/รอบ
รอบที่ยิงไม่ออก  :  5 วิ (รอ timeout) + sleep 5    = 10 วิ/รอบ   ← ตัวปัญหา

_hb_fail ครบ 4 จึงไปเกิดที่ ~40 วิ ไม่ใช่ 20 วิอย่างที่ตั้งใจ
```

จับเวลาตรงๆ ไม่มีปัญหานี้ และเป็น**สูตรเดียวกับที่ Backend ใช้เป๊ะ**
(`last_seen < NOW() - INTERVAL HEARTBEAT_TIMEOUT SECOND`) — อ่านโค้ดสองฝั่งแล้วเทียบกันได้ตรงๆ

### ⚠ กับดักที่ต้องกัน — รีเซ็ต `_hb_last_ok` ตอน Start

`command_flow()` ต้องตั้ง `_hb_last_ok = time.time()` **ก่อน** `is_running = True` เสมอ

```
Pi นั่งว่างอยู่ตอน backend ดับไป 5 นาที → _hb_last_ok ค้างเก่า 5 นาที
backend ฟื้น → กด Start → is_running=True ทันที แต่ heartbeat รอบใหม่ยังไม่ทันยิง
heartbeat_loop ตื่นมาเห็น "ขาดการติดต่อ 5 นาที" → หยุด session ทิ้งทันที
```

ทั้งที่ทุกอย่างปกติดี — บั๊กนี้เจอยากมากเพราะต้องให้ backend ดับนานพอก่อนกด Start

### เวลาจริงที่ทั้งสองฝั่งตัดสิน (จำลองแล้ว 13 ส.ค. 2569)

```
Backend : 15-20 วิ    last_seen เกิน 15 วิ + checker ตื่นทุก 5 วิ

Pi      : 15-20 วิ    ถ้า POST เด้ง error ทันที
                      (สายหลุดที่ Pi เอง → "network unreachable" ไม่ต้องรอ)
        : 20-25 วิ    ถ้า POST ค้างจนครบ timeout=5 วิ
                      (switch ดับ / PC ดับ → SYN ไม่มีคนตอบ ต้องรอเต็มเวลา)
```

**Backend ตัดสินก่อน Pi เสมอ ซึ่งเป็นลำดับที่ถูกต้อง** — Backend ปิด session
แล้วแจ้งหน้าเว็บก่อน จากนั้น Pi ค่อยหยุดตาม ไม่มีจังหวะที่ Pi หยุดไปแล้วแต่หน้าเว็บ
ยังขึ้น RUNNING อยู่

ช่วง 20-25 วิเกิดจากรอบที่ยิงไม่ออกกินเวลา `timeout=5` ไปก่อนแล้วค่อย `sleep(5)`
= 10 วิ/รอบ (ตัวเดียวกับที่ทำให้วิธี "นับจำนวนครั้ง" เพี้ยน แต่แบบจับเวลาเพี้ยนน้อยกว่ามาก
เพราะเทียบกับนาฬิกาจริง ไม่ใช่สมมติว่าทุกรอบยาว 5 วิ)

### สิ่งที่ดีไซน์นี้ยังไม่ครอบคลุม

เคสที่ **Backend ตอบได้ปกติแต่ session ตายไปแล้ว** เช่นเน็ตกระตุก ~17 วิแล้วกลับมา —
Backend mark `timeout` ไปแล้ว ส่วน Pi ยิงผ่านบ้างไม่ผ่านบ้างจนนาฬิกาไม่ถึงเกณฑ์ →
Pi วัดต่อ ค่าที่ POST เข้ามาโดน `create_measurement` ตอบ `409` ทิ้งเงียบๆ
(ข้อมูลไม่เพี้ยน แต่เสียชิ้นงานกับเวลาฟรี)

อันนี้คือช่องที่ `should_stop` จะปิดให้ — **ตัดสินใจยังไม่ทำ** รอดูว่าเกิดจริงไหม

`HB_TIMEOUT_HINT` มีอยู่ในโค้ดแล้ว (`send_command(Pi).py:67`) แต่ตอนนี้ใช้แค่พิมพ์ข้อความเตือน
ยังไม่ได้เอามาบังคับใช้จริง

### ❌ ทำไมถึงไม่ทำ `should_stop`

แผนเดิมคือให้ `POST /api/heartbeat` ตอบ `{"ok": true, "should_stop": true}` เมื่อ session
ไม่ได้อยู่ในสถานะ `running` แล้ว — **แต่บนสาย LAN นิ่งๆ มันเหลืองานแค่เคสเดียว**

| เคส | เกิดได้บน LAN ไหม |
|---|---|
| กด Stop แล้วคำสั่งไม่ถึง Pi | สาย LAN ดี = `/command` ถึงแน่นอน → แทบไม่เกิด |
| Start ได้ `ReadTimeout` แต่ Pi เริ่มไปแล้ว | ต้องให้ Pi ค้างเอง ไม่ใช่เรื่องเน็ต → หายาก |
| **สายหลุดแล้วเสียบกลับ** | เคสเดียวที่เหลือ — **นาฬิกาของ Pi ครอบคลุมอยู่แล้ว** |

```
สายหลุด   → Pi ยิงไม่ออก → _hb_last_ok เก่าเกิน 15 วิ → Pi หยุดเอง
เสียบกลับ → Pi หยุดไปแล้ว ไม่มีอะไรให้สั่งหยุดอีก
```

แลกกับการต้องแก้ 2 ไฟล์แทนที่จะเป็น 1 จึง **ไม่คุ้ม** สำหรับสภาพหน้างานนี้

> **ข้อมูลเพิ่ม 13 ส.ค. 2569** — ต้นทุนฝั่ง Backend ถูกกว่าที่ประเมินไว้ตอนแรก
> เพราะ `heartbeat()` มี `WHERE ... AND state = 'running'` อยู่แล้ว (`main.py:1662`)
> แค่ `SELECT state` ต่ออีกตัวก็ได้คำตอบ ไม่ต้อง query ใหม่ทั้งชุด
>
> แต่**ยังคงตัดสินใจไม่ทำ** เพราะช่องที่เหลือ (เน็ตกระตุก 15-20 วิ) แคบ และ
> ความเสียหายคือ "เสียชิ้นงานฟรี" ไม่ใช่ข้อมูลเพี้ยน — `409` ใน `create_measurement`
> กันไว้ให้แล้ว · ถ้าหน้างานเจอเคสนี้จริงค่อยกลับมาเปิดข้อนี้
>
> ⚠ ถ้าจะทำจริง **ห้ามใช้ `cur.rowcount` แทน `SELECT`** — MySQL นับ affected rows
> จาก "แถวที่ค่าเปลี่ยนจริง" ถ้า `last_seen` บังเอิญเท่ากับ `NOW()` อยู่แล้ว
> (เช่นเผลอรัน `mockup.py` ค้างไว้พร้อมกับ Pi จริง ยิงมาในวินาทีเดียวกัน)
> จะได้ `rowcount = 0` ทั้งที่ session ยัง running → Pi หยุดกลางคันโดยไม่มีสาเหตุ

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
