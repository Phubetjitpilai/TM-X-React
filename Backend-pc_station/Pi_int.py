"""Pi_test.py — Pi.py ฉบับตัด Backend/DB ออก สำหรับเทสต์ร่วมกับ MCU
⚠⚠ **ห้ามเอาไฟล์นี้ไปใช้หน้างานเด็ดขาด** — ค่าที่วัดได้ถูกเก็บไว้ในหน่วยความจำ
    เท่านั้น ปิดโปรแกรมแล้วหายหมด ไม่มีอะไรลงฐานข้อมูลจริง
สร้างจาก Pi.py โดยแทน **เฉพาะ 6 ฟังก์ชันที่ยิง HTTP ไปหา backend** ด้วยของจำลอง
ที่เหลือ (การคุย TM-X, ตรรกะการวัด, การตัดสิน OK/NG, การจัดการ error) เหมือนเดิม
ทุกบรรทัด — จะได้เทสต์สิ่งที่ต้องเทสต์จริง ๆ
    ฟังก์ชันที่ถูกแทน   get_measured_count · heartbeat_loop · wait_for_trigger_mcu
                       report · ask_user · post_measurement_from_pi
วิธีใช้ (ไม่ต้องมี backend / MySQL / Data-receiver เลย)
    python Pi_test.py
    แล้วสั่งงานผ่านเบราว์เซอร์หรือ curl ที่พอร์ต 9998
      เริ่มวัด     http://127.0.0.1:9998/start?count=3
      หยุด        http://127.0.0.1:9998/stop
      ดูสถานะ     http://127.0.0.1:9998/status
      ดูค่าที่เก็บ  http://127.0.0.1:9998/mock/db
⚠⚠ **ตัวสั่งวัดรายชิ้น (trigger) ยังไม่มีในไฟล์นี้** — ต้องเขียนเพิ่มเองที่
    `wait_for_trigger_mcu()` ให้ไปอ่านสัญญาณจาก MCU · ตอนนี้กด /start แล้วจะ
    ค้างอยู่ที่ "รอสัญญาณจาก MCU ..." ตลอดจนกว่าจะยิง /stop ซึ่งถูกต้องแล้ว
    ไม่ใช่โปรแกรมแฮงก์ · อ่านสัญญา 3 ข้อใน docstring ของฟังก์ชันนั้นก่อนแก้
⚠ ต้องมี ESP (หรืออะไรก็ได้) ฟัง TCP อยู่ที่ TMX_HOST:TMX_PORT ใน .env และตอบ
  ตามรูปแบบใน ESP_PROTOCOL.md ไม่งั้นจะติดตั้งแต่ขั้น R0
"""
import os
import socket
import threading
import time
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


# new
########################
import glob
import serial
import sys

# ── Serial Config สำหรับเชื่อมต่อ Arduino Mega ──────────────────────────────
BAUD_RATE   = 115200
TIMEOUT_SEC = 1

def find_mega_port() -> str | None:
    """ค้นหาพอร์ต USB ที่เชื่อมต่อกับ Mega 2560 อัตโนมัติ"""
    ports = glob.glob("/dev/ttyACM*") + glob.glob("/dev/ttyUSB*")
    return ports[0] if ports else None

# ทำการเชื่อมต่อ Serial ทันทีที่รันสคริปต์
port = find_mega_port()
if not port:
    log.error("[ERROR] No Arduino/Mega found on USB. Check connection.")
    sys.exit(1)

log.info(f"[INFO] Connecting to Mega on {port} @ {BAUD_RATE} baud ...")
mega_ser = serial.Serial(port, BAUD_RATE, timeout=TIMEOUT_SEC)
time.sleep(2)  # รอ Mega รีเซ็ตตัวเองหลังเชื่อมต่อ
log.info("[INFO] Mega Serial Connected Successfully.")
#########################




load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))
TMX_IP = os.getenv("TMX_HOST", "192.168.0.11")
TMX_PORT = int(os.getenv("TMX_PORT", 8600))
BUFFER_SIZE = 1024

TRIGGER_COMMAND = "T1\r"
TRIGGER_TIMEOUT = 10.0  # วินาที — รอ response จาก TM-X หลังส่ง trigger

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")
AGENT_PORT = int(os.getenv("AGENT_PORT", 9998))

HB_INTERVAL     = float(os.getenv("HEARTBEAT_INTERVAL", 5))
HB_TIMEOUT_HINT = float(os.getenv("HEARTBEAT_TIMEOUT", 15))

