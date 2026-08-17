"""routers/session.py — คุมรอบการวัด · คุยกับ Pi และ Recieve_tm-x · SSE ไปหาเบราว์เซอร์

ย้ายมาจาก main.py แบบยกก้อน ไม่ได้แก้ตรรกะใดๆ
⚠ ห้ามประกาศ session_queues / measure_timeouts / subscribers ซ้ำในไฟล์นี้
  ต้องดึงจาก shared.py เท่านั้น ไม่งั้นจะกลายเป็นคนละ object โดยไม่มี error
"""
from fastapi import APIRouter

from shared import *  # noqa: F401,F403

router = APIRouter()


# ══════════════════════════════════════════════════════════════════════════════
# SSE Stream
# ══════════════════════════════════════════════════════════════════════════════
@router.get("/api/stream")
async def sse_stream(request: Request):
    """Endpoint SSE ที่ dashboard เชื่อมต่อเข้ามาเพื่อรับข้อมูล real-time

    ทำไม: แทนที่ frontend จะ poll backend ทุกวินาที มันเปิด connection ค้างไว้ทีเดียว
    ที่นี่ แล้วเรา push event ไปให้ตอนมันเกิดขึ้นจริง (ดู push_event) แต่ละ client
    จะมี queue ของตัวเองที่ลงทะเบียนใน `subscribers` เราจะ yield "ping" ทุก 25 วินาที
    ตอนไม่มีอะไรใหม่ แค่เพื่อ keep connection ไว้ไม่ให้ proxy/browser ตัดการเชื่อมต่อ
    ที่ idle อยู่ SSE เป็นทางเดียว (server → client เท่านั้น) — ฝั่ง frontend ยังใช้
    POST request ปกติในการส่งคำสั่งไปที่ backend
    """
    async def generator():
        queue: asyncio.Queue = asyncio.Queue()
        subscribers.append(queue)
        log.info("SSE client connected  (total=%d)", len(subscribers))
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=25)
                    yield event
                except asyncio.TimeoutError:
                    yield {"event": "ping", "data": ""}
        finally:
            if queue in subscribers:
                subscribers.remove(queue)
            log.info("SSE client disconnected (total=%d)", len(subscribers))

    return EventSourceResponse(generator())

@router.get("/api/config")
def get_ui_config():
    """ค่าจาก .env ที่ฝั่งหน้าเว็บต้องใช้ — เบราว์เซอร์อ่านไฟล์ .env เองไม่ได้

    หน้าเว็บเรียกครั้งเดียวตอนโหลด แล้วเอาไปตั้ง setInterval ของ pollSessionState
    ถ้าเรียกไม่สำเร็จให้ใช้ค่า default ฝั่ง JS ไปก่อน (หน้าเว็บต้องทำงานได้เสมอ
    แม้ endpoint นี้ล่ม — มันเป็นแค่การปรับจูน ไม่ใช่ข้อมูลที่ขาดไม่ได้)

    ไม่แตะ DB เลย จึงไม่มีทางตอบ 503 เหมือน endpoint อื่น

    ⚠ ห้ามใส่ความลับ (รหัส DB / path ภายในเครื่อง) ลงใน response นี้เด็ดขาด —
      ใครเปิดหน้าเว็บได้ก็เรียกได้ และตอนนี้ระบบยังไม่มี auth เลย
    """
    return {
        # ส่งเป็น ms ให้ตรงกับหน่วยที่ setInterval ใช้ จะได้ไม่ต้องคูณฝั่ง JS
        # แล้วเผลอลืมจนกลายเป็น poll ทุก 2 ms
        "poll_interval_ms": int(UI_POLL_INTERVAL * 1000),
        # ส่งไปด้วยเพื่อให้หน้าเว็บอธิบายผู้ใช้ได้ว่า "เงียบเกินกี่วิถึงนับว่าออฟไลน์"
        "heartbeat_timeout": HEARTBEAT_TIMEOUT,
    }


@router.get("/api/session/state")
def get_session_state():
    """คืนสถานะปัจจุบันของ session ล่าสุด

    ทำไม: ตอน dashboard โหลดครั้งแรก (หรือ refresh) มันต้องรู้ว่า "มี run การวัด
    กำลังทำงานอยู่ไหม" ก่อนที่ SSE connection จะเปิดเสียอีก นี่คือ snapshot
    แบบครั้งเดียวที่ใช้ sync ตอนเริ่ม หลังจากนั้น SSE event จะคอยอัปเดตให้ real-time

    ── pi_status ────────────────────────────────────────────────────────────
    แนบสถานะ Pi มากับ response นี้ด้วย **แทนที่จะทำ SSE event หรือ endpoint ใหม่**
    เพราะหน้าเว็บ poll เส้นนี้ทุก 5 วิอยู่แล้ว (setInterval(pollSessionState, 5000)
    ใน index.html) จึงได้ชิปที่อัปเดตสดโดยไม่เพิ่ม request สักตัว และจังหวะลงตัว
    พอดี — Pi ยิง heartbeat ทุก 5 วิ · หน้าเว็บ poll ทุก 5 วิ · เกณฑ์ 15 วิ
    ผลคือ Pi ตายแล้วชิปเปลี่ยนภายใน 15-20 วิ ซึ่งพร้อมกับที่ session ขึ้น timeout

    ค่าที่เป็นไปได้มี 3 อย่าง ไม่ใช่ 2:
        true  = ได้ heartbeat ภายใน HEARTBEAT_TIMEOUT
        false = เงียบเกินเกณฑ์แล้ว
        null  = **ไม่ทราบ** (อ่านตารางไม่ได้ / ยังไม่ได้ migrate)
    หน้าเว็บต้องแยก null ออกจาก false ห้ามยุบรวม ไม่งั้นจะกลายเป็นบอกว่า
    "Pi ตาย" ทั้งที่จริงคือ "เราไม่รู้" — คนละเรื่องกันตอนไล่หาสาเหตุ

    ⚠ ต้องใส่ pi_status ให้ **ทั้ง 2 ทางออก** ของฟังก์ชันนี้ (มี session กับ
      ไม่มี session เลย) ไม่งั้น DB ที่ยังไม่เคยมี session จะไม่มีคีย์นี้ →
      หน้าเว็บได้ undefined → ชิปเพี้ยนแบบเงียบๆ
    """
    pi_status = read_pi_status()   # อ่านนอก try ของ sessions — ล้มเหลวได้โดยไม่ลากทั้ง endpoint

    db = get_db()
    try:
        with db.cursor() as cur:
            # queue_state แนบไปด้วย — frontend ใช้วาดแถบคิว ALPL ใน Live Telemetry
            # (ต้องได้คิวเต็มไม่ใช่แค่ ALPL ตัวแรก) และทำให้แถบนี้รอดการ refresh
            # หน้าเว็บกลาง session ด้วย เพราะอ่านคิวกลับจาก DB ได้ตรงๆ
            cur.execute(
                "SELECT session_id, state, target_count, measured_count, "
                "queue_state, last_seen, started_at, ended_at "
                "FROM sessions ORDER BY session_id DESC LIMIT 1"
            )
            row = cur.fetchone()
        if row:
            row["pi_status"] = pi_status
            return row
        return {"state": "idle", "pi_status": pi_status}
    finally:
        db.close()

def _limits_of(row, measure_type: str) -> Dict[str, Any]:
    """แปลง nominal/tolerance เป็น "ขอบเขตสำเร็จรูป" ที่ Pi เอาไปเทียบตรงๆ

    **ส่งขอบ ไม่ส่ง nominal/tol ดิบ** — จำนวนตัวเลขเท่ากัน (4 ตัว) แต่ Pi ไม่ต้อง
    ลอก `_TOL_EPS` มาไว้ที่ตัวเอง ถ้าลืมเมื่อไหร่จะตัดสินไม่ตรงกับ backend
    **เฉพาะชิ้นที่ตกขอบพอดี** ซึ่งเป็นชิ้นที่สำคัญที่สุดและหาสาเหตุยากที่สุด
    (คอลัมน์เป็น FLOAT — `5.02` อ่านกลับได้ `5.0199999809265137`)

    ห้ามปัดเศษให้สวย ต้องเป็นตัวเลขชุดเดียวกับที่ `_within_tolerance` ใช้เป๊ะ

    `offset_max: null` = ไม่ต้องตรวจข้อนี้ — **ไม่ส่ง `measure_type` ไปด้วย**
    เพราะจะเปิดช่องให้มีคนเขียน `if measure_type == "IPM"` ที่ฝั่ง Pi แล้วกฎ
    เรื่องโหมดจะไปอยู่ 2 ที่ (`_offset_limit` ที่นี่ควรเป็นที่เดียว)
    """
    return {
        "x_lo": row["nominal_x"] - row["lower_tol"] - _TOL_EPS,
        "x_hi": row["nominal_x"] + row["upper_tol"] + _TOL_EPS,
        "y_lo": row["nominal_y"] - row["lower_tol"] - _TOL_EPS,
        "y_hi": row["nominal_y"] + row["upper_tol"] + _TOL_EPS,
        "offset_max": _offset_limit(measure_type, row),
    }

