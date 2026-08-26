# Backend-pc_station/mockup.py
# Agent จำลอง (mock) สำหรับเทสต์ระบบตอนไม่มีฮาร์ดแวร์ TM-X จริง
#
# How to run:
#   cd Backend-pc_station
#   python mockup.py
#
# ทำอะไร: ทำตัวเป็น Agent ตัวหนึ่งเหมือน send_command.py/agent.py ทุกประการใน
# มุมของ Backend (ฟัง POST /command ที่ port เดียวกัน + ส่ง heartbeat) แต่แทนที่
# จะไปคุย TCP/FTP กับ TM-X จริง มันจะ "สุ่มค่า" value_x/value_y ขึ้นมาเองแล้ว
# POST /api/measurements กลับไปให้ Backend ทีละชิ้นจนครบ target_count
#
# ต่างจาก send_command.py ตรงที่:
#   - ไม่ต้องกด Enter ทีละชิ้น (เดินอัตโนมัติ เว้นระยะตาม MEASURE_INTERVAL)
#   - ไม่ต่อ TM-X เลย (ไม่มี R0/PW/T1/S0, ไม่มี FTP, ไม่มีรูปภาพ)
#   - สุ่มค่าให้ "อิงกับ nominal/tolerance จริงของ ALPL นั้น" ที่ดึงจาก Backend
#     เพื่อให้ผล OK/NG ที่ออกมาสมจริง ไม่ใช่สุ่มมั่วจนได้ NG หมดทุกชิ้น

import os
import random
import threading
import time
import uuid

import httpx
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))

# ── Config ──────────────────────────────────────────────────────────────────
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")
AGENT_PORT  = int(os.getenv("AGENT_PORT", 9998))
# ⚠ เดิม hardcode เป็น 5 ไว้เฉยๆ ทั้งที่ .env มี HEARTBEAT_INTERVAL อยู่แล้ว —
#   พอมีคนไปลด HEARTBEAT_TIMEOUT ใน .env เป็น 5 ตัวนี้ไม่ตามให้ กลายเป็น
#   interval(5) = timeout(5) พอดีเป๊ะ ไม่มีระยะเผื่อเลย → backend ฆ่า session
#   ทิ้งเองแทบทุกครั้งที่บีตมาช้ากว่ากำหนดแม้แต่เสี้ยววินาที
#   (send_command(Pi).py อ่านจาก .env มาตั้งแต่แรก ตัวนี้จึงเป็นตัวเดียวที่หลุด)
HB_INTERVAL = float(os.getenv("HEARTBEAT_INTERVAL", 5))
# ขาดการติดต่อ backend นานเกินเท่านี้ = หยุดวัดเอง (ดู heartbeat_loop)
# ต้องเป็นค่าเดียวกับที่ backend ใช้ และตรงกับ send_command(Pi).py
HB_TIMEOUT_HINT = float(os.getenv("HEARTBEAT_TIMEOUT", 15))

# เวลาหน่วงระหว่างการวัดแต่ละชิ้น (วินาที) — จำลองเวลาที่เครื่องจริงใช้วัด 1 ชิ้น
# ตั้งให้ช้าลงได้ถ้าอยากดู SSE อัปเดตทีละชิ้นบน dashboard ชัดๆ
MEASURE_INTERVAL = float(os.getenv("MOCK_MEASURE_INTERVAL", 2.0))

# สัดส่วนชิ้นงานที่จงใจสุ่มให้ "หลุด tolerance" (ได้ NG) — 0.2 = ประมาณ 20%
# ตั้งเป็น 0 ถ้าอยากให้ OK ทุกชิ้น หรือ 1 ถ้าอยากเทสต์เคส NG ล้วน
NG_RATE = float(os.getenv("MOCK_NG_RATE", 0.2))

# ขอบเขตสำรองตอน payload ไม่มี groups มาให้ (เช่นมีคนยิง /command เองด้วยมือ)
# — สุ่มในช่วงนี้แทนเพื่อให้ยังเทสต์ต่อได้
FALLBACK_LIMITS = {"x_lo": 2.99, "x_hi": 3.02, "y_lo": 2.99, "y_hi": 3.02, "offset_max": None}

# ╔═══ โหมดจำลองความผิดพลาด (MOCK_MODE ใน .env) ═══════════════════════════════╗
#
# เดิม mock "ไม่เคยพลาด" — สุ่มค่าส่งสำเร็จทุกชิ้น จึงเทสต์เส้นทาง error ทั้งหมด
# ไม่ได้เลย (modal ถามผู้ใช้ · ปุ่มลองใหม่ · ปุ่มรับค่าจาก Pi · การนับ 3 รอบ)
# ต้องรอไปเจอของจริงหน้างานอย่างเดียว ซึ่งเป็นที่ที่แพงที่สุดในการเจอบั๊ก
#
#   default   ทำงานปกติ ไม่จำลอง error (ค่าเริ่มต้น)
#   t1        จำลอง "TM-X ปฏิเสธคำสั่ง T1"      → ของยังอยู่ในเครื่อง → ปุ่ม "ลองใหม่"
#   gm        จำลอง "GM ไม่คืนค่าใหม่"          → วัดไม่ติด          → ปุ่ม "ลองใหม่"
#   recieve   จำลอง "ค่าไม่ถึง DB"              → วัดแล้วแต่ไม่บันทึก → ปุ่ม "รับค่าจาก Pi"
#
# ⚠ ทั้ง 3 โหมดเดินเส้นทางเดียวกับ Pi.py เป๊ะ (report → ask_user → retry/accept/stop)
#   ไม่ใช่แค่ print หลอก ๆ — ไม่งั้นก็ยังเทสต์ modal ไม่ได้อยู่ดี
MOCK_MODE = os.getenv("MOCK_MODE", "default").strip().lower()

# ชิ้นที่จะให้พัง (นับจาก 1) — ตั้งเป็น 2 เพื่อให้เห็นชิ้นแรกสำเร็จก่อนจะได้
# เทียบกันเห็นชัดว่าอะไรเปลี่ยน
MOCK_FAIL_PIECE = int(os.getenv("MOCK_FAIL_PIECE", 1))

# พังกี่ครั้งติดกันก่อนจะยอมสำเร็จ — ใช้เทสต์ 2 ทางที่ต่างกันมาก:
#   1  = พังครั้งเดียว กด "ลองใหม่" แล้วผ่าน  → เทสต์ทางที่กู้คืนได้
#   99 = พังตลอด                              → เทสต์การนับครบ 3 รอบแล้วหยุด session
MOCK_FAIL_ROUNDS = int(os.getenv("MOCK_FAIL_ROUNDS", 1))

