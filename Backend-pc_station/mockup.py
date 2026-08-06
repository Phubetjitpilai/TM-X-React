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
from fastapi import FastAPI
from pydantic import BaseModel

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))

# ── Config ──────────────────────────────────────────────────────────────────
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")
AGENT_PORT  = int(os.getenv("AGENT_PORT", 9998))
HB_INTERVAL = 5  # วินาที — ต้องน้อยกว่า HEARTBEAT_TIMEOUT ของ backend (15s)

# เวลาหน่วงระหว่างการวัดแต่ละชิ้น (วินาที) — จำลองเวลาที่เครื่องจริงใช้วัด 1 ชิ้น
# ตั้งให้ช้าลงได้ถ้าอยากดู SSE อัปเดตทีละชิ้นบน dashboard ชัดๆ
MEASURE_INTERVAL = float(os.getenv("MOCK_MEASURE_INTERVAL", 2.0))

# สัดส่วนชิ้นงานที่จงใจสุ่มให้ "หลุด tolerance" (ได้ NG) — 0.2 = ประมาณ 20%
# ตั้งเป็น 0 ถ้าอยากให้ OK ทุกชิ้น หรือ 1 ถ้าอยากเทสต์เคส NG ล้วน
NG_RATE = float(os.getenv("MOCK_NG_RATE", 0.2))

# ค่า fallback ตอนดึง nominal/tolerance ของ ALPL จาก Backend ไม่ได้ (เช่น ALPL
# นั้นยังไม่ได้ตั้ง part_number) — สุ่มรอบๆ ค่านี้แทนเพื่อให้ยังเทสต์ต่อได้
FALLBACK_SPEC = {"nominal_x": 3.0, "nominal_y": 3.0, "upper_tol": 0.02, "lower_tol": 0.01}

# ── State ───────────────────────────────────────────────────────────────────
current_session_id = None   # session ที่กำลังวัดอยู่ (None = idle)
is_running = False          # ธงหยุดกลางคัน — ตั้งเป็น False เมื่อได้คำสั่ง stop
is_paused = False           # ธงพักชั่วคราว — True ระหว่าง pause, loop จะวนรอเฉยๆ

http_app = FastAPI(title="TM-X Mock Agent")


# ── Helper ──────────────────────────────────────────────────────────────────
def fetch_spec(number_alpl):
    """ดึง nominal/tolerance จริงของ ALPL นี้จาก Backend (GET /api/parts/{alpl})

    ทำไมต้องดึง: ถ้าสุ่มค่ามั่วๆ ไม่อิง nominal เลย ผลจะเป็น NG เกือบทุกชิ้น
    ทำให้เทสต์ flow ปกติ (OK) ไม่ได้ — ดึงมาก่อนแล้วสุ่มรอบๆ ค่านั้นแทน
    ถ้าดึงไม่ได้/ไม่มีข้อมูล จะ fallback ไปใช้ FALLBACK_SPEC เพื่อให้เทสต์ต่อได้
    """
    try:
        r = httpx.get(f"{BACKEND_URL}/api/parts/{number_alpl}", timeout=5)
        if r.is_success:
            d = r.json()
            if d.get("nominal_x") is not None and d.get("upper_tol") is not None:
                return {
                    "nominal_x": float(d["nominal_x"]),
                    "nominal_y": float(d["nominal_y"]),
                    "upper_tol": float(d["upper_tol"]),
                    "lower_tol": float(d["lower_tol"]),
                }
            print(f"⚠ ALPL {number_alpl} ยังไม่ได้ตั้ง Part Number (ไม่มี nominal/tolerance) — ใช้ค่า fallback")
    except Exception as exc:
        print(f"⚠ ดึง spec ของ ALPL {number_alpl} ไม่สำเร็จ ({exc}) — ใช้ค่า fallback")
    return dict(FALLBACK_SPEC)


def random_value(nominal, upper_tol, lower_tol, force_ng):
    """สุ่มค่าวัด 1 แกน

    - ปกติ (force_ng=False): สุ่มให้อยู่ในช่วง [nominal-lower_tol, nominal+upper_tol]
      โดยหดขอบเข้ามาเล็กน้อย (85%) กันค่าไปตกขอบพอดีแล้วกลายเป็น NG โดยไม่ตั้งใจ
      จากการปัดเศษทศนิยม
    - บังคับ NG (force_ng=True): สุ่มให้หลุดออกไปนอกช่วง tolerance ฝั่งใดฝั่งหนึ่ง
    """
    if force_ng:
        overshoot = random.uniform(1.5, 4.0)  # หลุดออกไป 1.5–4 เท่าของ tolerance
        if random.random() < 0.5:
            return round(nominal - lower_tol * overshoot, 3)
        return round(nominal + upper_tol * overshoot, 3)
    return round(random.uniform(nominal - lower_tol * 0.85, nominal + upper_tol * 0.85), 3)


