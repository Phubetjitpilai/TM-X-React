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
HB_INTERVAL = 5  # วินาที — ต้องน้อยกว่า HEARTBEAT_TIMEOUT ของ backend (15s)
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

# ── State ───────────────────────────────────────────────────────────────────
current_session_id = None   # session ที่กำลังวัดอยู่ (None = idle)
is_running = False          # ธงหยุดกลางคัน — ตั้งเป็น False เมื่อได้คำสั่ง stop
_hb_last_ok = time.time()   # เวลาที่ heartbeat ยิงออกสำเร็จครั้งล่าสุด

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
                json={"session_id": current_session_id},
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


def judge(value_x, value_y, offset, limits):
    """ตัดสิน OK/NG แบบเดียวกับที่ Pi ตัวจริงจะทำ — เทียบกับขอบเขตตรงๆ

    ไม่มี `_TOL_EPS` ที่นี่โดยตั้งใจ: backend บวก/ลบให้เรียบร้อยแล้วตอนสร้าง
    `limits` (ดู `_limits_of` ใน main.py) ถ้ามาเผื่อซ้ำอีกรอบจะกลายเป็นเผื่อ 2 เท่า
    """
    ok_x = limits["x_lo"] <= value_x <= limits["x_hi"]
    ok_y = limits["y_lo"] <= value_y <= limits["y_hi"]
    om   = limits.get("offset_max")
    ok_o = True if om is None else abs(offset) <= om
    return "OK" if (ok_x and ok_y and ok_o) else "NG"


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

        time.sleep(MEASURE_INTERVAL)  # จำลองเวลาที่เครื่องใช้วัด 1 ชิ้น

        # เช็คซ้ำหลังหน่วงเวลา — เผื่อ Stop มาถึงระหว่างที่กำลังวัดชิ้นนี้อยู่
        if not is_running:
            print("\n⏹ ได้รับคำสั่ง Stop — หยุดการวัด")
            break

        force_ng = random.random() < NG_RATE
        value_x = random_value(limits["x_lo"], limits["x_hi"], force_ng)
        value_y = random_value(limits["y_lo"], limits["y_hi"], force_ng)
        offset  = random_offset(limits.get("offset_max"))
        verdict = judge(value_x, value_y, offset, limits)

        print(f"\n🔍 ชิ้นที่ {piece}/{target_count} (ALPL {alpl}) — "
              f"X={value_x}  Y={value_y}  offset={offset}  → Pi ตัดสิน: {verdict}"
              f"{'  (จงใจให้ NG)' if force_ng else ''}")
        d = post_measurement(session_id, alpl, value_x, value_y, offset)
        # ⚠ จุดที่ควรจับตา: ถ้า Pi กับ Backend ตัดสินไม่ตรงกัน แปลว่า `limits`
        #   ที่ส่งมากับเกณฑ์ที่ backend ใช้ query ตอนบันทึกไม่ใช่ชุดเดียวกัน
        #   (เคสนี้คือสิ่งที่ _build_groups พยายามกันไว้ — เห็นตรงนี้ถือว่าหลุด)
        if d and d.get("result") and d["result"] != verdict:
            print(f"   ⚠⚠ ไม่ตรงกัน! Pi={verdict} แต่ Backend บันทึก {d['result']}")

    is_running = False
    current_session_id = None  # heartbeat กลับไปยิงแบบ idle
    print(f"\n✅ จบ session {session_id}\n")


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
    global is_running
    if req.action == "start":
        groups = [g.model_dump() for g in (req.groups or [])]
        threading.Thread(
            target=measurement_flow,
            args=(req.session_id, groups, req.target_count),
            daemon=True,
        ).start()
    elif req.action == "stop":
        print("\n⏹ ได้รับคำสั่ง Stop จาก Backend")
        is_running = False  # loop ใน measurement_flow จะเห็นแล้วหยุดเอง
    elif req.action == "continue":
        # ผู้ใช้กด "วัดชิ้นถัดไป" ใน modal ตอนที่ backend ไม่ได้รับค่าการวัด
        # (Backend ขยับ position ให้เรียบร้อยแล้วก่อนยิงมา — ดู continue_session)
        #
        # ⚠ mock ไม่มีทางเข้าสถานะ "รอคำตอบ" ได้จริง เพราะมันสุ่มค่าส่งเองทุกชิ้น
        #   ไม่เคยพลาด — แต่ **ต้องรับ action นี้ให้ได้** ไม่งั้นจะตอบ 400 กลับไป
        #   ทั้งที่ Pi ตัวจริงรับได้ กลายเป็นเทสต์ด้วย mock แล้วเจอ error ที่
        #   เครื่องจริงไม่มี (เคสกลับด้านของ pause ที่เคยพลาดมาแล้ว)
        print("\n▶ ได้รับคำสั่ง Continue จาก Backend (mock ไม่ต้องทำอะไร — วัดต่ออยู่แล้ว)")
    # ปฏิเสธ action ที่ไม่รู้จักเหมือน send_command(Pi).py — ต้องมีพฤติกรรมตรงกัน
    # ทั้ง 2 ตัว ไม่งั้นเทสต์ด้วย mockup ผ่านแต่เครื่องจริงพัง (เคสเดิมของ pause)
    else:
        raise HTTPException(400, f"ไม่รู้จัก action '{req.action}' — รองรับแค่ start/stop/continue")
    return {"status": "ok", "action": req.action}


if __name__ == "__main__":
    threading.Thread(target=heartbeat_loop, daemon=True).start()
    print(f"🤖 mockup.py — Mock Agent (สุ่มค่าแทนฮาร์ดแวร์จริง)")
    print(f"   Backend  : {BACKEND_URL}")
    print(f"   หน่วงเวลา/ชิ้น: {MEASURE_INTERVAL}s   |   NG rate: {NG_RATE:.0%}")
    print(f"   กำลังรอคำสั่ง Start จาก Backend ที่ port {AGENT_PORT}...\n")
    uvicorn.run(http_app, host="0.0.0.0", port=AGENT_PORT)
