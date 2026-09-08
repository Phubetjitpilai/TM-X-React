import os
import socket
import threading
import time

import httpx
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# ── ตั้ง logging ─────────────────────────────────────────────────────────
# ทุกบรรทัดจะมี timestamp นำหน้า จำเป็นตอนรันเป็น service แบบไม่มีหน้าต่าง
# แล้วมาเปิดไฟล์ log อ่านทีหลัง — ไม่มีเวลากำกับจะไล่ลำดับเหตุการณ์ไม่ได้เลย
#
# ⚠ ป้าย [Pi] ไว้แยกจาก [Server] ของ Backend เวลาเอา log 2 เครื่องมาวางเทียบกัน
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [Pi] %(message)s")
log = logging.getLogger(__name__)

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))
TMX_IP = os.getenv("TMX_HOST", "192.168.10.11")
TMX_PORT = int(os.getenv("TMX_PORT", 8600))
BUFFER_SIZE = 1024

TRIGGER_COMMAND = "T1\r"

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")
AGENT_PORT = int(os.getenv("AGENT_PORT", 9998))

HB_INTERVAL     = float(os.getenv("HEARTBEAT_INTERVAL", 5))
HB_TIMEOUT_HINT = float(os.getenv("HEARTBEAT_TIMEOUT", 15))

MEASURE_TIMEOUT       = float(os.getenv("MEASURE_TIMEOUT", 15))    # รอค่าสูงสุดกี่วินาที
MEASURE_POLL_INTERVAL = float(os.getenv("MEASURE_POLL_INTERVAL", 0.4))

SOCKET_TIMEOUT   = float(os.getenv("SOCKET_TIMEOUT", 5))
# ── GM: ดึงค่าที่วัดได้จาก TM-X โดยตรง ──────────────────────────────────────
GM_POLL_INTERVAL = 0.02                                  # 20 ms
GM_MAX_WAIT      = float(os.getenv("GM_MAX_WAIT", 8))    # รอค่าสูงสุดต่อชิ้น
NO_VALUE_ABS     = 9999.0        # |ค่า| >= นี้ = TM-X ยังวัดไม่เสร็จ/วัดไม่ติด
# T1 ที่โดน ER,...,03 (READY ยังไม่กลับมาหลัง RESET ที่พ่วงมากับ PW) ยิงซ้ำได้

T1_RETRY = int(os.getenv("T1_RETRY", 3))
T1_RETRY_WAIT = float(os.getenv("T1_RETRY_WAIT", 0.3))

# รอกี่วินาทีหลังส่ง `PW` ก่อนจะเริ่มวัด — TM-X ต้องโหลดโปรแกรมจากการ์ด SD
# และ RESET ที่พ่วงมาทำให้ READY ดับชั่วคราว ยิง `T1` เร็วเกินไปจะได้ `ER,T1,03`
#
# ⚠ ตัวนี้ถูกใช้ **ทุกครั้งที่ข้ามรอยต่อกลุ่ม** ไม่ใช่แค่ตอนเริ่ม session แล้ว
#   ตั้งสูงไปจะช้าทุกกลุ่ม ตั้งต่ำไปชิ้นแรกของกลุ่มจะพังแล้วเด้งถามผู้ใช้
PW_LOAD_WAIT = float(os.getenv("PW_LOAD_WAIT", 1.0))

# รอคำตอบของ `PW` ได้นานกว่าคำสั่งอื่น — TM-X ต้องโหลดโปรแกรมจากการ์ด SD ก่อน
# ถึงจะตอบกลับ วัดจริงที่หน้างานได้ **2.7 วินาที** (log 8 ก.ย. 2569)
#
# ⚠ ห้ามใช้ `SOCKET_TIMEOUT` (5 วิ) เฉย ๆ — เฉียดเกินไป การ์ด SD ที่ช้ากว่านี้
#   หรือโปรแกรมวัดที่ใหญ่กว่าจะทำให้ session พังทั้งรอบตรงชิ้นแรกของกลุ่ม
PW_CMD_TIMEOUT = float(os.getenv("PW_CMD_TIMEOUT", 10))

MAX_ASK_USER_ROUNDS = int(os.getenv("MAX_ASK_USER_ROUNDS", 4))

_answer_event  = threading.Event()
_answer_action = None                  # "retry" | "stop" | None
_answer_lock   = threading.Lock()

# รอคำตอบจากคนได้นานสุดกี่วิ — ต้อง **มากกว่า** ตัวนับถอยหลังในหน้าเว็บ (60 วิ)
# เพราะคนกดหยุดเองหรือหน้าเว็บกดให้อัตโนมัติก็ตาม คำตอบจะวิ่งกลับมาทางเดียวกัน
# ตัวนี้เป็นแค่ตาข่ายกันค้างถาวรตอนหน้าเว็บไม่ได้เปิดอยู่เลย
ASK_USER_TIMEOUT = float(os.getenv("ASK_USER_TIMEOUT", 70))

# คำสั่งล้างค่าเก่า — คู่มือหน้า 5-9 พิมพ์ 2 แบบไม่ตรงกันเอง ต้องลองเอง
CLEAR_CANDIDATES = ["MRS", "MSR"]
_clear_cmd = None    # None=ยังไม่ได้ลอง · "MRS"/"MSR"=ตัวที่ใช้ได้ · False=ไม่ผ่านทั้งคู่
MCU_TIMEOUT = float(os.getenv("MCU_TIMEOUT", 10))
def _idx(name, default):
    v = os.getenv(name, default)
    return None if v in ("", "none", "None", None) else int(v)

