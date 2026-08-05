"""
send_command.py — รันบน Raspberry Pi

สถาปัตยกรรมใหม่ (แยกออกจาก ftp.py/agent.py เดิม): Pi ตอนนี้มีหน้าที่แค่รับ
คำสั่ง Start/Stop จาก Backend แล้วคุย TCP กับ TM-X อย่างเดียว (R0, โหลด
โปรแกรมวัด, T1 trigger ต่อชิ้น, S0 ตอนจบ) — **ไม่ยุ่งกับรูปภาพ/ค่าที่วัดได้
เลย** เพราะตอนนี้ TM-X ถูกตั้งให้ส่งค่า (.txt) + รูป ตรงไปที่ PC โดยตรงผ่าน
FTP (ดู Recieve_tm-x.py ที่รันบน PC แทน ซึ่งเป็นคนรับ+parse ค่า+อัปโหลดรูป+
POST เข้า Backend เอง)

Flow:
  1. รับคำสั่ง Start + template จาก Backend ผ่าน POST /command
  2. ต่อ TM-X → ส่ง R0 (reset) → โหลดโปรแกรมวัด PW,1,<template>
  3. ต่อ 1 ชิ้นงาน (จนครบ target_count หรือโดนสั่ง Stop):
     - รอพิมพ์เริ่มที่ terminal (แทน trigger จาก MCU จริง)
     - ส่งคำสั่ง T1 ไปสั่ง TM-X ให้ถ่าย/วัดตอนนี้เลย ผ่าน connection ใหม่แยก
       ต่างหาก (ไม่ใช่ connection เดิมที่ค้างไว้ส่ง R0/PW/S0) — ทดสอบกับ
       ฮาร์ดแวร์จริงแล้วว่าใช้งานได้ด้วยวิธีนี้
  4. จบ session (ครบ target_count หรือโดนสั่ง Stop) → ส่ง S0

หมายเหตุสำคัญ: เพราะ Pi ไม่เห็นผลค่า/รูปที่วัดได้เลย (ไม่มี FTP server บน Pi
อีกต่อไป) จึงไม่มีการ "รอยืนยันว่าได้ค่า+รูปจริง" หรือ retry ต่อชิ้นแบบที่
เคยทำใน ftp.py (arm_and_capture) — Pi แค่ส่ง T1 แล้ววนไปชิ้นถัดไปตามจำนวน
target_count ที่ได้รับตอน Start เท่านั้น ถ้า TM-X พลาดรอบไหนไปจริงๆ (ไม่ส่ง
ค่า/รูปมาที่ PC) Pi จะไม่รู้ตัวเลย — measured_count ฝั่ง Backend อาจไม่ครบ
target_count ในกรณีนั้น (ต้องกด Stop เองจากเว็บถ้าเจอ)
"""
import os
import socket
import threading
import time

import httpx
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI
from pydantic import BaseModel

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))

# ── TM-X (TCP) ────────────────────────────────────────────────────────────
TMX_IP = os.getenv("TMX_HOST", "192.168.10.11")
TMX_PORT = int(os.getenv("TMX_PORT", 8600))
BUFFER_SIZE = 1024
# คำสั่ง trigger แบบ active — ส่งผ่าน connection ใหม่แยกต่างหาก (ไม่ใช่ตัวที่
# ค้างไว้ส่ง R0/PW/S0) ไปสั่งให้ TM-X ถ่าย/วัด 1 ครั้งตอนกด Enter แต่ละชิ้น
TRIGGER_COMMAND = "T1\r"
TRIGGER_TIMEOUT = 2.0  # วินาที — รอ response จาก TM-X หลังส่ง trigger

# BACKEND_URL: IP ของเครื่อง PC ที่รัน Backend (Pi กับ PC คนละเครื่องกันแล้ว
# ต้องตั้งเป็น IP จริงใน .env เสมอ ไม่ใช่ localhost)
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")