def _criteria_from_config(cur, gi: int, group: Dict[str, Any], entry_mode: str):
    """เกณฑ์ของกลุ่ม — อ่านจาก **config ที่ผู้ใช้กรอก** ไม่ใช่จากแถว Part

    จำเป็นต้องเป็นแบบนี้เพราะตอนกด Start ยังไม่มีแถว Part ให้ query เลยในโหมด
    New (Part ถูกสร้างพร้อม measurement ของชิ้นนั้น — ดู `create_measurement`)
    และโหมด IPM ก็มี ALPL บางตัวที่ยังไม่ลงทะเบียน

    ใช้ตารางเดียวกับ `_load_criteria` ตามโหมด (IPM → `package_size`,
    New/Rework → `part_number`) ค่าที่ได้จึงตรงกับที่ backend จะใช้ตัดสินจริง
    ตอน measurement เข้ามา
    """
    if entry_mode == "IPM":
        cur.execute(
            "SELECT nominal_x, nominal_y, upper_tol, lower_tol, offset_tol "
            "FROM package_size WHERE package_size = %s",
            ((group.get("package_size") or "").strip(),),
        )
    else:
        cur.execute(
            "SELECT nominal_x, nominal_y, upper_tol, lower_tol, offset_tol "
            "FROM part_number WHERE part_number_name = %s",
            ((group.get("part_number") or "").strip(),),
        )
    row = cur.fetchone()
    if not row:
        raise HTTPException(400, f"กลุ่มที่ {gi + 1}: หาเกณฑ์ตัดสินของกลุ่มนี้ไม่เจอ")
    return row

def _build_groups(cur, groups, group_of, queue, templates, entry_mode: str):
    """สร้างฟิลด์ `groups` ที่แนบไปกับ `POST /command` ให้ Pi

    Pi เอาไปทำ 2 อย่าง: รู้ว่าถึง ALPL ตัวไหนต้องสลับ `PW` เป็น template อะไร
    และตัดสิน OK/NG เองจากค่าที่อ่านผ่าน `GM` เพื่อสั่ง MCU ได้ทันทีโดยไม่ต้อง
    ถาม backend กลับ (ดู PLAN_criteria_and_multigroup.md ข้อ F)

    **payload ของ IPM กับ New/Rework หน้าตาเหมือนกันเป๊ะ** ต่างแค่ตัวเลข →
    Pi มี code path เดียว ตรงกับที่เป็นอยู่แล้ววันนี้ (Pi ไม่เคยรู้เรื่องโหมด)

    **ไม่ส่ง `queue` แยก** — เป็น `[a for g in groups for a in g["alpl"]]`
    บรรทัดเดียว ส่งซ้ำมีแต่จะเสี่ยงไม่ตรงกันเอง
    """
    out = []
    for gi, g in enumerate(groups):
        alpl = [queue[i] for i, gg in enumerate(group_of) if gg == gi]
        crit = _criteria_from_config(cur, gi, g, entry_mode)

        # ── กันเกณฑ์ 2 ฝั่งไม่ตรงกันแบบเงียบๆ (เฉพาะ IPM) ──────────────────
        # IPM ไม่แตะ config ของ Part ที่ลงทะเบียนไว้แล้ว ถ้าผู้ใช้พิมพ์ Package
        # Size ในฟอร์มไม่ตรงกับที่ Part ตัวนั้นผูกไว้จริง จะเกิดสภาพ:
        #   Pi คัดของตามเกณฑ์ของกลุ่ม · backend บันทึกตามเกณฑ์รายตัว
        # ไม่มีใครรู้จนกว่าจะไปนับของจริง — เปลี่ยนเป็นข้อความตอนกด Start แทน
        #
        # New: ยังไม่มีแถว Part เลย (validate แล้ว) ไม่มีอะไรให้ชน
        # Rework: `_update_part_row` จะเขียนทับ config เดิมด้วยค่าจากฟอร์มอยู่แล้ว
        #         "ไม่ตรง" คือเจตนาของผู้ใช้ ไม่ใช่ความผิดพลาด
        if entry_mode == "IPM":
            want = _limits_of(crit, entry_mode)
            for a in alpl:
                cur.execute("SELECT 1 FROM parts_specifications WHERE number_alpl = %s", (a,))
                if not cur.fetchone():
                    continue                      # ยังไม่ลงทะเบียน — จะถูกสร้างด้วย config นี้อยู่แล้ว
                got = _limits_of(_load_criteria(cur, a, entry_mode), entry_mode)
                if got != want:
                    raise HTTPException(
                        400,
                        f"เริ่มวัดไม่ได้ — ALPL {a} ที่ลงทะเบียนไว้ใช้เกณฑ์ไม่ตรงกับ "
                        f"Package Size \"{g.get('package_size')}\" ที่กรอกในกลุ่มที่ {gi + 1} "
                        f"(X {got['x_lo']:.3f}–{got['x_hi']:.3f} vs {want['x_lo']:.3f}–{want['x_hi']:.3f}) "
                        f"— แก้ Package Size ของ ALPL นี้ที่หน้า Edit › Parts หรือแยกไปกรอกคนละกลุ่ม",
                    )

        out.append({
            "template_name": templates[gi],
            "alpl": alpl,
            "limits": _limits_of(crit, entry_mode),
        })
    return out