# ── ถามผู้ใช้ (ต้องตรงกับ Pi.py ทุกประการ) ──────────────────────────────────
# รอคำตอบจากคนได้นานสุดกี่วิ — ต้อง **มากกว่า** ตัวนับถอยหลังในหน้าเว็บ (60 วิ)
ASK_USER_TIMEOUT    = float(os.getenv("ASK_USER_TIMEOUT", 70))
MAX_ASK_USER_ROUNDS = int(os.getenv("MAX_ASK_USER_ROUNDS", 3))

# ── State ───────────────────────────────────────────────────────────────────
current_session_id = None   # session ที่กำลังวัดอยู่ (None = idle)
is_running = False          # ธงหยุดกลางคัน — ตั้งเป็น False เมื่อได้คำสั่ง stop
_hb_last_ok = time.time()   # เวลาที่ heartbeat ยิงออกสำเร็จครั้งล่าสุด

# คำตอบจาก modal — เขียนโดย /command (thread ของ uvicorn) อ่านโดย measurement_flow
# ⚠ ต้องประกาศระดับโมดูล ไม่ใช่ในฟังก์ชัน เพราะคนละ thread ต้องเห็นตัวเดียวกัน
_answer_event  = threading.Event()
_answer_action = None       # "retry" | "accept" | "stop" | None

# ── จำลองสัญญาณทริกเกอร์ (ต้องตรงกับ Pi.py) ────────────────────────────────
# Pi ตัวจริง **รอสัญญาณก่อนวัดทุกชิ้น** ส่วน mock เดิมวัดรวดเดียวจนครบ
# ต่างกันโดยตั้งใจ เพราะ mock มีไว้ให้เทสต์ได้โดยไม่ต้องมีใครกดอะไร
#
# MOCK_WAIT_TRIGGER=1 → ทำตัวเหมือน Pi จริง คือยืนรอทุกชิ้น ใช้ตอนอยากเทสต์
#                       ปุ่ม ⚡ Trigger บนหน้าเว็บให้ครบวง
# MOCK_WAIT_TRIGGER=0 → วัดเองรวดเดียว (ค่าเริ่มต้น — คงพฤติกรรมเดิมไว้)
#
# ⚠ ไม่ว่าโหมดไหน action `trigger` ต้องรับได้เสมอ ห้ามตอบ 400 เพราะ Pi รับได้
#   นี่คือกับดักเดียวกับ pause ที่เคยทำให้เทสต์ผ่านแต่เครื่องจริงพัง
MOCK_WAIT_TRIGGER = os.getenv("MOCK_WAIT_TRIGGER", "0") == "1"

_trigger = threading.Event()
_waiting_for_trigger = False   # heartbeat แนบค่านี้ไป → ปุ่มบนหน้าเว็บสว่างตามจริง
_answer_lock   = threading.Lock()

http_app = FastAPI(title="TM-X Mock Agent")


# ── Helper ──────────────────────────────────────────────────────────────────
def expand_groups(groups, target_count):
    """คลี่ `groups` จาก payload เป็นแผนรายชิ้น: [(alpl, template_name, limits), ...]

    ก่อนหน้านี้ mock ต้องยิง `GET /api/parts/{alpl}` ถาม nominal/tolerance เอง
    ตอนนี้ Backend ส่ง **ขอบเขตสำเร็จรูป** (`x_lo`/`x_hi`/…) มาให้ในคำสั่ง start
    เลย จึงไม่ต้องถามกลับอีก — และได้ผลพลอยได้สำคัญคือ mock ใช้ตัวเลข "ชุด
    เดียวกันเป๊ะ" กับที่ Pi ตัวจริงจะใช้ ไม่ใช่คนละชุดที่บังเอิญใกล้กัน

    ⚠ ALPL ที่ยังไม่ลงทะเบียน (โหมด New/IPM) เดิมจะ fallback ไปใช้ค่ามั่วๆ เพราะ
      ถาม backend แล้วไม่เจอ — ตอนนี้ได้ขอบเขตที่ถูกต้องมาตั้งแต่แรกทุกตัว
    """
    plan = []
    for g in groups or []:
        limits = g.get("limits") or dict(FALLBACK_LIMITS)
        for a in g.get("alpl") or []:
            plan.append((a, g.get("template_name"), limits))
    if not plan:
        # ไม่มี groups มาด้วย (payload เก่า / ยิงเองด้วยมือ) — เดินต่อแบบไม่รู้ ALPL
        print("⚠ payload ไม่มี groups — ใช้ขอบเขตสำรองและปล่อยให้ backend จับคู่ ALPL เอง")
        plan = [(None, None, dict(FALLBACK_LIMITS)) for _ in range(target_count or 1)]
    return plan


def random_value(lo, hi, force_ng):
    """สุ่มค่าวัด 1 แกนจากช่วงที่ backend ส่งมา

    - ปกติ (force_ng=False): สุ่มในช่วง [lo, hi] โดยหดขอบเข้ามา 10% ทั้ง 2 ฝั่ง
      กันค่าไปตกขอบพอดีแล้วกลายเป็น NG โดยไม่ตั้งใจจากการปัดเศษทศนิยม
    - บังคับ NG (force_ng=True): สุ่มให้หลุดออกไปนอกช่วงฝั่งใดฝั่งหนึ่ง
    """
    span = hi - lo
    if force_ng:
        out = span * random.uniform(0.5, 2.0)     # หลุดออกไป 0.5–2 เท่าของความกว้างช่วง
        return round(lo - out if random.random() < 0.5 else hi + out, 3)
    pad = span * 0.10
    return round(random.uniform(lo + pad, hi - pad), 3)


def random_offset(offset_max):
    """สุ่มค่า offset (ความเยื้อง)

    ไม่ผูกกับ force_ng เหมือน value_x/value_y โดยตั้งใจ — offset เป็นเกณฑ์อิสระ

    `offset_max = None` (โหมด IPM) แปลว่า backend ไม่เอา offset มาตัดสินเลย
    สุ่มกว้างๆ ได้ ไม่กระทบผล · ถ้ามีเพดาน จะสุ่มให้เกินเพดานบ้างตาม NG_RATE
    เพื่อให้เทสต์เคส "ตกเพราะ offset อย่างเดียว" ได้จริง (X/Y ผ่านแต่ผลเป็น NG)
    """
    if offset_max is None:
        return round(random.uniform(0.0, 0.030), 3)
    if random.random() < NG_RATE:
        return round(random.uniform(offset_max * 1.2, offset_max * 3.0), 3)
    return round(random.uniform(0.0, offset_max * 0.85), 3)


