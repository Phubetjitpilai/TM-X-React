import os
import socket
import threading
import time

import httpx
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))
TMX_IP = os.getenv("TMX_HOST", "192.168.10.11")
TMX_PORT = int(os.getenv("TMX_PORT", 8600))
BUFFER_SIZE = 1024

TRIGGER_COMMAND = "T1\r"
TRIGGER_TIMEOUT = 2.0  # วินาที — รอ response จาก TM-X หลังส่ง trigger

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")
AGENT_PORT = int(os.getenv("AGENT_PORT", 9998))

HB_INTERVAL     = float(os.getenv("HEARTBEAT_INTERVAL", 5))
HB_TIMEOUT_HINT = float(os.getenv("HEARTBEAT_TIMEOUT", 15))

MEASURE_TIMEOUT       = float(os.getenv("MEASURE_TIMEOUT", 15))    # รอค่าสูงสุดกี่วินาที
MEASURE_POLL_INTERVAL = float(os.getenv("MEASURE_POLL_INTERVAL", 0.4))

# ── GM: ดึงค่าที่วัดได้จาก TM-X โดยตรง ──────────────────────────────────────
SOCKET_TIMEOUT   = float(os.getenv("SOCKET_TIMEOUT", 5))
GM_POLL_INTERVAL = 0.02                                  # 20 ms
GM_MAX_WAIT      = float(os.getenv("GM_MAX_WAIT", 8))    # รอค่าสูงสุดต่อชิ้น
NO_VALUE_ABS     = 9999.0        # |ค่า| >= นี้ = TM-X ยังวัดไม่เสร็จ/วัดไม่ติด
# T1 ที่โดน ER,...,03 (READY ยังไม่กลับมาหลัง RESET ที่พ่วงมากับ PW) ยิงซ้ำได้
T1_RETRY      = 3
T1_RETRY_WAIT = 0.3

# คำสั่งล้างค่าเก่า — คู่มือหน้า 5-9 พิมพ์ 2 แบบไม่ตรงกันเอง ต้องลองเอง
CLEAR_CANDIDATES = ["MRS", "MSR"]
_clear_cmd = None    # None=ยังไม่ได้ลอง · "MRS"/"MSR"=ตัวที่ใช้ได้ · False=ไม่ผ่านทั้งคู่
MCU_TIMEOUT = float(os.getenv("MCU_TIMEOUT", 10))
def _idx(name, default):
    v = os.getenv(name, default)
    return None if v in ("", "none", "None", None) else int(v)

GM_IDX_X      = _idx("GM_IDX_X", "0")
GM_IDX_Y      = _idx("GM_IDX_Y", "1")
GM_IDX_OFFSET_X = _idx("GM_IDX_OFFSET_X", "6")     # ว่าง = ไม่มี offset ใน GM
GM_IDX_OFFSET_Y = _idx("GM_IDX_OFFSET_Y", "7")     # ว่าง = ไม่มี offset ใน GM

# ── สถานะระดับโมดูล ────────────────────────────────────────────────────────
# ทุกตัวต้องมีค่าตั้งต้นตรงนี้ ห้ามให้ไปเกิดครั้งแรกใน command_flow เท่านั้น
# เพราะ heartbeat_loop รันใน thread แยกตั้งแต่เปิดโปรแกรม = อ่านก่อนที่จะมีใคร
# กด Start → NameError
is_running = False          # ตอนนี้มี session กำลังวัดอยู่ไหม (ไม่ใช่ "สคริปต์รันอยู่ไหม")
current_session_id = None   # session ที่กำลังวัด (None = idle) heartbeat แนบไปด้วย
_tmx_sock = None            # socket ที่ค้างไว้คุย TM-X ให้ stop handler ยิง S0 ได้
_hb_last_ok = time.time()   # เวลาที่ heartbeat ยิงออกสำเร็จครั้งล่าสุด

# "กระดิ่ง" ที่บอกว่าชิ้นงานเข้าที่พร้อมวัดแล้ว — ตอนนี้มาจาก curl /trigger
# พอต่อ MCU จริงค่อยเพิ่ม thread อ่าน Serial แล้วเรียก _trigger.set() บรรทัดเดียว
# ตัวรอไม่ต้องแก้เลย เพราะ Event รับสัญญาณจากหลายแหล่งได้
_trigger = threading.Event()

# ตอนนี้อยู่ในช่วง "รอสัญญาณ" จริงหรือยัง — endpoint ใช้ตอบให้ตรงความจริงว่า
# สัญญาณที่ยิงมาจะถูกใช้หรือถูกทิ้ง ไม่งั้น curl แล้วเครื่องไม่ขยับจะนึกว่าพัง
_waiting_for_trigger = False