MEASURE_TIMEOUT       = float(os.getenv("MEASURE_TIMEOUT", 15))    # รอค่าสูงสุดกี่วินาที
MEASURE_POLL_INTERVAL = float(os.getenv("MEASURE_POLL_INTERVAL", 0.4))

# ── GM: ดึงค่าที่วัดได้จาก TM-X โดยตรง ──────────────────────────────────────
SOCKET_TIMEOUT   = float(os.getenv("SOCKET_TIMEOUT", TRIGGER_TIMEOUT))
GM_POLL_INTERVAL = 0.02                                  # 20 ms
GM_MAX_WAIT      = float(os.getenv("GM_MAX_WAIT", 8))    # รอค่าสูงสุดต่อชิ้น
NO_VALUE_ABS     = 9999.0        # |ค่า| >= นี้ = TM-X ยังวัดไม่เสร็จ/วัดไม่ติด
# T1 ที่โดน ER,...,03 (READY ยังไม่กลับมาหลัง RESET ที่พ่วงมากับ PW) ยิงซ้ำได้

T1_RETRY = int(os.getenv("T1_RETRY", 3))
T1_RETRY_WAIT = float(os.getenv("T1_RETRY_WAIT", 0.3))

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

# ══════════════════════════════════════════════════════════════════════════
# [MOCK] ฐานข้อมูลจำลอง — แทน MySQL + Backend ทั้งก้อน
# ══════════════════════════════════════════════════════════════════════════
# ⚠ อยู่ในหน่วยความจำล้วน ปิดโปรแกรมแล้วหาย · มีไว้ให้ flow เดินได้ครบเท่านั้น
#
# ⚠ ต้องมี lock เพราะถูกอ่าน/เขียนจาก 3 เธรด: เธรด HTTP (endpoint),
#   เธรด command_flow, และเธรดตั้งเวลาของ _mock_schedule_measurement()
_mock_lock = threading.Lock()
_mock_db = {
    "session_id":     None,
    "state":          "idle",     # idle | running | stopped
    "target_count":   0,
    "measured_count": 0,
    "reason":         None,
    "rows":           [],         # ค่าที่ "บันทึกลง DB" แล้ว
}

# หน่วงกี่วินาทีหลังยิง T1 ก่อนจะถือว่า "ค่าเข้า DB แล้ว"
#   จำลองเวลาที่ TM-X ส่งไฟล์ทาง FTP มาให้ Data-receiver แล้ว POST เข้า backend
#
# ⚠ ตั้งให้ **มากกว่า MEASURE_TIMEOUT** เมื่อไหร่ จะได้ทดสอบเส้นทาง
#   "วัดได้แต่ค่าไม่ถึง DB" ที่เด้งถาม retry / accept / stop
MOCK_MEASURE_DELAY = float(os.getenv("MOCK_MEASURE_DELAY", 1.0))

def _mock_schedule_measurement():
    """ตั้งเวลาเพิ่ม measured_count — เลียนแบบ Data-receiver ที่รับไฟล์ FTP แล้ว POST"""
    def _bump():
        time.sleep(MOCK_MEASURE_DELAY)
        with _mock_lock:
            if _mock_db["state"] != "running":
                return                      # session ปิดไปแล้ว ค่าที่มาช้าถูกทิ้ง
            _mock_db["measured_count"] += 1
            _mock_db["rows"].append({"source": "mock-ftp",
                                     "n": _mock_db["measured_count"]})
            n, t = _mock_db["measured_count"], _mock_db["target_count"]
            if n >= t:
                _mock_db["state"] = "stopped"
                _mock_db["reason"] = "วัดครบตามจำนวนแล้ว"
        log.info("   📥 [MOCK] ค่าเข้า DB แล้ว (%s/%s)", n, t)
    threading.Thread(target=_bump, daemon=True).start()

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
        # [MOCK] ถอด httpx.post /api/heartbeat ออก — ไม่มี backend ให้แจ้ง
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
        templates = {g.template_name for g in groups}
        if len(templates) > 1:
            raise HTTPException(400, f"Pi ยังรองรับ template เดียวต่อ session — ได้มา {sorted(templates)}")

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
            f"start/stop/retry/accept",
        )
    return {"status": "ok", "action": req.action}