def random_offsets(offset_max):
    """สุ่มค่า offset ให้ครบทุกช่องที่ `MeasurementCreate` บังคับ

    คืน `(offset_opx, offset_opy, tr_op, tl_op, bl_op, br_op)` — **6 ค่า**

    ⚠ เดิม mock ส่งแค่ `offset` ตัวเดียว ซึ่งเป็นชื่อฟิลด์สมัยก่อนถอด GH ออก
      พอ model เปลี่ยนเป็นบังคับ 8 ฟิลด์ (`value_x/value_y` + 4 มุม + offset 2 แกน)
      backend ตอบ **422 Unprocessable Entity** ทุกชิ้น → `measured_count` ไม่ขยับ
      → session จบที่ 0 ชิ้นโดยไม่มีใครเห็นสาเหตุ (เกิดจริงกับ session 60)

    **ให้แกน X เป็นตัวตัดสินว่าจะเกินเพดานไหมแกนเดียว** แล้วแกน Y กับมุมทั้ง 4
    อิงจากมันอีกที — ถ้าสุ่มอิสระทุกตัว โอกาสได้ NG จะกลายเป็น ~6 เท่าของ
    `NG_RATE` ที่ตั้งไว้ ทำให้เทสต์ NG rate ไม่ได้ตามที่ตั้งใจ
    """
    ox = random_offset(offset_max)                          # ตัวนี้ถือ NG_RATE ไว้
    oy = round(abs(ox) * random.uniform(0.30, 0.95), 3)     # แกน Y อ่อนกว่าเสมอ

    # 4 มุมกระจายรอบ ๆ ค่าที่มากที่สุด — backend เอาไปหา "มุมที่แคบที่สุด"
    # (`_get_min_position_label`) ค่าต้องไม่เท่ากันหมด ไม่งั้นได้มุมเดิมทุกแถว
    base = max(abs(ox), abs(oy))
    tr, tl, bl, br = (round(max(0.0, base + random.uniform(-0.004, 0.004)), 3)
                      for _ in range(4))
    return ox, oy, tr, tl, bl, br


def post_measurement(session_id, number_alpl, value_x, value_y,
                     offset_opx, offset_opy, tr_op, tl_op, bl_op, br_op):
    """ส่งผลวัด 1 ชิ้นไปที่ Backend (POST /api/measurements)

    number_alpl ที่ส่งไปเป็นแค่ค่า fallback — Backend จะเพิกเฉยแล้วใช้ ALPL ตาม
    ตำแหน่งในคิวของ session นั้นเอง (ดู create_measurement) Agent ไม่จำเป็นต้อง
    รู้ว่ากำลังวัด ALPL ตัวไหนอยู่ในคิว
    client_uuid: สร้างใหม่ทุกชิ้น ใช้กัน insert ซ้ำถ้ามีการ retry

    ⚠⚠ **payload ต้องตรงกับ `MeasurementCreate` ใน shared.py เป๊ะ** — ทุกฟิลด์
       เป็น required ไม่มี default แล้ว (จงใจ เพราะ default 0.0 ทำให้ผู้ส่งที่
       ลืมใส่ได้แถวที่ดูสมบูรณ์แต่เป็นศูนย์ปลอม) ขาดตัวเดียว = **422 ทุกชิ้น**
       และอาการที่เห็นคือ "session จบที่ 0 ชิ้น" ซึ่งชี้ไปคนละทางกับสาเหตุจริง
       ถ้าแก้ model เมื่อไหร่ ต้องมาแก้ที่นี่ + `Recieve_tm-x.py` พร้อมกันเสมอ
    """
    payload = {
        "session_id":  session_id,
        "number_alpl": number_alpl,
        "value_x":     value_x,
        "value_y":     value_y,
        # ── offset 2 แกน ──
        "offset_opx":  offset_opx,
        "offset_opy":  offset_opy,
        # ── ค่ามุม 4 จุดของ OP (backend หา "มุมที่แคบที่สุด" จากชุดนี้) ──
        "tr_op":       tr_op,
        "tl_op":       tl_op,
        "bl_op":       bl_op,
        "br_op":       br_op,
        "client_uuid": str(uuid.uuid4()),
    }
    try:
        r = httpx.post(f"{BACKEND_URL}/api/measurements", json=payload, timeout=10)
        if r.is_success:
            d = r.json()
            print(f"   → บันทึกแล้ว: result={d.get('result')} "
                  f"({d.get('measured')}/{d.get('target')}) status={d.get('status')}")
            return d

        # ── Backend ปฏิเสธ — ต้องดังพอที่จะไม่หลุดสายตา ─────────────────────
        # ⚠ ของเดิมพิมพ์บรรทัดเดียวกลืนไปกับ log อื่น ทำให้ 422 ที่เกิดทุกชิ้น
        #   ถูกมองข้ามไปหลายรอบ กว่าจะรู้ว่าเป็นเพราะ payload ไม่ตรง model
        #   422 = Pydantic validate ไม่ผ่าน → payload ที่นี่ไม่ตรงกับ
        #   MeasurementCreate ให้ไปเทียบฟิลด์กันทีละตัว
        hint = " ← payload ไม่ตรงกับ MeasurementCreate (ฟิลด์ขาด/เกิน)" if r.status_code == 422 else ""
        print("\n" + "!" * 66)
        print(f"   ✖✖ Backend ปฏิเสธผลวัด (HTTP {r.status_code}){hint}")
        print(f"      {r.text[:400]}")
        print("!" * 66 + "\n")
        # ส่งขึ้นหน้าเว็บด้วย — ไม่งั้นคนที่ดูแต่หน้าจอจะเห็นแค่ "วัดไม่ขึ้น"
        report("BACKEND_REJECT", f"Backend ปฏิเสธผลวัด (HTTP {r.status_code}): {r.text[:200]}")
    except Exception as exc:
        print(f"   ✖ ส่งผลวัดไม่สำเร็จ: {exc}")
        report("BACKEND_REJECT", f"ส่งผลวัดไม่สำเร็จ: {exc}")
    return None