http_app = FastAPI()

class Limits(BaseModel):
    x_lo: float; x_hi: float; y_lo: float; y_hi: float
    offset_max: float | None = None

class Group(BaseModel):
    template_name: str
    alpl: list[int]
    limits: Limits | None = None

class CommandRequest(BaseModel):
    action: str
    session_id: int | None = None
    target_count: int | None = None
    groups: list[Group] | None = None

@http_app.post("/command")
async def command(req: CommandRequest):
    global is_running
    if req.action == "start":
        print("\n ได้รับคำสั่ง Start จาก Backend")
        groups = req.groups
        if not groups:
            raise HTTPException(400, "payload ไม่มี `groups`")
        if any(not g.alpl for g in groups):
            raise HTTPException(400, "มีกลุ่มที่ `alpl` ว่างเปล่า")
        if any(g.limits is None for g in groups):
            raise HTTPException(400, "มีกลุ่มที่ไม่ได้ระบุ `limits`")

        all_alpl = [a for g in groups for a in g.alpl]
        if len(set(all_alpl)) != len(all_alpl):
            raise HTTPException(400, "มี ALPL ซ้ำข้ามกลุ่ม")
        if req.target_count != len(all_alpl):
            raise HTTPException(400, f"target_count ({req.target_count}) ไม่เท่ากับจำนวน ALPL รวมทุกกลุ่ม ({len(all_alpl)})")
        templates = {g.template_name for g in groups}
        if len(templates) > 1:
            raise HTTPException(400, f"Pi ยังรองรับ template เดียวต่อ session — ได้มา {sorted(templates)}")
        
        threading.Thread(
            target=command_flow,
            args=(req.session_id, groups, req.target_count),
            daemon=True,
        ).start()
    elif req.action == "stop":
       is_running = False
    else:
        raise HTTPException(
            400,
            f"ไม่รู้จัก action '{req.action}' — ตอนนี้รองรับแค่ start/stop "
            f"(continue ถูกปิดไว้ชั่วคราวพร้อมกับ modal)",
        )
    return {"status": "ok", "action": req.action}

@http_app.api_route("/trigger", methods=["GET", "POST"])
async def trigger():
    """จำลองเซนเซอร์ — ยิงอะไรมาก็ได้ที่ URL นี้ = "ชิ้นงานเข้าที่แล้ว วัดได้เลย"

        curl -X POST http://<ip-ของ-pi>:9998/trigger

    guard 2 ชั้น ตอบให้ตรงความจริงว่าสัญญาณจะถูกใช้หรือถูกทิ้ง — ไม่งั้นยิงมาแล้ว
    เครื่องไม่ขยับจะนึกว่าระบบพัง แล้วหาสาเหตุไม่เจอ
    """
    if not is_running:
        return {"ok": False, "reason": "ไม่มี session กำลังวัดอยู่ — กด Start ที่หน้าเว็บก่อน"}
    if not _waiting_for_trigger:
        # ยิงมาถูกจังหวะแต่ยังไม่ถึงช่วงรอ (กำลังส่ง R0/PW อยู่ หรือกำลังรอผลวัด
        # ของชิ้นก่อนหน้า) — สัญญาณนี้จะโดน _trigger.clear() ล้างทิ้งอยู่ดี
        return {"ok": False,
                "reason": "ยังไม่ถึงช่วงรอสัญญาณ — รอข้อความ 'รอสัญญาณ trigger ...' ก่อนแล้วยิงใหม่"}
    _trigger.set()
    print("⚡ ได้รับสัญญาณ trigger")
    return {"ok": True}


def heartbeat_loop():
    global is_running, _hb_last_ok
    while True:
        try:
            httpx.post(
                f"{BACKEND_URL}/api/heartbeat",
                json={"session_id": current_session_id},
                timeout=5,
            )
            _hb_last_ok = time.time()
        except Exception:
            pass  # backend ล่มชั่วคราวไม่เป็นไร รอบหน้าค่อยยิงใหม่
                  # (ไม่ต้องนับอะไร แค่ "ไม่อัปเดตเวลา" ก็พอ)

        # เช็คนอก try เสมอ — ต้องทำงานทุกรอบไม่ว่ารอบนี้จะยิงออกหรือไม่
        if is_running and time.time() - _hb_last_ok > HB_TIMEOUT_HINT:
            print(f"\n⏹ ติดต่อ Backend ไม่ได้เกิน {HB_TIMEOUT_HINT:g} วิ — หยุดวัด")
            print(f"   (backend น่าจะ mark session เป็น 'timeout' ไปแล้ว วัดต่อไปค่าก็ถูกทิ้ง)")
            is_running = False
        time.sleep(HB_INTERVAL)


