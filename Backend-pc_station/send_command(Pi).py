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
     - รอสัญญาณว่าชิ้นงานเข้าที่ — ตอนนี้ยังไม่มี MCU จริง จึงจำลองด้วยการยิง
       POST/GET มาที่ /trigger ของสคริปต์นี้ (เดิมใช้ input() ซึ่งบล็อก thread
       จนกด Stop ไม่หลุด) พอต่อ MCU จริงค่อยเปลี่ยนเป็นอ่านสัญญาณจาก Serial
     - ส่งคำสั่ง T1 ไปสั่ง TM-X ให้ถ่าย/วัดตอนนี้เลย ผ่าน connection ใหม่แยก
       ต่างหาก (ไม่ใช่ connection เดิมที่ค้างไว้ส่ง R0/PW/S0) — ทดสอบกับ
       ฮาร์ดแวร์จริงแล้วว่าใช้งานได้ด้วยวิธีนี้
  4. จบ session (ครบ target_count หรือโดนสั่ง Stop) → ส่ง S0 แล้วถ้า session
     ยังค้าง 'running' อยู่ ให้แจ้ง backend ปิดให้ด้วย

หมายเหตุสำคัญ: Pi ไม่เห็นค่า/รูปที่วัดได้เลย (ไม่มี FTP server บน Pi อีกต่อไป
TM-X ส่งตรงเข้า PC) จึงรู้ผลทางอ้อมด้วยการ poll ว่า sessions.measured_count
ขยับไหมหลังยิง T1 — ถ้าครบ MEASURE_TIMEOUT แล้วไม่ขยับ จะแจ้ง backend ให้เด้ง
ถามผู้ใช้บนหน้าเว็บว่าจะวัดต่อหรือหยุด เลือก "วัดต่อ" = ข้ามชิ้นนั้นไป ไม่ได้
ยิง T1 ซ้ำ (ไม่มี retry) พอวนครบ measured_count จึงอาจไม่ถึง target_count ได้
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

# ╔═══ trigger จากภายนอก — เริ่มส่วนที่เพิ่ม ══════════════════════════════════╗
#
# "กระดิ่ง" ที่บอกว่าชิ้นงานเข้าที่พร้อมวัดแล้ว
#
# ทำไมต้องเป็น Event ไม่ใช่ input(): input() บล็อก thread ของ command_flow ไว้
#   ไม่มีกำหนดและปลุกจากข้างนอกไม่ได้ กด Stop บนเว็บแล้ว TM-X หยุดทันที (stop
#   handler ยิง S0 เอง) หน้าเว็บก็อัปเดตทันที แต่ thread ของ Pi ค้างคาที่
#   input() → finally ไม่ทำงาน → ไม่ปิด socket/ไม่เคลียร์สถานะ จนกว่าจะมีคน
#   เดินไปเคาะ Enter ที่เทอร์มินัล
#
# Event แยก "ใครส่งสัญญาณ" ออกจาก "ใครรอสัญญาณ" ตัวรอจึงวนเช็ค is_running ได้
#   ตลอดโดยไม่ต้องรู้ว่าสัญญาณมาจากไหน
#
# 🔌 ตอนต่อ MCU/sensor จริงผ่าน Serial: เพิ่ม thread อ่าน serial แล้วเรียก
#   `_trigger.set()` บรรทัดเดียวกับที่ endpoint /trigger ใช้ — ตัวรอกับที่เหลือ
#   ทั้งระบบไม่ต้องแก้เลย และเก็บ /trigger ไว้เป็น manual override ได้ด้วย
#   (เผื่อเซนเซอร์เสีย หรือต้องเทสต์โดยไม่มีชิ้นงาน) เพราะ Event รับหลายแหล่งได้
#   ⚠ ตอนนั้นต้อง ser.reset_input_buffer() คู่กับ _trigger.clear() ด้วย เพราะ
#     clear() ล้างได้แค่กระดิ่ง byte ที่ค้างใน buffer ของ OS ยังอยู่
_trigger = threading.Event()