def heartbeat_loop():
    """ยิง POST /api/heartbeat ทุก HB_INTERVAL วิ ตลอดเวลาที่ mock รันอยู่
    (แนบ session_id ปัจจุบันถ้ากำลังวัดอยู่ — backend ใช้ต่ออายุ sessions.last_seen
    กัน heartbeat_checker mark session เป็น timeout) รันใน daemon thread แยก

    ⚠ ต้องมีพฤติกรรมตรงกับ send_command(Pi).py เสมอ — รวมถึงการหยุดตัวเองเมื่อ
    ขาดการติดต่อ backend เกิน HB_TIMEOUT_HINT (ดีไซน์สมมาตร: backend mark
    'timeout' ฝั่งมัน ส่วนเราตั้ง is_running=False ฝั่งเรา ต่างคนต่างตัดสินจาก
    กติกาเดียวกัน) เคยพลาดมาแล้วตอน pause ที่ mock รองรับแต่ Pi ไม่รองรับ
    เลยเทสต์ผ่านหมดแต่เครื่องจริงพัง
    """
    global is_running, _hb_last_ok
    while True:
        try:
            httpx.post(
                f"{BACKEND_URL}/api/heartbeat",
                json={
                    "session_id": current_session_id,
                    # ต้องส่งเหมือน Pi.py — ไม่งั้นปุ่ม ⚡ Trigger บนหน้าเว็บ
                    # จะดับค้างตอนเทสต์ด้วย mock แล้วเข้าใจผิดว่าฟีเจอร์พัง
                    "waiting_for_trigger": _waiting_for_trigger,
                },
                timeout=5,
            )
            _hb_last_ok = time.time()
        except Exception:
            pass  # backend ล่มชั่วคราวไม่ควรทำให้ mock ตาย

        # เช็คนอก try เสมอ — ต้องทำงานทุกรอบไม่ว่ารอบนี้จะยิงออกหรือไม่
        if is_running and time.time() - _hb_last_ok > HB_TIMEOUT_HINT:
            print(f"\n⏹ ติดต่อ Backend ไม่ได้เกิน {HB_TIMEOUT_HINT:g} วิ — หยุดวัด")
            is_running = False
        time.sleep(HB_INTERVAL)


def report(event: str, detail: str, *, persist: bool = True):
    """แจ้ง Backend ว่าเกิดอะไรขึ้น — พิมพ์ก่อนเสมอ แล้วค่อยส่ง (ตรงกับ Pi.py)

    Backend เขียนลง `sessions.last_event / last_event_detail` แล้ว broadcast SSE
    `station_event` · ค่านี้คือสิ่งที่ `/api/measure-timeout` หยิบไปแปะเป็นบรรทัด
    "สาเหตุ" ใน modal — **ต้องเรียกก่อน ask_user() เสมอ** ไม่งั้น modal จะขึ้น
    แต่ไม่มีสาเหตุ

    ⚠ ห้ามโยน exception ออกไป — การรายงานปัญหาต้องไม่กลายเป็นปัญหาเสียเอง
    """
    print(f"   📣 {event}: {detail}")
    try:
        r = httpx.post(f"{BACKEND_URL}/api/session/event",
                       json={"event": event, "detail": detail, "persist": persist},
                       timeout=2)
        if r.status_code != 200:
            print(f"   ⚠️ Backend ไม่รับรายงาน (HTTP {r.status_code})")
    except Exception as exc:
        print(f"   ⚠️ แจ้ง Backend ไม่สำเร็จ: {exc}")


def ask_user(session_id, piece, target) -> str:
    """เด้ง modal ถามผู้ใช้แล้ว **บล็อกรอคำตอบ** — คืน "retry" | "accept" | "stop"

    คำตอบไม่ได้กลับมาทางนี้ — มันเข้ามาทาง `/command` ซึ่งอยู่คนละ thread แล้ว
    `_answer_event.set()` ปลุกเราอีกที (Event ไม่มีที่ใส่ข้อมูล จึงต้องมี
    `_answer_action` แยกไว้รับเนื้อหา)

    ทุกทางที่ผิดพลาดคืน "stop" — ถามไม่ได้/ไม่มีคนตอบ = ห้ามเดินหน้าต่อเอง
    (fail-safe ตรงกับตัวนับถอยหลังในหน้าเว็บที่กดหยุดให้เมื่อไม่มีคนอยู่)
    """
    global _answer_action
    with _answer_lock:
        _answer_action = None
        _answer_event.clear()

    try:
        r = httpx.post(f"{BACKEND_URL}/api/measure-timeout",
                       json={"session_id": session_id, "piece": piece, "target": target},
                       timeout=5)
        if r.status_code != 200:
            print(f"   ⚠️ Backend ไม่รับคำถาม (HTTP {r.status_code}) — ถือว่าหยุด")
            return "stop"
    except Exception as exc:
        print(f"   ⚠️ ถามผู้ใช้ไม่ได้: {exc} — ถือว่าหยุด")
        return "stop"

    print(f"   ⏳ รอผู้ใช้ตัดสินใจ (สูงสุด {ASK_USER_TIMEOUT:.0f} วิ) ...")
    if not _answer_event.wait(ASK_USER_TIMEOUT):
        print(f"   ⏱ ไม่มีคำตอบใน {ASK_USER_TIMEOUT:.0f} วิ — ถือว่าหยุด")
        return "stop"

    with _answer_lock:
        return _answer_action or "stop"


def mock_should_fail(mode: str, piece: int, rounds: int) -> bool:
    """โหมดนี้ควรทำให้ชิ้นที่ `piece` พังในรอบที่ `rounds` ไหม (rounds เริ่มที่ 0)

    แยกออกมาเป็นฟังก์ชันเดียวเพื่อให้ทั้ง 3 โหมดใช้กติกาเดียวกัน — ไม่งั้น
    แต่ละโหมดจะค่อย ๆ เพี้ยนกันเองจนเทียบผลกันไม่ได้
    """
    return MOCK_MODE == mode and piece == MOCK_FAIL_PIECE and rounds < MOCK_FAIL_ROUNDS