def heartbeat_loop():
    """[MOCK] เดิมยิง POST /api/heartbeat ทุก HB_INTERVAL วิ
    ของจริงมี 2 หน้าที่: บอก backend ว่า Pi ยังมีชีวิต และ **หยุดวัดเองถ้าติดต่อ
    backend ไม่ได้เกิน HB_TIMEOUT_HINT วิ** (กันวัดต่อทั้งที่ค่าจะถูกทิ้ง)
    ⚠ ที่นี่ถอดส่วน "หยุดเองเมื่อขาดการติดต่อ" ออกด้วย เพราะไม่มี backend ให้ขาด
      → session จะไม่จบเองจากเหตุนี้อีก · ตอนกลับไปใช้ Pi.py ตัวจริง
      พฤติกรรมนี้จะกลับมา อย่าแปลกใจถ้าเครื่องหยุดเองตอนเน็ตหลุด
    """
    while True:
        if is_running:
            log.info("   💓 heartbeat (mock) session=%s", current_session_id)
        time.sleep(HB_INTERVAL)


def send_command(sock, command):
    cmd_to_send = command + "\r"  # ต้องต่อท้ายด้วยตัวคั่น CR (\r) เสมอ
    sock.sendall(cmd_to_send.encode("ascii"))
    time.sleep(0.1)  # หน่วงเวลาให้กล้องประมวลผลเล็กน้อย
    response = sock.recv(BUFFER_SIZE).decode("ascii").strip()
    return response

def get_measured_count(session_id):
    """[MOCK] เดิมยิง GET /api/session/state ไปถาม backend
    ของจริง: backend เพิ่ม measured_count ทุกครั้งที่ Data-receiver POST ค่าที่
    TM-X ส่งมาทาง FTP เข้ามา · ที่นี่ไม่มีทั้ง backend และ FTP จึงจำลองด้วย
    ตัวนับในหน่วยความจำที่ `trigger_tmx()` สั่งเพิ่มให้หลังยิง T1 สำเร็จ
    (หน่วง MOCK_MEASURE_DELAY วิ เลียนแบบเวลาที่ไฟล์วิ่งมาทาง FTP)
    ⚠ คืน None เมื่อ session_id ไม่ตรง — พฤติกรรมเดียวกับของจริง
      `wait_for_measurement()` เช็ค `count_after is not None` อยู่
    """
    with _mock_lock:
        if _mock_db["session_id"] != session_id:
            return None
        return _mock_db["measured_count"]


# new
# รอ Trigger จาก MCU
def wait_for_trigger_mcu():
    """รอสัญญาณ <TRIGGER_TMX> จาก MCU ผ่าน Serial"""
    log.info("   ⏳ รอสัญญาณจาก MCU ... (กด Stop เพื่อยกเลิก)")
    while is_running:
        if mega_ser.in_waiting > 0:
            try:
                line = mega_ser.readline().decode("utf-8").strip()
                if line == "<TRIGGER_TMX>":
                    log.info("   📥 [RX ← Mega] ได้รับคำสั่ง <TRIGGER_TMX> แล้ว")
                    return True
            except UnicodeDecodeError:
                pass
        time.sleep(0.05)
    return False           # ออกจาก loop เพราะโดน Stop จาก Backend และ return False



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
            # [MOCK] ของจริง measured_count ขยับเมื่อ Data-receiver รับไฟล์จาก
            #   FTP แล้ว POST เข้า backend · ที่นี่ไม่มีทั้งคู่ จึงตั้งเวลาเพิ่ม
            #   ให้เองหลัง MOCK_MEASURE_DELAY วิ เพื่อให้ wait_for_measurement()
            #   ทำงานเหมือนของจริงทุกบรรทัด
            #   ⚠ ตั้ง MOCK_MEASURE_DELAY ให้ **มากกว่า** MEASURE_TIMEOUT เพื่อ
            #     ทดสอบเส้นทาง "วัดไม่ถึง DB" (จะเด้งถาม retry/accept/stop)
            _mock_schedule_measurement()
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

# new
#วนไปถามว่าพร้อมรับ result ยัง ให้ MCU set Flag เอา idle(ยังไม่มีชิ้นงาน) -> obj_is_ready(เมื่อวางชิ้นงานแล้ว) -> waiting_for_result(พร้อมรับ result) -> idle(เสร็จการวัด 1 ชิ้น)
def send_result_to_mcu(result, mcu_timeout=MCU_TIMEOUT):
    """ส่งผลการวัด (OK/NG) กลับไปหา MCU ผ่าน Serial"""
    icon = {"OK": "✅", "NG": "❌", "UNKNOWN": "❓"}.get(result, "•")
    log.info("   🔀 → MCU: %s %s", icon, result)
    
    # กำหนด Token ที่จะส่งกลับหา Mega ตามผลลัพธ์
    if result == "OK":
        ack_msg = "<MEASURE_OK>\n"
    else:
        ack_msg = "<MEASURE_NG>\n"
        
    mega_ser.write(ack_msg.encode("utf-8"))
    log.info(f"   [TX → Mega] {ack_msg.strip()}")
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
    """[MOCK] เดิมยิง POST /api/session/event ให้ backend เก็บไว้โชว์บนหน้าเว็บ
    — ที่นี่พิมพ์ลง log อย่างเดียว ตัวเรียกไม่ต้องแก้"""
    log.info("   📣 %s: %s", event, detail)