def send_command(sock, command):
    cmd_to_send = command + "\r"  # ต้องต่อท้ายด้วยตัวคั่น CR (\r) เสมอ
    sock.sendall(cmd_to_send.encode("ascii"))
    time.sleep(0.1)  # หน่วงเวลาให้กล้องประมวลผลเล็กน้อย
    response = sock.recv(BUFFER_SIZE).decode("ascii").strip()
    return response

def get_measured_count(session_id):
    try:
        data = httpx.get(f"{BACKEND_URL}/api/session/state", timeout=5).json()
    except Exception as exc:
        print(f"   ⚠️ อ่าน session state ไม่ได้: {exc}")
        return None
    if data.get("session_id") != session_id:
        return None
    return data.get("measured_count")

# curl -X POST http://<ip-ของ-pi>:9998/trigger
# วนถามจนกว่ามันจะตอบ is_ready 
def wait_for_trigger_mcu():
    global _waiting_for_trigger
    _trigger.clear()
    _waiting_for_trigger = True
    try:
        while is_running:
            if _trigger.wait(0.1):   # ตื่นทุก 0.1 วิ ไปเช็ค is_running
                return True
        return False
    finally:
        _waiting_for_trigger = False
_mcu_ready = threading.Event()  
_mcu_ack   = threading.Event()  
_mcu_waiting = {"ready": False, "ack": False}

def send_recv(sock, command, timeout=SOCKET_TIMEOUT):
    """ส่ง 1 คำสั่ง แล้ว **วน recv จนเจอ CR** — คืน (response, ok)

    ต่างจาก send_command() ข้างบนที่ใช้ sleep(0.1) + recv ครั้งเดียว ซึ่งผิด 2 อย่าง:
      - sleep เดาเวลาเอา ไม่ได้ช่วยอะไร (recv บล็อกรอข้อมูลอยู่แล้วโดยธรรมชาติ)
        และทำให้ poll GM ทุก 20 ms เป็นไปไม่ได้เลย
      - TCP เป็น stream — recv ครั้งเดียวอาจได้ข้อความมาครึ่งเดียว แล้วพาร์สพัง
        แบบเงียบๆ (GM คืนมายาวมาก 8 เครื่องมือ = 24 ช่อง)

    ⚠ R0/PW ยังใช้ send_command() ตัวเดิมอยู่ ควรย้ายมาใช้ตัวนี้ด้วยตามแผนข้อ 7
    """
    sock.settimeout(timeout)
    deadline = time.time() + timeout
    sock.sendall((command + "\r").encode("ascii"))

    buf = b""
    while b"\r" not in buf:
        remain = deadline - time.time()
        if remain <= 0:
            return "<timeout>", False
        sock.settimeout(remain)
        try:
            chunk = sock.recv(BUFFER_SIZE)
        except socket.timeout:
            return "<timeout>", False
        if not chunk:                       # อีกฝั่งปิด connection
            return "<closed>", False
        buf += chunk

    resp = buf.decode("ascii", "replace").strip()
    return resp, not resp.upper().startswith("ER")


def parse_gm(resp):
    """แยก `GM,t,m,i,j,…` เป็น [(m, i, j), ...] — คืน None ถ้ารูปแบบไม่ตรง

        m = ค่าที่วัดได้
        i = สถานะ  0:ไม่ทำงาน 1:ค่าปกติ 2:แก้ตำแหน่งล้มเหลว 3:ข้อมูลไม่ถูกต้อง 4:รอตัดสิน
        j = ผลตัดสินของ TM-X เอง  0:OK  1:NG

    ไม่ยึดว่าต้องมีกี่เครื่องมือ — `t=0` แปลว่า "ทุกเครื่องมือ" TM-X บอกจำนวนจริงกลับมา
    """
    parts = [p.strip() for p in resp.split(",")]
    if len(parts) < 2 or parts[0].upper() != "GM":
        return None
    try:
        count = int(parts[1])
    except ValueError:
        return None
    body = parts[2:]
    if count == 0:
        count = len(body) // 3
    if count == 0 or len(body) < count * 3:
        return None

    def _int(s):
        try:    return int(s)
        except (ValueError, TypeError): return None

    tools = []
    for k in range(count):
        m_s, i_s, j_s = body[k * 3:k * 3 + 3]
        try:    m = float(m_s)
        except ValueError: m = None
        tools.append((m, _int(i_s), _int(j_s)))
    return tools


