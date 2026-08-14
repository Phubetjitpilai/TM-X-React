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
# ╔═══ สรุป: Pi แจ้ง "การวัดผิดพลาด" ไปหา Backend ═══════════════════════════════╗
#
# มี 2 ทางเท่านั้น — Pi ไม่เคยเขียน DB ตรงๆ เลย ทุกอย่างผ่าน Backend หมด
# (Backend เป็น Single Source of Truth ดู CLAUDE.md)
#
# ── ① POST /api/measure-timeout ──────── เมื่อรอค่าจนหมดเวลาแล้วยังไม่ขยับ
#   {"session_id": 42, "piece": 2, "target": 3}
#
#   = "การวัดผิดพลาด ค่าไม่ได้ถูกบันทึกลง DB" — รู้ได้จากการ poll
#     GET /api/session/state แล้ว measured_count ไม่ขยับภายใน MEASURE_TIMEOUT
#     Pi แยกสาเหตุไม่ออกว่าเป็น TM-X วัดไม่ติด หรือ FTP มาช้า /
#     Recieve_tm-x.py ไม่ได้รัน จึงโยนให้คนตัดสิน
#   → Backend เด้ง modal ถามผู้ใช้บนหน้าเว็บว่า "วัดต่อ / หยุดการวัด"
#     (หน้าเว็บนับถอยหลัง 60 วิ ครบแล้วถือว่าหยุด — Pi ไม่ได้นับเอง)
#
#   ⚠ Pi ส่งไปแค่ 3 ฟิลด์ **Backend เติมให้อีก 2 ก่อน broadcast**:
#
#       Pi      → {"session_id": 42, "piece": 3, "target": 6}
#       Backend → {"session_id": 42, "piece": 3, "target": 6,
#                  "number_alpl": 402,        ← เติมจาก queue[position] ของตัวเอง
#                  "detail": "TM-X วัดไม่ติด (-9999.999, -9999.999)"}
#                                             ↑ เติมจาก last_event ที่
#                                               Recieve_tm-x.py เขียนไว้ (ถ้ายังสด)
#
#   **ห้าม Pi ส่ง number_alpl มาเอง** — ไม่งั้นจะมี 2 แหล่งที่บอกว่าชิ้นนี้คือ
#   ALPL อะไร (Pi นับเอง vs คิวจริงของ Backend) แล้วเหลื่อมกันได้โดยไม่มีใครรู้
#   · detail เป็น None ได้ ถ้ารูปไม่มาเลยหรือ last_event เก่าเกินไป
#
# ── ② POST /api/session/stop ─────────── ตอน finally ถ้า session ยังค้าง running
#   {"session_id": 42, "reason": "..."}
#
#   = "สั่งหยุดเพราะการวัดผิดพลาด ซึ่งเกิดจาก Error ของ Pi เอง"
#     reason บอกสาเหตุที่ Pi ล้มเลิกเอง Backend เก็บลง last_event แล้ว broadcast
#     ต่อ หน้าเว็บจะได้บอกผู้ใช้ได้ว่าหยุดเพราะอะไร ค่าที่เป็นไปได้:
#       None                                    ← จบปกติ หรือคนกด Stop เอง
#       "Backend ไม่ได้ส่ง target_count มา..."
#       "ต่อ TM-X ที่ <ip>:<port> ไม่ได้ (...)"
#       "session พังกลางทาง — <ExcType>: <msg>"
#
#   ⚠ ยิงตัวนี้แล้ว Backend จะยิง POST /command {"action":"stop"} **กลับมาหา Pi**
#     จึงต้องตั้ง _tmx_sock = None ให้เสร็จก่อนเสมอ (ดู finally ใน command_flow)
# ╚═══════════════════════════════════════════════════════════════════════════╝
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
# เดิมอ่าน TIMEOUT มา "เตือน" อย่างเดียว ตอนนี้บังคับใช้จริงแล้ว (ดู heartbeat_loop)
# ใช้ค่าเดียวกับที่ backend ใช้ตัดสินใน heartbeat_checker() โดยตั้งใจ — สองฝั่งจึง
# ตัดสินใจตรงกันเสมอโดยไม่ต้องส่งคำสั่งหากัน (ดีไซน์สมมาตร ดู Handle_Pi_Error 2.1)
HB_TIMEOUT_HINT = float(os.getenv("HEARTBEAT_TIMEOUT", 15))

# เวลาที่ heartbeat "ยิงออกสำเร็จ" ครั้งล่าสุด — heartbeat_loop ใช้ตัวนี้ตัดสินว่า
# ขาดการติดต่อกับ backend นานเกินไปหรือยัง
#
# ทำไมจับเวลา ไม่นับจำนวนครั้ง: การนับ (_hb_fail × HB_INTERVAL) เพี้ยนเวลาจริง
# เพราะรอบที่ยิงไม่ออกแบบ ConnectTimeout จะกินเวลา timeout=5 วิ ไปก่อน แล้วค่อย
# sleep(HB_INTERVAL) อีก = ~10 วิต่อรอบ ไม่ใช่ 5 → นับครบ 4 ครั้งจะไปเกิดที่ ~40 วิ
# ไม่ใช่ 20 วิอย่างที่ตั้งใจ · จับเวลาตรงๆ ไม่มีปัญหานี้ และเป็นสูตรเดียวกับที่
# backend ใช้เป๊ะ (`last_seen < NOW() - INTERVAL HEARTBEAT_TIMEOUT SECOND`)
_hb_last_ok = time.time()

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