def random_offset():
    """สุ่มค่า offset (ความเยื้อง) 0.000 – 0.030 ตามที่กำหนด

    ไม่ผูกกับ force_ng เหมือน value_x/value_y โดยตั้งใจ — offset เป็นเกณฑ์อิสระ
    ที่เทียบกับ offset_tol ของ part_number ถ้า offset_tol ตั้งไว้ต่ำกว่า 0.030
    ค่าที่สุ่มได้บางส่วนจะทำให้ NG เองตามธรรมชาติ ซึ่งเป็นสิ่งที่อยากทดสอบพอดี
    """
    return round(random.uniform(0.0, 0.030), 3)


def post_measurement(session_id, number_alpl, value_x, value_y, offset):
    """ส่งผลวัด 1 ชิ้นไปที่ Backend (POST /api/measurements)

    number_alpl ที่ส่งไปเป็นแค่ค่า fallback — Backend จะเพิกเฉยแล้วใช้ ALPL ตาม
    ตำแหน่งในคิวของ session นั้นเอง (ดู create_measurement ใน main.py) Agent
    ไม่จำเป็นต้องรู้ว่ากำลังวัด ALPL ตัวไหนอยู่ในคิว
    client_uuid: สร้างใหม่ทุกชิ้น ใช้กัน insert ซ้ำถ้ามีการ retry
    """
    payload = {
        "session_id":  session_id,
        "number_alpl": number_alpl,
        "value_x":     value_x,
        "value_y":     value_y,
        "offset":      offset,
        "client_uuid": str(uuid.uuid4()),
    }
    try:
        r = httpx.post(f"{BACKEND_URL}/api/measurements", json=payload, timeout=10)
        if r.is_success:
            d = r.json()
            print(f"   → บันทึกแล้ว: result={d.get('result')} "
                  f"({d.get('measured')}/{d.get('target')}) status={d.get('status')}")
            return d
        print(f"   ✖ Backend ปฏิเสธ (HTTP {r.status_code}): {r.text[:200]}")
    except Exception as exc:
        print(f"   ✖ ส่งผลวัดไม่สำเร็จ: {exc}")
    return None


def heartbeat_loop():
    """ยิง POST /api/heartbeat ทุก HB_INTERVAL วิ ตลอดเวลาที่ mock รันอยู่
    (แนบ session_id ปัจจุบันถ้ากำลังวัดอยู่ — backend ใช้ต่ออายุ sessions.last_seen
    กัน heartbeat_checker mark session เป็น timeout) รันใน daemon thread แยก
    """
    while True:
        try:
            httpx.post(
                f"{BACKEND_URL}/api/heartbeat",
                json={"session_id": current_session_id},
                timeout=5,
            )
        except Exception:
            pass  # backend ล่มชั่วคราวไม่ควรทำให้ mock ตาย
        time.sleep(HB_INTERVAL)