# พอร์ตที่สคริปต์นี้เปิดรอรับ POST /command จาก Backend — ต้องตรงกับ AGENT_PORT
# ที่ main.py ใช้ยิงมา เดิม hardcode เป็น 9998 ทำให้ตอนย้ายไปรันบน Pi แล้วเปลี่ยน
# พอร์ตใน .env มันไม่ตามให้ (backend ยิงไปพอร์ตใหม่ แต่สคริปต์ยังฟังพอร์ตเก่า)
AGENT_PORT = int(os.getenv("AGENT_PORT", 9998))

# ── heartbeat ───────────────────────────────────────────────────────────────
# เดิม hardcode 5 ไว้เฉยๆ ทั้งที่ .env มี HEARTBEAT_INTERVAL อยู่แล้ว — ใครไป
# แก้ค่าใน .env จะไม่มีผลกับสคริปต์นี้เลย แล้วหาสาเหตุยากมากเพราะอาการที่ออกมา
# คือ "session โดน mark timeout เอง" ซึ่งดูไม่เกี่ยวกับ heartbeat เลยเมื่อมองผ่านๆ
HB_INTERVAL     = float(os.getenv("HEARTBEAT_INTERVAL", 5))
# อ่าน TIMEOUT มาด้วยเพื่อ "เตือน" อย่างเดียว — ตัวที่บังคับใช้จริงคือ backend
HB_TIMEOUT_HINT = float(os.getenv("HEARTBEAT_TIMEOUT", 15))

# ── รอยืนยันผลวัดหลังส่ง T1 ────────────────────────────────────────────────
# หลังยิง T1 ไม่ไปชิ้นถัดไปทันทีอีกแล้ว แต่รอดูว่า sessions.measured_count ขยับ
# ขึ้นจริงไหม (ผ่าน GET /api/session/state) — ถ้าขยับ = Recieve_tm-x.py รับค่า
# จาก TM-X แล้ว POST เข้า Backend สำเร็จ
#
# ทำไมต้องมี: TM-X วัดไม่ติดบ่อยกว่าที่คิดมาก (ข้อมูลจริงหน้างาน 31/07 เจอ
# -9999.999 ไป 7 จาก 8 ครั้ง) ซึ่ง Recieve_tm-x.py ข้ามไม่บันทึก ถ้า Pi ยิง T1
# แล้ววนต่อเลยแบบเดิม จะจบ session ทั้งที่ measured_count ไม่ครบ target_count
# แล้วไม่มีใครรู้จนกว่าจะไปเปิดดูหน้าเว็บ
MEASURE_TIMEOUT       = float(os.getenv("MEASURE_TIMEOUT", 15))    # รอค่าสูงสุดกี่วินาที
MEASURE_POLL_INTERVAL = float(os.getenv("MEASURE_POLL_INTERVAL", 0.4))

# session ที่กำลังวัดอยู่ตอนนี้ (None = idle) — heartbeat_loop อ่านตัวนี้ไปแนบ
# กับทุก heartbeat เพื่อให้ backend อัปเดต sessions.last_seen ของ session
# ที่ถูกต้อง ไม่งั้น heartbeat_checker ฝั่ง backend จะคิดว่า Agent ตาย (เงียบ
# เกิน 15s) แล้ว mark session เป็น timeout → หน้าเว็บโดน resetTelemetry กลางคัน
current_session_id = None

# สถานะ session ปัจจุบัน — /command action="stop" ตั้ง is_running=False แล้ว
# command_flow เช็คก่อนวัดแต่ละชิ้นเพื่อหยุด loop ส่วน _tmx_sock เก็บ socket
# ที่กำลังใช้อยู่ให้ stop handler ยิง S0 ไป TM-X ได้ทันที
is_running = False
_tmx_sock = None

http_app = FastAPI()