async def _notify_agent_start(
    session_id: int,
    target_count: int,
    groups: List[Dict[str, Any]],
) -> None:
    """ยิง POST ไปที่ Agent (`send_command.py` บน Pi / `mockup.py`) ให้เริ่มวัด

    ```json
    {"action": "start", "session_id": 42, "target_count": 6,
     "groups": [
       {"template_name": "021", "alpl": [400, 401, 402],
        "limits": {"x_lo": 5.009999, "x_hi": 5.030001,
                   "y_lo": 3.389999, "y_hi": 3.410001, "offset_max": null}},
       {"template_name": "007", "alpl": [501, 502, 503],
        "limits": {"x_lo": 3.199999, "x_hi": 3.240001,
                   "y_lo": 3.199999, "y_hi": 3.240001, "offset_max": 0.03}}
     ]}
    ```

    **ไม่มี `template_name` / `number_alpl` ระดับบนสุดแล้ว** — ทั้งคู่เป็นของ
    "กลุ่มแรก" ซึ่งอยู่ใน `groups[0]` อยู่แล้ว ถ้าส่งซ้ำไว้ข้างบนด้วยจะมีแหล่ง
    ความจริง 2 ที่ แล้ววันหนึ่งจะมีโค้ดฝั่ง Agent ที่อ่านตัวข้างบน (= ของกลุ่มแรก)
    ไปใช้กับทุกกลุ่มโดยไม่มีใครรู้ตัว

    **ไม่ส่ง `queue` แยก** — คือ `[a for g in groups for a in g["alpl"]]`
    บรรทัดเดียว ส่งซ้ำมีแต่จะเสี่ยงไม่ตรงกันเอง (`target_count` ส่งไว้เพราะเป็น
    ตัวที่ Agent ใช้วนลูป และตรวจได้ทันทีว่าตรงกับผลรวมของ `groups` ไหม)

    ╔═══ ถ้าสั่งไม่สำเร็จ ต้องเคลียร์ให้สะอาด (Handle_Pi_Error.md ข้อ 1.3) ═══╗
    ของเดิม `await client.post(...)` เฉยๆ ไม่เก็บผลลัพธ์เลย — Pi ตอบ 400/500
    หรือไม่ได้รันอยู่ ก็เดินหน้าต่อเหมือนกันหมด แล้ว session ค้างที่ `running`
    จนกว่า `heartbeat_checker` จะ mark เป็น `timeout` ใน 15 วิ ซึ่ง**ชี้ผิดสาเหตุ**
    (ผู้ใช้เห็นแค่ "กด Start แล้วไม่มีอะไรเกิดขึ้น")

    ตอนนี้ทุกทางที่พังวิ่งไปที่ `_fail_start()` ซึ่งเคลียร์ทุกอย่างแล้ว raise 502
    ออกไปให้หน้าเว็บขึ้น popup — ต้อง raise **ก่อน** `push_event("session_started")`
    ไม่งั้นหน้าเว็บทุกเครื่องจะเข้าโหมดวัดพร้อมกันทั้งที่ไม่มีอะไรเกิดขึ้น

    **timeout แยก 2 ค่า** — `connect=3` เพราะอยู่วง LAN เดียวกัน (ปกติต่อติดใน
    ~10 ms) ถ้า IP ผิดจะรู้ผลใน 3 วิแทนที่จะกิน 10 วิเต็ม · `read=10` ต้องเผื่อ
    ให้ Pi ประมวลผล  → จับเวลาแล้วเดาสาเหตุได้เลย: ~3 วิ = หา Pi ไม่เจอ ·
    ~10 วิ = Pi ค้าง
    ╚═══════════════════════════════════════════════════════════════════════╝
    """
    payload: Dict[str, Any] = {
        "action": "start",
        "session_id": session_id,
        "target_count": target_count,
        "groups": groups,
    }
    # log ก่อนยิงเสมอ — เป็นจุดเดียวที่เห็น "สิ่งที่ backend ส่งให้ Agent" ได้จริง
    # (POST นี้ไม่ผ่านเบราว์เซอร์ DevTools จึงมองไม่เห็น) ถ้า Agent ไม่ตอบ
    # อย่างน้อยยังรู้ว่าเราส่งอะไรออกไป ไม่ต้องเดา
    log.info("📤 ส่งไป Agent %s/command:\n%s",
             AGENT_BASE_URL, json.dumps(payload, ensure_ascii=False, indent=2))
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{AGENT_BASE_URL}/command", json=payload,
                timeout=httpx.Timeout(connect=3.0, read=10.0, write=10.0, pool=3.0),
            )
    # ⚠ ลำดับ except สำคัญมาก — `ConnectTimeout` เป็นลูกของ `TimeoutException`
    #   ถ้าเขียน TimeoutException ไว้บนสุดจะกลืน ConnectTimeout ไปด้วย แล้ว
    #   ข้อความจะบอกว่า "Pi ค้าง" ทั้งที่จริงคือ "หา Pi ไม่เจอ" — ชี้ผิดทางเลย
    except httpx.ConnectError:
        # ต่อไปถึงเครื่องแล้วแต่ไม่มีใครฟังพอร์ตนั้น (โดน RST กลับมาทันที)
        _fail_start(session_id,
                    f"ติดต่อโปรแกรมบนเครื่อง Pi ไม่ได้ ({AGENT_BASE_URL}) — "
                    f"ตรวจว่า send_command.py รันอยู่ไหม · สาย LAN · IP ของ Pi เปลี่ยนหรือเปล่า")
    except httpx.ConnectTimeout:
        # ไม่มีใครอยู่ที่ IP นั้นเลย (ไม่มีแม้แต่ RST) — IP ผิด/เครื่องดับ/สายหลุด
        _fail_start(session_id,
                    f"หาเครื่อง Pi ไม่เจอที่ {AGENT_BASE_URL} — ตรวจ IP หรือสาย LAN")
    except httpx.TimeoutException:
        # ── ReadTimeout: อันตรายที่สุดในกลุ่มนี้ ──────────────────────────
        # ต่อติดแล้ว payload ส่งออกไปแล้ว แต่ Pi ไม่ตอบใน 10 วิ — **เป็นไปได้ว่า
        # มันรับไปแล้วและกำลังยิง T1 อยู่** ต่างจาก ConnectError/ConnectTimeout
        # ที่รู้แน่ว่าไม่มีอะไรเริ่ม
        #
        # ถ้าปิด session เงียบๆ โดยไม่บอก Pi จะได้สภาพ: DB บอก stopped แต่ Pi
        # ยังวัดต่อและยิงค่าเข้ามาเรื่อยๆ → create_measurement ปฏิเสธ → Pi รอ
        # measured_count ขยับจนครบ MEASURE_TIMEOUT → เด้ง modal ถามผู้ใช้ทั้งที่
        # หน้าเว็บบอกว่าไม่มี session แล้ว
        await _notify_agent_action("stop", session_id)
        _fail_start(session_id,
                    "Pi ไม่ตอบภายใน 10 วินาที — อาจติดคำสั่งเดิมค้างอยู่ "
                    "(สั่งหยุดกลับไปแล้ว) ลองรีสตาร์ท send_command.py")
    except Exception as exc:
        # กันไว้ไม่ให้ exception แปลกๆ หลุดออกไปเป็น 500 ที่ไม่มี CORS header
        # (browser จะเข้าใจผิดว่าเป็น CORS error ทั้งที่จริงคือ Agent ไม่ตอบ)
        _fail_start(session_id, f"สั่งงาน Pi ไม่สำเร็จ: {exc}")

    # ต่อติดและตอบกลับมาแล้ว — แต่ยังต้องดูว่า "ตอบว่าอะไร"
    # Pi ปฏิเสธด้วย 400 ได้ 2 กรณี: action ที่ไม่รู้จัก · payload ไม่สมเหตุสมผล
    # (เช่น len(groups) ไม่ตรงกับ target_count) ทั้งคู่แปลว่า **Pi ไม่ได้เริ่มวัด**
    # จึงไม่ต้องส่ง stop ตามไป ต่างจากเคส ReadTimeout ข้างบน
    if resp.status_code != 200:
        _fail_start(session_id, f"Pi ปฏิเสธคำสั่ง (HTTP {resp.status_code}): {resp.text[:300]}")

def _fail_start(session_id: int, msg: str) -> None:
    """เคลียร์ session ที่เพิ่งสร้างแล้วโยน 502 ออกไป — ใช้ตอนสั่ง Pi ไม่สำเร็จ

    ทำ 3 อย่างที่ลืมง่ายทั้งหมด:

    ① `session_queues.pop()` — เป็น dict ในหน่วยความจำล้วนๆ ไม่มีใครมาเก็บกวาดให้
       กด Start ไม่ติด 20 ครั้งก็ค้าง 20 คิว
    ② ปิด session ใน DB ทันที — อย่าทิ้ง `running` ไว้ให้ `heartbeat_checker`
       มาเก็บใน 15 วิ เพราะมันจะขึ้นเป็น `timeout` ซึ่งชี้ผิดสาเหตุ
    ③ `raise HTTPException(502)` — ต้องเกิด **ก่อน** `push_event("session_started")`
       ใน start_session ไม่งั้นหน้าเว็บทุกเครื่องเข้าโหมดวัดพร้อมกันทั้งที่ไม่มี
       อะไรเกิดขึ้น · การ raise ยังทำให้ fetch ฝั่งเว็บพัง → ขึ้น popup แทนที่จะ
       แสดงหน้าจอวัดงานปลอมๆ

    **ไม่ broadcast SSE `session_stopped`** ต่างจากปุ่ม Stop โดยตั้งใจ — เพราะยัง
    ไม่มีแท็บไหนเคยได้ `session_started` เลย (raise เกิดก่อน) จึงไม่มีใครอยู่ใน
    โหมดวัดให้ต้องพาออกมา ส่วนแท็บอื่นจะเห็น state='stopped' เองในรอบ poll ถัดไป
    """
    session_queues.pop(session_id, None)
    measure_timeouts.pop(session_id, None)
    try:
        db = get_db()
        try:
            with db.cursor() as cur:
                cur.execute(
                    "UPDATE sessions SET state = 'stopped', ended_at = NOW(), "
                    "last_event = 'START_FAILED', last_event_detail = %s, last_event_at = NOW() "
                    "WHERE session_id = %s",
                    (msg, session_id),
                )
        finally:
            db.close()
    except Exception as exc:
        # ปิด session ไม่สำเร็จก็ยังต้องแจ้งผู้ใช้ให้ได้ — ห้ามกลืน error ต้นทาง
        log.error("_fail_start: ปิด session %s ไม่สำเร็จ: %s", session_id, exc)
    log.warning("Start session %s ล้มเหลว — %s", session_id, msg)
    raise HTTPException(502, msg)