# ╔═══ [MODAL] ปิดไว้ชั่วคราวเพื่อทดสอบ — 14 ส.ค. 2569 ═══════════════════════╗
# ⛔ **โค้ดในบล็อก [MODAL] ทั้ง 4 จุดถูก comment ปิดไว้หมดแล้ว ไม่ทำงาน**
#    ค้นคำว่า [MODAL] เจอครบทุกจุด — เปิดกลับด้วยการลบ `# ` หน้าบรรทัด
#      ① _continue (ตรงนี้)          ② ask_user_on_timeout()
#      ③ จุดที่เรียกใน command_flow   ④ /command action="continue"
#
# ผลที่ตามมาระหว่างปิด:
#   - Pi ไม่ POST /api/measure-timeout อีกแล้ว → หน้าเว็บไม่มี modal เด้ง
#   - ชิ้นที่ไม่ได้ค่าในเวลาที่กำหนด → **เตือนแล้วข้ามไปชิ้นถัดไปเลย** (ดูจุด ③)
#   - measured_count จะไม่ครบ target_count → finally สั่งปิด session ให้เอง
#   - "continue" ที่ยิงเข้ามาจะตอบ 400 (ไม่ควรมี เพราะไม่มี modal ให้ตอบ)
#
# 📌 ตอนเปิดกลับ ให้ดูแผนข้อ 9 ด้วย — เงื่อนไขจะเปลี่ยนจาก
#    "measured_count ไม่ขยับ" เป็น "GM ไม่คืนค่า" ซึ่งเกิดก่อนแตะชิ้นงาน
#    จึงยังถามผู้ใช้ได้อยู่ (ถ้าถามหลัง MCU คัดของไปแล้ว คำถามจะไม่มีความหมาย)
#
# "กระดิ่ง" อีกใบ — ผู้ใช้กด "วัดชิ้นถัดไป" ใน modal ตอนที่ชิ้นก่อนไม่ได้ค่า
#
# ต้องเป็นคนละ Event กับ _trigger เด็ดขาด: ถ้าใช้ใบเดียวกัน สัญญาณ "วัดต่อ" ที่
# มาช้าจะถูกนับเป็น "ชิ้นงานพร้อมวัด" ของชิ้นถัดไป แล้ว T1 จะถูกยิงตอนที่ยังไม่มี
# ชิ้นงานอยู่ใต้กล้อง
# _continue = threading.Event()
# ╚═══ [MODAL] จบ ═══════════════════════════════════════════════════════════╝

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


# ╔═══ คุยกับ MCU — เริ่มส่วนที่เพิ่ม (14 ส.ค. 2569) ═══════════════════════════╗
#
# ⚠ ยังไม่มีใครเรียกใช้ — ลูปเดิมยังเป็นแบบชั้นเดียวและใช้ wait_for_trigger() อยู่
#   ส่วนนี้เตรียมไว้ให้เสียบตอนรื้อ command_flow() เป็นลูป 2 ชั้น (แผนข้อ 8-9)
#   จงใจแยกลงมาก่อน เพื่อให้ curl ทดสอบกลไกรอ/หยุดได้จริงก่อนไปแตะลูป
#
# โปรโตคอลที่ตกลงกันไว้ — **2 สัญญาณเท่านั้น** (ย่อจาก 5 สัญญาณในภาคผนวก ก ของ
# FLOW_send_command.md) ต่อการวัด 1 ชิ้น:
#
#   ① Pi ถาม MCU ก่อนยิง T1 ว่า "พร้อมหรือยัง"  → รอ _mcu_ready
#   ② Pi ส่งผล OK/NG/UNKNOWN ให้ MCU            → รอ _mcu_ack ว่ารับไปแล้ว
#
# ทำไมยุบจาก 5 เหลือ 2 ได้: แผนเดิมแยก "MCU จัดการชิ้นนี้เสร็จแล้ว" ออกมาเป็น
#   สัญญาณต่างหาก เพราะกลัวชิ้นถัดไปถูกวางทับตอนชิ้นเดิมยังไม่ออกจากพื้นที่ —
#   แต่การถาม ① ของชิ้นถัดไปกลืนหน้าที่นั้นไปแล้ว เพราะ MCU จะไม่ตอบว่าพร้อม
#   จนกว่ามันจะเคลียร์ชิ้นเก่าเสร็จ · และการจับมือตอนเริ่ม session (ช่วง 3) ก็
#   ไม่ต้องมี เพราะชิ้นแรกถาม ① อยู่แล้ว = การจับมือในตัว
#
# 📌 ข้อแม้ที่ต้องส่งให้คนเขียนเฟิร์มแวร์ MCU: คำว่า "พร้อม" ต้องแปลว่า
#   "ชิ้นใหม่อยู่ใต้กล้องแล้ว **และ** ชิ้นเก่าออกไปแล้ว" ไม่ใช่แค่ "ฉันว่าง"
#   ถ้าตอบพร้อมตั้งแต่ยังไม่วางชิ้นงาน T1 จะยิงใส่ที่ว่าง
#
# 📌 ต้องส่งผลให้ MCU ทุกครั้งที่ยิง T1 รวมถึงตอน GM ไม่คืนค่า (ส่ง UNKNOWN)
#   ไม่ใช่ข้ามไปเงียบๆ ไม่งั้น MCU จะมีชิ้นงานคาอยู่โดยไม่มีคำสั่ง แล้วมันจะไม่มี
#   วันตอบ "พร้อม" อีกเลย = ค้างทั้งคู่
#
# 🔌 ตอนต่อ MCU จริงผ่าน Serial: เพิ่ม thread อ่าน serial แล้วเรียก
#   `_mcu_ready.set()` / `_mcu_ack.set()` — ตัวรอไม่ต้องแก้เลย เหมือนที่ทำกับ
#   _trigger (เก็บ endpoint ไว้เป็น manual override ได้ด้วย)
#
# ⚠ ต้องเป็นคนละ Event เด็ดขาด เหตุผลเดียวกับ _trigger vs _continue:
#   ถ้าใช้ใบเดียวกัน สัญญาณ ② ของชิ้นก่อนที่มาช้าจะถูกนับเป็น ① ของชิ้นถัดไป
#   แล้ว T1 จะถูกยิงตอนที่ยังไม่มีชิ้นงานอยู่ใต้กล้อง
_mcu_ready = threading.Event()   # MCU: พร้อมแล้ว (ชิ้นใหม่เข้าที่ + ชิ้นเก่าออกแล้ว)
_mcu_ack   = threading.Event()   # MCU: รับผลไปจัดการแล้ว