def send_command(sock, command):
    """ส่งคำสั่งไปยัง TM-X และรอรับผลลัพธ์ตอบกลับ — ใช้กับ connection หลักที่
    เปิดค้างไว้ตลอด session (R0/PW/S0 เท่านั้น ไม่ใช้กับ T1 อีกต่อไป — T1 ส่ง
    ผ่าน trigger_sensor() ด้วย connection ใหม่แยกต่างหากเสมอ)
    """
    cmd_to_send = command + "\r"  # ต้องต่อท้ายด้วยตัวคั่น CR (\r) เสมอ
    sock.sendall(cmd_to_send.encode("ascii"))
    time.sleep(0.1)  # หน่วงเวลาให้กล้องประมวลผลเล็กน้อย
    response = sock.recv(BUFFER_SIZE).decode("ascii").strip()
    return response


def trigger_sensor(timeout=TRIGGER_TIMEOUT):
    """ส่งคำสั่ง T1 ไปสั่งให้ TM-X ถ่าย/วัด 1 ครั้ง ผ่าน connection ใหม่แยก
    ต่างหาก — ทดสอบกับฮาร์ดแวร์จริงแล้วว่าใช้งานได้จริงด้วยวิธีนี้ คืน
    True/False ว่าส่งคำสั่งสำเร็จไหม (แค่ส่งสำเร็จ ไม่รอ/ไม่ตรวจผลว่าได้ค่า+
    รูปจริงไหม — ฝั่ง PC เป็นคนรับแล้วรายงานไป Backend เอง ดู Recieve_tm-x.py)
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect((TMX_IP, TMX_PORT))
            s.sendall(TRIGGER_COMMAND.encode("ascii"))
            response = s.recv(BUFFER_SIZE).decode("ascii").strip()
            print(f"📡 TM-X ตอบ trigger: {response}")
            return True
    except socket.timeout:
        print("❌ ส่ง trigger ไม่สำเร็จ: timeout")
        return False
    except ConnectionRefusedError:
        print(f"❌ ส่ง trigger ไม่สำเร็จ: connection refused (port {TMX_PORT})")
        return False
    except Exception as exc:
        print(f"❌ ส่ง trigger ไม่สำเร็จ: {exc}")
        return False


def get_measured_count(session_id):
    """อ่าน measured_count ปัจจุบันของ session นี้จาก Backend

    คืน None ถ้าอ่านไม่ได้ หรือ session ที่ backend รายงานไม่ใช่ตัวที่เรากำลังวัด
    อยู่ (กันนับผิด session ตอนมีคนไปกด Start ตัวใหม่ระหว่างที่เรายังรอค่าอยู่)
    ผู้เรียกต้องมองว่า None = "ยังไม่รู้" ไม่ใช่ "ไม่มีค่า"
    """
    try:
        data = httpx.get(f"{BACKEND_URL}/api/session/state", timeout=5).json()
    except Exception as exc:
        print(f"   ⚠️ อ่าน session state ไม่ได้: {exc}")
        return None
    if data.get("session_id") != session_id:
        return None
    return data.get("measured_count")


def wait_for_measurement(session_id, count_before, timeout=MEASURE_TIMEOUT):
    """รอจนกว่า measured_count จะขยับขึ้นจาก count_before — คืน True ถ้าได้ค่าแล้ว

    หลุด loop ก่อนครบเวลาได้ 2 กรณี:
      - is_running กลายเป็น False (ผู้ใช้กด Stop ระหว่างรอ) → คืน True เพื่อให้
        loop หลักไปเจอ `if not is_running` แล้วออกเองอย่างสะอาด ไม่ต้องเด้ง
        คำถาม timeout ให้ผู้ใช้ทั้งที่เขาเพิ่งสั่งหยุดไปเอง
      - measured_count ขยับ → สำเร็จตามปกติ
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not is_running:
            return True
        now = get_measured_count(session_id)
        if now is not None and count_before is not None and now > count_before:
            return True
        time.sleep(MEASURE_POLL_INTERVAL)
    return False