def measurement_flow(session_id, template_name, number_alpl, target_count):
    """Flow หลัก — รันใน thread แยกเพื่อไม่ block FastAPI server

    วนสุ่มค่าส่งให้ Backend ทีละชิ้นจนครบ target_count หรือจนกว่าจะโดนสั่ง Stop
    """
    global current_session_id, is_running, is_paused
    current_session_id = session_id
    is_running = True
    is_paused = False
    target_count = target_count or 1

    print(f"\n{'='*62}")
    print(f"✅ START — session={session_id}, template={template_name!r}, "
          f"ALPL แรก={number_alpl}, จำนวน {target_count} ชิ้น")
    print(f"{'='*62}")

    spec = fetch_spec(number_alpl)
    print(f"📐 spec ที่ใช้สุ่ม: nominal=({spec['nominal_x']}, {spec['nominal_y']}) "
          f"tol=+{spec['upper_tol']}/-{spec['lower_tol']}  |  NG rate ≈ {NG_RATE:.0%}")

    # ใช้ while + ตัวนับเอง (ไม่ใช่ for range) เพราะถ้าโดนสั่ง pause ระหว่างที่
    # กำลัง "วัด" ชิ้นหนึ่งอยู่ ต้องย้อนกลับไปวัดชิ้นเดิมใหม่หลัง resume — ถ้าใช้
    # for + continue ตัวนับจะเดินหน้าไปเอง ทำให้ชิ้นนั้นถูกข้ามไปเลย
    piece = 1
    while piece <= target_count:
        if not is_running:
            print("\n⏹ ได้รับคำสั่ง Stop — หยุดการวัด")
            break

        # ── รอตรงนี้ถ้าถูกสั่ง pause ─────────────────────────────────────────
        # วนรอเป็นช่วงสั้นๆ แทนการ block ยาว เพื่อให้ Stop ที่มาระหว่างพักมีผล
        # ทันที (ไม่ต้องรอ resume ก่อนถึงจะหยุดได้)
        if is_paused:
            print(f"\n⏸ พักการวัดชั่วคราว (ค้างที่ชิ้นที่ {piece}/{target_count}) — รอคำสั่ง Start")
            while is_paused and is_running:
                time.sleep(0.2)
            if not is_running:
                print("\n⏹ ได้รับคำสั่ง Stop ระหว่างพัก — หยุดการวัด")
                break
            print(f"▶ วัดต่อจากชิ้นที่ {piece}/{target_count}")

        time.sleep(MEASURE_INTERVAL)  # จำลองเวลาที่เครื่องใช้วัด 1 ชิ้น

        # เช็คซ้ำหลังหน่วงเวลา — เผื่อ Stop/Pause มาถึงระหว่างที่กำลังวัดชิ้นนี้อยู่
        if not is_running:
            print("\n⏹ ได้รับคำสั่ง Stop — หยุดการวัด")
            break
        if is_paused:
            # โดนสั่งพักกลางคันก่อนได้ผล — ทิ้งรอบนี้ไปโดยไม่ส่งผล แล้ววนกลับไป
            # เริ่มชิ้นเดิมใหม่ (ไม่เพิ่ม piece) ชิ้นนี้จะถูกวัดจริงหลัง resume
            continue

        force_ng = random.random() < NG_RATE
        value_x = random_value(spec["nominal_x"], spec["upper_tol"], spec["lower_tol"], force_ng)
        value_y = random_value(spec["nominal_y"], spec["upper_tol"], spec["lower_tol"], force_ng)
        offset  = random_offset()

        print(f"\n🔍 ชิ้นที่ {piece}/{target_count} — สุ่มได้ X={value_x}  Y={value_y}  offset={offset}"
              f"{'  (จงใจให้ NG)' if force_ng else ''}")
        post_measurement(session_id, number_alpl, value_x, value_y, offset)
        piece += 1

    is_running = False
    is_paused = False
    current_session_id = None  # heartbeat กลับไปยิงแบบ idle
    print(f"\n✅ จบ session {session_id}\n")


# ── HTTP endpoint (Backend เรียกเข้ามาสั่ง Start/Stop) ────────────────────────
class CommandRequest(BaseModel):
    action: str
    session_id: int | None = None
    template_name: str | None = None
    number_alpl: int | None = None
    target_count: int | None = None


@http_app.post("/command")
async def command(req: CommandRequest):
    global is_running, is_paused
    if req.action == "start":
        threading.Thread(
            target=measurement_flow,
            args=(req.session_id, req.template_name, req.number_alpl, req.target_count),
            daemon=True,
        ).start()
    elif req.action == "pause":
        print("\n⏸ ได้รับคำสั่ง Pause จาก Backend")
        is_paused = True   # loop จะไปค้างรออยู่ที่ชิ้นถัดไป
    elif req.action == "resume":
        print("\n▶ ได้รับคำสั่ง Resume จาก Backend")
        is_paused = False  # ปลดล็อกให้ loop วัดต่อจากชิ้นเดิม
    elif req.action == "stop":
        print("\n⏹ ได้รับคำสั่ง Stop จาก Backend")
        is_running = False  # loop ใน measurement_flow จะเห็นแล้วหยุดเอง
        is_paused = False   # ปลดออกจาก wait loop ของ pause ด้วย ไม่งั้นค้าง
    return {"status": "ok", "action": req.action}


if __name__ == "__main__":
    threading.Thread(target=heartbeat_loop, daemon=True).start()
    print(f"🤖 mockup.py — Mock Agent (สุ่มค่าแทนฮาร์ดแวร์จริง)")
    print(f"   Backend  : {BACKEND_URL}")
    print(f"   หน่วงเวลา/ชิ้น: {MEASURE_INTERVAL}s   |   NG rate: {NG_RATE:.0%}")
    print(f"   กำลังรอคำสั่ง Start จาก Backend ที่ port {AGENT_PORT}...\n")
    uvicorn.run(http_app, host="0.0.0.0", port=AGENT_PORT)