def _mock_stage(mode: str, event: str, detail: str, session_id, piece, target) -> bool:
    """จำลองด่านที่ "ลองใหม่ได้" (T1 / GM) — คืน True ถ้าผ่านไปต่อได้

    วนแบบเดียวกับ `handle_error` ใน Pi.py เป๊ะ: report → ถามผู้ใช้ → ลองใหม่
    ครบ MAX_ASK_USER_ROUNDS แล้วยังไม่ผ่าน → คืน False ให้ผู้เรียก break

    คืน True ทันทีถ้าโหมดนี้ไม่ได้ถูกเลือก หรือชิ้นนี้ไม่ใช่ชิ้นที่ตั้งให้พัง
    """
    if MOCK_MODE != mode or piece != MOCK_FAIL_PIECE:
        return True

    rounds = 0
    while mock_should_fail(mode, piece, rounds):
        print(f"\n💥 (จำลอง) ชิ้นที่ {piece}/{target} — {event}")
        report(event, f"{detail} [ครั้งที่ {rounds + 1}/{MAX_ASK_USER_ROUNDS}]")

        if rounds + 1 >= MAX_ASK_USER_ROUNDS:
            report(f"{event.split('_')[0]}_GAVE_UP",
                   f"ชิ้นที่ {piece}/{target}: ครบ {MAX_ASK_USER_ROUNDS} ครั้งแล้ว — หยุดการวัด")
            return False
        if not is_running:
            return False
        if ask_user(session_id, piece, target) != "retry":
            print("   ⏹ ผู้ใช้เลือกหยุดการวัด")
            return False

        rounds += 1
        print(f"   🔁 ลองใหม่รอบที่ {rounds + 1}/{MAX_ASK_USER_ROUNDS}")

    if rounds:
        print(f"   ✅ (จำลอง) สำเร็จในรอบที่ {rounds + 1}")
    return True


def judge(value_x, value_y, offset_opx, offset_opy, limits):
    """ตัดสิน OK/NG แบบเดียวกับที่ Pi ตัวจริงจะทำ — เทียบกับขอบเขตตรงๆ

    ไม่มี `_TOL_EPS` ที่นี่โดยตั้งใจ: backend บวก/ลบให้เรียบร้อยแล้วตอนสร้าง
    `limits` (ดู `_limits_of`) ถ้ามาเผื่อซ้ำอีกรอบจะกลายเป็นเผื่อ 2 เท่า

    ⚠ ต้องตรวจ offset **ทั้ง 2 แกน** ให้ตรงกับ `_judge` ฝั่ง backend
      (`ok_opx and ok_opy`) — ถ้าตรวจแกนเดียว จะมีชิ้นที่ mock บอก OK แต่
      backend บันทึก NG แล้วขึ้นเตือน "ไม่ตรงกัน!" ทั้งที่ไม่มีอะไรผิด
    """
    ok_x = limits["x_lo"] <= value_x <= limits["x_hi"]
    ok_y = limits["y_lo"] <= value_y <= limits["y_hi"]
    om   = limits.get("offset_max")
    ok_o = True if om is None else (abs(offset_opx) <= om and abs(offset_opy) <= om)
    return "OK" if (ok_x and ok_y and ok_o) else "NG"


def wait_for_trigger_mock(piece, target_count):
    """ยืนรอสัญญาณทริกเกอร์ก่อนวัดชิ้นนี้ — คืน False ถ้าถูกสั่ง Stop ระหว่างรอ

    ลอกกลไกมาจาก `wait_for_trigger_mcu()` ใน Pi.py ทั้งดุ้น รวมถึงเหตุผลด้วย:

    ① `_trigger.clear()` ก่อนเสมอ — ถ้าไม่ล้าง สัญญาณค้างจากชิ้นก่อนหน้าจะทำให้
       รอบนี้ผ่านทันทีโดยไม่มีใครกด แล้วก็จะ "วัดอากาศ"

    ② `wait(0.1)` วนแทนที่จะ `wait()` รอไม่จำกัด — ต้องได้กลับมาเช็ค `is_running`
       เรื่อยๆ ไม่งั้นกด Stop จากหน้าเว็บแล้วเธรดนี้จะค้างตลอดไป ไม่มีใครปลุก

    ③ `finally` ปิดธงเสมอ — ถ้าค้างเป็น True สัญญาณรอบถัดไปจะถูกรับทั้งที่ไม่มีใครรอ
    """
    global _waiting_for_trigger
    _trigger.clear()
    _waiting_for_trigger = True
    print(f"\nชิ้นที่ {piece}/{target_count} — รอสัญญาณ trigger ... "
          f"(กดปุ่ม ⚡ Trigger บนหน้าเว็บ หรือ curl -X POST :{AGENT_PORT}/trigger)")
    try:
        while is_running:
            if _trigger.wait(0.1):
                return True
        return False
    finally:
        _waiting_for_trigger = False