def ask_user_on_timeout(session_id, piece, target):
    """แจ้ง Backend ว่าไม่ได้รับค่า แล้วรอคำตอบจากผู้ใช้บนหน้าเว็บ

    คืน "continue" (วัดต่อ) หรือ "stop" (หยุด) — ถ้าติดต่อ Backend ไม่ได้เลย
    ถือว่า "stop" ไว้ก่อน เพราะปล่อยให้เครื่องวัดต่อทั้งที่ไม่มีใครเห็นผลอันตราย
    กว่าการหยุดแล้วให้คนมากดใหม่
    """
    try:
        httpx.post(
            f"{BACKEND_URL}/api/measure-timeout",
            json={"session_id": session_id, "piece": piece, "target": target},
            timeout=10,
        )
    except Exception as exc:
        print(f"   ⚠️ แจ้ง Backend เรื่อง timeout ไม่สำเร็จ: {exc} — ถือว่าหยุด")
        return "stop"

    print("   ⏳ รอผู้ใช้ตอบบนหน้าเว็บ (วัดต่อ / หยุด)...")
    while True:
        if not is_running:          # ผู้ใช้กด Stop ตรงๆ ระหว่างที่คำถามค้างอยู่
            return "stop"
        try:
            data = httpx.get(
                f"{BACKEND_URL}/api/measure-timeout/{session_id}", timeout=5
            ).json()
            decision = data.get("decision")
            if decision:
                return decision
        except Exception as exc:
            print(f"   ⚠️ ถามคำตอบจาก Backend ไม่สำเร็จ: {exc} — ถือว่าหยุด")
            return "stop"
        time.sleep(MEASURE_POLL_INTERVAL)


def heartbeat_loop():
    """ยิง POST /api/heartbeat ทุก HB_INTERVAL วิ ตลอดเวลาที่ Agent รันอยู่
    (แนบ session_id ปัจจุบันไปด้วยถ้ากำลังวัดอยู่ — backend ใช้ต่ออายุ
    sessions.last_seen กัน heartbeat_checker mark session เป็น timeout)
    รันใน daemon thread แยก จึงไม่กวน command_flow และตายไปพร้อม process
    """
    while True:
        try:
            httpx.post(
                f"{BACKEND_URL}/api/heartbeat",
                json={"session_id": current_session_id},
                timeout=5,
            )
        except Exception:
            pass  # backend ล่มชั่วคราวไม่เป็นไร รอบหน้าค่อยยิงใหม่
        time.sleep(HB_INTERVAL)