# ตอนนี้อยู่ในช่วง "รอสัญญาณ" จริงหรือยัง — endpoint /trigger ใช้ตอบให้ตรงความจริง
# ว่าสัญญาณที่ยิงมาจะถูกใช้หรือถูกทิ้ง
#
# ที่มา: เจอตอนเทสต์ว่าถ้ายิง /trigger เร็วเกินไป (ช่วง ~1.5 วิแรกที่ยังส่ง
# R0/PW ให้ TM-X อยู่) สัญญาณจะโดน _trigger.clear() ล้างทิ้งพอดี แต่ endpoint
# ตอบ ok:True ไปแล้ว → คนยิงนึกว่าสำเร็จ แต่เครื่องไม่ขยับ หาสาเหตุไม่เจอ
_waiting_for_trigger = False


def wait_for_trigger():
    """รอสัญญาณว่าชิ้นงานพร้อมวัด — True = ได้สัญญาณ · False = โดน Stop ระหว่างรอ

    clear() ก่อนเสมอ เพื่อทิ้งสัญญาณที่ยิงมาตอนยังไม่ถึงคิว (เช่นกดรัวไว้ตอน
    ชิ้นก่อนหน้ายังวัดไม่เสร็จ) ไม่งั้นชิ้นถัดไปจะถูก trigger ทันทีทั้งที่ยัง
    ไม่ได้วางชิ้นงาน — และกันสัญญาณเด้ง (bounce) ของเซนเซอร์จริงไปในตัว
    """
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
# ╚═══ trigger จากภายนอก — จบส่วนที่เพิ่ม ════════════════════════════════════╝

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