def has_real_value(tools):
    """ค่าที่ได้เป็นของจริงหรือยัง — 9999.999 = TM-X ยังวัดไม่เสร็จ/วัดไม่ติด"""
    if not tools:
        return False
    return any(m is not None and abs(m) < NO_VALUE_ABS for m, _, _ in tools)


def clear_measurement(sock):
    """ล้างค่าเก่าใน TM-X ด้วย MRS — **ขั้นที่สำคัญที่สุดของทั้ง flow**

    GM ดึง "ค่าของภาพล่าสุด" และ **ไม่มีเลขลำดับกำกับ** จึงมองไม่ออกว่าค่าที่ได้
    เป็นของชิ้นที่เพิ่งวัดหรือของชิ้นก่อน ถ้า T1 รอบนี้วัดไม่ติด GM จะคืนค่าของ
    ชิ้นก่อนมาให้เฉยๆ ไม่มี error ไม่มีอะไรเตือน แล้วเราจะตัดสินชิ้นใหม่ด้วย
    ตัวเลขของชิ้นเก่า **แล้วสั่ง MCU ขยับของจริงตามนั้น**

    ข้อมูลหน้างาน 31/07: TM-X วัดไม่ติด 7 ครั้งจาก 8 — ไม่ใช่กรณีหายาก

    ⚠ คู่มือหน้า 5-9 พิมพ์ชื่อคำสั่งไม่ตรงกันเอง หัวข้อเขียน `MRS` แต่ช่องส่ง/รับ
      เขียน `MSR` จึงลองทีละตัวแล้วจำตัวที่ใช้ได้ไว้ (ไม่ต้องลองซ้ำทุกชิ้น)
    """
    global _clear_cmd
    if _clear_cmd is False:
        return False
    if _clear_cmd is not None:
        _, ok = send_recv(sock, _clear_cmd)
        return ok

    for cand in CLEAR_CANDIDATES:
        resp, ok = send_recv(sock, cand)
        if ok:
            _clear_cmd = cand
            print(f"   ℹ️ ใช้คำสั่งล้างค่า `{cand}` ได้ (จะใช้ตัวนี้ตลอดทั้ง session)")
            return True
    _clear_cmd = False
    print("   ⚠️ TM-X ไม่รู้จักทั้ง MRS และ MSR — GM อาจคืนค่าของชิ้นก่อนหน้า!")
    return False


def trigger_tmx(sock):
    """ล้างค่าเก่า → ยิง T1 สั่ง TM-X วัด 1 ครั้ง — คืน True ถ้าส่งสำเร็จ

    **ส่งผ่าน sock หลัก ไม่เปิด connection ใหม่** — ต่างจากของเดิม เพราะ TM-X
    ให้มีอุปกรณ์ควบคุมได้ทีละตัวเดียว พอเปิดสายที่สองมันตัดสายแรกทิ้ง แล้ว GM
    ที่ต้องถามตามมาทันทีจะยิงลงสายที่ตายไปแล้ว (และเป็นสาเหตุที่ S0 ตอนจบ
    session ไม่เคยสำเร็จมาก่อนด้วย — ดูแผนข้อ 7 กติกา #2)

    `ER,...,03` = READY ยังไม่กลับมาหลัง RESET ที่พ่วงมากับ PW — **ยิงซ้ำได้
    อย่างปลอดภัย** เพราะรหัส 03 แปลว่าทริกเกอร์ถูก *ละเว้น* ไม่ได้วัดเลย
    จึงไม่มีทางได้ measurement ซ้ำสองอัน
    """
    #clear_measurement(sock)                      # MRS ก่อนเสมอ ห้ามลืม
    
    for attempt in range(1, T1_RETRY + 1):
        resp, ok = send_recv(sock, "T1")
        if ok:
            print(f"📡 TM-X ตอบ T1: {resp}")
            return True
        if ",03" in resp:
            print(f"   ⏳ T1 โดนละเว้น ({resp}) — READY ยังไม่กลับมา ลองใหม่ครั้งที่ {attempt}")
            time.sleep(T1_RETRY_WAIT)
            continue
        print(f"❌ ส่ง T1 ไม่สำเร็จ: {resp}")
        return False
    print(f"❌ ส่ง T1 ไม่สำเร็จหลังลอง {T1_RETRY} ครั้ง")
    return False