def _parse_entry_groups(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """แปลง payload ของ /api/session/start ให้เป็น "ลิสต์ของกลุ่ม" เสมอ

    ฟอร์ม Part Entry กด +Add เพิ่มกลุ่มได้ แต่ละกลุ่มมี ALPL ได้หลายตัวและมี
    config ของตัวเอง (Package Size / Part Number / PO / Vendor / Owner / …)
    ส่วน Operator อยู่นอกกลุ่ม ใช้ร่วมกันทั้ง session (คนวัดคนเดียวกัน)

        {"Measure_Type": "New", "Operator": "somchai",
         "groups": [{"number_alpl": [400,401], "package_size": "5x5", ...},
                    {"number_alpl": [501],     "package_size": "3x3", ...}]}

    ยังรับ payload แบบเก่า (field อยู่ระดับบนสุด ไม่มี `groups`) ได้ด้วย โดยตี
    ความว่าเป็น "กลุ่มเดียว" — ไม่ใช่เพื่อรองรับหน้าเว็บเก่า (ย้ายพร้อมกันอยู่แล้ว)
    แต่เพื่อให้เครื่องมือทดสอบ/สคริปต์เดิมที่ยิง payload ตรงๆ ไม่พังหมดทีเดียว
    """
    groups = data.get("groups")
    if groups is None:
        return [data]
    if not isinstance(groups, list) or not groups:
        raise HTTPException(400, "groups ต้องเป็น array และมีอย่างน้อย 1 กลุ่ม")
    for i, g in enumerate(groups):
        if not isinstance(g, dict):
            raise HTTPException(400, f"groups[{i}] ต้องเป็น object")
    return groups

def _flatten_groups(groups: List[Dict[str, Any]]) -> tuple:
    """คลี่ ALPL ของทุกกลุ่มออกเป็นคิวเส้นเดียว พร้อม "แผนที่ชิ้น → กลุ่ม"

    คืน (queue, group_of) ที่ยาวเท่ากัน — `group_of[i]` คือลำดับกลุ่มของชิ้นที่ i
    create_measurement ใช้ค่านี้หา config ที่ถูกต้องของชิ้นที่กำลังวัดอยู่
    (ไม่ใช่ config ของกลุ่มแรกเสมอแบบเดิม)

    ⚠ ALPL ห้ามซ้ำ **ข้ามกลุ่ม** ด้วย ไม่ใช่แค่ในกลุ่มเดียวกัน — ถ้าปล่อยให้ซ้ำ
      ชิ้นเดียวกันจะถูกวัด 2 ครั้งด้วย config คนละชุด แล้วอันหลังเขียนทับ Part
      ของอันแรกโดยที่ผู้ใช้ไม่รู้ตัว
    """
    queue: List[int] = []
    group_of: List[int] = []
    seen: Dict[int, int] = {}
    for gi, g in enumerate(groups):
        try:
            alpls = [int(x) for x in g["number_alpl"]]
        except KeyError:
            raise HTTPException(400, f"กลุ่มที่ {gi + 1} ไม่มี field 'number_alpl'")
        except (ValueError, TypeError):
            raise HTTPException(400, f"กลุ่มที่ {gi + 1}: number_alpl ต้องเป็นเลขจำนวนเต็มทั้งหมด")
        if not alpls:
            raise HTTPException(400, f"กลุ่มที่ {gi + 1} ต้องมี ALPL อย่างน้อย 1 ตัว")
        for a in alpls:
            if a in seen:
                where = ("ในกลุ่มเดียวกัน" if seen[a] == gi
                         else f"ซ้ำกับกลุ่มที่ {seen[a] + 1}")
                raise HTTPException(400, f"ALPL {a} ซ้ำ ({where}) — แก้ให้ไม่ซ้ำก่อนเริ่มวัด")
            seen[a] = gi
            queue.append(a)
            group_of.append(gi)
    return queue, group_of

def _validate_group(cur, gi: int, group: Dict[str, Any], measure_type: str,
                    alpls: List[int]) -> str:
    """ตรวจกลุ่มหนึ่งให้ครบ **โดยไม่เขียนอะไรลง DB เลย** แล้วคืน template_name

    เจตนา: ให้ผู้ใช้รู้ทุกปัญหา "ตั้งแต่กด Start" ไม่ใช่ไปรู้ตอนวัดชิ้นแรกเสร็จ
    แล้ว Part insert ไม่ผ่าน (ดู PLAN_criteria_and_multigroup.md ข้อ C2)

    เงื่อนไข ALPL ต่อโหมดตรงข้ามกัน (ข้อ D5) — หน้าเว็บเช็คให้แล้วตอนกด Save
    แต่ backend ต้องเช็คซ้ำ เพราะหน้าเว็บไม่ใช่ที่กันข้อมูลเสีย มันแค่ทำให้
    ผู้ใช้รู้เร็วขึ้น
    """
    label = f"กลุ่มที่ {gi + 1}"

    pkg = (group.get("package_size") or "").strip()
    if not pkg:
        raise HTTPException(400, f"{label}: ต้องเลือก Package Size")
    cur.execute("SELECT package_size_id FROM package_size WHERE package_size = %s", (pkg,))
    if not cur.fetchone():
        raise HTTPException(400, f"{label}: ไม่รู้จัก Package Size \"{pkg}\"")

    part_number = (group.get("part_number") or "").strip()
    if measure_type in ("New", "Rework"):
        if not part_number:
            raise HTTPException(400, f"{label}: โหมด {measure_type} ต้องเลือก Part Number")
        cur.execute(
            "SELECT 1 FROM part_number WHERE part_number_name = %s", (part_number,)
        )
        if not cur.fetchone():
            raise HTTPException(400, f"{label}: ไม่รู้จัก Part Number \"{part_number}\"")

    # ── ALPL มี/ไม่มีใน DB ตามที่โหมดนั้นต้องการไหม ──────────────────────
    placeholders = ", ".join(["%s"] * len(alpls))
    cur.execute(
        f"SELECT number_alpl FROM parts_specifications WHERE number_alpl IN ({placeholders})",
        alpls,
    )
    found = {r["number_alpl"] for r in cur.fetchall()}
    missing = [a for a in alpls if a not in found]
    existing = [a for a in alpls if a in found]

    if measure_type == "New" and existing:
        raise HTTPException(
            409,
            f"{label}: ALPL {', '.join(map(str, existing))} มีอยู่ในระบบแล้ว — "
            f"ถ้าจะวัดซ้ำใช้โหมด IPM · ถ้าเป็นงานแก้จาก vendor ใช้ Rework",
        )
    if measure_type == "Rework" and missing:
        raise HTTPException(
            404,
            f"{label}: ALPL {', '.join(map(str, missing))} ไม่มีในระบบ — "
            f"Rework ต้องเป็นชิ้นที่เคยวัดมาก่อนเท่านั้น ถ้าเป็นชิ้นใหม่ให้ใช้โหมด New",
        )
    # IPM: ตัวที่ยังไม่มีจะถูกลงทะเบียนให้ตอนวัดจริง (ผู้ใช้ยืนยันมาแล้วจากหน้าเว็บ)
    # จึงไม่บล็อกที่นี่ — แต่ต้องมี Package Size ในกลุ่ม ซึ่งเช็คไปแล้วข้างบน

    # template ผูกกับ package_size ของกลุ่ม (ไม่ต้องพึ่ง Part ที่อาจยังไม่มี)
    cur.execute(
        "SELECT t.template_name FROM package_size ps "
        "LEFT JOIN template t ON ps.template_id = t.template_id "
        "WHERE ps.package_size = %s",
        (pkg,),
    )
    row = cur.fetchone()
    if not row or not row["template_name"]:
        raise HTTPException(
            400,
            f"{label}: Package Size \"{pkg}\" ยังไม่ได้ตั้ง Template ของเครื่อง TM-X "
            f"(แก้ที่หน้า Edit › Lookup Tables › Package Size)",
        )
    return row["template_name"]

@router.post("/api/session/start")
async def start_session(request: Request):
    """เริ่ม session การวัดใหม่ จาก Part Entry card (โหมด IPM, New หรือ Rework)

    **ฟอร์มส่งมาเป็น "กลุ่ม"** — 1 กลุ่ม = ALPL หลายตัวที่ใช้ config ชุดเดียวกัน
    กด +Add เพิ่มกลุ่มได้ (ดู `_parse_entry_groups`) ทั้ง 3 โหมดใช้โครงเดียวกัน
    ต่างกันแค่ลิสต์ field ในกลุ่มและเงื่อนไขว่า ALPL ต้องมี/ต้องไม่มีใน DB

    **ไม่มีการเขียน Part ลง DB ที่นี่เลยทุกโหมด** — ตรวจอย่างเดียว (`_validate_group`)
    แล้วเก็บ config ไว้ใน `queue_state` ให้ `create_measurement` เอาไปสร้าง/อัปเดต
    Part "พร้อมกับ measurement ของชิ้นนั้น" ทีละชิ้น ผลคือ

        กด Start แล้วกด Stop ทันที   → ไม่มีอะไรเกิดขึ้นใน DB เลย
        วัดชิ้นที่ 1 สำเร็จ            → Part + Measurement เกิดพร้อมกัน
        วัดชิ้นที่ 1 ไม่ติด            → ไม่มีอะไรเกิดขึ้น

    เดิม New insert Part ตัวแรกไว้ก่อนเพราะ `sessions.number_alpl` มี FK — ตอนนี้
    คอลัมน์นั้นถูกถอดออกไปแล้ว จึงไม่มีเหตุผลให้ insert ล่วงหน้าอีก

    ทั้ง 3 กรณี — Agent ไม่ต้องรู้ความต่างเลย ได้รับ payload หน้าตาเดียวกัน
    (action/session_id/template_name/target_count/number_alpl ตัวแรก) ส่วน
    การ map ALPL ตัวต่อๆไปในคิวเข้ากับ measurement ที่จะตามมา เป็นเรื่องที่
    backend จัดการเองทั้งหมดผ่าน session_queues (ดู create_measurement)

    หมายเหตุ (เพิ่มเข้ามาทีหลัง): Race condition ตอนกด Start ซ้ำเร็วๆ — ครอบ
    check+insert ด้วย MySQL GET_LOCK/RELEASE_LOCK กันสอง request แข่งกันผ่าน
    Button Guard พร้อมกันได้ (เดิมเช็คแล้ว insert คนละคำสั่ง ไม่มีอะไรล็อก
    ระหว่างนั้นเลย)
    """
    data = await request.json()
    log.info("📥 ได้รับ payload จาก /api/session/start:\n%s", json.dumps(data, ensure_ascii=False, indent=2))

    measure_type = data.get("Measure_Type")
    if measure_type not in ("New", "IPM", "Rework"):
        raise HTTPException(400, "Measure_Type ต้องเป็น 'New', 'IPM' หรือ 'Rework'")

    groups = _parse_entry_groups(data)
    alpl_queue, group_of = _flatten_groups(groups)
    first_alpl = alpl_queue[0]
    target_count = len(alpl_queue)

    # **การ map โหมดที่เลือกหน้าเว็บ → ค่าที่บันทึกลง measurements**
    # (ตามที่ตกลงกันไว้ — Rework ไม่ใช่ measure_type ของตัวเอง แต่ถือเป็นการวัด
    # แบบ New ที่มีหมายเหตุกำกับว่าเป็นงาน Rework):
    #   หน้าเว็บเลือก "Rework" → measure_type = 'New',  note = 'Rework'
    #   หน้าเว็บเลือก "New"    → measure_type = 'New',  note = NULL
    #   หน้าเว็บเลือก "IPM"    → measure_type = 'IPM',  note = NULL
    # entry_mode ตรงนี้คือค่าที่ create_measurement จะเอาไปใส่คอลัมน์ measure_type
    # ตรงๆ และเป็นตัวเลือกแหล่งเกณฑ์ (`_load_criteria`) ด้วย จึงต้อง map ให้เสร็จ
    # ตั้งแต่ก่อนเข้า DB block เพราะ `_build_groups` ต้องใช้
    entry_mode = "New" if measure_type in ("New", "Rework") else "IPM"
    entry_note = "Rework" if measure_type == "Rework" else None

    db = get_db()
    try:
        # GET_LOCK ครอบทั้ง Button Guard + insert — ให้ทั้งสองเป็น atomic
        # section เดียวกันจริงๆ ในระดับ DB (ไม่ใช่แค่ระดับ Python) กันสอง
        # request "Start" ที่มาถึงพร้อมกันเป๊ะๆ ผ่าน check ทั้งคู่ก่อนจะมีใคร
        # insert ทัน — timeout 5 วิ พอสำหรับ critical section สั้นๆ นี้
        with db.cursor() as cur:
            cur.execute("SELECT GET_LOCK('tmx_start_session', 5) AS got")
            if not cur.fetchone()["got"]:
                raise HTTPException(503, "ระบบกำลังประมวลผลคำสั่ง Start อื่นอยู่ ลองใหม่อีกครั้ง")

        try:
            with db.cursor() as cur:
                # Button Guard — กันรัน 2 session ซ้อนกัน (เหมือนของเดิมก่อนหน้านี้)
                cur.execute("SELECT session_id FROM sessions WHERE state = 'running'")
                if cur.fetchone():
                    raise HTTPException(400, "A session is already running")

                # 1) ตรวจทุกกลุ่มให้ครบก่อน — **ยังไม่เขียนอะไรลง DB**
                #    ตรวจให้จบทุกกลุ่มแล้วค่อยตัดสิน ไม่ใช่เจอกลุ่มแรกผิดแล้วหยุด
                #    เพราะผู้ใช้ควรได้แก้ทีเดียวจบ ไม่ใช่กด Start ซ้ำทีละรอบ
                #    ต่อ 1 กลุ่มที่ผิด (ตอนนี้ _validate_group ยัง raise ทันทีที่
                #    เจอ — ยอมรับได้เพราะหน้าเว็บกรองชั้นแรกให้แล้วตอนกด Save)
                templates: List[str] = []
                for gi, g in enumerate(groups):
                    alpls_of_group = [a for a, gg in zip(alpl_queue, group_of) if gg == gi]
                    templates.append(_validate_group(cur, gi, g, measure_type, alpls_of_group))

                # ⚠ ยังสลับ template กลางคันไม่ได้ — Pi รับ template_name ตัวเดียว
                #   ตอน start แล้วส่ง PW ครั้งเดียว (การสลับ PW ระหว่างคิวคือแผน E
                #   ใน PLAN_criteria_and_multigroup.md ซึ่งยังไม่ได้ทำ)
                #   ถ้าปล่อยผ่าน กลุ่มที่ 2 เป็นต้นไปจะถูกวัดด้วยโปรแกรมของกลุ่มแรก
                #   → ได้ค่าที่ "ดูเหมือนใช้ได้" แต่ผิดทั้งกลุ่มโดยไม่มีอะไรเตือน
                distinct = sorted(set(templates))
                if len(distinct) > 1:
                    raise HTTPException(
                        400,
                        "กลุ่มที่กรอกมาใช้ Template ของ TM-X คนละตัวกัน "
                        f"({', '.join(distinct)}) — ตอนนี้ยังสลับโปรแกรมกลางคันไม่ได้ "
                        "กรุณาแยกวัดทีละ Template (กลุ่มที่ Package Size ให้ Template "
                        "เดียวกันรวมรอบเดียวกันได้)",
                    )
                template_name = templates[0]

                # 1.5) ประกอบ `groups` ที่จะแนบไปกับ /command ให้ Pi
                #      ทำ "ก่อน" insert sessions โดยตั้งใจ — ถ้าเกณฑ์ 2 ฝั่งไม่ตรงกัน
                #      (ดู _build_groups) จะ raise ตรงนี้แล้วไม่มี session ค้างใน DB
                agent_groups = _build_groups(
                    cur, groups, group_of, alpl_queue, templates, entry_mode
                )

                # 2) Insert sessions row — ไม่มี number_alpl แล้ว (ถอดออกพร้อม FK
                #    เพราะเก็บได้แค่ ALPL ตัวแรกของคิว ไม่เคยถูก UPDATE ระหว่าง
                #    session จึงไม่มีใครใช้ได้จริง — คิวตัวจริงอยู่ใน queue_state)
                cur.execute(
                    "INSERT INTO sessions (state, target_count, measured_count) "
                    "VALUES ('running', %s, 0)",
                    (target_count,),
                )
                session_id = cur.lastrowid
        finally:
            with db.cursor() as cur:
                cur.execute("SELECT RELEASE_LOCK('tmx_start_session')")

        # 3) เก็บคิวไว้ใน memory ผูกกับ session_id นี้ (หลัง insert สำเร็จแล้ว
        # ค่อยผูก กัน insert fail แล้วมี state ค้างอยู่ใน session_queues)
        # entry_mode / entry_note ถูก map ไว้ตั้งแต่ต้นฟังก์ชันแล้ว
        queue_state = {
            "entry_mode": entry_mode,
            "measure_mode": measure_type,   # โหมดดิบที่ผู้ใช้เลือก (แยก New/Rework ออกจากกัน)
            "queue": alpl_queue,
            # group_of[i] = ชิ้นที่ i อยู่กลุ่มไหน — create_measurement ใช้หา
            # config ของชิ้นที่กำลังวัด ไม่ใช่ใช้ config ของกลุ่มแรกกับทุกชิ้น
            "group_of": group_of,
            # config ของแต่ละกลุ่ม (part_number/package_size/vendor/owner/PO/…)
            # เก็บไว้ให้ create_measurement สร้าง/อัปเดต Part พร้อม measurement
            # ของชิ้นนั้น — ไม่มีการเขียน Part ล่วงหน้าตอน Start อีกแล้วทุกโหมด
            "groups": groups,
            # template ต่อกลุ่ม — ตอนนี้บังคับให้เหมือนกันหมด (ดูเช็คด้านบน)
            # แต่เก็บแยกรายกลุ่มไว้ก่อน เพื่อให้แผน E (Pi สลับ PW กลางคิว) มา
            # ต่อได้เลยโดยไม่ต้องรื้อโครงสร้างนี้ใหม่
            "group_templates": templates,
            "position": 0,
            "operator": data.get("Operator"),
            "note": entry_note,
        }
        session_queues[session_id] = queue_state
        measure_timeouts.pop(session_id, None)  # session ใหม่ต้องไม่มีคำถามค้างจากรอบก่อน

        # เขียนสำเนา queue_state ลง DB ด้วย (คอลัมน์ sessions.queue_state) — ถ้า
        # backend restart กลาง session นี้ จะโหลดกลับเข้า memory ได้ตอน boot
        # แทนที่จะ fallback ไปใช้ ALPL ตัวแรกผิดๆ ตลอดที่เหลือ (ดู create_measurement
        # และ lifespan())
        with db.cursor() as cur:
            cur.execute(
                "UPDATE sessions SET queue_state = %s WHERE session_id = %s",
                (json.dumps(queue_state), session_id),
            )

        # 4) Notify Agent ให้เริ่มวัด — ส่ง groups (template + ขอบเขต OK/NG
        #    รายกลุ่ม) ไปทั้งก้อน เพื่อให้ Pi สลับ PW ได้เองและตัดสิน OK/NG เอง
        #    แล้วสั่ง MCU ได้โดยไม่ต้องถาม backend กลับ (ดู _build_groups / PLAN ข้อ F)
        await _notify_agent_start(session_id, target_count, agent_groups)

        await push_event(
            "session_started",
            {
                "session_id": session_id,
                "number_alpl": first_alpl,
                "template_name": template_name,
                "target_count": target_count,
            },
        )
        return {"session_id": session_id, "template_name": template_name, "target_count": target_count}
    finally:
        db.close()

@router.post("/api/session/stop")
async def stop_session(req: StopSessionRequest):
    """หยุด session ที่กำลัง running จากปุ่ม Stop บน dashboard

    ทำไมเรื่องนี้สำคัญ: นี่คือ path "web-initiated stop" — มันอัปเดต DB
    (state='stopped', ended_at=NOW()) แล้วบอก Agent ให้หยุด ซึ่งต่างจากปุ่ม
    Stop ทางกายภาพที่ MCU (ในการ implement ปัจจุบันของ Agent) ที่แค่ flip
    flag ใน memory ฝั่ง Agent โดยไม่แตะ DB เลย — เป็นความไม่สมดุล (asymmetry)
    ที่รู้กันอยู่ระหว่าง stop ทั้ง 2 path นี้

    **นี่คือทางเดียวในระบบที่ปิด session ได้** — ทุกปุ่มและทุกเส้นทางวิ่งมาที่นี่หมด
    (ปุ่ม Stop บนเว็บ · "หยุดการวัด" ใน modal · modal หมดเวลา 60 วิ · Pi ล้มเลิกเอง)
    ตั้งใจไม่ให้มีทางที่สอง เพราะถ้าแยกกันแล้วลืมทำอะไรสักอย่างในเส้นทางไหน
    จะเกิดอาการ "กดหยุดจากตรงนี้แล้วค้าง แต่กดจากตรงนั้นแล้วปกติ" ซึ่งหาสาเหตุยากมาก

    reason: Pi ส่งมาตอนล้มเลิกเอง (ER,PW / T1 retry ครบ / สาย TM-X ขาด) เพื่อให้
            หน้าเว็บบอกผู้ใช้ได้ว่าหยุดเพราะอะไร — หน้าเว็บไม่ต้องส่งมา (None)
    """
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute("SELECT state FROM sessions WHERE session_id = %s", (req.session_id,))
            if not cur.fetchone():
                raise HTTPException(404, "Session not found")
            if req.reason:
                # Pi ล้มเลิกเอง — เก็บสาเหตุไว้เป็นบันทึกถาวรว่า session นี้จบเพราะอะไร
                # (session ปิดแล้ว จึงไม่มีอะไรมาเขียนทับ last_event อีก)
                cur.execute(
                    "UPDATE sessions SET state = 'stopped', ended_at = NOW(), "
                    "last_event = 'PI_ERROR', last_event_detail = %s, last_event_at = NOW() "
                    "WHERE session_id = %s",
                    (req.reason, req.session_id),
                )
                log.warning("Session %s: Pi ล้มเลิกเอง — %s", req.session_id, req.reason)
            else:
                cur.execute(
                    "UPDATE sessions SET state = 'stopped', ended_at = NOW() "
                    "WHERE session_id = %s",
                    (req.session_id,),
                )

        agent_err = await _notify_agent_action("stop", req.session_id)

        session_queues.pop(req.session_id, None)  # กดหยุดเองก่อนคิวหมด ก็เคลียร์ memory ทิ้งด้วย
        measure_timeouts.pop(req.session_id, None)  # กันคำถามค้างจาก session ที่จบไปแล้ว

        # ⚠ สั่ง Pi ไม่สำเร็จ = **เครื่องอาจยังวัดอยู่จริง** ทั้งที่ DB ปิดไปแล้ว
        #   ไม่ raise (DB หยุดไปเรียบร้อยแล้ว กดซ้ำไม่ช่วยอะไร) แต่ต้องบอกให้คน
        #   หน้าเครื่องรู้ว่า "ต้องไปกดหยุดที่เครื่องเอง" ไม่งั้นของจะไหลต่อโดย
        #   ไม่มีใครบันทึก — อันตรายกว่ากรณี Start พังมาก
        if agent_err:
            with db.cursor() as cur:
                cur.execute(
                    "UPDATE sessions SET last_event = 'STOP_NOT_DELIVERED', "
                    "last_event_detail = %s, last_event_at = NOW() WHERE session_id = %s",
                    (agent_err, req.session_id),
                )

        await push_event(
            "session_stopped",
            {"session_id": req.session_id, "reason": req.reason, "agent_error": agent_err},
        )
        return {"ok": True, "agent_error": agent_err}
    finally:
        db.close()

async def _notify_agent_action(action: str, session_id: int | None = None) -> Optional[str]:
    """ยิงคำสั่งสั้นๆ ไปหา Pi (stop / continue) — คืนข้อความ error ถ้าสั่งไม่สำเร็จ

    ╔═══ ทำไม stop ต้องปฏิบัติต่างจาก start (Handle_Pi_Error.md ข้อ 1.4) ═══╗
    **Start พังแล้วเคลียร์ทิ้งได้** เพราะรู้ว่ายังไม่มีอะไรเกิดขึ้น
    **Stop พังแปลว่าเครื่องอาจยังวัดอยู่จริง** — จะไปเคลียร์ session ทิ้งเฉยๆ
    ไม่ได้ เพราะ DB จะบอกว่าจบแล้วทั้งที่ของยังไหลอยู่บนสายพาน

    ที่นี่จึง **ไม่ raise และไม่แตะสถานะ session เลย** — DB ถูกอัปเดตไปแล้วก่อน
    เรียกฟังก์ชันนี้ (ดู stop_session) การโยน exception ออกไปจะทำให้ผู้ใช้เข้าใจ
    ว่า "กดหยุดไม่สำเร็จ" แล้วกดซ้ำ ทั้งที่ฝั่ง DB หยุดไปเรียบร้อยแล้ว

    แค่ **คืนข้อความกลับไปให้ผู้เรียกตัดสินใจ** ว่าจะเอาไปบอกผู้ใช้ยังไง
    (`stop_session` เอาไปแนบใน SSE `session_stopped` → หน้าเว็บเด้งเตือนว่า
     "หยุดในระบบแล้ว แต่สั่ง Pi ไม่ได้ — ไปกดหยุดที่เครื่องด้วย")
    ╚═══════════════════════════════════════════════════════════════════════╝
    """
    body: dict = {"action": action}
    if session_id is not None:
        body["session_id"] = session_id
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{AGENT_BASE_URL}/command", json=body,
                timeout=httpx.Timeout(connect=3.0, read=10.0, write=10.0, pool=3.0),
            )
    # ลำดับ except เดียวกับ _notify_agent_start — ConnectTimeout ต้องมาก่อน
    # TimeoutException ไม่งั้นโดนกลืนแล้วข้อความชี้ผิดสาเหตุ
    except httpx.ConnectError:
        msg = (f"ติดต่อโปรแกรมบนเครื่อง Pi ไม่ได้ ({AGENT_BASE_URL}) — "
               f"ตรวจว่า send_command.py รันอยู่ไหม")
    except httpx.ConnectTimeout:
        msg = f"หาเครื่อง Pi ไม่เจอที่ {AGENT_BASE_URL} — ตรวจ IP หรือสาย LAN"
    except httpx.TimeoutException:
        msg = "Pi ไม่ตอบภายใน 10 วินาที — อาจติดคำสั่งเดิมค้างอยู่"
    except Exception as exc:
        msg = f"สั่งงาน Pi ไม่สำเร็จ: {exc}"
    else:
        if resp.status_code == 200:
            return None
        msg = f"Pi ปฏิเสธคำสั่ง '{action}' (HTTP {resp.status_code}): {resp.text[:200]}"

    log.warning("Agent %s notify failed: %s", action, msg)
    return msg