def command_flow(session_id, template_name, number_alpl, target_count):
    """Flow หลัก — รันใน thread แยกเพื่อไม่ block FastAPI server

    ⚠ ทุกอย่างอยู่ใน try/finally เพราะถ้าต่อ TM-X ไม่ได้ (สาย LAN หลุด / TM-X
    ปิดอยู่ / IP ผิด) แล้วปล่อยให้ exception หลุดออกไปเฉยๆ ตัวแปรสถานะจะค้าง:
      - is_running ค้าง True         → กด Start ใหม่ไม่ได้
      - current_session_id ค้าง      → heartbeat ยังแนบ session เดิมไปเรื่อยๆ
                                        backend เลยคิดว่า session ยังมีชีวิต
                                        ไม่ยอม mark timeout → หน้าเว็บค้าง RUNNING
    ต้องปิดสคริปต์แล้วกด Stop จากเว็บล้างเอง ซึ่งไม่ควรต้องทำ
    """
    global current_session_id, is_running, _tmx_sock
    current_session_id = session_id  # heartbeat จะเริ่มแนบ session นี้ทันที
    is_running = True
    client_socket = None

    try:
        # ── แสดงสิ่งที่ Backend ส่งมาให้เห็นชัดๆ ────────────────────────────
        # target_count มาจาก len(alpl_queue) ฝั่ง backend (1 ALPL = 1 ชิ้น)
        # ถ้าขึ้นไม่ตรงกับที่กรอกหน้าเว็บ แปลว่าปัญหาอยู่ที่ payload ไม่ใช่ที่ loop
        print(f"\n{'='*60}")
        print(f"✅ ได้รับคำสั่ง Start จาก Backend")
        print(f"   session_id    : {session_id}")
        print(f"   template_name : {template_name!r}")
        print(f"   number_alpl   : {number_alpl}")
        print(f"   target_count  : {target_count}  ← จำนวนชิ้นที่จะวัดรอบนี้")
        print(f"{'='*60}")

        if not target_count or target_count < 1:
            # เดิมใช้ (target_count or 1) เงียบๆ ทำให้ payload ที่ไม่มี
            # target_count กลายเป็น "วัด 1 ชิ้นแล้วจบ" โดยไม่มีอะไรเตือนเลย
            print("❌ Backend ไม่ได้ส่ง target_count มา (หรือส่งมาเป็น 0)")
            print("   → ไม่เริ่มวัด กด Stop ที่หน้าเว็บแล้วลองใหม่")
            return

        try:
            client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client_socket.settimeout(5.0)
            client_socket.connect((TMX_IP, TMX_PORT))
        except Exception as exc:
            # แยก except ของการต่อออกมาต่างหาก เพื่อให้ข้อความบอกจุดที่พังชัดเจน
            # (ต่อไม่ติดตั้งแต่แรก ≠ พังกลางทางหลังวัดไปแล้วบางชิ้น)
            print(f"\n❌ ต่อ TM-X ที่ {TMX_IP}:{TMX_PORT} ไม่ได้ — {type(exc).__name__}: {exc}")
            print("   ตรวจ: สาย LAN ต่ออยู่ไหม · TM-X เปิดอยู่ไหม · TMX_HOST/TMX_PORT ใน .env ถูกไหม")
            print("   → กด Stop ที่หน้าเว็บเพื่อล้าง session นี้ แล้วลองใหม่")
            return

        _tmx_sock = client_socket  # ให้ stop handler ยิง S0 ผ่าน socket นี้ได้

        # Reset (เข้าโหมดดำเนินงาน)
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

            # รอสัญญาณว่าชิ้นงานพร้อม (แทน trigger จาก Micro ด้วยการพิมพ์ไปก่อน)
            input(f"\nชิ้นที่ {piece}/{target_count} — กด Enter เพื่อ trigger: ")

            # เช็คอีกทีหลัง input — เผื่อ Stop มาถึงระหว่างที่กำลังรอพิมพ์อยู่
            if not is_running:
                print("⏹ ได้รับคำสั่ง Stop — หยุดการวัด")
                break

            # จำจำนวนที่บันทึกไว้ "ก่อน" ยิง T1 เพื่อเอาไว้เทียบว่าขยับไหม
            count_before = get_measured_count(session_id)

            trigger_sensor()

            # ── รอยืนยันว่าค่าเข้า DB จริง ก่อนไปชิ้นถัดไป ──────────────────
            if wait_for_measurement(session_id, count_before):
                if is_running:
                    print(f"   ✅ ชิ้นที่ {piece}/{target_count} บันทึกแล้ว")
                continue

            # หมดเวลาแล้วยังไม่มีค่าเข้ามา — โยนให้คนตัดสินใจ เพราะ Pi แยกไม่ออก
            # ว่าเป็น "TM-X วัดไม่ติด" หรือ "FTP มาช้า/Recieve_tm-x.py ไม่ได้รัน"
            print(f"\n⚠️ ชิ้นที่ {piece}/{target_count}: รอ {MEASURE_TIMEOUT:.0f} วิแล้วไม่ได้รับค่าการวัด")
            if ask_user_on_timeout(session_id, piece, target_count) == "stop":
                print("⏹ ผู้ใช้เลือกหยุด — จบ session")
                break
            print("▶ ผู้ใช้เลือกวัดต่อ — ไปชิ้นถัดไป")

    except Exception as exc:
        print(f"\n❌ session พังกลางทาง — {type(exc).__name__}: {exc}")

    finally:
        # ── ล้างสถานะให้สะอาดเสมอ ไม่ว่าจะจบปกติ พัง หรือโดนสั่ง Stop ──────
        # จบการทำงาน — กลับโหมดตั้งค่า (S0 ยิงซ้ำกับตอน stop handler ได้ไม่เป็นไร
        # TM-X รับซ้ำได้)
        if client_socket is not None:
            try:
                send_command(client_socket, "S0")
                time.sleep(0.5)
            except Exception:
                pass  # socket อาจถูกปิดไปแล้วจาก stop handler
            try:
                client_socket.close()
            except Exception:
                pass
        _tmx_sock = None
        is_running = False
        current_session_id = None  # heartbeat กลับไปยิงแบบ idle (ไม่แนบ session)
        print("\n✅ จบ session — ปิดการเชื่อมต่อ TM-X แล้ว")