def judge(x, y, offset_x, offset_y, limits):
    """ตัดสิน OK/NG จาก limits ที่ Backend คำนวณมาให้ — คืน ("OK"|"NG", เหตุผล[])

    เทียบขอบตรงๆ ไม่ต้องคำนวณอะไรเอง เพราะ Backend บวก/ลบ _TOL_EPS มาให้แล้ว
    `offset_max = None` → โหมดนี้ไม่ตรวจ offset (IPM) ให้ถือว่าผ่าน
    """

    reasons = []
    if x is None:
        reasons.append("อ่านค่า Xไม่ได้ (ค่าเป็น None)")
    elif not (limits.x_lo <= x <= limits.x_hi):
        reasons.append(f"ค่า X ({x:.4f}) นอกช่วงเกณฑ์ ({limits.x_lo:.4f}–{limits.x_hi:.4f})")
    if y is None:
        reasons.append("อ่านค่า Y ไม่ได้ (ค่าเป็น None)")
    elif not (limits.y_lo <= y <= limits.y_hi):
        reasons.append(f"ค่า Y ({y:.4f}) นอกช่วงเกณฑ์ ({limits.y_lo:.4f}–{limits.y_hi:.4f})")
    if limits.offset_max is not None:
        if offset_x is None or abs(offset_x) > limits.offset_max:
            reasons.append(f"offset_x {offset_x} เกิน {limits.offset_max}")
        if offset_y is None or abs(offset_y) > limits.offset_max:
            reasons.append(f"offset_y {offset_y} เกิน {limits.offset_max}")
    return ("NG" if reasons else "OK"), reasons

def clean_tools(tools):
    """คัดกรองเอาเฉพาะข้อมูลที่สถานะ (index 1) ไม่เป็น 0 และ 3"""
    if not tools:
        return []
        # กรองเอาเฉพาะ item ที่สถานะไม่ใช่ 0 หรือ 3 (รองรับทั้ง int และ string)
    return [item for item in tools if str(item[0]) not in ("-9999.999")]

            # ── ดึงค่าออกมาตาม index ที่ตั้งไว้ ────────────────────────────
def _val(idx,tools):
    if idx is None or idx >= len(tools):
        return None
    return tools[idx][0]
            

def get_measurement_tmx(sock, limits, timeout=GM_MAX_WAIT):
    """วน GM จนได้ค่าใหม่ → ตัดสิน OK/NG → พิมพ์ผล

    คืน `(result, x, y, offset)` โดย result เป็น "OK" / "NG" / "UNKNOWN"

    **ทำไมต้องวน**: `T1` ตอบกลับตอน *รับทริกเกอร์* ไม่ใช่ตอนวัดเสร็จ (คู่มือหน้า
    5-4: "เวลาในการประมวลผลการวัดจะไม่ได้รับผลกระทบ") ยิง GM ตามติดจึงยังไม่มีค่า
    ให้ดึง ต้องถามซ้ำทุก ~20 ms จนกว่าจะได้ค่าที่ไม่ใช่ 9999.999

    **"UNKNOWN" เป็นสถานะที่สามที่ต้องมี** ไม่ใช่แค่ OK กับ NG — ครบเวลาแล้วยังไม่
    ได้ค่าแปลว่า TM-X วัดชิ้นนี้ไม่ติดจริง ต้องบอก MCU ว่า "ไม่รู้ผล" แล้วให้มัน
    ตัดสินใจเอง **ห้ามเดาเป็น NG** เพราะของอาจดีอยู่ แค่กล้องไม่เห็น
    """
    deadline = time.time() + timeout
    polls = 0
    t0 = time.time()

    while time.time() < deadline:
        if not is_running:                       # กด Stop ระหว่างรอ
            return "UNKNOWN", None, None, None

        resp, ok = send_recv(sock, "GM,3,0", timeout=2.0)
        polls += 1
        tools = parse_gm(resp) if ok else None
        if tools and has_real_value(tools):
            tools_new = clean_tools(tools)
            print(tools_new)
        
            x, y, offset_x, offset_y = _val(GM_IDX_X,tools_new), _val(GM_IDX_Y,tools_new), _val(GM_IDX_OFFSET_X,tools_new), _val(GM_IDX_OFFSET_Y,tools_new)
            result, reasons = judge(x, y, offset_x, offset_y, limits)

            print(f"   📥 ได้ค่าหลัง {(time.time()-t0)*1000:.0f} ms "
                  f"(ถาม GM {polls} ครั้ง · TM-X คืนมา {len(tools)} เครื่องมือ)")
            print(f"      X={x} · Y={y} · offset_x={offset_x} · offset_y={offset_y} ")
            print(f"   {'✅' if result == 'OK' else '❌'} ผลตัดสิน: {result}")
            for r in reasons:
                print(f"      • {r}")

            # เทียบกับผลที่ TM-X ตัดสินมาเอง (j) — ได้ตัวเฝ้าระวัง config drift ฟรีๆ
            '''j_x = tools[GM_IDX_X][2] if GM_IDX_X is not None and GM_IDX_X < len(tools) else None
            if j_x is not None and limits is not None:
                tmx_says = "OK" if j_x == 0 else "NG"
                if tmx_says != result:
                    print(f"   ⚠️ TM-X ตัดสินว่า {tmx_says} แต่เราคำนวณได้ {result} — "
                          f"tolerance ในโปรแกรมวัดกับใน DB อาจเพี้ยนกันแล้ว")'''
            return result, x, y, offset_x, offset_y

        time.sleep(GM_POLL_INTERVAL)

    print(f"   ⚠️ รอ {timeout:.0f} วิแล้ว GM ยังไม่คืนค่าใหม่ (ถาม {polls} ครั้ง) "
          f"— TM-X วัดชิ้นนี้ไม่ติด")
    return "UNKNOWN", None, None, None