def trigger_sensor(session_id, timeout=TRIGGER_TIMEOUT):
    """รอสัญญาณว่าชิ้นงานพร้อม แล้วส่ง T1 ไปสั่ง TM-X ถ่าย/วัด 1 ครั้ง

    T1 ส่งผ่าน connection ใหม่แยกต่างหากทุกครั้ง (ไม่ใช่ตัวที่ค้างไว้ส่ง
    R0/PW/S0) — ทดสอบกับฮาร์ดแวร์จริงแล้วว่าต้องทำแบบนี้ และแค่ส่งสำเร็จเท่านั้น
    ไม่รอ/ไม่ตรวจว่าได้ค่า+รูปจริงไหม (ฝั่ง PC เป็นคนรับแล้วรายงานไป Backend เอง
    ดู Recieve_tm-x.py)

    คืน (ok, count_before):
      ok           – ส่ง T1 สำเร็จไหม · False = โดน Stop ระหว่างรอสัญญาณ
                     (ไม่ได้ส่ง T1 เลย) หรือส่งไปแล้วแต่ไม่สำเร็จ
      count_before – measured_count ก่อนยิง T1 ไว้ให้ wait_for_measurement
                     เทียบว่าขยับไหม (None = อ่านไม่ได้ หรือยังไม่ได้อ่าน)

    ทำไม count_before อ่านตรงนี้ ไม่ใช่ที่ command_flow ก่อนเรียกฟังก์ชันนี้:
      ช่วงรอสัญญาณอาจกินเวลาเป็นนาที ถ้าอ่านไว้ตั้งแต่ก่อนรอ แล้วระหว่างนั้นมี
      ค่าของ "ชิ้นก่อนหน้าที่มาช้า" หลุดเข้ามา (เกิดได้จริงตอนชิ้นก่อน timeout
      แล้วผู้ใช้เลือกวัดต่อ — TM-X วัดไม่ติดบ่อยมากตามข้อมูลหน้างาน)
      measured_count จะขยับตั้งแต่ยังไม่ได้ยิง T1 ของชิ้นนี้ →
      wait_for_measurement เห็นว่า "ขยับแล้ว" ทันที → รายงานว่าชิ้นนี้สำเร็จ
      ทั้งที่ TM-X ยังไม่ได้วัดเลย
    """
    # ── ขั้นที่ 1: รอสัญญาณ (ยกเลิกได้เมื่อกด Stop) ────────────────────────
    if not wait_for_trigger():
        return False, None

    # ── ขั้นที่ 2: จำค่าตั้งต้นไว้ ให้ชิดกับ T1 ที่สุด ──────────────────────
    count_before = get_measured_count(session_id)

    # ── ขั้นที่ 3: ยิง T1 ──────────────────────────────────────────────────
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect((TMX_IP, TMX_PORT))
            s.sendall(TRIGGER_COMMAND.encode("ascii"))
            response = s.recv(BUFFER_SIZE).decode("ascii").strip()
            print(f"📡 TM-X ตอบ trigger: {response}")
            return True, count_before
    except socket.timeout:
        print("❌ ส่ง trigger ไม่สำเร็จ: timeout")
        return False, count_before
    except ConnectionRefusedError:
        print(f"❌ ส่ง trigger ไม่สำเร็จ: connection refused (port {TMX_PORT})")
        return False, count_before
    except Exception as exc:
        print(f"❌ ส่ง trigger ไม่สำเร็จ: {exc}")
        return False, count_before


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
        if not is_running: #ถ้า Stop
            return True
        count_after = get_measured_count(session_id) 
        if count_after is not None and count_before is not None and count_after > count_before:
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

            # รอสัญญาณว่าชิ้นงานพร้อม แล้วยิง T1 (trigger_sensor อ่าน
            # count_before ให้เองหลังได้สัญญาณ — ดูเหตุผลใน docstring)
            print(f"\nชิ้นที่ {piece}/{target_count} — รอสัญญาณ trigger ...")
            _sent, count_before = trigger_sensor(session_id)

            # โดน Stop ระหว่างรอสัญญาณ → trigger_sensor ไม่ได้ยิง T1 ให้
            if not is_running:
                print("⏹ ได้รับคำสั่ง Stop — หยุดการวัด")
                break


            # ── รอยืนยันว่าค่าเข้า DB จริง ก่อนไปชิ้นถัดไป ────────────────── ถ้า wait_for_measurement return true 
            if wait_for_measurement(session_id, count_before): 
                if is_running:
                    print(f"   ✅ ชิ้นที่ {piece}/{target_count} บันทึกแล้ว")
                continue
                # Retry 3 ครั้ง ถ้าไม่ได้รับค่า
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

        # ╔═══ ปิด session ที่ค้าง 'running' — เริ่มส่วนที่เพิ่ม ═══════════════╗
        #
        # ปัญหา: backend ปิด session ให้เฉพาะตอนมี measurement ใหม่เข้ามาเท่านั้น
        #   (create_measurement เช็ค `measured >= target` แล้วค่อยตั้ง stopped)
        #   ถ้ามีชิ้นที่วัดไม่ติดแล้วผู้ใช้เลือก "วัดต่อ" measured_count จะไม่มีวัน
        #   ถึง target_count → ไม่มีใครรันบรรทัดนั้นอีก → session ค้าง 'running'
        #   ทั้งที่ Pi เลิกทำงานไปแล้ว (heartbeat_checker จะมา mark 'timeout' ให้
        #   ใน ~15 วิ แต่บอกสาเหตุผิด เหมือน Pi ตาย ทั้งที่แค่ข้ามชิ้น)
        #
        # ทำไมเช็คแค่ state ไม่เทียบ measured_count กับ target_count:
        #   `measured >= target` เป็นเงื่อนไขเดียวที่ทำให้ auto-complete ทำงาน
        #   ดังนั้น state=='running' ตอนถึง finally = วัดไม่ครบอยู่แล้วในตัว
        #   ถ้าไปเทียบตัวเลขตรงๆ จะพังตอนผู้ใช้กด Stop เองกลางคัน (measured <
        #   target จริง แต่ backend ตั้ง stopped ไปแล้ว) → ยิง stop ซ้ำ →
        #   ended_at โดนเขียนทับ เพราะ stop_session ไม่ได้เช็ค state ก่อน UPDATE
        #
        # ต้องเทียบ session_id ด้วย: /api/session/state คืน session ล่าสุดเสมอ
        #   (ORDER BY session_id DESC LIMIT 1) ไม่ได้รับ param ถ้ามีคนกด Start
        #   ตัวใหม่ระหว่างนี้จะกลายเป็นไปปิด session ของคนอื่นแทน
        #
        # ⚠ ต้องวางหลัง `_tmx_sock = None` เท่านั้น: stop_session ยิง
        #   POST /command {"action":"stop"} กลับมาหา Pi ด้วย ซึ่ง handler นั้นจะ
        #   send_command(_tmx_sock, "S0") ถ้า socket ยังไม่ None — วางก่อนหน้านี้
        #   จะกลายเป็นยิง S0 ใส่ socket ที่เพิ่งปิดไป พอเป็น None แล้ว callback
        #   จะเป็น no-op ปลอดภัย (ไม่ deadlock เพราะ command_flow อยู่คนละ thread
        #   กับ event loop ของ Pi จึงรับ callback ของตัวเองได้)
        try:
            st = httpx.get(f"{BACKEND_URL}/api/session/state", timeout=5).json()
            if st.get("session_id") == session_id and st.get("state") == "running":
                httpx.post(
                    f"{BACKEND_URL}/api/session/stop",
                    json={"session_id": session_id},
                    timeout=10,
                )
                print(f"⏹ แจ้ง backend ปิด session แล้ว "
                      f"(วัดได้ {st.get('measured_count')}/{target_count} — ไม่ครบ)")
        except Exception as exc:
            # ปล่อยผ่านได้ heartbeat_checker ฝั่ง backend ยังเป็นตาข่ายสำรองอยู่
            print(f"   ⚠️ แจ้งปิด session ไม่ได้: {exc} — "
                  f"backend จะปิดเองใน ~{HB_TIMEOUT_HINT:g} วิ (ขึ้นเป็น 'timeout')")
        # ╚═══ ปิด session ที่ค้าง 'running' — จบส่วนที่เพิ่ม ═════════════════╝


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
            #args=(req.session_id, req.template_name, req.target_count),
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