class CommandRequest(BaseModel):
    action: str
    session_id: int | None = None
    template_name: str | None = None
    number_alpl: int | None = None
    target_count: int | None = None


@http_app.post("/command")
async def command(req: CommandRequest):
    global is_running
    if req.action == "start":
        threading.Thread(
            target=command_flow,
            args=(req.session_id, req.template_name, req.number_alpl, req.target_count),
            daemon=True,
        ).start()
    elif req.action == "stop":
        print("\n⏹ ได้รับคำสั่ง Stop จาก Backend")
        is_running = False  # loop ใน command_flow จะเห็นแล้วหยุดเอง
        # ยิง S0 ไป TM-X ทันทีเลยถ้ายังต่ออยู่ — ไม่ต้องรอ loop วนมาเช็ค flag
        if _tmx_sock is not None:
            try:
                send_command(_tmx_sock, "S0")
                print("→ ส่ง S0 ไป TM-X แล้ว")
            except Exception:
                pass
    return {"status": "ok", "action": req.action}


if __name__ == "__main__":
    # heartbeat รันตลอดอายุโปรแกรมใน daemon thread — เริ่มก่อนเปิด server
    threading.Thread(target=heartbeat_loop, daemon=True).start()
    # port ต้องตรงกับ AGENT_PORT ใน main.py ของ backend (default 9998)
    print("─" * 66)
    print("send_command.py — รอคำสั่ง Start จาก Backend")
    print(f"  ฟัง /command ที่    : 0.0.0.0:{AGENT_PORT}   (.env: AGENT_PORT)")
    print(f"  TM-X ที่            : {TMX_IP}:{TMX_PORT}    (.env: TMX_HOST/TMX_PORT)")
    print(f"  Backend ที่         : {BACKEND_URL}          (.env: BACKEND_URL)")
    print(f"  heartbeat ทุก       : {HB_INTERVAL:g} วิ   (.env: HEARTBEAT_INTERVAL)")
    print(f"  รอค่าวัดสูงสุด       : {MEASURE_TIMEOUT:g} วิ   (.env: MEASURE_TIMEOUT)")
    print("─" * 66)

    # เตือนตอนเริ่มถ้าตั้งค่าจนเสี่ยงโดน mark timeout ทั้งที่เครื่องยังปกติดี
    # (backend เช็คทุก HEARTBEAT_INTERVAL ของฝั่งมันเอง แล้วตัดที่ HEARTBEAT_TIMEOUT
    #  ถ้าเรายิงถี่ไม่พอ จังหวะที่พลาดไปแค่รอบเดียวก็เกินเวลาแล้ว)
    if HB_INTERVAL * 2 > HB_TIMEOUT_HINT:
        print(f"⚠️  HEARTBEAT_INTERVAL ({HB_INTERVAL:g}s) ถี่ไม่พอเมื่อเทียบกับ "
              f"HEARTBEAT_TIMEOUT ({HB_TIMEOUT_HINT:g}s)")
        print("    backend อาจ mark session เป็น timeout ทั้งที่เครื่องยังทำงานปกติ")
        print(f"    แนะนำให้ HEARTBEAT_INTERVAL ไม่เกิน {HB_TIMEOUT_HINT/2:g}s\n")
    uvicorn.run(http_app, host="0.0.0.0", port=AGENT_PORT)