@router.post("/api/session/event")
async def session_event(body: SessionEventRequest):
    """รับรายงานสาเหตุจาก Recieve_tm-x.py

    ⚠ last_event มีช่องเดียว ค่าใหม่ทับค่าเก่า — จึงเก็บเฉพาะเรื่องที่ "มีคนรอ
      คำตอบอยู่" (ค่าไม่ลง DB แล้ว Pi กำลังนับถอยหลัง) ส่วนเรื่องที่ค่าลงไปแล้ว
      เช่น IMAGE_UPLOAD_FAILED ต้องส่ง persist=False มา ไม่งั้นจะไปทับสาเหตุที่
      Backend ต้องหยิบไปตอบ Pi ตอน measure-timeout
    """
    if body.persist:
        db = get_db()
        try:
            with db.cursor() as cur:
                cur.execute(
                    "UPDATE sessions SET last_event = %s, last_event_detail = %s, "
                    "last_event_at = NOW() WHERE state = 'running'",
                    (body.event, body.detail),
                )
        finally:
            db.close()

    log.warning("Station event: %s — %s", body.event, body.detail)
    await push_event("station_event", {"event": body.event, "detail": body.detail})
    return {"ok": True}

@router.post("/api/measure-timeout")
async def report_measure_timeout(req: MeasureTimeoutRequest):
    """Pi แจ้งว่ารอค่าการวัดชิ้นนี้จนหมดเวลาแล้วยังไม่มาถึง

    Pi รู้แค่ "ไม่ได้ค่า" ไม่รู้สาเหตุ — Backend เป็นคนเติมให้ 2 อย่างก่อน broadcast:
      number_alpl  จาก queue[position] ของตัวเอง (ห้ามให้ Pi ส่งมา ไม่งั้นมี 2 แหล่ง
                   ที่บอกว่าชิ้นนี้คือ ALPL อะไร แล้วเหลื่อมกันได้)
      detail       จาก last_event ที่ Recieve เขียนไว้ก่อนหน้า (ถ้ายังสด)

    detail เป็น None ได้ — เกิดเมื่อรูปไม่มาเลย (Recieve ไม่เคยรายงาน) หรือ
    last_event เก่าเกินไป · หน้าเว็บต้องรองรับกรณีนี้ด้วยข้อความกลางๆ
    """
    measure_timeouts[req.session_id] = {"piece": req.piece, "target": req.target}

    detail = None
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute(
                "SELECT last_event_detail, last_event_at FROM sessions WHERE session_id = %s",
                (req.session_id,),
            )
            row = cur.fetchone()
    finally:
        db.close()

    if row and row["last_event_at"]:
        age = (datetime.now() - row["last_event_at"]).total_seconds()
        if age < LAST_EVENT_FRESH_SEC:
            detail = row["last_event_detail"]

    # ALPL ที่กำลังวัดอยู่ — มาจากคิวของ Backend เท่านั้น
    number_alpl = None
    qstate = session_queues.get(req.session_id)
    if qstate is not None:
        queue = qstate.get("queue") or []
        pos = qstate.get("position", 0)
        if 0 <= pos < len(queue):
            number_alpl = queue[pos]

    await push_event(
        "measure_timeout",
        {
            "session_id":  req.session_id,
            "piece":       req.piece,
            "target":      req.target,
            "number_alpl": number_alpl,
            "detail":      detail,
        },
    )
    log.warning(
        "Measure timeout: session=%s piece=%s alpl=%s — รอผู้ใช้ตัดสินใจ (สาเหตุ: %s)",
        req.session_id, req.piece, number_alpl, detail or "ไม่ทราบ",
    )
    return {"ok": True}