def measurement_flow(session_id, groups, target_count):
    """Flow หลัก — รันใน thread แยกเพื่อไม่ block FastAPI server

    วนสุ่มค่าส่งให้ Backend ทีละชิ้นตามแผนที่คลี่จาก `groups` จนครบ target_count
    หรือจนกว่าจะโดนสั่ง Stop

    เดินตามกลุ่มเหมือน Pi ตัวจริง — พอข้ามกลุ่มจะพิมพ์บอกว่า "ต้องสลับ PW"
    (Pi จริงยิง `PW,1,<template>` ตรงจุดนี้) เพื่อให้เห็นด้วยตาว่าลำดับถูกไหม
    """
    global current_session_id, is_running, _hb_last_ok
    # รีเซ็ตนาฬิกา heartbeat ก่อนตั้ง is_running=True เสมอ — ไม่งั้นถ้า backend
    # เพิ่งฟื้นจากดับไปนาน _hb_last_ok จะค้างเก่าจน heartbeat_loop หยุด session
    # ทิ้งทันทีที่กด Start (เหตุผลเต็มอยู่ใน send_command(Pi).py)
    _hb_last_ok = time.time()
    current_session_id = session_id
    is_running = True
    target_count = target_count or 1
    stop_reason = None          # เหตุผลที่จบกลางคัน — แนบไปกับ /api/session/stop

    plan = expand_groups(groups, target_count)

    print(f"\n{'='*62}")
    print(f"✅ START — session={session_id}, {len(plan)} ชิ้น / {len(groups or [])} กลุ่ม"
          f"  (target_count={target_count})")
    for gi, g in enumerate(groups or []):
        L = g.get("limits") or {}
        print(f"   กลุ่มที่ {gi+1}: template={g.get('template_name')!r}  ALPL={g.get('alpl')}")
        print(f"      X {L.get('x_lo')}–{L.get('x_hi')} · Y {L.get('y_lo')}–{L.get('y_hi')}"
              f" · offset_max={L.get('offset_max')}")
    print(f"   NG rate ≈ {NG_RATE:.0%}")
    print(f"{'='*62}")

    if len(plan) != target_count:
        # ไม่หยุดการทำงาน แต่ต้องเห็นทันที — แปลว่าคิวกับเกณฑ์เหลื่อมกัน
        print(f"⚠ จำนวน ALPL ใน groups ({len(plan)}) ไม่เท่ากับ target_count ({target_count})")

    prev_template = None
    for piece, (alpl, template_name, limits) in enumerate(plan[:target_count], start=1):
        if not is_running:
            print("\n⏹ ได้รับคำสั่ง Stop — หยุดการวัด")
            break

        if template_name != prev_template:
            print(f"\n🔄 สลับโปรแกรมวัด → PW,1,{template_name}  (Pi จริงยิงคำสั่งนี้ตรงนี้)")
            prev_template = template_name

        # ── รอสัญญาณทริกเกอร์ (เฉพาะ MOCK_WAIT_TRIGGER=1) ────────────────
        # ลำดับเดียวกับ Pi.py — โหลดโปรแกรมเสร็จแล้วค่อยยืนรอชิ้นงาน
        if MOCK_WAIT_TRIGGER and not wait_for_trigger_mock(piece, target_count):
            print("\n⏹ ได้รับคำสั่ง Stop — หยุดการวัด")
            break

        time.sleep(MEASURE_INTERVAL)  # จำลองเวลาที่เครื่องใช้วัด 1 ชิ้น

        # เช็คซ้ำหลังหน่วงเวลา — เผื่อ Stop มาถึงระหว่างที่กำลังวัดชิ้นนี้อยู่
        if not is_running:
            print("\n⏹ ได้รับคำสั่ง Stop — หยุดการวัด")
            break

        # ── ② จำลอง T1 ไม่ผ่าน — ของยังอยู่ในเครื่อง ลองใหม่ได้ ───────────
        if not _mock_stage("t1", "T1_FAILED",
                           f"TM-X ปฏิเสธคำสั่ง T1 — ER,T1,05 (จำลองจาก MOCK_MODE=t1)",
                           session_id, piece, target_count):
            stop_reason = f"ชิ้นที่ {piece}/{target_count}: ยิง T1 ไม่สำเร็จ (จำลอง)"
            break

        # ── ③ จำลอง GM ไม่คืนค่า — TM-X วัดไม่ติด ─────────────────────────
        if not _mock_stage("gm", "GM_NO_VALUE",
                           f"รอ 8 วิแล้ว GM ยังไม่คืนค่าใหม่ (จำลองจาก MOCK_MODE=gm)",
                           session_id, piece, target_count):
            stop_reason = f"ชิ้นที่ {piece}/{target_count}: TM-X วัดไม่ติด (จำลอง)"
            break

        force_ng = random.random() < NG_RATE
        value_x = random_value(limits["x_lo"], limits["x_hi"], force_ng)
        value_y = random_value(limits["y_lo"], limits["y_hi"], force_ng)
        offset_opx, offset_opy, tr_op, tl_op, bl_op, br_op = \
            random_offsets(limits.get("offset_max"))
        verdict = judge(value_x, value_y, offset_opx, offset_opy, limits)

        print(f"\n🔍 ชิ้นที่ {piece}/{target_count} (ALPL {alpl}) — "
              f"X={value_x}  Y={value_y}  offset=({offset_opx}, {offset_opy})"
              f"  มุม tr/tl/bl/br=({tr_op}, {tl_op}, {bl_op}, {br_op})"
              f"  → Pi ตัดสิน: {verdict}"
              f"{'  (จงใจให้ NG)' if force_ng else ''}")

        # ── จำลองค่าไม่ถึง DB — **วัดสำเร็จแล้ว** แต่ Recieve ส่งไม่ถึง ─────
        # ⚠ เคสนี้ไม่มี "ลองใหม่" โดยตั้งใจ — ของถูกวัดและคัดแยกไปแล้ว
        #   ทางเดียวคือรับค่าที่ถืออยู่ (ไม่มีรูป) หรือหยุด
        if MOCK_MODE == "recieve" and piece == MOCK_FAIL_PIECE:
            print("   🚫 (จำลอง) ไม่ POST ค่าเข้า Backend — เหมือน Recieve ส่งไม่ถึง")
            report("NO_DB_ROW",
                   f"ชิ้นที่ {piece}/{target_count}: วัดได้แล้วแต่ค่าไม่ถึงฐานข้อมูล "
                   f"— ตรวจว่า Recieve_tm-x.py รันอยู่ไหม (จำลองจาก MOCK_MODE=recieve)")
            if ask_user(session_id, piece, target_count) != "accept":
                print("   ⏹ ผู้ใช้เลือกหยุดการวัด")
                stop_reason = f"ชิ้นที่ {piece}/{target_count}: ค่าไม่ถึงฐานข้อมูล (จำลอง)"
                break
            print("   📥 ผู้ใช้เลือกรับค่าจาก Pi — บันทึกโดยไม่มีรูป")

        d = post_measurement(session_id, alpl, value_x, value_y,
                             offset_opx, offset_opy, tr_op, tl_op, bl_op, br_op)
        # ⚠ จุดที่ควรจับตา: ถ้า Pi กับ Backend ตัดสินไม่ตรงกัน แปลว่า `limits`
        #   ที่ส่งมากับเกณฑ์ที่ backend ใช้ query ตอนบันทึกไม่ใช่ชุดเดียวกัน
        #   (เคสนี้คือสิ่งที่ _build_groups พยายามกันไว้ — เห็นตรงนี้ถือว่าหลุด)
        if d and d.get("result") and d["result"] != verdict:
            print(f"   ⚠⚠ ไม่ตรงกัน! Pi={verdict} แต่ Backend บันทึก {d['result']}")

    # ⚠ ล้างธงเฉพาะเมื่อเรายังเป็น "เจ้าของ" อยู่จริง — ถ้ามี session ใหม่เริ่มไป
    #   แล้วระหว่างที่เรากำลังเก็บกวาด (เช่นเราค้างอยู่ใน ask_user 90 วิ) การเซ็ต
    #   is_running=False ตรงนี้จะไปฆ่า session ของคนอื่นทิ้งกลางคัน
    if current_session_id == session_id:
        is_running = False
        current_session_id = None  # heartbeat กลับไปยิงแบบ idle
    else:
        print(f"   ℹ️ มี session ใหม่ ({current_session_id}) เริ่มไปแล้ว — ไม่แตะธงร่วม")
    print(f"\n✅ จบ session {session_id}\n")

    # ── แจ้ง backend ปิด session ถ้าจบกลางคัน (ตรงกับ finally ของ Pi.py) ─────
    # ⚠ ต้องเช็คว่ายังเป็น session ของเราและยัง running อยู่ก่อน — กันยิงซ้ำตอน
    #   ผู้ใช้กด Stop เอง (backend ปิดไปแล้ว) และกันไปปิด session ของรอบใหม่
    try:
        st = httpx.get(f"{BACKEND_URL}/api/session/state", timeout=5).json()

        # ── log วินิจฉัย: บอกให้ครบว่าเห็นอะไรและตัดสินใจยังไง ──────────────
        # ของเดิมพิมพ์เฉพาะตอน "ยิง" ทำให้ตอนไม่ยิงมองไม่เห็นเลยว่าเพราะอะไร
        # และตอนยิงก็ไม่รู้ว่า backend ตอบอะไรมาจริง ๆ — ไล่ปัญหาไม่ได้
        print(f"   🔎 backend ตอบ: session_id={st.get('session_id')} "
              f"state={st.get('state')!r} measured={st.get('measured_count')} "
              f"(ของเรา session_id={session_id})")

        if st.get("session_id") != session_id:
            print("   ↳ ไม่ใช่ session ของเราแล้ว — ไม่แจ้งปิด")
        elif st.get("state") != "running":
            print(f"   ↳ ถูกปิดไปแล้ว (state={st.get('state')}) — ไม่ต้องแจ้งซ้ำ")
        else:
            measured = st.get("measured_count")
            # ห้ามส่ง None — backend เช็ค `if req.reason:` ถ้าว่างจะไม่เขียนลง DB
            # แล้วหน้าเว็บขึ้น STOPPED เปล่า ๆ โดยไม่มีคำอธิบาย
            reason = stop_reason or (
                f"session จบก่อนครบจำนวน (วัดได้ {measured}/{target_count}) "
                f"— ไม่ทราบสาเหตุแน่ชัด ดู log ของ mockup.py"
            )
            httpx.post(f"{BACKEND_URL}/api/session/stop",
                       json={"session_id": session_id, "reason": reason}, timeout=10)
            print(f"⏹ แจ้ง backend ปิด session แล้ว (วัดได้ {measured}/{target_count})")
            print(f"   เหตุผล: {reason}")
    except Exception as exc:
        print(f"   ⚠️ แจ้งปิด session ไม่ได้: {exc}")
        if stop_reason:
            print(f"   เหตุผลที่จะหายไป: {stop_reason}")