def ask_user(session_id, piece, target) -> str:
    """[MOCK] เดิมยิง POST /api/measure-timeout ให้หน้าเว็บเด้ง modal ถามผู้ใช้
    ที่นี่ไม่มีหน้าเว็บ จึงรอคำตอบผ่าน endpoint ของตัวเองแทน
        curl -X POST http://127.0.0.1:9998/answer/retry    ← วัดชิ้นเดิมใหม่
        curl -X POST http://127.0.0.1:9998/answer/accept   ← รับค่าที่ Pi อ่านได้
        curl -X POST http://127.0.0.1:9998/answer/stop     ← หยุดทั้ง session
    หรือเปิด URL เดียวกันในเบราว์เซอร์ก็ได้ (รองรับ GET ด้วย)
    ⚠ ถ้าไม่มีใครตอบใน ASK_USER_TIMEOUT วิ จะถือว่า "stop" เหมือนของจริงเป๊ะ
    """
    global _answer_action
    with _answer_lock:
        _answer_action = None
        _answer_event.clear()

    log.info("   ❓ ถามผู้ใช้: ชิ้นที่ %s/%s วัดไม่สำเร็จ — จะเอายังไงต่อ", piece, target)
    log.info("      retry  : curl -X POST http://127.0.0.1:%s/answer/retry", AGENT_PORT)
    log.info("      accept : curl -X POST http://127.0.0.1:%s/answer/accept", AGENT_PORT)
    log.info("      stop   : curl -X POST http://127.0.0.1:%s/answer/stop", AGENT_PORT)
    log.info("   ⏳ รอผู้ใช้ตัดสินใจ (สูงสุด %.0f วิ) ...", ASK_USER_TIMEOUT)

    if not _answer_event.wait(ASK_USER_TIMEOUT):
        log.info("   ⏱ ไม่มีคำตอบใน %.0f วิ — ถือว่าหยุด", ASK_USER_TIMEOUT)
        return "stop"

    with _answer_lock:
        return _answer_action or "stop"

def handle_error(kind, session_id, piece, target, detail, rounds) -> bool:
    report(f"{kind}_FAILED",
           f"ชิ้นที่ {piece}/{target} (ครั้งที่ {rounds}/{MAX_ASK_USER_ROUNDS}): {detail}")
    if rounds >= MAX_ASK_USER_ROUNDS:
        report(f"{kind}_GAVE_UP", f"ชิ้นที่ {piece}/{target}: ครบ {MAX_ASK_USER_ROUNDS} ครั้งแล้ว — หยุดการวัด")
        return False

    if not is_running:          # กด Stop จากเว็บระหว่างนี้
        return False

    return ask_user(session_id, piece, target) == "retry"