GM_IDX_X      = _idx("GM_IDX_X", "0")
GM_IDX_Y      = _idx("GM_IDX_Y", "1")
# ระยะ opening 4 ด้าน — จับเป็น 2 คู่แกน ไม่ใช่ 4 มุม
#
# ⚠⚠ ชื่อคีย์เปลี่ยนแล้ว (เดิม GM_IDX_TR/TL/BL/BR_OFFSET) — **ต้องแก้ `.env` บน
#     เครื่อง Pi จริงให้ตรงด้วย** ไม่งั้น `_idx()` จะหาคีย์ไม่เจอแล้ว **คืนค่า
#     default ให้เงียบๆ ไม่มี error** ถ้าเครื่องนั้นเคยตั้งช่องไว้ไม่ตรงกับ
#     default มันจะอ่านค่าจากช่องผิดตลอดทั้ง session โดยไม่มีอะไรเตือนเลย
GM_IDX_HORIZON_LEFT    = _idx("GM_IDX_HORIZON_LEFT", "2")
GM_IDX_HORIZON_RIGHT   = _idx("GM_IDX_HORIZON_RIGHT", "3")
GM_IDX_VERTICAL_TOP    = _idx("GM_IDX_VERTICAL_TOP", "4")
GM_IDX_VERTICAL_BOTTOM = _idx("GM_IDX_VERTICAL_BOTTOM", "5")
GM_IDX_OFFSET_X = _idx("GM_IDX_OFFSET_X", "6")    
GM_IDX_OFFSET_Y = _idx("GM_IDX_OFFSET_Y", "7") 

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
    global is_running, _answer_action
    if req.action == "start":
        try:
            httpx.post(f"{BACKEND_URL}/api/heartbeat",
                json={"session_id": current_session_id, "waiting_for_trigger": _waiting_for_trigger},
                timeout=5)
        except Exception:
            pass
        log.info("\n ได้รับคำสั่ง Start จาก Backend")
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
        if any(not g.template_name for g in groups):
            raise HTTPException(400, "มีกลุ่มที่ไม่ได้ระบุ `template_name`")

        with _answer_lock:
            _answer_action = None
            _answer_event.clear()
        
        threading.Thread(
            target=command_flow,
            args=(req.session_id, groups, req.target_count),
            daemon=True,
        ).start()

    elif req.action == "retry":
        with _answer_lock:
            _answer_action = "retry"
        _answer_event.set()

    elif req.action == "accept":
        # ผู้ใช้กด "รับค่าจาก Pi (ไม่มีรูป)" — ใช้เฉพาะเคสที่ wait_for_measurement
        # หมดเวลา คือ **วัดสำเร็จแล้วแต่ค่าไม่ถึง DB** (Recieve ส่งไม่ถึง)
        #
        # ⚠ ไม่ใช่การวัดใหม่ — ชิ้นงานถูก MCU คัดแยกออกไปแล้ว ไม่มีอะไรให้วัด
        #   Pi แค่ POST ค่าที่อ่านจาก GM ไว้แล้วเข้า /api/measurements เอง
        #
        # ⚠ ห้ามแตะ is_running เหมือน retry — session ยังเดินต่อหลังบันทึกเสร็จ
        log.info("📥 ได้รับคำสั่ง Accept จาก Backend")
        with _answer_lock:
            _answer_action = "accept"
        _answer_event.set()    

    elif req.action == "trigger":
        # ปุ่มจำลองทริกเกอร์บนหน้าเว็บ (ใช้ชั่วคราวระหว่างที่ยังไม่มี MCU)
        #
        # เส้นทางคือ เบราว์เซอร์ → Backend → ที่นี่ **ไม่ให้เบราว์เซอร์ยิงตรงมา**
        # เพราะหน้าเว็บจะต้องรู้ IP ของ Pi เอง และต้องเปิด CORS ที่นี่เพิ่ม
        #
        # guard ชุดเดียวกับ /trigger เป๊ะ แต่ตอบเป็น HTTP error แทน {"ok": False}
        # เพื่อให้ Backend แยกออกว่าถูกปฏิเสธ ไม่ใช่สำเร็จ แล้วส่งเหตุผลถึงหน้าเว็บได้
        if not is_running:
            raise HTTPException(400, "ไม่มี session กำลังวัดอยู่ — กด Start ที่หน้าเว็บก่อน")
        if not _waiting_for_trigger:
            raise HTTPException(
                409,
                "ยังไม่ถึงช่วงรอสัญญาณ — ระบบกำลังโหลดโปรแกรมวัด "
                "หรือกำลังรอผลของชิ้นก่อนหน้าอยู่",
            )
        _trigger.set()
        log.info("⚡ ได้รับสัญญาณ trigger (จากปุ่มบนหน้าเว็บ)")

    elif req.action == "stop":
        is_running = False
        # ⚠ ต้อง set ด้วย ไม่งั้นกด Stop ตอน modal เปิดอยู่
        #   ask_user() จะค้างรอต่ออีก 90 วิทั้งที่ session จบไปแล้ว
        with _answer_lock:
            _answer_action = "stop"
        _answer_event.set()
    else:
        raise HTTPException(
            400,
            f"ไม่รู้จัก action '{req.action}' — ตอนนี้รองรับแค่ "
            f"start/stop/retry/accept/trigger",
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
    log.info("⚡ ได้รับสัญญาณ trigger")
    return {"ok": True}


def heartbeat_loop():
    global is_running, _hb_last_ok
    while True:
        try:
            httpx.post(
                f"{BACKEND_URL}/api/heartbeat",
                json={
                    "session_id": current_session_id,
                    "waiting_for_trigger": _waiting_for_trigger,
                },
                timeout=5,
            )
            _hb_last_ok = time.time()
        except Exception:
            pass  # backend ล่มชั่วคราวไม่เป็นไร รอบหน้าค่อยยิงใหม่
                  # (ไม่ต้องนับอะไร แค่ "ไม่อัปเดตเวลา" ก็พอ)

        # เช็คนอก try เสมอ — ต้องทำงานทุกรอบไม่ว่ารอบนี้จะยิงออกหรือไม่
        if is_running and time.time() - _hb_last_ok > HB_TIMEOUT_HINT:
            log.info(f"\n⏹ ติดต่อ Backend ไม่ได้เกิน {HB_TIMEOUT_HINT:g} วิ — หยุดวัด")
            log.info(f"   (backend น่าจะ mark session เป็น 'timeout' ไปแล้ว วัดต่อไปค่าก็ถูกทิ้ง)")
            is_running = False
        time.sleep(HB_INTERVAL)


def send_command(sock, command, timeout=SOCKET_TIMEOUT):
    """ส่ง 1 คำสั่งแล้ว `recv` ครั้งเดียว — ใช้กับ R0 / PW ที่คำตอบสั้นและมาทีเดียว

    ⚠⚠ **ต้อง `settimeout` เองทุกครั้ง ห้ามพึ่งค่าที่ติดมากับ socket** —
      `send_recv()` เปลี่ยนค่าบน socket ตัวเดียวกันแล้ว **ไม่คืนค่าเดิม** ถ้า
      ฟังก์ชันนี้ไม่ตั้งเอง มันจะรับมรดกค่าล่าสุดที่ใครก็ไม่รู้ตั้งทิ้งไว้

      เคยพังมาแล้วจริง (8 ก.ย. 2569): การวน `GM` ใช้ `timeout=2.0` พอจบลูป
      ค่านั้นค้างบน socket · ชิ้นแรกของกลุ่มที่ 2 ยิง `PW` แล้ว TM-X ตอบใน
      2.7 วิ (ต้องโหลดโปรแกรมจากการ์ด SD ก่อน) แต่ timeout เหลือ 2.0 →
      `TimeoutError` → session พังทั้งรอบ · `PW` ตัวแรกรอดเพราะตอนนั้น
      `send_recv` ยังไม่เคยรัน ค่ายังเป็น 5.0 ที่ตั้งไว้ตอน connect

    ⚠ `recv` ครั้งเดียวไม่ได้วนหา CR แบบ `send_recv` — ถ้าคำตอบยาวจนมาไม่ครบ
      ในทีเดียวจะได้มาครึ่งเดียวแล้วพาร์สเพี้ยนเงียบ ๆ · ใช้ได้เพราะ R0/PW
      ตอบสั้นมาก (2 ตัวอักษร) ถ้าจะเอามาใช้กับคำสั่งที่คืนค่ายาวให้ย้ายไปใช้
      `send_recv()` แทน
    """
    sock.settimeout(timeout)
    cmd_to_send = command + "\r"  # ต้องต่อท้ายด้วยตัวคั่น CR (\r) เสมอ
    sock.sendall(cmd_to_send.encode("ascii"))
    time.sleep(0.1)  # หน่วงเวลาให้กล้องประมวลผลเล็กน้อย
    response = sock.recv(BUFFER_SIZE).decode("ascii").strip()
    return response

def get_measured_count(session_id):
    try:
        data = httpx.get(f"{BACKEND_URL}/api/session/state", timeout=5).json()
    except Exception as exc:
        log.info(f"   ⚠️ อ่าน session state ไม่ได้: {exc}")
        return None
    if data.get("session_id") != session_id:
        return None
    return data.get("measured_count")

# curl -X POST http://<ip-ของ-pi>:9998/trigger
# วนถามจนกว่ามันจะตอบ is_ready 
# รอ Trigger จาก MCU
def wait_for_trigger_mcu():
    log.info("arrive")
    global _waiting_for_trigger
    _trigger.clear()
    _waiting_for_trigger = True
    # บอก Backend ทันทีว่าพร้อมรับ trigger — ไม่ต้องรอ heartbeat รอบถัดไป
    #
    # ⚠ timeout สั้นมากโดยตั้งใจ เพราะบรรทัดนี้อยู่ใน **เธรดที่กำลังวัดงาน**
    #   ถ้า Backend ช้าหรือค้าง Pi จะหยุดรอตรงนี้ก่อนเข้าลูปรอสัญญาณ ทำให้เกิด
    #   อาการ "กดปุ่มแล้วเครื่องไม่ขยับ" ซึ่งหาสาเหตุยากมาก
    #   ส่งไม่ทันก็ไม่เป็นไร — heartbeat รอบปกติจะตามมาใน HB_INTERVAL วิอยู่แล้ว
    try:
        httpx.post(f"{BACKEND_URL}/api/heartbeat",
            json={"session_id": current_session_id, "waiting_for_trigger": _waiting_for_trigger},
            timeout=0.5)
    except Exception:
        pass
    try:
        while is_running:
            if _trigger.wait(0.1):
                return True
        return False
    finally:
        _waiting_for_trigger = False
        # บอก Backend ทันทีว่าไม่รอแล้ว → ปุ่มดับเลย
        try:
            httpx.post(f"{BACKEND_URL}/api/heartbeat",
                json={"session_id": current_session_id, "waiting_for_trigger": _waiting_for_trigger},
                timeout=5)
        except Exception:
            pass

def send_recv(sock, command, timeout=SOCKET_TIMEOUT):
    """ส่ง 1 คำสั่ง แล้ว **วน recv จนเจอ CR** — คืน (response, ok)
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
            log.info(f"   ℹ️ ใช้คำสั่งล้างค่า `{cand}` ได้ (จะใช้ตัวนี้ตลอดทั้ง session)")
            return True
    _clear_cmd = False
    log.info("   ⚠️ TM-X ไม่รู้จักทั้ง MRS และ MSR — GM อาจคืนค่าของชิ้นก่อนหน้า!")
    return False


def trigger_tmx(sock):
    """ล้างค่าเก่า → ยิง T1 สั่ง TM-X วัด 1 ครั้ง — คืน (ok, resp)

    **ส่งผ่าน sock หลัก ไม่เปิด connection ใหม่** — TM-X ให้มีอุปกรณ์ควบคุมได้
    ทีละตัวเดียว พอเปิดสายที่สองมันตัดสายแรกทิ้ง แล้ว GM ที่ต้องถามตามมาทันที
    จะยิงลงสายที่ตายไปแล้ว

    `ER,...,03` = READY ยังไม่กลับมาหลัง RESET ที่พ่วงมากับ PW — **ยิงซ้ำได้
    อย่างปลอดภัย** เพราะรหัส 03 แปลว่าทริกเกอร์ถูก *ละเว้น* ไม่ได้วัดเลย
    จึงไม่มีทางได้ measurement ซ้ำสองอัน
    """
    clear_measurement(sock)          # MRS ก่อนเสมอ ห้ามลืม
    for attempt in range(1, T1_RETRY + 1):
        resp, ok = send_recv(sock, "T1")
        log.info(resp)
        if ok:
            log.info(f"📡 TM-X ตอบ T1: {resp}")
            log.info(f"ส่ง T1 สำเร็จหลังลอง {T1_RETRY} ครั้ง  {resp}")
            return True, resp
        if ",03" in resp:
            log.info(f"   ⏳ T1 โดนละเว้น ({resp}) — READY ยังไม่กลับมา "
                  f"ลองใหม่ครั้งที่ {attempt}/{T1_RETRY}")
            time.sleep(T1_RETRY_WAIT)
            continue
        log.info(f"❌ ส่ง T1 ไม่สำเร็จ: {resp}")
        return False, resp

    log.info(f"❌ ส่ง T1 ไม่สำเร็จหลังลอง {T1_RETRY} ครั้ง")
    return False, f"{resp} (ลองครบ {T1_RETRY} ครั้ง)"


def judge(x, y, offset_x, offset_y, limits):
    """ตัดสิน OK/NG จาก limits ที่ Backend คำนวณมาให้ — คืน ("OK"|"NG", เหตุผล[])

    เทียบขอบตรงๆ ไม่ต้องคำนวณอะไรเอง เพราะ Backend ปัดทศนิยมมาให้เรียบร้อยแล้ว
    (ดู `_limits_of` ใน `routers/session.py`)

    ⚠ **ห้ามปัดค่า x/y ซ้ำที่นี่** — ค่าฝั่งนี้มาจากการ parse ข้อความ `GM` ตรง ๆ
      ไม่เคยผ่านคอลัมน์ FLOAT จึงไม่มีหางให้ต้องปัด · `float("8.05")` กับขอบที่
      backend ปัดมาแล้วเป็น double ตัวเดียวกันเป๊ะอยู่แล้ว ปัดซ้ำมีแต่จะทำให้
      กฎการปัดไปอยู่ 2 ที่แล้วเพี้ยนกันวันหลัง

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
    if not tools:
        return []
    return [item for item in tools if item[0] is not None and item[0] >= 0]

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
            return "UNKNOWN", None, None, None, None, None, None, None, None

        resp, ok = send_recv(sock, "GM,3,0", timeout=2.0)
        polls += 1
        tools = parse_gm(resp) if ok else None
        if tools and has_real_value(tools):
            tools_new = clean_tools(tools)
            log.info(tools_new)
        
            x, y, horizon_left, horizon_right, vertical_top, vertical_bottom, offset_x, offset_y = (
            _val(GM_IDX_X,tools_new),
            _val(GM_IDX_Y,tools_new),
            _val(GM_IDX_HORIZON_LEFT,tools_new),
            _val(GM_IDX_HORIZON_RIGHT,tools_new),
            _val(GM_IDX_VERTICAL_TOP,tools_new),
            _val(GM_IDX_VERTICAL_BOTTOM,tools_new),
            _val(GM_IDX_OFFSET_X,tools_new), 
            _val(GM_IDX_OFFSET_Y,tools_new)
             )
            result, reasons = judge(x, y, offset_x, offset_y, limits)

            log.info("   📥 ได้ค่าหลัง %.0f ms (ถาม GM %s ครั้ง · TM-X คืนมา %s เครื่องมือ)",
                     (time.time() - t0) * 1000, polls, len(tools))
            log.info("      X=%s · Y=%s · offset_x=%s · offset_y=%s", x, y, offset_x, offset_y)
            log.info("   %s ผลตัดสิน: %s", "✅" if result == "OK" else "❌", result)
            for r in reasons:
                log.info("      • %s", r)

            # เทียบกับผลที่ TM-X ตัดสินมาเอง (j) — ได้ตัวเฝ้าระวัง config drift ฟรีๆ
            '''j_x = tools[GM_IDX_X][2] if GM_IDX_X is not None and GM_IDX_X < len(tools) else None
            if j_x is not None and limits is not None:
                tmx_says = "OK" if j_x == 0 else "NG"
                if tmx_says != result:
                    print(f"   ⚠️ TM-X ตัดสินว่า {tmx_says} แต่เราคำนวณได้ {result} — "
                          f"tolerance ในโปรแกรมวัดกับใน DB อาจเพี้ยนกันแล้ว")'''
            return result, x, y, horizon_left, horizon_right,vertical_top, vertical_bottom,offset_x, offset_y
        time.sleep(GM_POLL_INTERVAL)

    log.info("   ⚠️ รอ %.0f วิแล้ว GM ยังไม่คืนค่าใหม่ (ถาม %s ครั้ง) "
             "— TM-X วัดชิ้นนี้ไม่ติด", timeout, polls)
    return "UNKNOWN", None, None, None, None, None, None, None, None

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
    log.info("   🔀 → MCU: %s %s", icon, result)
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


def report(event: str, detail: str, *, persist: bool = True):
    log.info("   📣 %s: %s", event, detail)
    try:
        resp = httpx.post(
            f"{BACKEND_URL}/api/session/event",
            json={"event": event, "detail": detail, "persist": persist},
            timeout=2,
        )
        if resp.status_code != 200:
            log.info("   ⚠️ Backend ไม่รับรายงาน (HTTP %s)", resp.status_code)
    except Exception as exc:
        log.info("   ⚠️ แจ้ง Backend ไม่สำเร็จ: %s", exc)

def ask_user(session_id, piece, target) -> str:
    global _answer_action
    with _answer_lock:
        _answer_action = None
        _answer_event.clear()

    try:
        resp = httpx.post(
            f"{BACKEND_URL}/api/measure-timeout",
            json={"session_id": session_id, "piece": piece, "target": target},
            timeout=5,
        )
        if resp.status_code != 200:
            log.info("   ⚠️ Backend ไม่รับคำถาม (HTTP %s) — ถือว่าหยุด", resp.status_code)
            return "stop"
    except Exception as exc:
        log.info("   ⚠️ ถามผู้ใช้ไม่ได้: %s — ถือว่าหยุด", exc)
        return "stop"

    log.info("   ⏳ รอผู้ใช้ตัดสินใจ (สูงสุด %.0f วิ) ...", ASK_USER_TIMEOUT)
    if not _answer_event.wait(ASK_USER_TIMEOUT):
        log.info("   ⏱ ไม่มีคำตอบใน %.0f วิ — ถือว่าหยุด", ASK_USER_TIMEOUT)
        return "stop"

    with _answer_lock:
        return _answer_action or "stop"

def handle_error(kind, session_id, piece, target, detail, rounds) -> bool:
    report(f"{kind}_FAILED",
           f"ชิ้นที่ {piece}/{target} (ครั้งที่ {rounds}/{MAX_ASK_USER_ROUNDS-1}): {detail}")
    if rounds >= MAX_ASK_USER_ROUNDS:
        report(f"{kind}_GAVE_UP", f"ชิ้นที่ {piece}/{target}: ครบ {MAX_ASK_USER_ROUNDS-1} ครั้งแล้ว — หยุดการวัด")
        return False

    if not is_running:          # กด Stop จากเว็บระหว่างนี้
        return False

    return ask_user(session_id, piece, target) == "retry"

def post_measurement_from_pi(session_id, piece, x, y, horizon_left, horizon_right, vertical_top, vertical_bottom,
                             offset_x, offset_y) -> bool:
    """POST ค่าที่ Pi อ่านจาก GM เข้า Backend แทน Recieve — คืน True ถ้าสำเร็จ

    ใช้เฉพาะตอน `wait_for_measurement` หมดเวลา = **วัดสำเร็จแล้วแต่ค่าไม่ถึง DB**
    (ชิ้นงานถูก MCU คัดแยกไปแล้ว ไม่มีอะไรให้วัดใหม่) สิ่งที่ขาดคือแถวใน DB
    ไม่ใช่การวัด — จึงเป็น "บันทึกค่าที่มี" ไม่ใช่ "retry"

    ⚠ ไม่มีการกันยิงซ้ำแล้ว — `client_uuid` ถูกถอดออกทั้งระบบ เพราะฟังก์ชันนี้
      ยิงครั้งเดียวจบ (พลาดแล้วตั้ง stop_reason แล้ว break ไม่มี retry loop)
      ถ้าวันหลังใส่ retry เข้ามา ต้องกลับมาคิดเรื่องกันซ้ำใหม่ด้วย

    ⚠ ต้อง PATCH image ต่อด้วย `upload_failed=True` — ไม่งั้น `image_path = NULL`
      จะแปลว่า "รูปยังไม่มา" ซึ่งปกติหมายถึงกำลังจะมาในไม่กี่วินาที แต่เคสนี้
      **ไม่มีวันมา** คนเปิดรายงานจะนั่งรอรูปที่ไม่มีอยู่จริง

    ไม่ส่ง `number_alpl` / `measure_type` / `operator_id` — backend เลือกเองจาก
    ตำแหน่งในคิวกับ queue_state เหมือนตอนที่ Recieve ส่ง (แหล่งความจริงเดียว)
    """
    body = {
        "session_id":  session_id,
        "value_x":     x,
        "value_y":     y,
        "horizon_left":       horizon_left,
        "horizon_right":       horizon_right,
        "vertical_top":       vertical_top,
        "vertical_bottom":       vertical_bottom,
        "offset_opx":  offset_x,
        "offset_opy":  offset_y,
        "note":        "ค่าจาก Pi (GM) — Recieve ส่งไม่ถึง ไม่มีรูป",
    }
    try:
        resp = httpx.post(f"{BACKEND_URL}/api/measurements", json=body, timeout=10)
    except Exception as exc:
        report("PI_POST_FAILED", f"ชิ้นที่ {piece}: POST ค่าจาก Pi ไม่สำเร็จ — {exc}")
        return False

    if resp.status_code != 200:
        detail = ""
        try:
            detail = resp.json().get("detail", "")
        except Exception:
            detail = resp.text[:200]
        report("PI_POST_FAILED",
               f"ชิ้นที่ {piece}: backend ปฏิเสธค่าจาก Pi (HTTP {resp.status_code}): {detail}")
        return False

    mid = resp.json().get("measurement_id")
    log.info("   ✅ บันทึกค่าจาก Pi แล้ว (measurement_id=%s)", mid)

    # ปักธงว่า "ไม่มีรูปถาวร" — ล้มก็ไม่ถือว่างานหลักพัง แถวลง DB ไปแล้ว
    try:
        httpx.patch(f"{BACKEND_URL}/api/measurements/{mid}/image",
                    json={"image_path": None, "upload_failed": True}, timeout=5)
    except Exception as exc:
        report("PI_POST_FAILED", f"ชิ้นที่ {piece}: ปักธงไม่มีรูปไม่สำเร็จ — {exc}",
               persist=False)   # ← ค่าลง DB แล้ว ห้ามทับสาเหตุที่ Pi กำลังรอ
    return True

def command_flow(session_id, groups, target_count):

    global current_session_id, is_running, _tmx_sock, _hb_last_ok
    _hb_last_ok = time.time()
    current_session_id = session_id  # heartbeat จะเริ่มแนบ session นี้ทันที
    is_running = True
    client_socket = None
    stop_reason = None

    try:
        log.info(f"\n{'='*60}")
        log.info(f"✅ ได้รับคำสั่ง Start จาก Backend")
        log.info(f"   session_id    : {session_id}")
        log.info(f"   target_count  : {target_count}  ← จำนวนชิ้นที่จะวัดรอบนี้")
        for gi, g in enumerate(groups, 1):
            log.info(f"   กลุ่มที่ {gi}      : template={g.template_name!r} "
                  f"ALPL={g.alpl}")
            if g.limits:
                L = g.limits
                log.info(f"                   X {L.x_lo:.4f}–{L.x_hi:.4f} · "
                      f"Y {L.y_lo:.4f}–{L.y_hi:.4f} · offset_max={L.offset_max}")
        log.info(f"{'='*60}")

        # ── ชิ้นที่ i อยู่กลุ่มไหน ──────────────────────────────────────────
        # ทำได้ด้วยบรรทัดเดียวเพราะ **คิวไม่เคยสลับกลุ่ม** — `_flatten_groups`
        # ฝั่ง backend (routers/session.py) ต่อ ALPL ของกลุ่ม 0 ให้หมดก่อน
        # แล้วค่อยกลุ่ม 1 ดังนั้นแต่ละกลุ่มเป็นบล็อกติดกันเสมอ ลำดับที่ได้ตรงกับ
        # `queue` ที่ backend ใช้เลือก ALPL ให้ measurement เป๊ะ
        #
        # ⚠ ถ้าวันหลัง backend เปลี่ยนไปเรียงคิวแบบสลับกลุ่ม บรรทัดนี้พังทันที
        #   และจะพังแบบเงียบ ๆ (วัดด้วย template ผิดโดยไม่มี error) — ต้องให้
        #   backend ส่ง `group_of` มาตรง ๆ แทนการเดาจากลำดับ
        group_of = [gi for gi, g in enumerate(groups) for _ in g.alpl]
        if len(group_of) != target_count:
            log.info("⚠️ จำนวน ALPL รวม (%s) ไม่เท่า target_count (%s) — payload เพี้ยน",
                     len(group_of), target_count)

        try:
            client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client_socket.settimeout(5.0)
            client_socket.connect((TMX_IP, TMX_PORT))
        except Exception as exc:
            log.info("\n❌ ต่อ TM-X ที่ %s:%s ไม่ได้ — %s: %s", TMX_IP, TMX_PORT, type(exc).__name__, exc)
            log.info("   ตรวจ: สาย LAN ต่ออยู่ไหม · TM-X เปิดอยู่ไหม · TMX_HOST/TMX_PORT ใน .env ถูกไหม")
            log.info("   → กด Stop ที่หน้าเว็บเพื่อล้าง session นี้ แล้วลองใหม่")
            stop_reason = (f"ต่อ TM-X ที่ {TMX_IP}:{TMX_PORT} ไม่ได้ ({type(exc).__name__}) "f"— ตรวจสาย LAN · TM-X เปิดอยู่ไหม · TMX_HOST/TMX_PORT ใน .env")
            return

        _tmx_sock = client_socket  # ให้ stop handler ยิง S0 ผ่าน socket นี้ได้

        # Running (เข้าโหมดดำเนินงาน)
        log.info("→ R0 : %s", send_command(client_socket, "R0"))
        time.sleep(0.5)

        # `PW` ย้ายเข้าไปในลูปแล้ว (ดูข้างล่าง) เพราะแต่ละกลุ่มใช้ template คนละตัวได้
        current_tmpl = None      # template ที่โหลดค้างอยู่ใน TM-X ตอนนี้

        for piece in range(1, target_count + 1):
            if not is_running:
                log.info("⏹ ได้รับคำสั่ง Stop — หยุดการวัด")
                break

            # ── ⓪ โหลดโปรแกรมวัดของกลุ่มนี้ ถ้ายังไม่ตรงกับที่ค้างอยู่ ──────
            #
            # ยิงก่อน `wait_for_trigger_mcu()` โดยตั้งใจ — ช่วงรอสัญญาณจาก MCU
            # ไม่มีกำหนดเวลาอยู่แล้ว ปล่อยให้ TM-X โหลดโปรแกรมไปพร้อมกันเลย
            # ถ้าย้ายไปไว้หลัง trigger จะเพิ่มดีเลย์ ~1 วิให้ชิ้นแรกของทุกกลุ่ม
            #
            # ⚠ `PW` พ่วง RESET มาด้วย ทำให้ READY ดับชั่วคราว ยิง `T1` ตามติด
            #   จะได้ `ER,T1,03` · ที่รอดอยู่ทุกวันนี้เพราะ sleep 1 วิ + `T1_RETRY`
            #   ลองซ้ำให้อีก 3 ครั้ง (~0.9 วิ) รวมเผื่อไว้ ~1.9 วิ
            #   **ถ้าหน้างานพบว่าชิ้นแรกของกลุ่มพังบ่อย ให้เพิ่ม PW_LOAD_WAIT**
            #   ทางที่สะอาดกว่าคือใช้คำสั่ง `RM` อ่านโหมดยืนยันแทนการเดาเวลา
            tmpl = groups[group_of[piece - 1]].template_name
            if tmpl != current_tmpl:
                pw = f"PW,1,{str(tmpl).zfill(3)}"
                log.info("→ %s : %s  (กลุ่มที่ %s)", pw,
                         send_command(client_socket, pw, timeout=PW_CMD_TIMEOUT),
                         group_of[piece - 1] + 1)
                time.sleep(PW_LOAD_WAIT)
                current_tmpl = tmpl

            # ── ① รอ MCU บอกว่าชิ้นงานเข้าที่แล้ว (ตอนนี้ = curl /trigger) ──
            log.info("\nชิ้นที่ %s/%s — รอสัญญาณ trigger ...", piece, target_count)
            if not wait_for_trigger_mcu():
                log.info("⏹ ได้รับคำสั่ง Stop — หยุดการวัด")
                break

            # อ่านให้ชิดกับ T1 ที่สุด — ช่วงรอสัญญาณข้างบนกินเวลาเป็นนาทีได้
            # ถ้าอ่านก่อนรอ แล้วค่าของชิ้นก่อนที่มาช้าหลุดเข้ามาระหว่างนั้น
            # measured_count จะขยับตั้งแต่ยังไม่ได้ยิง T1 ของชิ้นนี้
            count_before = get_measured_count(session_id)

            # ── ② MRS ล้างค่าเก่า แล้วยิง T1 ────────────────────────────────
            rounds = 0
            while True:
                ok, t1_resp = trigger_tmx(client_socket)
                if ok:
                    break
                rounds += 1
                if not handle_error("T1", session_id, piece, target_count,
                                    f"TM-X ปฏิเสธคำสั่ง T1 — {t1_resp}", rounds):
                    stop_reason = f"ชิ้นที่ {piece}/{target_count}: ยิง T1 ไม่สำเร็จ ({t1_resp})"
                    break
            if not ok:
                break                     # ← ออกจาก for → finally → ยิง stop
                
            # ── ③ วน GM จนได้ค่า ────────────────────────────────────────────
            #
            # ⚠⚠ **ต้องเป็น limits ของกลุ่มที่ชิ้นนี้อยู่ ห้ามใช้ groups[0]** —
            #   ถ้าโหลด template ถูกแต่ตัดสินด้วยเกณฑ์ของกลุ่มแรก ค่าที่ได้จะ
            #   ดูปกติทุกอย่างแต่คัดของผิดทั้งกลุ่มหลัง โดยไม่มี error ใด ๆ
            #   (backend บันทึกด้วยเกณฑ์รายตัวที่ถูกต้อง → DB กับ MCU ขัดกันเงียบ ๆ)
            rounds = 0
            while True:
                result, x, y, horizon_left, horizon_right,vertical_top, vertical_bottom, offset_x, offset_y = get_measurement_tmx(client_socket, groups[group_of[piece - 1]].limits)
                if result != "UNKNOWN":
                    break
                rounds += 1
                if not handle_error("GM", session_id, piece, target_count,
                                    f"รอ {GM_MAX_WAIT:.0f} วิแล้ว GM ไม่คืนค่าใหม่", rounds):
                    stop_reason = f"ชิ้นที่ {piece}/{target_count}: TM-X วัดไม่ติด"
                    #send_result_to_mcu("UNKNOWN")   # ปล่อยของออกก่อนจบ
                    break
            if result == "UNKNOWN":
                break

            # ── ④ ส่งผลให้ MCU ไปคัดแยก — ส่งทุกชิ้นรวมถึง UNKNOWN ─────────
            send_result_to_mcu(result)
            # TODO: รอ MCU ตอบรับ (wait_mcu_ack) ก่อนไปชิ้นถัดไป — ยังไม่ทำ

            if not is_running:
                log.info("⏹ หยุดการวัด")
                break

            # ── รอยืนยันว่าค่าเข้า DB จริง ก่อนไปชิ้นถัดไป ────────────────── ถ้า wait_for_measurement return true 
            if wait_for_measurement(session_id, count_before):
                if is_running:
                    log.info("   ✅ ชิ้นที่ %s/%s บันทึกแล้ว", piece, target_count)
                continue

            # ── ค่าไม่ถึง DB — วัดสำเร็จแล้ว แต่ Recieve ส่งไม่ถึง ────────────
            # ⚠ ไม่มี retry ในเคสนี้ ชิ้นงานถูก MCU คัดแยกไปแล้ว ไม่มีอะไรให้วัดใหม่
            #   Pi ถือค่าอยู่ในมือครบ → ถามผู้ใช้ว่าจะรับค่านั้นโดยไม่มีรูปไหม
            report("NO_DB_ROW",
                   f"ชิ้นที่ {piece}/{target_count}: วัดได้แล้วแต่ค่าไม่ถึงฐานข้อมูลใน "
                   f"{MEASURE_TIMEOUT:.0f} วิ — ตรวจว่า Recieve_tm-x.py รันอยู่ไหม")

            if ask_user(session_id, piece, target_count) != "accept":
                stop_reason = (f"ชิ้นที่ {piece}/{target_count}: ค่าไม่ถึงฐานข้อมูล "
                               f"— ผู้ใช้เลือกหยุด")
                break

            # ⚠ เช็คอีกครั้งก่อน POST — ระหว่างที่ modal เปิดรอคน (นานได้ถึง
            #   ASK_USER_TIMEOUT) FTP อาจส่งมาช้าแต่มาถึงแล้ว ถ้าไม่เช็คจะได้
            #   2 แถวสำหรับชิ้นเดียว → position ขยับ 2 → ALPL เลื่อนทั้งคิว
            #   ⚠ การเช็คตรงนี้เป็น **ด่านเดียวที่กันแถวซ้ำ** — ระบบไม่มี client_uuid
            #     หรือกลไกกันซ้ำฝั่ง backend อีกแล้ว ห้ามถอดออก
            if get_measured_count(session_id) != count_before:
                log.info("   ℹ️ ค่ามาถึงระหว่างรอคำตอบ — ไม่ต้องบันทึกซ้ำ")
                continue

            if not post_measurement_from_pi(session_id, piece, x, y,
                                            horizon_left, horizon_right, vertical_top, vertical_bottom,
                                            offset_x, offset_y):
                stop_reason = f"ชิ้นที่ {piece}/{target_count}: บันทึกค่าจาก Pi ไม่สำเร็จ"
                break
    except Exception as exc:
        log.info("\n❌ session พังกลางทาง — %s: %s", type(exc).__name__, exc)
        stop_reason = f"session พังกลางทาง — {type(exc).__name__}: {exc}" 
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
        log.info("\n✅ จบ session — ปิดการเชื่อมต่อ TM-X แล้ว")
        try:
            st = httpx.get(f"{BACKEND_URL}/api/session/state", timeout=5).json()
            if st.get("session_id") == session_id and st.get("state") == "running":
                measured = st.get("measured_count")

                # ⚠ ห้ามส่ง None — session.py:707 เช็ค `if req.reason:` ถ้าเป็น None
                #   จะไม่เขียนอะไรลง DB เลย หน้าเว็บขึ้น STOPPED เปล่า ๆ เหมือนเดิม
                #   ทางที่ยังไม่ได้ตั้ง reason ให้บอกตรง ๆ ว่าไม่ทราบ ดีกว่าเงียบ
                reason = stop_reason or (
                    f"session จบก่อนครบจำนวน (วัดได้ {measured}/{target_count}) "
                    f"— ไม่ทราบสาเหตุแน่ชัด ดู log บนเครื่อง Pi"
                )
                httpx.post(
                    f"{BACKEND_URL}/api/session/stop",
                    json={"session_id": session_id, "reason": reason},
                    timeout=10,
                )
                log.info("⏹ แจ้ง backend ปิด session แล้ว (วัดได้ %s/%s)", measured, target_count)
                log.info("   เหตุผล: %s", reason)

        except Exception as exc:
            log.info("   ⚠️ แจ้งปิด session ไม่ได้: %s — "
                     "backend จะปิดเองใน ~%g วิ (ขึ้นเป็น 'timeout')", exc, HB_TIMEOUT_HINT)
            # reason กำลังจะหายไปทั้งก้อน — เทอร์มินัลคือหลักฐานเดียวที่เหลือ
            if stop_reason:
                log.info("   เหตุผลที่จะหายไป: %s", stop_reason)

if __name__ == "__main__":
    # heartbeat ต้องเริ่ม "ก่อน" เปิด server และรันตลอดอายุโปรแกรมใน daemon thread
    threading.Thread(target=heartbeat_loop, daemon=True).start()

    log.info("─" * 66)
    log.info("Pi.py — รอคำสั่ง Start จาก Backend")
    log.info(f"  ฟัง /command ที่    : 0.0.0.0:{AGENT_PORT}   (.env: AGENT_PORT)")
    log.info(f"  TM-X ที่            : {TMX_IP}:{TMX_PORT}    (.env: TMX_HOST/TMX_PORT)")
    log.info(f"  Backend ที่         : {BACKEND_URL}          (.env: BACKEND_URL)")
    log.info(f"  heartbeat ทุก       : {HB_INTERVAL:g} วิ · หยุดเองถ้าขาดติดต่อเกิน {HB_TIMEOUT_HINT:g} วิ")
    log.info(f"  รอค่าการวัดสูงสุด    : {MEASURE_TIMEOUT:g} วิ (poll ทุก {MEASURE_POLL_INTERVAL:g} วิ)")
    # แยก 2 บรรทัดโดยตั้งใจ — เดิมพิมพ์ "curl -X POST http://..." ติดกันบรรทัดเดียว
    # แล้วมีคนก๊อปทั้งบรรทัดไปวางในช่อง address ของเบราว์เซอร์ ได้ URL เพี้ยนเป็น
    #   http://127.0.0.1:9998/curl%20-X%20POST%20http://...
    # (%20 = ช่องว่าง) · บรรทัดล่างจึงเป็น URL ล้วนที่ก๊อปแล้ววางได้ทันที
    log.info(f"  จำลองเซนเซอร์ (เบราว์เซอร์): http://127.0.0.1:{AGENT_PORT}/trigger")
    log.info(f"  จำลองเซนเซอร์ (เทอร์มินัล) : curl -X POST http://127.0.0.1:{AGENT_PORT}/trigger")
    log.info(f"     ยิงจากเครื่องอื่นให้เปลี่ยน 127.0.0.1 เป็น IP ของ Pi")
    log.info("─" * 66)

    # ── เตือนถ้า heartbeat ตั้งค่าไม่สัมพันธ์กัน ────────────────────────────
    # ต้อง INTERVAL × 2 ≤ TIMEOUT เป็นอย่างน้อย เพื่อให้ทนบีตหาย 1 ครั้งได้
    #
    # ถ้าตั้งเท่ากันเป๊ะ (เช่น 5/5) จะไม่มีระยะเผื่อเลยแม้แต่มิลลิวินาทีเดียว —
    # บีตต้องมาตรงเวลาพอดีทุกครั้งถึงจะรอด ซึ่งเป็นไปไม่ได้จริงเพราะมี network
    # latency + เวลาที่ MySQL เขียน UPDATE + GC ของ Python · ผลคือ backend
    # ฆ่า session ทิ้งเองกลางการวัด (ทิ้งคิวด้วย กู้ไม่ได้) โดยไม่มีสาเหตุจริง
    # แล้วหน้าเว็บขึ้นว่า 'timeout' ซึ่งชี้ไปที่ "Pi ตาย" ทั้งที่ Pi ปกติดี
    if HB_INTERVAL * 2 > HB_TIMEOUT_HINT:
        log.info(f"⚠️  HEARTBEAT_INTERVAL ({HB_INTERVAL:g}s) ถี่ไม่พอเมื่อเทียบกับ "
              f"HEARTBEAT_TIMEOUT ({HB_TIMEOUT_HINT:g}s)")
        log.info(f"    แนะนำให้ HEARTBEAT_INTERVAL ไม่เกิน {HB_TIMEOUT_HINT/2:g}s "
              f"— แก้ที่ .env\n")

    # port ต้องตรงกับ AGENT_PORT ที่ main.py ใช้ยิงมา
    uvicorn.run(http_app, host="0.0.0.0", port=AGENT_PORT)