# ── HTTP endpoint (Backend เรียกเข้ามาสั่ง Start/Stop) ────────────────────────
class GroupLimits(BaseModel):
    x_lo: float
    x_hi: float
    y_lo: float
    y_hi: float
    offset_max: float | None = None   # None = โหมด IPM (ไม่เอา offset มาตัดสิน)


class EntryGroup(BaseModel):
    template_name: str | None = None
    alpl: list[int] = []
    limits: GroupLimits | None = None


class CommandRequest(BaseModel):
    action: str
    session_id: int | None = None
    target_count: int | None = None
    # groups = แหล่งความจริงเดียวของ "วัดอะไร ด้วยโปรแกรมไหน เกณฑ์เท่าไหร่"
    # (Backend เลิกส่ง template_name/number_alpl ระดับบนสุดแล้ว — ทั้งคู่เป็นของ
    #  กลุ่มแรกซึ่งอยู่ใน groups[0] อยู่ดี ส่งซ้ำจะมีแหล่งความจริง 2 ที่)
    groups: list[EntryGroup] | None = None


@http_app.post("/command")
async def command(req: CommandRequest):
    """ประตูเดียวที่รับคำสั่งจากข้างนอก — ต้องรับ action ชุดเดียวกับ Pi.py เป๊ะ

    ⚠ ทุก action ที่ตอบคำถามค้าง (retry/accept/stop) ต้อง `_answer_event.set()`
      เสมอ ไม่งั้น ask_user() ที่บล็อกรออยู่จะค้างจนครบ ASK_USER_TIMEOUT

    ⚠ ถอด action `continue` ออกแล้ว (22 ส.ค. 2569) — Pi.py ไม่เคยรองรับ กดแล้ว
      backend ขยับคิวไปแล้วแต่สั่ง Pi ไม่ผ่าน → คิวเหลื่อมถาวร · ที่นี่เคยรองรับ
      อยู่ฝ่ายเดียวจึงเป็นกับดักซ้ำรอย pause พอดี
    """
    global is_running, _answer_action

    if req.action == "start":
        groups = [g.model_dump() for g in (req.groups or [])]
        # ล้างคำตอบค้างจาก session ก่อนหน้า — ถ้ารอบที่แล้วจบตอน modal เปิดอยู่
        with _answer_lock:
            _answer_action = None
            _answer_event.clear()
        threading.Thread(
            target=measurement_flow,
            args=(req.session_id, groups, req.target_count),
            daemon=True,
        ).start()

    elif req.action == "retry":
        # ผู้ใช้กด "ลองใหม่" — ชิ้นเดิม ตำแหน่งคิวไม่ขยับ
        print("\n🔁 ได้รับคำสั่ง Retry จาก Backend")
        with _answer_lock:
            _answer_action = "retry"      # ← เขียนค่าก่อน
        _answer_event.set()               # ← ค่อยปลุก (ห้ามสลับลำดับ)

    elif req.action == "accept":
        # ผู้ใช้กด "รับค่าจาก Pi (ไม่มีรูป)" — ใช้กับ MOCK_MODE=recieve
        print("\n📥 ได้รับคำสั่ง Accept จาก Backend")
        with _answer_lock:
            _answer_action = "accept"
        _answer_event.set()

    elif req.action == "trigger":
        # ปุ่ม ⚡ Trigger บนหน้าเว็บ — guard ชุดเดียวกับ Pi.py เป๊ะ รวมถึงรหัส HTTP
        # ⚠ ต้องรับ action นี้ได้แม้ตอน MOCK_WAIT_TRIGGER=0 (จะตอบ 409 ไป)
        #   ห้ามตกไปที่ else แล้วตอบ 400 เพราะ Pi รับได้ — จะกลายเป็นความต่าง
        #   แบบเดียวกับ pause ที่เคยทำให้เทสต์ผ่านแต่เครื่องจริงพัง
        if not is_running:
            raise HTTPException(400, "ไม่มี session กำลังวัดอยู่ — กด Start ที่หน้าเว็บก่อน")
        if not _waiting_for_trigger:
            raise HTTPException(
                409,
                "ยังไม่ถึงช่วงรอสัญญาณ — ระบบกำลังโหลดโปรแกรมวัด "
                "หรือกำลังรอผลของชิ้นก่อนหน้าอยู่"
                + ("" if MOCK_WAIT_TRIGGER else " (mock ตั้ง MOCK_WAIT_TRIGGER=0 จึงวัดเองไม่รอสัญญาณ)"),
            )
        _trigger.set()
        print("\n⚡ ได้รับสัญญาณ trigger (จากปุ่มบนหน้าเว็บ)")

    elif req.action == "stop":
        print("\n⏹ ได้รับคำสั่ง Stop จาก Backend")
        is_running = False  # loop ใน measurement_flow จะเห็นแล้วหยุดเอง
        # ⚠ ต้อง set ด้วย ไม่งั้นกด Stop ตอน modal เปิดอยู่ ask_user() จะค้างต่อ
        with _answer_lock:
            _answer_action = "stop"
        _answer_event.set()

    # ปฏิเสธ action ที่ไม่รู้จักเหมือน Pi.py — ต้องมีพฤติกรรมตรงกันทั้ง 2 ตัว
    # ไม่งั้นเทสต์ด้วย mockup ผ่านแต่เครื่องจริงพัง (เคสเดิมของ pause)
    else:
        raise HTTPException(
            400, f"ไม่รู้จัก action '{req.action}' — "
                 f"รองรับแค่ start/stop/retry/accept/trigger")
    return {"status": "ok", "action": req.action}