# ตอนนี้กำลังรอสัญญาณไหนอยู่ — endpoint ใช้ตอบให้ตรงความจริงว่าสัญญาณที่ยิงมา
# จะถูกใช้หรือถูกทิ้ง (เหตุผลเดียวกับ _waiting_for_trigger)
_mcu_waiting = {"ready": False, "ack": False}


def _wait_mcu(ev, key, timeout=None):
    """รอสัญญาณจาก MCU — True = ได้สัญญาณ · False = โดน Stop / หมดเวลา

    clear() ก่อนเสมอ เพื่อทิ้งสัญญาณที่ยิงมาตอนยังไม่ถึงคิว (เช่น curl รัวไว้
    ล่วงหน้า หรือ MCU เด้งสัญญาณซ้ำ) ไม่งั้นชิ้นถัดไปจะวิ่งทันทีโดยไม่ได้รอจริง

    วนเช็ค is_running ทุก 0.1 วิระหว่างรอ ไม่บล็อกยาว — กด Stop แล้วหลุดได้เสมอ
    ภายใน ~0.1 วิ ไม่ว่ากำลังรออะไรอยู่

    timeout=None = รอไม่จำกัด (จนกว่าจะได้สัญญาณหรือโดน Stop) ซึ่งเป็นค่าที่ควร
    ใช้ตอนรอ ① เพราะการวางชิ้นงานกินเวลาไม่แน่นอน อาจเป็นวินาทีหรือเป็นนาที
    """
    ev.clear()
    _mcu_waiting[key] = True
    try:
        deadline = None if timeout is None else time.time() + timeout
        while is_running:
            if ev.wait(0.1):
                return True
            if deadline is not None and time.time() > deadline:
                return False
        return False
    finally:
        _mcu_waiting[key] = False


def wait_mcu_ready(timeout=None):
    """① รอ MCU บอกว่าพร้อมให้วัด — เรียกก่อนยิง T1 ทุกชิ้น"""
    return _wait_mcu(_mcu_ready, "ready", timeout)


def wait_mcu_ack(timeout=None):
    """② รอ MCU บอกว่ารับผลไปจัดการแล้ว — เรียกหลังส่งผลตัดสิน"""
    return _wait_mcu(_mcu_ack, "ack", timeout)


def report_to_mcu(result):
    """ส่งผลตัดสินให้ MCU — result เป็น "OK" / "NG" / "UNKNOWN"

    ตอนนี้ยังไม่มี MCU จริง จึงแค่พิมพ์ให้เห็นว่าส่งอะไรออกไป พอต่อ Serial จริง
    ค่อยเปลี่ยนบรรทัดข้างในเป็นการเขียนลงพอร์ต — ตัวเรียกไม่ต้องแก้

    "UNKNOWN" = GM ไม่คืนค่าภายในเวลาที่กำหนด (TM-X วัดไม่ติด) เป็นสถานะที่สาม
    ที่ต้องมี ไม่ใช่แค่ OK กับ NG — ให้ MCU เป็นคนตัดสินใจว่าจะจัดการยังไง
    """
    print(f"🔀 → MCU: {result}")
# ╚═══ คุยกับ MCU — จบส่วนที่เพิ่ม ═══════════════════════════════════════════╝

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


# ╔═══ [MODAL] ② ถามผู้ใช้บนหน้าเว็บ ═════════════════════════════════════════╗
# def ask_user_on_timeout(session_id, piece, target):
#     """แจ้ง Backend ว่าไม่ได้รับค่า แล้วรอคำตอบจากผู้ใช้บนหน้าเว็บ
#
#     คืน "continue" (วัดต่อ) หรือ "stop" (หยุด)
#
#     ╔═══ เลิก poll แล้ว — 7 ส.ค. 2569 ═══════════════════════════════════════╗
#     เดิมวน GET /api/measure-timeout/{id} ทุก 0.4 วิถามว่ามีคำตอบหรือยัง
#     ตอนนี้ Backend ยิง POST /command มาปลุกแทน — ตื่นทันทีที่คำตอบมาถึง และ
#     คำสั่งจากข้างนอกเข้าทาง /command ทางเดียวหมด (start / stop / continue)
#
#     ทางออกเหลือ 3 ทางเท่านั้น:
#       is_running = False  ← /command stop  (ปุ่ม Stop · "หยุด" ใน modal ·
#                             modal หมดเวลา 60 วิ — ทุกทางวิ่งผ่าน
#                             POST /api/session/stop เหมือนกันหมด)
#       is_running = False  ← heartbeat_loop  (ขาดการติดต่อ backend เกิน
#                             HEARTBEAT_TIMEOUT — เพิ่ม 13 ส.ค. 2569)
#                             **จำเป็นต้องมีทางนี้** ไม่งั้นถ้า backend ตายตอน
#                             modal ค้างอยู่ จะไม่มีใครมาปลุกเลย Pi รอตลอดกาล
#       _continue.set()     ← /command continue  (กด "วัดชิ้นถัดไป")
#
#     ไม่มี timeout ฝั่งนี้ — **หน้าเว็บเป็นคนนับ 60 วิ** เพราะการวัดต้องมีคนวาง
#     ชิ้นงานอยู่แล้ว ไม่มีคน = ไม่มี modal · และผู้ใช้เห็นเวลาเดินจริงบนจอด้วย
#     ถ้าแท็บถูกปิดตอน modal โผล่ → เปิดเว็บใหม่แล้วกด Stop (/command ยังถึง Pi ปกติ)
#     ╚═══════════════════════════════════════════════════════════════════════╝
#     """
#     _continue.clear()   # ล้างสัญญาณค้างจากรอบก่อน — เหตุผลเดียวกับ wait_for_trigger()
#     try:
#         httpx.post(
#             f"{BACKEND_URL}/api/measure-timeout",
#             json={"session_id": session_id, "piece": piece, "target": target},
#             timeout=10,
#         )
#     except Exception as exc:
#         # แจ้งไม่ได้ = ไม่มี modal เด้ง = ไม่มีใครตอบได้ รอไปก็เท่านั้น
#         print(f"   ⚠️ แจ้ง Backend เรื่อง timeout ไม่สำเร็จ: {exc} — ถือว่าหยุด")
#         return "stop"
#
#     print("   ⏳ รอผู้ใช้ตอบบนหน้าเว็บ (วัดต่อ / หยุด)...")
#     while is_running:
#         if _continue.wait(0.1):     # ตื่นทุก 0.1 วิไปเช็ค is_running ด้วย
#             if not is_running:      # กันไว้อีกชั้น: ถ้ามีใครไปตั้ง _continue ตอน stop
#                 break
#             print("   ▶ ผู้ใช้เลือกวัดชิ้นถัดไป")
#             return "continue"
#     print("   ⏹ ผู้ใช้เลือกหยุด (หรือ modal หมดเวลา)")
#     return "stop"
# ╚═══ [MODAL] ② จบ ═════════════════════════════════════════════════════════╝