def post_measurement_from_pi(session_id, piece, x, y, horizon_left, horizon_right, vertical_top, vertical_bottom,
                             offset_x, offset_y) -> bool:
    """[MOCK] เดิมยิง POST /api/measurements แล้ว PATCH ธง "ไม่มีรูป" ตามหลัง
    ที่นี่เก็บลง list ในหน่วยความจำ (`_mock_db["rows"]`) ดูได้ที่
        http://127.0.0.1:9998/mock/db
    ⚠ ของจริง backend เป็นคนเลือก number_alpl จากตำแหน่งในคิวเอง — Pi ไม่เคยส่ง
      ค่านั้นไป · mock นี้จึงไม่มี ALPL เหมือนกัน เพื่อให้หน้าตาข้อมูลตรงกัน
    """
    with _mock_lock:
        _mock_db["rows"].append({
            "piece": piece, "value_x": x, "value_y": y,
            "horizon_left": horizon_left, "horizon_right": horizon_right,
            "vertical_top": vertical_top, "vertical_bottom": vertical_bottom,
            "offset_opx": offset_x, "offset_opy": offset_y,
            "source": "pi-fallback",
        })
        _mock_db["measured_count"] += 1
        mid = len(_mock_db["rows"])
    log.info("   ✅ [MOCK] บันทึกค่าจาก Pi แล้ว (measurement_id=%s)", mid)
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
        template_name = groups[0].template_name

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

        # Load Program ตาม template ที่ backend ส่งมา (zero-pad เป็น 3 หลัก)
        pw = f"PW,1,{str(template_name).zfill(3)}"
        log.info("→ %s : %s", pw, send_command(client_socket, pw))
        time.sleep(1.0)

        for piece in range(1, target_count + 1):
            if not is_running:
                log.info("⏹ ได้รับคำสั่ง Stop — หยุดการวัด")
                break
            # ── ① รอ MCU บอกว่าชิ้นงานเข้าที่แล้ว ──────────────────────────
            # ⚠ wait_for_trigger_mcu() ยังเป็นโครงเปล่า ต้องเขียนส่วนอ่าน MCU เอง
            log.info("\nชิ้นที่ %s/%s — รอสัญญาณจาก MCU ...", piece, target_count)
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
            rounds = 0
            while True:
                result, x, y, horizon_left, horizon_right,vertical_top, vertical_bottom, offset_x, offset_y = get_measurement_tmx(client_socket, groups[0].limits)
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
        # [MOCK] เดิมถาม GET /api/session/state แล้ว POST /api/session/stop
        #   ที่นี่ปิด session ในหน่วยความจำแทน — เงื่อนไข "ปิดเฉพาะ session
        #   ตัวเองที่ยัง running อยู่" คงไว้เหมือนเดิม เพราะเป็นตัวกันไม่ให้ไป
        #   ปิด session ใหม่ที่เพิ่งกด Start ระหว่างที่ finally ของรอบเก่าทำงานค้าง
        with _mock_lock:
            same = _mock_db["session_id"] == session_id
            running = _mock_db["state"] == "running"
            measured = _mock_db["measured_count"]
        if same and running:
            reason = stop_reason or (
                f"session จบก่อนครบจำนวน (วัดได้ {measured}/{target_count}) "
                f"— ไม่ทราบสาเหตุแน่ชัด ดู log บนเครื่อง Pi"
            )
            with _mock_lock:
                _mock_db["state"] = "stopped"
                _mock_db["reason"] = reason
            log.info("⏹ [MOCK] ปิด session แล้ว (วัดได้ %s/%s)", measured, target_count)
            log.info("   เหตุผล: %s", reason)

# ══════════════════════════════════════════════════════════════════════════
# [MOCK] endpoint สำหรับสั่งงานเองโดยไม่ต้องมี Backend
# ══════════════════════════════════════════════════════════════════════════
# ⚠ รับทั้ง GET และ POST โดยตั้งใจ — GET เพื่อให้ "พิมพ์ URL ในเบราว์เซอร์แล้ว
#   ทำงานเลย" ซึ่งสะดวกมากตอนเทสต์คู่กับ MCU ที่มือไม่ว่าง
#   **ของจริงใน Pi.py มีแต่ POST /command เท่านั้น อย่าเอาแนวนี้ไปใส่ตัวจริง**


@http_app.api_route("/start", methods=["GET", "POST"])
async def mock_start(count: int = 1, template: str = "201"):
    """เริ่ม session จำลอง — http://127.0.0.1:9998/start?count=3
    ⚠ สร้าง `groups` ให้เหมือนที่ backend ตัวจริงส่งมาเป๊ะ (ดู _build_groups
      ใน routers/session.py) เพื่อให้เส้นทางตรวจ payload ใน /command ถูกใช้จริง
      — ถ้าข้ามไปเรียก command_flow ตรง ๆ จะเทสต์ไม่ครบ
    """
    if is_running:
        return {"ok": False, "error": "กำลังวัดอยู่ — กด /stop ก่อน"}

    with _mock_lock:
        _mock_db.update(session_id=_mock_db["session_id"] or 0)
        _mock_db["session_id"] += 1
        sid = _mock_db["session_id"]
        _mock_db.update(state="running", target_count=count,
                        measured_count=0, reason=None, rows=[])

    req = CommandRequest(
        action="start", session_id=sid, target_count=count,
        groups=[Group(
            template_name=template,
            alpl=list(range(201, 201 + count)),
            limits=Limits(x_lo=5.0, x_hi=5.03, y_lo=5.0, y_hi=5.03,
                          offset_max=None),
        )],
    )
    await command(req)
    return {"ok": True, "session_id": sid, "target_count": count,
            "next": "รอสัญญาณจาก MCU — ต้องเขียนส่วนอ่านสัญญาณใน "
                    "wait_for_trigger_mcu() เองก่อน ไม่งั้นจะค้างตรงนี้"}