@http_app.api_route("/trigger", methods=["GET", "POST"])
async def trigger():
    """จำลองเซนเซอร์ — มีไว้ให้ยิงด้วยมือเหมือน Pi.py

        curl -X POST http://localhost:9998/trigger

    ตอบเป็น {"ok": ...} ไม่ใช่ HTTP error ต่างจาก action `trigger` ใน /command
    เพราะเส้นนี้มีไว้ให้คนยิงเล่นจากเทอร์มินอล — อ่านง่ายกว่า traceback
    (Pi.py ก็แยกสองเส้นแบบนี้ด้วยเหตุผลเดียวกัน)
    """
    if not is_running:
        return {"ok": False, "reason": "ไม่มี session กำลังวัดอยู่ — กด Start ที่หน้าเว็บก่อน"}
    if not _waiting_for_trigger:
        return {"ok": False,
                "reason": "ยังไม่ถึงช่วงรอสัญญาณ"
                          + ("" if MOCK_WAIT_TRIGGER
                             else " — mock ตั้ง MOCK_WAIT_TRIGGER=0 จึงวัดเองไม่รอสัญญาณ")}
    _trigger.set()
    print("\n⚡ ได้รับสัญญาณ trigger")
    return {"ok": True}


if __name__ == "__main__":
    threading.Thread(target=heartbeat_loop, daemon=True).start()
    print(f"🤖 mockup.py — Mock Agent (สุ่มค่าแทนฮาร์ดแวร์จริง)")
    print(f"   Backend  : {BACKEND_URL}")
    print(f"   หน่วงเวลา/ชิ้น: {MEASURE_INTERVAL}s   |   NG rate: {NG_RATE:.0%}")

    # ── โหมดจำลอง error ──────────────────────────────────────────────────
    _MODE_DESC = {
        "default": "ทำงานปกติ ไม่จำลอง error",
        "t1":      "จำลอง T1 ไม่ผ่าน   → modal ปุ่ม 'ลองใหม่'",
        "gm":      "จำลอง GM ไม่คืนค่า → modal ปุ่ม 'ลองใหม่'",
        "recieve": "จำลองค่าไม่ถึง DB  → modal ปุ่ม 'รับค่าจาก Pi'",
    }
    if MOCK_MODE not in _MODE_DESC:
        print(f"   ⚠️  MOCK_MODE='{MOCK_MODE}' ไม่รู้จัก — ใช้ default แทน "
              f"(เลือกได้: {' / '.join(_MODE_DESC)})")
    else:
        print(f"   MOCK_MODE: {MOCK_MODE}  — {_MODE_DESC[MOCK_MODE]}")
        if MOCK_MODE != "default":
            print(f"      พังที่ชิ้นที่ {MOCK_FAIL_PIECE} · พังติดกัน {MOCK_FAIL_ROUNDS} ครั้ง "
                  f"(โควตาถามผู้ใช้ {MAX_ASK_USER_ROUNDS} ครั้ง)")
            if MOCK_MODE != "recieve" and MOCK_FAIL_ROUNDS >= MAX_ASK_USER_ROUNDS:
                print(f"      → จะใช้โควตาหมดแล้วหยุด session (เทสต์ทางที่กู้ไม่ได้)")

    if MOCK_WAIT_TRIGGER:
        print("   ⚡ MOCK_WAIT_TRIGGER=1 — รอสัญญาณก่อนวัดทุกชิ้นเหมือน Pi จริง")
        print(f"      กดปุ่ม ⚡ Trigger บนหน้าเว็บ หรือ curl -X POST localhost:{AGENT_PORT}/trigger")
    else:
        print("   ⏩ MOCK_WAIT_TRIGGER=0 — วัดเองรวดเดียวไม่รอสัญญาณ "
              "(ตั้งเป็น 1 ถ้าอยากเทสต์ปุ่ม Trigger)")

    print(f"   heartbeat ทุก {HB_INTERVAL:g}s · หยุดเองถ้าขาดติดต่อเกิน {HB_TIMEOUT_HINT:g}s")
    print(f"   กำลังรอคำสั่ง Start จาก Backend ที่ port {AGENT_PORT}...\n")

    # เตือนแบบเดียวกับ send_command(Pi).py / Pi.py — ต้องมีทุกตัวที่ยิง heartbeat
    # ไม่งั้นเทสต์ด้วย mockup แล้วผ่าน พอไปเครื่องจริงถึงเจอ (กติกาใน CLAUDE.md)
    if HB_INTERVAL * 2 > HB_TIMEOUT_HINT:
        print(f"⚠️  HEARTBEAT_INTERVAL ({HB_INTERVAL:g}s) ถี่ไม่พอเมื่อเทียบกับ "
              f"HEARTBEAT_TIMEOUT ({HB_TIMEOUT_HINT:g}s)")
        print(f"    แนะนำให้ HEARTBEAT_INTERVAL ไม่เกิน {HB_TIMEOUT_HINT/2:g}s — แก้ที่ .env\n")
    uvicorn.run(http_app, host="0.0.0.0", port=AGENT_PORT)