@router.post("/api/session/continue")
async def continue_session(body: SessionContinueRequest):
    """ผู้ใช้กด "วัดชิ้นถัดไป" ใน modal — ข้ามชิ้นที่ไม่ได้ค่าแล้ววัดต่อ

    ╔═══ เปลี่ยนจากการ poll เป็นการ push — 7 ส.ค. 2569 ═══════════════════════╗
    เดิม Pi วน GET /api/measure-timeout/{id} ทุก 0.4 วิรอคำตอบ ตอนนี้ Backend
    ยิง POST /command {"action":"continue"} ไปปลุก Pi แทน — Pi ตื่นทันทีที่คำตอบ
    มาถึง ไม่ต้องรอรอบ poll และคำสั่งจากข้างนอกเข้าทาง /command ทางเดียวหมด
    (start / stop / continue) เหมือนกันทั้งระบบ
    ╚═══════════════════════════════════════════════════════════════════════╝

    ⚠ ลำดับสำคัญ: ต้องขยับ position + sync ลง DB ให้เสร็จ "ก่อน" ปลุก Pi
      ไม่งั้น Pi อาจวัดชิ้นถัดไปเสร็จก่อนที่ UPDATE จะลง แล้วผลถูกแปะ ALPL ผิด

    ส่วน "หยุดการวัด" ใน modal ไม่ผ่านที่นี่ — หน้าเว็บเรียก POST /api/session/stop
    ตรงๆ เพื่อให้เส้นทางการหยุด session มีทางเดียวตลอดทั้งระบบ
    """
    session_id = body.session_id
    if measure_timeouts.get(session_id) is None:
        raise HTTPException(404, "ไม่พบคำถามค้างของ session นี้ (อาจหมดอายุไปแล้ว)")
    measure_timeouts.pop(session_id, None)

    # ╔═══ ขยับตำแหน่งคิวตอนข้ามชิ้น — เริ่มส่วนที่เพิ่ม ═════════════════════╗
    #
    # บั๊กที่แก้: number_alpl ของแต่ละ measurement ไม่ได้มาจาก Agent แต่ Backend
    # เลือกเองจาก "ตำแหน่งในคิว" (ดู create_measurement: number_alpl = queue[pos])
    # และตำแหน่งนั้นขยับที่เดียวในระบบคือตอน INSERT สำเร็จ
    #
    # ชิ้นที่ผู้ใช้เลือกข้าม (action="continue") ไม่มี INSERT → ตำแหน่งไม่ขยับ →
    # ผลวัดของ "ทุกชิ้นที่เหลือ" ถูกแปะ ALPL เลื่อนไปหมด:
    #
    #   คิว [A, B, C, D]
    #   ชิ้น 1 (ของจริง A) → บันทึกเป็น A ✓   pos 0→1
    #   ชิ้น 2 (ของจริง B) → บันทึกเป็น B ✓   pos 1→2
    #   ชิ้น 3 (ของจริง C) → ข้าม            pos ค้างที่ 2
    #   ชิ้น 4 (ของจริง D) → บันทึกเป็น C ✗   ← ผิด
    #
    # อันตรายกว่า "ข้อมูลหาย" เพราะข้อมูลหายเห็นได้จาก measured_count ที่ไม่ครบ
    # แต่ข้อมูลผิด ALPL หน้าตาปกติทุกอย่าง ไม่มีใครรู้จนกว่าจะไปเทียบของจริง
    #
    # ทำไมแก้ตรงนี้: นี่คือจุดเดียวในระบบที่รู้ว่า "ผู้ใช้ตัดสินใจข้ามชิ้นนี้"
    # (Pi แค่รับคำตอบไปเดินต่อ ไม่ได้บอก Backend อีกที)
    #
    # ⚠ ข้อจำกัดที่ยังเหลือ: ถ้าค่าของชิ้นที่ถูกข้ามมาถึงทีหลัง (FTP ช้ากว่า
    #   MEASURE_TIMEOUT) มันจะไปกินตำแหน่งของชิ้นถัดไปแทน ยังแปะผิดอยู่ดี —
    #   แต่เป็นเคสที่แคบกว่าเดิมมาก (ต้องมาถึงในช่วงหลังผู้ใช้กดตอบ แต่ก่อนที่
    #   ชิ้นถัดไปจะวัดเสร็จ) ต่างจากของเดิมที่ผิด "ทุกชิ้นที่เหลือ" แน่นอน 100%
    #   ปิดช่องนี้ได้ด้วย client_uuid = ts_key + เลข 10 หลัก (ดู IMPROVEMENT_PLAN.md)
    qstate = session_queues.get(session_id)
    if qstate is not None:
        qstate["position"] += 1
        db = get_db()
        try:
            with db.cursor() as cur:
                cur.execute(
                    "UPDATE sessions SET queue_state = %s WHERE session_id = %s",
                    (json.dumps(qstate), session_id),
                )
        finally:
            db.close()
        log.info(
            "Session %s: ข้ามชิ้นงาน — ขยับตำแหน่งคิวเป็น %d/%d เพื่อไม่ให้ "
            "ชิ้นที่เหลือถูกแปะ ALPL ผิด",
            session_id, qstate["position"], len(qstate.get("queue", [])),
        )
    # ╚═══ ขยับตำแหน่งคิวตอนข้ามชิ้น — จบส่วนที่เพิ่ม ═══════════════════════╝

    # ปลุก Pi "หลัง" ขยับคิวเสร็จแล้วเท่านั้น (ดู docstring)
    #
    # ⚠ ต่างจาก stop: continue สั่งไม่ถึง = **Pi ยังรออยู่เฉยๆ ไม่มีอะไรเดินหน้า**
    #   ตำแหน่งคิวถูกขยับไปแล้วฝั่ง backend แต่ Pi ไม่รู้ตัว จึงต้องบอกผู้ใช้ให้
    #   ชัดว่ากดแล้วไม่ผ่าน จะได้กดซ้ำหรือไปกด Stop — ถ้าเงียบไว้ผู้ใช้จะยืนรอ
    #   เครื่องที่ไม่มีวันขยับ
    agent_err = await _notify_agent_action("continue", session_id)
    if agent_err:
        raise HTTPException(502, f"สั่งให้ Pi วัดชิ้นถัดไปไม่สำเร็จ — {agent_err}")
    return {"ok": True}