@http_app.api_route("/stop", methods=["GET", "POST"])
async def mock_stop():
    """หยุด session — เดินเส้นทางเดียวกับที่ backend ยิง /command action=stop"""
    await command(CommandRequest(action="stop", session_id=_mock_db["session_id"]))
    return {"ok": True}


@http_app.api_route("/answer/{action}", methods=["GET", "POST"])
async def mock_answer(action: str):
    """ตอบคำถามตอน ask_user() — retry / accept / stop"""
    if action not in ("retry", "accept", "stop"):
        raise HTTPException(400, "action ต้องเป็น retry / accept / stop")
    await command(CommandRequest(action=action, session_id=_mock_db["session_id"]))
    return {"ok": True, "answered": action}


@http_app.get("/status")
async def mock_status():
    """สถานะย่อ — ใช้ดูเร็ว ๆ ว่าตอนนี้เดินถึงไหน"""
    with _mock_lock:
        db = dict(_mock_db)
    return {
        "is_running": is_running,
        "current_session_id": current_session_id,
        "tmx": f"{TMX_IP}:{TMX_PORT}",
        "session": {k: db[k] for k in
                    ("session_id", "state", "target_count", "measured_count", "reason")},
    }


@http_app.get("/mock/db")
async def mock_db_dump():
    """ดูทุกอย่างที่ "ลง DB" ไปแล้ว — เทียบเท่าการ SELECT ตาราง measurements"""
    with _mock_lock:
        return dict(_mock_db)


if __name__ == "__main__":
    # heartbeat ต้องเริ่ม "ก่อน" เปิด server และรันตลอดอายุโปรแกรมใน daemon thread
    threading.Thread(target=heartbeat_loop, daemon=True).start()

    log.info("─" * 66)
    log.info("Pi_test.py — โหมดทดสอบ ไม่ใช้ Backend / ไม่ใช้ฐานข้อมูลจริง")
    log.info(f"  ฟังคำสั่งที่        : 0.0.0.0:{AGENT_PORT}   (.env: AGENT_PORT)")
    log.info(f"  ESP/TM-X ที่        : {TMX_IP}:{TMX_PORT}    (.env: TMX_HOST/TMX_PORT)")
    log.info(f"  หน่วง 'ค่าเข้า DB'   : {MOCK_MEASURE_DELAY:g} วิ (env: MOCK_MEASURE_DELAY)")
    log.info(f"  รอค่าการวัดสูงสุด    : {MEASURE_TIMEOUT:g} วิ (poll ทุก {MEASURE_POLL_INTERVAL:g} วิ)")
    # แยก 2 บรรทัดโดยตั้งใจ — เดิมพิมพ์ "curl -X POST http://..." ติดกันบรรทัดเดียว
    # แล้วมีคนก๊อปทั้งบรรทัดไปวางในช่อง address ของเบราว์เซอร์ ได้ URL เพี้ยนเป็น
    #   http://127.0.0.1:9998/curl%20-X%20POST%20http://...
    # (%20 = ช่องว่าง) · บรรทัดล่างจึงเป็น URL ล้วนที่ก๊อปแล้ววางได้ทันที
    log.info("  เปิด URL พวกนี้ในเบราว์เซอร์ได้เลย (ยิงจากเครื่องอื่นเปลี่ยน 127.0.0.1 เป็น IP ของ Pi)")
    log.info(f"     เริ่มวัด 3 ชิ้น : http://127.0.0.1:{AGENT_PORT}/start?count=3")
    log.info(f"     หยุด          : http://127.0.0.1:{AGENT_PORT}/stop")
    log.info(f"     สถานะ         : http://127.0.0.1:{AGENT_PORT}/status")
    log.info(f"     ค่าที่เก็บไว้    : http://127.0.0.1:{AGENT_PORT}/mock/db")
    log.info("")
    log.info("  ⚠ ยังไม่มีตัวสั่งวัดรายชิ้น — ต้องเขียนส่วนอ่านสัญญาณ MCU ที่")
    log.info("    wait_for_trigger_mcu() เอง · กด /start ตอนนี้จะค้างที่")
    log.info("    'รอสัญญาณจาก MCU ...' จนกว่าจะยิง /stop (ถูกต้องแล้ว ไม่ใช่แฮงก์)")
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