#วนไปถามว่าพร้อมรับ result ยัง ให้ MCU set Flag เอา idle(ยังไม่มีชิ้นงาน) -> obj_is_ready(เมื่อวางชิ้นงานแล้ว) -> waiting_for_result(พร้อมรับ result) -> idle(เสร็จการวัด 1 ชิ้น)
def send_result_to_mcu(result, mcu_timeout=MCU_TIMEOUT):
    """ส่งผลตัดสินให้ MCU — `result` เป็น "OK" / "NG" / "UNKNOWN"

    ตอนนี้ยังไม่มีบอร์ด MCU จริง จึงแค่พิมพ์ให้เห็นว่าส่งอะไรออกไป
    พอต่อ Serial จริงค่อยเปลี่ยนบรรทัดข้างในเป็นการเขียนลงพอร์ต — **ตัวเรียก
    ไม่ต้องแก้เลย** นี่คือเหตุผลที่แยกออกมาเป็นฟังก์ชันตั้งแต่ตอนที่ยังไม่มีอะไร

    ⚠ "UNKNOWN" ต้องส่งไปด้วยเสมอ ห้ามข้ามเงียบๆ — เป็นสถานะที่สามที่ต้องมี
      ไม่ใช่แค่ OK กับ NG · ถ้าไม่ส่ง MCU จะมีชิ้นงานคาอยู่โดยไม่มีคำสั่ง แล้วมัน
      จะไม่มีวันตอบว่า "พร้อม" สำหรับชิ้นถัดไปอีกเลย = ค้างกันทั้งคู่
      **ห้ามเดา UNKNOWN เป็น NG** เพราะของอาจดีอยู่ แค่กล้องไม่เห็น

    `mcu_timeout` ยังไม่ได้ใช้ — รับไว้ก่อนเพื่อให้ signature นิ่ง ไว้ใช้ตอนเพิ่ม
    การรอ MCU ตอบรับ (`wait_mcu_ack` ผ่าน `_mcu_ack` ที่ประกาศไว้แล้วข้างบน)
    """
    icon = {"OK": "✅", "NG": "❌", "UNKNOWN": "❓"}.get(result, "•")
    print(f"   🔀 → MCU: {icon} {result}")
    return True


def wait_for_measurement(session_id, count_before, timeout=MEASURE_TIMEOUT):

    deadline = time.time() + timeout
    while time.time() < deadline:
        if not is_running: #ถ้า Stop
            return True
        count_after = get_measured_count(session_id) 
        if count_after is not None and count_before is not None and count_after > count_before:
            return True
        time.sleep(MEASURE_POLL_INTERVAL)
    return False