# ╔═══ endpoint จำลอง sensor — เริ่มส่วนที่เพิ่ม ══════════════════════════════╗
#
# ยิงอะไรมาก็ได้ที่ URL นี้ = "ชิ้นงานเข้าที่แล้ว วัดได้เลย" แทนการกด Enter เดิม
#
#   curl -X POST http://<ip-ของ-pi>:9998/trigger
#   หรือพิมพ์ http://<ip-ของ-pi>:9998/trigger บน address bar ของเบราว์เซอร์
#
# รับทั้ง GET และ POST เพราะ address bar ของเบราว์เซอร์ยิงได้แค่ GET เท่านั้น
# (พิมพ์ URL แล้ว Enter = GET เสมอ ส่ง POST จากช่อง URL ไม่ได้)
#
# ไม่ต้องเพิ่ม thread ใดๆ — uvicorn รันอยู่แล้วสำหรับ /command ตัวนี้เกาะไปด้วย
# ส่วน command_flow อยู่คนละ thread จึงเห็น Event ที่ถูก set() ทันที
#
# ⚠ ไม่มี auth เหมือน /command ที่มีอยู่เดิม — ใครยิงถึงพอร์ตนี้ได้ก็สั่งวัดได้
#   ต้องพึ่ง firewall rule ถ้าจะให้แน่นควรจำกัดให้รับเฉพาะ IP ของเครื่อง Backend
@http_app.api_route("/trigger", methods=["GET", "POST"])
async def trigger():
    if not is_running: #ยังไม่เริ่มRun
        # ไม่ทำอะไร แต่ตอบให้รู้ว่ากดแล้วไม่มีผล ไม่งั้นกดตอนไม่มี session
        # แล้วเงียบๆ จะนึกว่าระบบพัง
        return {"ok": False, "reason": "ไม่มี session กำลังวัดอยู่ — กด Start ที่หน้าเว็บก่อน"}
    if not _waiting_for_trigger:
        # ยิงมาถูกจังหวะแต่ยังไม่ถึงช่วงรอ (กำลังส่ง R0/PW ให้ TM-X อยู่ หรือ
        # กำลังรอผลวัดของชิ้นก่อนหน้า) — สัญญาณนี้จะโดน clear() ทิ้งอยู่ดี
        # จึงบอกไปตรงๆ ให้ยิงใหม่ ดีกว่าตอบ ok แล้วเครื่องไม่ขยับ
        return {"ok": False, "reason": "ยังไม่ถึงช่วงรอสัญญาณ — รอข้อความ 'รอสัญญาณ trigger ...' ก่อนแล้วยิงใหม่"}
    _trigger.set()
    print("⚡ ได้รับสัญญาณ trigger")
    return {"ok": True}
# ╚═══ endpoint จำลอง sensor — จบส่วนที่เพิ่ม ════════════════════════════════╝


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
    print(f"  จำลอง trigger ด้วย   : curl -X POST http://<ip-นี้>:{AGENT_PORT}/trigger")
    print(f"                       (หรือเปิด http://<ip-นี้>:{AGENT_PORT}/trigger บนเบราว์เซอร์)")
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