def heartbeat_loop():
    """ยิง POST /api/heartbeat ทุก HB_INTERVAL วิ ตลอดเวลาที่ Agent รันอยู่
    (แนบ session_id ปัจจุบันไปด้วยถ้ากำลังวัดอยู่ — backend ใช้ต่ออายุ
    sessions.last_seen กัน heartbeat_checker mark session เป็น timeout)
    รันใน daemon thread แยก จึงไม่กวน command_flow และตายไปพร้อม process

    ╔═══ หยุดตัวเองเมื่อขาดการติดต่อ — เริ่มส่วนที่เพิ่ม ══════════════════════╗
    เดิม loop นี้รู้อยู่แก่ใจว่ายิงไม่ออกแล้วก็ `pass` ทิ้งทันที ผลคือเวลาสาย LAN
    หลุด/backend ล่มกลาง session: backend mark session เป็น 'timeout' + ทิ้งคิว
    ไปแล้ว แต่ Pi ไม่รู้เรื่อง ยัง T1 สั่ง TM-X วัดต่อจนครบ target_count กลายเป็น
    "เครื่องเดินอยู่คนเดียวโดยไม่มีใครฟัง" — ค่าที่ Recieve_tm-x.py POST ตามมา
    จะโดน create_measurement ตอบ 409 ทิ้งเงียบๆ เสียทั้งชิ้นงานและเวลา

    ดีไซน์ที่ใช้คือ **สมมาตร** — สองฝั่งใช้กติกาเดียวกันคือ "เวลาตั้งแต่ heartbeat
    สำเร็จครั้งล่าสุด > HEARTBEAT_TIMEOUT" แล้วต่างคนต่างหยุดเอง ไม่มีใครสั่งใคร:
        backend : last_seen เก่าเกิน → state='timeout' + ทิ้งคิว + แจ้ง SSE
        Pi      : _hb_last_ok เก่าเกิน → is_running=False (โค้ดข้างล่างนี้)
    จงใจไม่ให้ backend ส่งคำสั่ง stop กลับมา เพราะตอนที่ heartbeat ขาด มันก็ยิง
    /command มาหา Pi ไม่ถึงอยู่แล้วด้วยเหตุผลเดียวกัน
    ╚═══════════════════════════════════════════════════════════════════════╝
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
            pass  # backend ล่มชั่วคราวไม่เป็นไร รอบหน้าค่อยยิงใหม่
                  # (ไม่ต้องนับอะไร แค่ "ไม่อัปเดตเวลา" ก็พอแล้ว)

        # เช็คนอก try เสมอ — ต้องทำงานทุกรอบไม่ว่ารอบนี้จะยิงออกหรือไม่ก็ตาม
        # เงื่อนไข is_running กันไม่ให้ไปยุ่งตอน Pi ว่างอยู่ (ไม่มีอะไรให้หยุด)
        if is_running and time.time() - _hb_last_ok > HB_TIMEOUT_HINT:
            print(f"\n⏹ ติดต่อ Backend ไม่ได้เกิน {HB_TIMEOUT_HINT:g} วิ — หยุดวัด")
            print(f"   (backend น่าจะ mark session เป็น 'timeout' ไปแล้ว "
                  f"วัดต่อไปค่าก็ถูกทิ้ง)")
            is_running = False   # command_flow เช็คตัวนี้ก่อนวัดชิ้นถัดไป
        time.sleep(HB_INTERVAL)


def command_flow(session_id, groups, target_count):
    """Flow หลัก — รันใน thread แยกเพื่อไม่ block FastAPI server

    ╔═══ ได้รับคำสั่ง Start แล้วทำอะไรบ้าง — ไล่ทีละขั้น ═══════════════════════╗
    │
    │  ① ตั้งสถานะฝั่ง Pi  (3 ตัวแปร ลำดับสำคัญ)
    │       _hb_last_ok = now()      รีเซ็ตนาฬิกา heartbeat **ก่อน** is_running
    │       current_session_id = id  heartbeat เริ่มแนบ session นี้ทันที
    │       is_running = True        เปิดสวิตช์ให้ทุก loop เดินได้
    │
    │  ② ตรวจ target_count ก่อนแตะ TM-X
    │       ไม่มี / เป็น 0 → ตั้ง stop_reason แล้ว return ทันที ไม่ต่อ TCP เลย
    │       (เดิมใช้ `target_count or 1` กลายเป็นวัด 1 ชิ้นจบเงียบๆ)
    │
    │  ③ เปิด TCP ไป TM-X  (timeout 5 วิ · แยก except ต่างหากให้รู้ว่าพังตรงไหน)
    │       สำเร็จ → _tmx_sock = socket  ให้ stop handler ยิง S0 ได้ทันที
    │
    │  ④ เข้าโหมดวัด + โหลดโปรแกรม
    │       R0                    แล้ว sleep 0.5
    │       PW,1,<template>       แล้ว sleep 1.0        ← zero-pad 3 หลัก
    │       ⚠ ไม่เช็ค response ทั้งคู่ — TM-X ตอบ error ก็เดินหน้าต่อ (Known Issue)
    │
    │  ⑤ วนวัดทีละชิ้นจนครบ target_count  ← ลูปชั้นเดียว (แผนข้อ 8 จะทำเป็น 2 ชั้น)
    │       เช็ค is_running                      → False = break
    │       trigger_sensor()
    │           รอสัญญาณ (Event · ตื่นทุก 0.1 วิ)  ← ตอนนี้มาจาก POST /trigger
    │           อ่าน count_before                  ← อ่านชิดกับ T1 ที่สุด
    │           เปิด socket **ใหม่** ยิง T1        ← ไม่ใช้สายหลัก
    │       เช็ค is_running อีกครั้ง               → False = break
    │       wait_for_measurement()                 poll measured_count 15 วิ
    │           ขยับ    → ✅ ชิ้นถัดไป
    │           ไม่ขยับ → [MODAL] ถามผู้ใช้บนหน้าเว็บ "วัดต่อ / หยุด"
    │
    │  ⑥ finally — ล้างเสมอไม่ว่าจบยังไง (ดูคอมเมนต์ในบล็อกนั้น ลำดับสำคัญมาก)
    │       S0 → shutdown+close → เคลียร์ตัวแปร → ปิด session ที่ backend ถ้าค้าง
    │
    ╚═══════════════════════════════════════════════════════════════════════╝

    หมายเหตุ: ค่าที่วัดได้ **ไม่ได้วิ่งผ่านฟังก์ชันนี้เลย** — TM-X ส่งตรงเข้า PC
    ทาง FTP แล้ว Recieve_tm-x.py เป็นคน POST เข้า Backend · Pi รู้ผลทางอ้อม
    ด้วยการดูว่า measured_count ขยับไหมเท่านั้น (ขั้น ⑤)

    ⚠ ทุกอย่างอยู่ใน try/finally เพราะถ้าต่อ TM-X ไม่ได้ (สาย LAN หลุด / TM-X
    ปิดอยู่ / IP ผิด) แล้วปล่อยให้ exception หลุดออกไปเฉยๆ ตัวแปรสถานะจะค้าง:
      - is_running ค้าง True         → กด Start ใหม่ไม่ได้
      - current_session_id ค้าง      → heartbeat ยังแนบ session เดิมไปเรื่อยๆ
                                        backend เลยคิดว่า session ยังมีชีวิต
                                        ไม่ยอม mark timeout → หน้าเว็บค้าง RUNNING
    ต้องปิดสคริปต์แล้วกด Stop จากเว็บล้างเอง ซึ่งไม่ควรต้องทำ
    """
    global current_session_id, is_running, _tmx_sock, _hb_last_ok
    # ⚠ ต้องรีเซ็ตนาฬิกา heartbeat ก่อนตั้ง is_running=True เสมอ ไม่งั้นเคสนี้พัง:
    #   Pi นั่งว่างอยู่ตอน backend ดับไปหลายนาที → _hb_last_ok ค้างเก่ามาก → พอ
    #   backend ฟื้นแล้วกด Start ปุ๊บ is_running เป็น True ทันทีแต่ heartbeat รอบ
    #   ใหม่ยังไม่ทันยิง → heartbeat_loop เห็นว่า "ขาดการติดต่อมานานแล้ว" แล้ว
    #   หยุด session ทิ้งทันทีทั้งที่ทุกอย่างปกติดี
    _hb_last_ok = time.time()
    current_session_id = session_id  # heartbeat จะเริ่มแนบ session นี้ทันที
    is_running = True
    client_socket = None

    # สาเหตุที่ Pi ล้มเลิกเอง — ส่งไปกับ POST /api/session/stop ให้ backend เก็บลง
    # last_event แล้ว broadcast ต่อ หน้าเว็บจะได้บอกผู้ใช้ได้ว่าหยุดเพราะอะไร
    # None = จบปกติ หรือคนสั่งหยุดเอง (ไม่ต้องมีเหตุผล)
    stop_reason = None

    try:
        # ── แสดงสิ่งที่ Backend ส่งมาให้เห็นชัดๆ ────────────────────────────
        # target_count มาจาก len(alpl_queue) ฝั่ง backend (1 ALPL = 1 ชิ้น)
        # ถ้าขึ้นไม่ตรงกับที่กรอกหน้าเว็บ แปลว่าปัญหาอยู่ที่ payload ไม่ใช่ที่ loop
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

        # ลูปยังเป็นชั้นเดียว จึงใช้ template ของกลุ่มแรก — ปลอดภัยเพราะ handler
        # บล็อกเคส template ต่างกันไปแล้ว (ดู /command) พอทำลูป 2 ชั้นตามแผนข้อ 8
        # บรรทัดนี้จะย้ายเข้าไปอยู่ในลูปนอกแทน
        template_name = groups[0].template_name

        if not target_count or target_count < 1:
            # เดิมใช้ (target_count or 1) เงียบๆ ทำให้ payload ที่ไม่มี
            # target_count กลายเป็น "วัด 1 ชิ้นแล้วจบ" โดยไม่มีอะไรเตือนเลย
            print("❌ Backend ไม่ได้ส่ง target_count มา (หรือส่งมาเป็น 0)")
            print("   → ไม่เริ่มวัด กด Stop ที่หน้าเว็บแล้วลองใหม่")
            stop_reason = "Backend ไม่ได้ส่ง target_count มา (หรือส่งมาเป็น 0)"
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
            stop_reason = (f"ต่อ TM-X ที่ {TMX_IP}:{TMX_PORT} ไม่ได้ ({type(exc).__name__}) "
                           f"— ตรวจสาย LAN · TM-X เปิดอยู่ไหม · TMX_HOST/TMX_PORT ใน .env")
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
            # ╔═══ [MODAL] ③ จุดที่เรียก — ปิดไว้ชั่วคราวเพื่อทดสอบ ═════════════╗
            # print(f"\n⚠️ ชิ้นที่ {piece}/{target_count}: รอ {MEASURE_TIMEOUT:.0f} วิแล้วไม่ได้รับค่าการวัด")
            # if ask_user_on_timeout(session_id, piece, target_count) == "stop":
            #     print("⏹ ผู้ใช้เลือกหยุด — จบ session")
            #     break
            # print("▶ ผู้ใช้เลือกวัดต่อ — ไปชิ้นถัดไป")
            #
            # ⚠ พฤติกรรมชั่วคราวระหว่างปิด modal: **เตือนแล้วข้ามไปชิ้นถัดไปเลย**
            #   เลือกแบบนี้เพราะข้อมูลหน้างาน 31/07 บอกว่า TM-X วัดไม่ติด 7 ใน 8
            #   ครั้ง ถ้าให้ break ทันที session จะตายตั้งแต่ชิ้นแรกเกือบทุกครั้ง
            #   แล้วทดสอบลูปไม่ได้เลย · ผลคือ measured_count จะไม่ครบ target_count
            #   แล้ว finally จะไปสั่งปิด session ให้เอง (ซึ่งถูกต้องอยู่แล้ว)
            print(f"\n⚠️ ชิ้นที่ {piece}/{target_count}: รอ {MEASURE_TIMEOUT:.0f} วิแล้วไม่ได้รับค่าการวัด")
            print("   ⏭ [MODAL ปิดอยู่] ข้ามชิ้นนี้ไปวัดชิ้นถัดไปเลย")
            # ╚═══ [MODAL] ③ จบ ═══════════════════════════════════════════╝

    except Exception as exc:
        print(f"\n❌ session พังกลางทาง — {type(exc).__name__}: {exc}")
        stop_reason = f"session พังกลางทาง — {type(exc).__name__}: {exc}" 

    finally:
        # ── ล้างสถานะให้สะอาดเสมอ ไม่ว่าจะจบปกติ พัง หรือโดนสั่ง Stop ──────
        # จบการทำงาน — กลับโหมดตั้งค่า (S0 ยิงซ้ำกับตอน stop handler ได้ไม่เป็นไร
        # TM-X รับซ้ำได้)
        #
        # ⚠ เดิมครอบ try/except แล้ว `pass` เฉยๆ ทั้งก้อน — ถ้า S0 ถูกปฏิเสธหรือ
        #   timeout จะไม่มีใครรู้เลยสักคน แล้ว TM-X ค้างอยู่ในโหมดดำเนินงานตลอด
        #   (คนหน้างานแตะจอแก้โปรแกรมไม่ได้ + เครื่องยังเปิดรับ T1 อยู่)
        #   ตอนนี้ยังกลืน exception เหมือนเดิม (ไม่ให้ session พังเพราะ S0)
        #   แต่ต้อง log ให้เห็นเสมอ
        if client_socket is not None:
            try:
                resp = send_command(client_socket, "S0")
                if str(resp).upper().startswith("ER"):
                    print(f"⚠️ S0 ถูกปฏิเสธ: {resp!r} — TM-X อาจยังค้างในโหมดดำเนินงาน")
                else:
                    print(f"→ S0 : {resp}")
                time.sleep(0.5)
            except Exception as exc:
                print(f"⚠️ ส่ง S0 ไม่สำเร็จ: {type(exc).__name__} — "
                      f"TM-X อาจยังค้างในโหมดดำเนินงาน")

            # ── ปิด connection ให้สะอาด ────────────────────────────────────
            # TM-X ให้มี "อุปกรณ์ควบคุม" ได้ทีละตัวเดียว — ตราบใดที่มันยังเห็นว่า
            # connection นี้มีชีวิตอยู่ จอสัมผัสหน้าเครื่องจะถูกล็อกไว้ ขึ้นข้อความ
            # "Another device is currently in use."
            #
            # close() เฉยๆ แค่คืน handle ให้ OS ไม่ได้ส่ง FIN บอก TM-X ทันทีเสมอไป
            # shutdown(SHUT_RDWR) บอกตรงๆ ว่า "จบแล้ว ตัดได้เลย"
            # (ยืนยันหน้างาน 6 ส.ค. 2569: S0 เปลี่ยนโหมดสำเร็จจริง แต่จอยังล็อก
            #  จนกว่าจะกด Close Other Device ที่เครื่อง = ปัญหาอยู่ที่การปล่อย
            #  connection ไม่ใช่ที่ตัวคำสั่ง S0)
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
                    json={"session_id": session_id, "reason": stop_reason},
                    timeout=10,
                )
                print(f"⏹ แจ้ง backend ปิด session แล้ว "
                      f"(วัดได้ {st.get('measured_count')}/{target_count} — ไม่ครบ)")
        except Exception as exc:
            # ปล่อยผ่านได้ heartbeat_checker ฝั่ง backend ยังเป็นตาข่ายสำรองอยู่
            print(f"   ⚠️ แจ้งปิด session ไม่ได้: {exc} — "
                  f"backend จะปิดเองใน ~{HB_TIMEOUT_HINT:g} วิ (ขึ้นเป็น 'timeout')")
        # ╚═══ ปิด session ที่ค้าง 'running' — จบส่วนที่เพิ่ม ═════════════════╝


class Limits(BaseModel):
    """ขอบเขตสำเร็จรูปที่ Backend คำนวณมาให้แล้ว — Pi เอาไปเทียบตรงๆ ได้เลย

    **ไม่ใช่ nominal/tolerance ดิบ** Backend บวก/ลบ _TOL_EPS (1e-6) มาให้แล้ว
    เพราะคอลัมน์ใน DB เป็น FLOAT (5.02 อ่านกลับได้ 5.0199999809265137)
    ถ้า Pi คำนวณเองแล้วลืมค่านี้ จะตัดสินไม่ตรงกับ Backend **เฉพาะชิ้นที่ตกขอบ
    พอดี** ซึ่งเป็นชิ้นที่สำคัญที่สุดและหาสาเหตุยากที่สุด

    offset_max = None → โหมดนี้ไม่ตรวจ offset (IPM) ให้ถือว่าผ่าน
    **ไม่มี measure_type ส่งมาด้วยโดยตั้งใจ** กันไม่ให้กฎเรื่องโหมดงอกที่ฝั่ง Pi
    """
    x_lo: float
    x_hi: float
    y_lo: float
    y_hi: float
    offset_max: float | None = None


class Group(BaseModel):
    """1 กลุ่ม = ALPL หลายตัวที่ใช้โปรแกรมวัดและเกณฑ์ตัดสินชุดเดียวกัน"""
    template_name: str
    alpl: list[int]
    limits: Limits | None = None


class CommandRequest(BaseModel):
    """หน้าตาต้องตรงกับ payload ที่ Backend ส่งมาจริงเสมอ (main.py:888)

        {"action": "start", "session_id": 42, "target_count": 6,
         "groups": [{"template_name": "021", "alpl": [400, 401, 402],
                     "limits": {"x_lo": ..., "x_hi": ..., "y_lo": ...,
                                "y_hi": ..., "offset_max": null}}, ...]}

    ⚠ เคยพลาดมาแล้ว: เดิมคลาสนี้มี `template_name` / `number_alpl` ระดับบนสุด
      ซึ่ง Backend **เลิกส่งไปแล้ว** (ย้ายเข้าไปอยู่ใน groups) แต่ไม่มีฟิลด์
      `groups` ให้รับ Pydantic จึงทิ้งทั้งก้อนเงียบๆ ผลคือ template_name เป็น
      None แล้วยิง `PW,1,None` เข้า TM-X → วัดด้วยโปรแกรมที่ค้างจากรอบก่อน
      โดยไม่มีอะไรเตือน (เพราะยังไม่เช็ค response ของ PW ด้วย)

      📌 เวลาแก้ payload ฝั่ง Backend ต้องมาแก้คลาสนี้ให้ตรงกันเสมอ
    """
    action: str
    session_id: int | None = None
    target_count: int | None = None
    groups: list[Group] | None = None


@http_app.post("/command")
async def command(req: CommandRequest):
    global is_running
    if req.action == "start":
        # ── รับ Start: โยนเข้า thread ใหม่แล้วตอบกลับทันที ──────────────────
        # ห้ามทำงานวัดใน request นี้เด็ดขาด เพราะจะบล็อก HTTP server ไว้ทั้งรอบ
        # (การวัดกินเวลาเป็นนาที) แล้วคำสั่ง stop ที่ตามมาทีหลังจะเข้าไม่ได้เลย
        # — Backend เองก็ตั้ง read timeout ไว้แค่ 10 วิ (ดู _notify_agent_start
        #   ใน main.py) ถ้ารอจนวัดเสร็จจะได้ ReadTimeout ทุกครั้ง
        #
        # daemon=True: ปิดสคริปต์แล้ว thread ตายตาม ไม่ค้างให้ต้อง kill เอง
        #
        # ── ตรวจ payload ให้ครบก่อนรับงาน ไม่ใช่รับไว้ก่อนแล้วค่อยพังกลางคัน ──
        # (FLOW_send_command.md ช่วงที่ 1) ผิดข้อไหนตอบ 400 กลับไปทันทีแล้วจบ
        # — ดีกว่าปล่อยให้ command_flow เริ่มไปแล้วค่อยล้มเลิกทีหลัง เพราะตอนนั้น
        #   session ฝั่ง Backend เปิดค้างไปแล้ว ต้องไปตามปิดทีหลังอีก
        groups = req.groups
        if not groups:
            raise HTTPException(400, "payload ไม่มี `groups` — Backend ส่ง template/ALPL "
                                     "มาในฟิลด์นี้ (ดู _build_groups ใน main.py)")
        if any(not g.alpl for g in groups):
            # กลุ่มว่าง = ยิง PW ฟรีโดยไม่มีชิ้นงานตามมา
            raise HTTPException(400, "มีกลุ่มที่ `alpl` ว่างเปล่า")

        all_alpl = [a for g in groups for a in g.alpl]
        if len(set(all_alpl)) != len(all_alpl):
            raise HTTPException(400, "มี ALPL ซ้ำข้ามกลุ่ม — คิวจะเหลื่อมกับฝั่ง Backend")
        if req.target_count != len(all_alpl):
            raise HTTPException(400, f"target_count ({req.target_count}) ไม่เท่ากับจำนวน ALPL "
                                     f"รวมทุกกลุ่ม ({len(all_alpl)})")

        # ⚠ ข้อนี้เป็นข้อจำกัด "ชั่วคราว" ของ Pi ไม่ใช่ของระบบ — ลูปข้างล่างยัง
        #   เป็นชั้นเดียวและยิง PW ครั้งเดียวตอนเริ่ม จึงรองรับได้แค่ template
        #   เดียวทั้ง session · ตอนนี้ Backend บล็อกเคสนี้ให้อยู่แล้ว แต่ Pi ต้อง
        #   กันตัวเองด้วย ไม่งั้นวันที่ทำแผนข้อ 8 แล้วปลดบล็อกฝั่ง Backend
        #   กลุ่มที่ 2 เป็นต้นไปจะถูกวัดด้วยโปรแกรมของกลุ่มแรก — ได้ค่าที่
        #   "ดูเหมือนใช้ได้" แต่ผิดทั้งกลุ่มโดยไม่มีอะไรเตือน
        #   → ลบเช็คนี้ทิ้งพร้อมกับตอนทำลูป 2 ชั้น
        templates = {g.template_name for g in groups}
        if len(templates) > 1:
            raise HTTPException(400, f"Pi ยังรองรับ template เดียวต่อ session — ได้มา "
                                     f"{sorted(templates)} (ลูป 2 ชั้นคือแผนข้อ 8)")

        threading.Thread(
            target=command_flow,
            args=(req.session_id, groups, req.target_count),
            daemon=True,
        ).start()
    elif req.action == "stop":
        print("\n⏹ ได้รับคำสั่ง Stop จาก Backend")
        is_running = False  # loop ใน command_flow จะเห็นแล้วหยุดเอง
        # ⚠ ห้าม _continue.set() ตรงนี้ — เคยใส่แล้วเจอบั๊ก: ask_user_on_timeout
        #   จะเห็นกระดิ่งดังแล้วคืน "continue" ทั้งที่ผู้ใช้กดหยุด
        #   ไม่ต้องปลุกอยู่แล้ว เพราะ _continue.wait(0.1) หมดเวลาเองทุก 0.1 วิ
        #   แล้ววนไปเช็ค is_running ต่อ — ออกจากลูปช้าสุด 0.1 วิ
        #   (ให้ _continue มีความหมายเดียวคือ "วัดชิ้นถัดไป" เท่านั้น)
        # ยิง S0 ไป TM-X ทันทีเลยถ้ายังต่ออยู่ — ไม่ต้องรอ loop วนมาเช็ค flag
        if _tmx_sock is not None:
            try:
                send_command(_tmx_sock, "S0")
                print("→ ส่ง S0 ไป TM-X แล้ว")
            except Exception:
                pass
    # ╔═══ [MODAL] ④ รับคำสั่ง continue — ปิดไว้ชั่วคราวเพื่อทดสอบ ═══════════╗
    # elif req.action == "continue":
    #     # ผู้ใช้กด "วัดชิ้นถัดไป" ใน modal — Backend ขยับ position ให้เรียบร้อย
    #     # แล้วก่อนยิงมา (ดู continue_session ใน main.py) จึงปลุกได้เลย
    #     print("\n▶ ได้รับคำสั่ง Continue จาก Backend — วัดชิ้นถัดไป")
    #     _continue.set()
    #
    # ปิดแล้ว "continue" จะตกไปที่ else ข้างล่างแล้วตอบ 400 ซึ่งถูกต้อง —
    # Backend จะยิง continue มาก็ต่อเมื่อผู้ใช้ตอบ modal เท่านั้น และตอนนี้เรา
    # ไม่ได้ POST /api/measure-timeout ไปแล้ว จึงไม่มีทางมี modal ให้ตอบ
    # ถ้าเห็น 400 นี้โผล่ขึ้นมาแปลว่ามีอะไรผิดคาด ไม่ใช่เรื่องปกติ
    # ╚═══ [MODAL] ④ จบ ═════════════════════════════════════════════════════╝
    # ╔═══ ปฏิเสธ action ที่ไม่รู้จัก — 7 ส.ค. 2569 ══════════════════════════╗
    #
    # เดิมไม่มี else — action ที่ไม่รู้จักจะตกท้ายมาที่ return แล้ว **ตอบว่า ok
    # ทั้งที่ไม่ได้ทำอะไรเลย**
    #
    # เคสจริงที่เกิดมาแล้ว: backend ยิง {"action": "pause"} มา สคริปต์นี้ไม่รู้จัก
    # จึงเงียบแล้วตอบ ok กลับไป → หน้าเว็บขึ้น 'paused' แต่เครื่องยังวัดต่อ
    # (Pause ถูกถอดออกทั้งระบบแล้ว แต่บรรทัดนี้กันไม่ให้เกิดเรื่องแบบเดิมซ้ำอีก
    #  เวลามีใครเพิ่ม action ใหม่ฝั่ง backend แล้วลืมทำฝั่งนี้)
    else:
        # ⚠ ข้อความนี้ต้องตรงกับ action ที่ "เปิดใช้งานจริง" เสมอ —
        #   ตอนนี้ continue ถูกปิดไว้ (ดู [MODAL] ④) จึงไม่อยู่ในลิสต์
        #   เปิด [MODAL] กลับเมื่อไหร่ อย่าลืมเติม continue กลับเข้าข้อความด้วย
        raise HTTPException(
            400,
            f"ไม่รู้จัก action '{req.action}' — ตอนนี้รองรับแค่ start/stop "
            f"(continue ถูกปิดไว้ชั่วคราวพร้อมกับ modal)",
        )
    # ╚═══════════════════════════════════════════════════════════════════════╝
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


# ╔═══ endpoint จำลอง MCU — เริ่มส่วนที่เพิ่ม (14 ส.ค. 2569) ══════════════════╗
#
# ยิง curl มาที่ 2 URL นี้ = "MCU ตอบกลับมา" แทนบอร์ดจริงที่ยังไม่มี
#
#   curl -X POST http://<ip-ของ-pi>:9998/mcu/ready   ← ① พร้อมให้วัดแล้ว
#   curl -X POST http://<ip-ของ-pi>:9998/mcu/ack     ← ② รับผลไปจัดการแล้ว
#
# ไม่มีโหมดตอบอัตโนมัติโดยตั้งใจ — รอ curl มืออย่างเดียว จะได้เห็นทุกจังหวะว่า
# ลูปหยุดรอตรงไหนจริงๆ (เคยคุยกันว่าจะทำโหมดหน่วงเวลาอัตโนมัติ แล้วตัดออก)
#
# guard 2 ชั้นเหมือน /trigger — ตอบให้ตรงความจริงว่าสัญญาณจะถูกใช้หรือถูกทิ้ง
# ไม่งั้น curl แล้วเครื่องไม่ขยับจะนึกว่าระบบพัง แล้วหาสาเหตุไม่เจอ
def _mcu_signal(ev, key, label):
    if not is_running:
        return {"ok": False, "reason": "ไม่มี session กำลังวัดอยู่ — กด Start ที่หน้าเว็บก่อน"}
    if not _mcu_waiting[key]:
        return {"ok": False,
                "reason": f"ยังไม่ถึงช่วงรอ '{label}' — ดูข้อความบนเทอร์มินัลของ Pi ก่อนแล้วยิงใหม่"}
    ev.set()
    print(f"🤝 MCU: {label}")
    return {"ok": True}


@http_app.api_route("/mcu/ready", methods=["GET", "POST"])
async def mcu_ready():
    """① แทน MCU ตอบว่า 'ชิ้นใหม่เข้าที่แล้ว ชิ้นเก่าออกแล้ว วัดได้เลย'"""
    return _mcu_signal(_mcu_ready, "ready", "พร้อมให้วัด")


@http_app.api_route("/mcu/ack", methods=["GET", "POST"])
async def mcu_ack():
    """② แทน MCU ตอบว่า 'รับผลตัดสินไปจัดการแล้ว'"""
    return _mcu_signal(_mcu_ack, "ack", "รับผลไปจัดการแล้ว")
# ╚═══ endpoint จำลอง MCU — จบส่วนที่เพิ่ม ═══════════════════════════════════╝


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