def command_flow(session_id, groups, target_count):

    global current_session_id, is_running, _tmx_sock, _hb_last_ok
    _hb_last_ok = time.time()
    current_session_id = session_id  # heartbeat จะเริ่มแนบ session นี้ทันที
    is_running = True
    client_socket = None
    stop_reason = None

    try:
        print(f"\n{'='*60}")
        print(f"✅ ได้รับคำสั่ง Start จาก Backend")
        print(f"   session_id    : {session_id}")
        print(f"   target_count  : {target_count}  ← จำนวนชิ้นที่จะวัดรอบนี้")
        for gi, g in enumerate(groups, 1):
            print(f"   กลุ่มที่ {gi}      : template={g.template_name!r} "
                  f"ALPL={g.alpl}")
            if g.limits:
                L = g.limits
                print(f"                   X {L.x_lo:.4f}–{L.x_hi:.4f} · "
                      f"Y {L.y_lo:.4f}–{L.y_hi:.4f} · offset_max={L.offset_max}")
        print(f"{'='*60}")
        template_name = groups[0].template_name

        try:
            client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client_socket.settimeout(5.0)
            client_socket.connect((TMX_IP, TMX_PORT))
        except Exception as exc:
            print(f"\n❌ ต่อ TM-X ที่ {TMX_IP}:{TMX_PORT} ไม่ได้ — {type(exc).__name__}: {exc}")
            print("   ตรวจ: สาย LAN ต่ออยู่ไหม · TM-X เปิดอยู่ไหม · TMX_HOST/TMX_PORT ใน .env ถูกไหม")
            print("   → กด Stop ที่หน้าเว็บเพื่อล้าง session นี้ แล้วลองใหม่")
            #stop_reason = (f"ต่อ TM-X ที่ {TMX_IP}:{TMX_PORT} ไม่ได้ ({type(exc).__name__}) "f"— ตรวจสาย LAN · TM-X เปิดอยู่ไหม · TMX_HOST/TMX_PORT ใน .env")
            return

        _tmx_sock = client_socket  # ให้ stop handler ยิง S0 ผ่าน socket นี้ได้

        # Running (เข้าโหมดดำเนินงาน)
        print(f"→ R0 : {send_command(client_socket, 'R0')}")
        time.sleep(0.5)

        # Load Program ตาม template ที่ backend ส่งมา (zero-pad เป็น 3 หลัก)
        pw = f"PW,1,{str(template_name).zfill(3)}"
        print(f"→ {pw} : {send_command(client_socket, pw)}")
        time.sleep(1.0)

        for piece in range(1, target_count + 1):
            if not is_running:
                print("⏹ ได้รับคำสั่ง Stop — หยุดการวัด")
                break
            # ── ① รอ MCU บอกว่าชิ้นงานเข้าที่แล้ว (ตอนนี้ = curl /trigger) ──
            print(f"\nชิ้นที่ {piece}/{target_count} — รอสัญญาณ trigger ...")
            if not wait_for_trigger_mcu():
                print("⏹ ได้รับคำสั่ง Stop — หยุดการวัด")
                break

            # อ่านให้ชิดกับ T1 ที่สุด — ช่วงรอสัญญาณข้างบนกินเวลาเป็นนาทีได้
            # ถ้าอ่านก่อนรอ แล้วค่าของชิ้นก่อนที่มาช้าหลุดเข้ามาระหว่างนั้น
            # measured_count จะขยับตั้งแต่ยังไม่ได้ยิง T1 ของชิ้นนี้
            count_before = get_measured_count(session_id)

            # ── ② MRS ล้างค่าเก่า แล้วยิง T1 (ผ่านสายหลัก) ─────────────────
            if not trigger_tmx(client_socket):
                print(f"   ⚠️ ยิง T1 ไม่สำเร็จ — ข้ามชิ้นที่ {piece}")
                continue

            # ── ③ วน GM จนได้ค่า แล้วตัดสิน OK/NG ───────────────────────────
            result, x, y, offset_x, offset_y = get_measurement_tmx(client_socket, groups[0].limits)

            # ── ④ ส่งผลให้ MCU ไปคัดแยก — ส่งทุกชิ้นรวมถึง UNKNOWN ─────────
            send_result_to_mcu(result)
            # TODO: รอ MCU ตอบรับ (wait_mcu_ack) ก่อนไปชิ้นถัดไป — ยังไม่ทำ

            if not is_running:
                print("⏹ ได้รับคำสั่ง Stop — หยุดการวัด")
                break
            # ── รอยืนยันว่าค่าเข้า DB จริง ก่อนไปชิ้นถัดไป ────────────────── ถ้า wait_for_measurement return true 
            if wait_for_measurement(session_id, count_before): 
                if is_running:
                    print(f"   ✅ ชิ้นที่ {piece}/{target_count} บันทึกแล้ว")
                continue
            print(f"\n⚠️ ชิ้นที่ {piece}/{target_count}: รอ {MEASURE_TIMEOUT:.0f} วิแล้วไม่ได้รับค่าการวัด")
            break

    except Exception as exc:
        print(f"\n❌ session พังกลางทาง — {type(exc).__name__}: {exc}")
        #stop_reason = f"session พังกลางทาง — {type(exc).__name__}: {exc}" 
    finally:
        if client_socket is not None:
            try:
                client_socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass  # อีกฝั่งตัดไปก่อนแล้ว หรือ socket ถูกปิดจาก stop handler
            try:
                client_socket.close()
            except Exception:
                pass
        _tmx_sock = None
        is_running = False
        current_session_id = None  # heartbeat กลับไปยิงแบบ idle (ไม่แนบ session)
        print("\n✅ จบ session — ปิดการเชื่อมต่อ TM-X แล้ว")
        try:
            st = httpx.get(f"{BACKEND_URL}/api/session/state", timeout=5).json()
            if st.get("session_id") == session_id and st.get("state") == "running":
                httpx.post(
                    f"{BACKEND_URL}/api/session/stop",
                    json={"session_id": session_id, "reason": stop_reason},
                    timeout=10,
                )
                print(f"⏹ แจ้ง backend ปิด session แล้ว "
                      f"(วัดได้ {st.get('measured_count')}/{target_count} — ไม่ครบ)")
        except Exception as exc:
            print(f"   ⚠️ แจ้งปิด session ไม่ได้: {exc} — "
                  f"backend จะปิดเองใน ~{HB_TIMEOUT_HINT:g} วิ (ขึ้นเป็น 'timeout')")