@router.post("/api/heartbeat")
def heartbeat(req: HeartbeatRequest):
    """รับ heartbeat จาก Agent (ดู agent.py heartbeat_loop — ยิงมาทุก
    HEARTBEAT_INTERVAL วิ ไม่ว่าจะมี session running อยู่หรือไม่)

    อัปเดต 2 ที่ **คนละที่เก็บกันคนละแบบ** ตามอายุของข้อมูล:

    ① `_pi_last_seen` ใน memory — **ทุกครั้ง ไม่ว่า session_id จะเป็น NULL หรือไม่**
       ตอบคำถาม "ตอนนี้ Pi ยังมีชีวิตอยู่ไหม" ซึ่งสำคัญที่สุดตอน Pi ว่าง
       (คนเปิดเว็บมาดูก่อนกด Start ว่าเครื่องพร้อมไหม) → ชิป PI ในแถบ Session Control

       เก็บใน memory ไม่ลง DB เพราะค่านี้ **หมดอายุใน PI_ONLINE_TIMEOUT วินาที**
       โดยธรรมชาติ — last_seen ของเมื่อ 5 นาทีที่แล้วบอกอะไรไม่ได้เลย ต่างจาก
       ผลการวัด/ทะเบียน ALPL ที่หายไม่ได้ (เคยมีตาราง `pi_status` เก็บสำเนาไว้
       ถอดออกแล้ว ดูเหตุผลที่ mark_pi_seen ใน shared.py)

       ⚠ ต้องทำ **ก่อน** แตะ DB เสมอ · ของเดิม return ทิ้งทันทีตอน Pi ว่าง
         ทำให้ไม่มีที่ไหนบันทึกเลยว่า Pi ยังอยู่

    ② `sessions.last_seen` ใน DB — เฉพาะตอนกำลังวัด ให้ heartbeat_checker() เอาไป
       เทียบว่า session นี้ยังมี Agent ส่งสัญญาณชีพอยู่ไหม · เงื่อนไข `state='running'`
       กันไม่ให้ heartbeat ที่มาช้า/ค้างจาก session เก่าไปอัปเดต session ผิดตัว

       อันนี้ต้องลง DB จริง เพราะ heartbeat_checker ตัดสินจากมันแล้วไปแก้สถานะ
       session ที่เป็นข้อมูลถาวร
    """
    # ── ① memory: ทำก่อนเสมอ และไม่มีทางพลาด ──────────────────────────────
    # เป็นแหล่งความจริงของชิป PI · เขียนฟรี ไม่แตะ DB จึงไม่มีทาง raise
    # ต้องอยู่บรรทัดแรกสุด: ต่อให้ DB ล่มทั้งก้อน ชิปก็ยังบอกได้ถูกว่า Pi ยังอยู่
    mark_pi_seen()

    # ── ② DB: เฉพาะตอนมี session ที่กำลังวัดอยู่ ───────────────────────────
    # Pi ว่าง (session_id เป็น None) → ไม่ต้องแตะ DB เลยสักครั้ง ซึ่งเป็นสถานะ
    # ปกติของเครื่องเกือบทั้งวัน — heartbeat ส่วนใหญ่จึงจบที่ memory ไม่เปิด
    # connection ไป MySQL เลย (get_db ไม่มี pool เปิดใหม่ทุกครั้ง จึงคุ้มมาก)
    #
    # กลืน exception ทิ้ง: heartbeat ต้องไม่พังเพราะ DB มีปัญหา ไม่งั้น Pi จะนับว่า
    # "ติดต่อ Backend ไม่ได้" แล้วหยุดวัดเอง ทั้งที่คุยกันได้ปกติ
    if req.session_id is None:
        return {"ok": True}

    try:
        db = get_db()
        try:
            with db.cursor() as cur:
                cur.execute(
                    "UPDATE sessions SET last_seen = NOW() "
                    "WHERE session_id = %s AND state = 'running'",
                    (req.session_id,),
                )
        finally:
            db.close()
    except Exception as exc:
        log.warning("heartbeat: อัปเดต sessions.last_seen ไม่สำเร็จ: %s", exc)
    return {"ok": True}