if __name__ == "__main__":
    # heartbeat ต้องเริ่ม "ก่อน" เปิด server และรันตลอดอายุโปรแกรมใน daemon thread
    threading.Thread(target=heartbeat_loop, daemon=True).start()

    print("─" * 66)
    print("Pi.py — รอคำสั่ง Start จาก Backend")
    print(f"  ฟัง /command ที่    : 0.0.0.0:{AGENT_PORT}   (.env: AGENT_PORT)")
    print(f"  TM-X ที่            : {TMX_IP}:{TMX_PORT}    (.env: TMX_HOST/TMX_PORT)")
    print(f"  Backend ที่         : {BACKEND_URL}          (.env: BACKEND_URL)")
    print(f"  heartbeat ทุก       : {HB_INTERVAL:g} วิ · หยุดเองถ้าขาดติดต่อเกิน {HB_TIMEOUT_HINT:g} วิ")
    print(f"  รอค่าการวัดสูงสุด    : {MEASURE_TIMEOUT:g} วิ (poll ทุก {MEASURE_POLL_INTERVAL:g} วิ)")
    # แยก 2 บรรทัดโดยตั้งใจ — เดิมพิมพ์ "curl -X POST http://..." ติดกันบรรทัดเดียว
    # แล้วมีคนก๊อปทั้งบรรทัดไปวางในช่อง address ของเบราว์เซอร์ ได้ URL เพี้ยนเป็น
    #   http://127.0.0.1:9998/curl%20-X%20POST%20http://...
    # (%20 = ช่องว่าง) · บรรทัดล่างจึงเป็น URL ล้วนที่ก๊อปแล้ววางได้ทันที
    print(f"  จำลองเซนเซอร์ (เบราว์เซอร์): http://127.0.0.1:{AGENT_PORT}/trigger")
    print(f"  จำลองเซนเซอร์ (เทอร์มินัล) : curl -X POST http://127.0.0.1:{AGENT_PORT}/trigger")
    print(f"     ยิงจากเครื่องอื่นให้เปลี่ยน 127.0.0.1 เป็น IP ของ Pi")
    print("─" * 66)

    # ── เตือนถ้า heartbeat ตั้งค่าไม่สัมพันธ์กัน ────────────────────────────
    # ต้อง INTERVAL × 2 ≤ TIMEOUT เป็นอย่างน้อย เพื่อให้ทนบีตหาย 1 ครั้งได้
    #
    # ถ้าตั้งเท่ากันเป๊ะ (เช่น 5/5) จะไม่มีระยะเผื่อเลยแม้แต่มิลลิวินาทีเดียว —
    # บีตต้องมาตรงเวลาพอดีทุกครั้งถึงจะรอด ซึ่งเป็นไปไม่ได้จริงเพราะมี network
    # latency + เวลาที่ MySQL เขียน UPDATE + GC ของ Python · ผลคือ backend
    # ฆ่า session ทิ้งเองกลางการวัด (ทิ้งคิวด้วย กู้ไม่ได้) โดยไม่มีสาเหตุจริง
    # แล้วหน้าเว็บขึ้นว่า 'timeout' ซึ่งชี้ไปที่ "Pi ตาย" ทั้งที่ Pi ปกติดี
    if HB_INTERVAL * 2 > HB_TIMEOUT_HINT:
        print(f"⚠️  HEARTBEAT_INTERVAL ({HB_INTERVAL:g}s) ถี่ไม่พอเมื่อเทียบกับ "
              f"HEARTBEAT_TIMEOUT ({HB_TIMEOUT_HINT:g}s)")
        print(f"    แนะนำให้ HEARTBEAT_INTERVAL ไม่เกิน {HB_TIMEOUT_HINT/2:g}s "
              f"— แก้ที่ .env\n")

    # port ต้องตรงกับ AGENT_PORT ที่ main.py ใช้ยิงมา
    uvicorn.run(http_app, host="0.0.0.0", port=AGENT_PORT)
