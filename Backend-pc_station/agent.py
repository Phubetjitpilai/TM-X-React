"""
Agent เวอร์ชันทดสอบ (minimal):
  1. รับคำสั่ง Start + template จาก Backend ผ่าน POST /command
  2. ต่อ TM-X → R0 → PW,1,<template>
  3. รอพิมพ์เริ่มที่ terminal (แทน trigger จาก Micro) — ตรงจุดนี้เดียวกันคือจุด
     ที่ "arm" FTP receiver ให้พร้อมรับทั้งค่าและรูปจาก TM-X (ดู arm_and_capture)
  4. **ไม่ส่ง GM ถามค่าเองแล้ว** — TM-X เป็นคนส่งค่าที่วัดได้มาเองผ่าน FTP ใน
     รูปไฟล์ .txt ที่มันเขียนต่อท้ายเรื่อยๆ (บรรทัดละ 1 ค่า รูปแบบ
     "+0005.017,+0005.029" คือ value_x,value_y) พร้อมกับรูปที่ส่งมาในคอนเนกชัน
     เดียวกัน — Agent แค่อ่านบรรทัดล่าสุดของไฟล์นั้นตอนที่ได้รูปจริงมาพอดี
     (ดู SingleShotImageHandler.on_file_received) ไม่ต้องยิง GM เองอีกต่อไป
  5. POST ค่าเข้า backend ที่ /api/measurements (format ตาม MeasurementCreate
     ใน main.py: session_id, number_alpl, value_x, value_y, client_uuid)
  6. อัปโหลดรูปที่ได้มาคู่กับค่าต่อให้ backend ผ่าน
     POST /api/measurements/{id}/image-upload (multipart) backend จะเป็นคน
     ตัดสินใจเก็บไฟล์ไว้ที่ ALPL/<วันที่ DD-MM-YYYY พ.ศ.>/ เอง พร้อมแปลงเป็น
     .jpg ให้ด้วย (ดู main.py)
  7. เมื่อจบ session (ครบ target_count หรือโดนสั่ง Stop) เคลียร์ทุกอย่างใน
     Store_image_temporary ทิ้ง (ดู _clear_temp_dir)

รับภาพ+ค่าจาก TM-X ยังไง (ใหม่): Agent รันเป็น FTP server ของตัวเอง (พอร์ต
แยกจาก TCP ที่คุยกับ TM-X) ปกติจะ "ล็อก" ไม่ให้ใครอัปโหลดอะไรเข้ามาได้เลย
จนกว่าจะถึง trigger ของแต่ละชิ้น ถึงจะปลดล็อกให้รับได้ แล้วล็อกกลับทันทีที่ได้
รูปจริง — กัน TM-X ส่งรูปผิดจังหวะ/ผิดชิ้นเข้ามาปนกัน (ดีไซน์เดียวกับที่เคยทำ
ใน ftp.py เวอร์ชันทดสอบเดี่ยวๆ ก่อนหน้านี้ ยกเข้ามารวมในนี้ — ต่างจาก ftp.py
ตรงที่ agent.py นี้ parse ค่า .txt ออกมาเป็น value_x/value_y แบบ float จริงๆ
ไม่ใช่แค่ปริ้นบรรทัดดิบๆ)
"""
import os
import shutil
import socket
import time
import threading
import uuid

import httpx
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI
from pydantic import BaseModel
from pyftpdlib.authorizers import DummyAuthorizer
from pyftpdlib.handlers import FTPHandler
from pyftpdlib.servers import FTPServer

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))

# การตั้งค่า IP และ Port ให้ตรงกับ TM-X (เหมือน tcp.py)
TMX_IP = '192.168.10.11'
TMX_PORT = 8600
BUFFER_SIZE = 1024
# คำสั่ง trigger แบบ active — ส่งผ่าน connection ใหม่แยกต่างหาก (ไม่ใช่ตัวที่
# ค้างไว้ส่ง R0/PW/S0) ไปสั่งให้ TM-X ถ่าย/วัด 1 ครั้งตอนกด Enter แต่ละชิ้น
# (ทดสอบกับฮาร์ดแวร์จริงแล้วว่าใช้งานได้ — ต่างจากที่เคยลองส่ง T1 ผ่าน
# connection เดิมที่ค้าง GM loop อยู่ตอนนั้นซึ่งได้ ER,T1,03 กลับมา)
TRIGGER_COMMAND = "T1\r"
TRIGGER_TIMEOUT = 2.0  # วินาที — รอ response จาก TM-X หลังส่ง trigger
# BACKEND_URL: อ่านจาก .env แล้ว (เดิม hardcode "http://localhost:8000" ตรงๆ
# ใช้ได้แค่ตอน Agent+Backend อยู่เครื่องเดียวกัน) — พอ Agent ย้ายมารันบน
# Raspberry Pi แยกจากเครื่อง PC ที่รัน backend ต้องตั้งเป็น IP ของ PC ใน .env
# แทน (ยังคง fallback เป็นค่าเดิมถ้าไม่ได้ตั้งไว้ ทดสอบเครื่องเดียวได้ปกติ)
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")
HB_INTERVAL = 5  # วินาที — ต้องน้อยกว่า HEARTBEAT_TIMEOUT ของ backend (15s) พอสมควร

# ── รับภาพจาก TM-X ผ่าน FTP (ใหม่) ────────────────────────────────────────────
# TEMP_IMAGE_DIR: โฟลเดอร์พักภาพชั่วคราวบนเครื่อง Agent (Pi) ก่อนอัปโหลดต่อให้
# backend — ตัวแปรเดียวกับที่ระบุไว้ใน CLAUDE.md/.env อยู่แล้ว
TEMP_IMAGE_DIR = os.getenv("TEMP_IMAGE_DIR", "./Store_image_temporary")
# AGENT_FTP_PORT: ตั้งไว้ที่ 2121 ไม่ใช่ 21 (พอร์ตมาตรฐาน FTP) เป็นค่าเริ่มต้น
# เพราะ Linux/Raspberry Pi ต้องรันเป็น root ถึงจะ bind พอร์ต < 1024 ได้ — ถ้า
# TM-X Controller ตั้งค่าไปที่พอร์ต 21 ตรงๆ ไม่ได้ ค่อยตั้ง AGENT_FTP_PORT=21
# ใน .env แล้วรัน agent.py ด้วย sudo แทน
AGENT_FTP_HOST = os.getenv("AGENT_FTP_HOST", "0.0.0.0")
AGENT_FTP_PORT = int(os.getenv("AGENT_FTP_PORT", 2121))
AGENT_FTP_USER = os.getenv("AGENT_FTP_USER", "TMX")
AGENT_FTP_PASS = os.getenv("AGENT_FTP_PASS", "tmx12345")
# เวลารอรูปสูงสุดหลัง trigger ก่อนจะยอมแพ้แล้ววัดต่อโดยไม่มีรูป (วินาที)
IMAGE_WAIT_TIMEOUT = float(os.getenv("AGENT_IMAGE_WAIT_TIMEOUT", 10))

# session ที่กำลังวัดอยู่ตอนนี้ (None = idle) — heartbeat_loop อ่านตัวนี้ไปแนบ
# กับทุก heartbeat เพื่อให้ backend อัปเดต sessions.last_seen ของ session
# ที่ถูกต้อง ไม่งั้น heartbeat_checker ฝั่ง backend จะคิดว่า Agent ตาย (เงียบ
# เกิน 15s) แล้ว mark session เป็น timeout → หน้าเว็บโดน resetTelemetry กลางคัน
current_session_id = None

# สถานะ session ปัจจุบัน — /command action="stop" ตั้ง is_running=False แล้ว
# measurement_flow เช็คก่อนวัดแต่ละชิ้นเพื่อหยุด loop ส่วน _tmx_sock เก็บ
# socket ที่กำลังใช้อยู่ให้ stop handler ยิง S0 ไป TM-X ได้ทันที
is_running = False
_tmx_sock = None

http_app = FastAPI()


# ══════════════════════════════════════════════════════════════════════════
# FTP: รับ "ค่า + รูป" จาก TM-X ได้ "1 คู่ต่อ 1 trigger" เท่านั้น
# ══════════════════════════════════════════════════════════════════════════
# ปกติ user FTP (AGENT_FTP_USER) มีแค่สิทธิ์อ่าน/list (_FTP_LOCKED_PERM) —
# อัปโหลดอะไรเข้ามาไม่ได้เลย โดน 550 Permission denied ตั้งแต่ระดับโปรโตคอล
# จนกว่า arm_and_capture() จะถูกเรียก (ตอน trigger ของแต่ละชิ้น — ดู
# measurement_flow) ซึ่งจะเปิดสิทธิ์เขียนให้ชั่วคราว พอรับไฟล์รูปครบ 1 ใบ
# (on_file_received) จะล็อกสิทธิ์กลับทันที กัน TM-X ส่งรูปถัดไปเข้ามาซ้อน
os.makedirs(TEMP_IMAGE_DIR, exist_ok=True)

_FTP_LOCKED_PERM = "elr"
_FTP_ARMED_PERM = "elradfmw"

_ftp_authorizer = DummyAuthorizer()
_ftp_authorizer.add_user(AGENT_FTP_USER, AGENT_FTP_PASS, TEMP_IMAGE_DIR, perm=_FTP_LOCKED_PERM)

_image_received_event = threading.Event()
_last_received_image_path = None
# path ของไฟล์ .txt ผลวัดล่าสุดที่ TM-X อัปโหลด/ต่อท้ายมา (ก่อนรูป) — TM-X
# เขียนไฟล์นี้ต่อท้ายเรื่อยๆ ตลอด session (ไม่ใช่ไฟล์ใหม่ทุกรอบ) ดังนั้น "ค่า
# ของชิ้นนี้" คือบรรทัดล่าสุดของไฟล์นี้ ณ จังหวะที่ได้รูปจริงมาพอดี (ดู
# on_file_received) — เก็บเป็น global เพราะ txt อาจมาถึงก่อนรูปในคอนเนกชัน
# เดียวกันไม่กี่มิลลิวินาที
_last_txt_path = None
# (value_x, value_y) ที่จับคู่กับรูปล่าสุดที่ arm_and_capture() ได้มา — ไม่ใช่
# ค่าจาก GM อีกต่อไป (ตัด GM ทิ้งทั้งหมดแล้วตามที่ตกลงกันไว้)
_last_result = None

# นามสกุลไฟล์ที่นับว่าเป็น "รูปจริง" ของ measurement — TM-X อัปโหลดไฟล์ .txt
# ผลวัดมาด้วยในคอนเนกชันเดียวกัน (พบจากทดสอบจริง) ซึ่งไม่ใช่รูป เลยต้องกรอง
# ด้วยนามสกุลก่อน ไม่งั้น arm_and_capture() จะคืน path ของไฟล์ .txt แทนรูป
_IMAGE_EXTS = {".bmp", ".jpg", ".jpeg", ".png", ".tif", ".tiff"}


def _parse_measurement_line(line: str):
    """แปลง 1 บรรทัดจากไฟล์ผลวัด (.txt) ของ TM-X เป็น (value_x, value_y)

    รูปแบบจริงที่ TM-X ส่งมา (ดู log ตัวอย่าง): "+0005.017,+0005.029" — คั่น
    ด้วย comma, มีเครื่องหมาย +/- นำหน้าเสมอ, เป็นทศนิยม 3 ตำแหน่งคงที่ —
    float() ของ Python แปลงสตริงที่มี +/- นำหน้าได้ตรงๆ อยู่แล้ว ไม่ต้อง strip
    เครื่องหมายเองเหมือนตอน parse ผลจาก GM (ที่มี placeholder 9999.999 ปนมา
    ด้วย) ไฟล์นี้เป็นค่าที่ TM-X ตัดสินใจแล้วว่า "ใช่" บรรทัดเดียวไม่มี noise
    """
    x_str, y_str = line.strip().split(",")
    return float(x_str), float(y_str)


def _read_last_measurement_line(path: str):
    """อ่านบรรทัดที่ไม่ว่างบรรทัดสุดท้ายของไฟล์ .txt ผลวัด แล้ว parse เป็น
    (value_x, value_y) — คืน None ถ้าอ่าน/parse ไม่สำเร็จ (ไฟล์ยังไม่มี, ยังไม่
    มีบรรทัดไหนเลย, หรือรูปแบบไม่ตรงตามที่คาดไว้)
    """
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            lines = [ln.strip() for ln in f if ln.strip()]
        if not lines:
            return None
        return _parse_measurement_line(lines[-1])
    except Exception as exc:
        print(f"⚠️ อ่านค่าจากไฟล์ผลวัด {path} ไม่สำเร็จ: {exc}")
        return None


class SingleShotImageHandler(FTPHandler):
    """หมายเหตุสำคัญ (พบจากทดสอบกับฮาร์ดแวร์จริง):

    รอบแรก — TM-X ไม่ได้ "เชื่อม 1 ครั้ง อัปโหลด 1 ไฟล์ ตัดสาย" อย่างที่คิดไว้
    ตอนแรก ใน 1 คอนเนกชันเดียวมันทำหลายสเต็ป (อัปโหลด/ต่อท้าย .txt ผลวัดก่อน
    แล้วค่อย CWD/MKD สร้างโฟลเดอร์ใหม่เพื่อเซฟรูปจริงต่อ) ถ้าล็อกสิทธิ์ทันทีที่
    ได้ไฟล์แรกโดยไม่กรองชนิดไฟล์ สเต็ปถัดไปในคอนเนกชันเดียวกันจะพังด้วย "Not
    enough privileges" — เลยกรองด้วยนามสกุลก่อน (ดู _IMAGE_EXTS) ไม่ล็อกตอนได้
    ไฟล์ .txt (แค่จำ path ไว้เป็น _last_txt_path เฉยๆ)

    รอบสอง — TM-X เป็นกล้อง "stream ต่อเนื่อง" ไม่ได้ส่งรูปแค่ 1 ใบต่อ
    trigger แล้วตัดการเชื่อมต่อเองเหมือนที่คิดไว้ ถ้าปล่อยรอ on_disconnect
    เฉยๆ (ไม่ล็อกตอนได้รูป) จะได้รูปรัวๆ ไม่หยุดเป็นสิบๆ ใบต่อวินาทีเพราะ
    คอนเนกชันไม่ตัดสายเอง — เลยต้อง**ล็อกทันทีที่ได้ไฟล์รูปจริงใบแรก** (ไม่ใช่
    รอ disconnect) ส่วน on_disconnect ยังเก็บไว้เป็น safety net เผื่อกรณี
    TM-X ตัดสายไปเองโดยยังไม่ได้ส่งรูปเลย (กันไม่ให้ค้าง ARMED ตลอดไป)

    รอบสาม (ตัด GM ออกแล้ว) — ค่าที่วัดได้ไม่ได้มาจากการยิง GM ถามเองอีกต่อไป
    แต่มาจากไฟล์ .txt ที่ TM-X ส่งมาเอง (ก่อนรูปเสมอในคอนเนกชันเดียวกัน) พอ
    ได้รูปจริงมา ณ จังหวะไหน ให้อ่านบรรทัดล่าสุดของ .txt ล่าสุด ณ จังหวะนั้น
    ทันที ถือว่าเป็นค่าคู่กับรูปนี้ (ทำใน on_file_received ตรงๆ ไม่ต้องรอ
    thread อื่นมา query เพิ่ม กันจังหวะ race ที่ไฟล์ .txt ถูกต่อท้ายอีกครั้ง
    ก่อนจะอ่านทัน)
    """

    def on_file_received(self, file):
        global _last_received_image_path, _last_txt_path, _last_result
        print(f"📥 รับไฟล์จาก TM-X แล้ว: {file}")
        if os.path.splitext(file)[1].lower() in _IMAGE_EXTS:
            _last_received_image_path = file
            _last_result = _read_last_measurement_line(_last_txt_path) if _last_txt_path else None
            if _last_result is None:
                print("⚠️ ได้รูปแล้วแต่ยังไม่มี/อ่านค่าจากไฟล์ผลวัด (.txt) ไม่สำเร็จ")
            _image_received_event.set()
            # ได้รูปจริงแล้ว 1 ใบ ล็อกทันที กัน TM-X stream รูปต่อไปเรื่อยๆ
            self.authorizer.user_table[AGENT_FTP_USER]["perm"] = _FTP_LOCKED_PERM
            print("🔒 ได้รูป+ค่าแล้ว — ล็อกไม่ให้รับไฟล์เพิ่มจนกว่าจะมี trigger รอบถัดไป")
        else:
            # ไฟล์ที่ไม่ใช่รูป (ไฟล์ .txt ผลวัด) — จำ path ไว้เฉยๆ ไม่ล็อก ปล่อย
            # ให้คอนเนกชันเดิมทำสเต็ปที่เหลือ (เช่น CWD/MKD สร้างโฟลเดอร์) ต่อได้
            # จนกว่าจะได้รูปจริงใบแรก
            _last_txt_path = file

    def on_disconnect(self):
        # safety net เฉยๆ — เผื่อ TM-X ตัดสายไปเองโดยไม่ได้ส่งรูปเลย
        self.authorizer.user_table[AGENT_FTP_USER]["perm"] = _FTP_LOCKED_PERM


def _run_ftp_server():
    """รันใน daemon thread แยก — pyftpdlib เป็น synchronous/blocking (serve_forever)"""
    handler = SingleShotImageHandler
    handler.authorizer = _ftp_authorizer
    handler.passive_ports = range(60000, 60100)
    server = FTPServer((AGENT_FTP_HOST, AGENT_FTP_PORT), handler)
    print(f"FTP: กำลังรอรับรูปจาก TM-X ที่ {AGENT_FTP_HOST}:{AGENT_FTP_PORT} (เก็บที่ {TEMP_IMAGE_DIR})")
    server.serve_forever()


def arm_and_capture(timeout=IMAGE_WAIT_TIMEOUT):
    """เปิดรับค่า+รูปจาก TM-X ได้ 1 คู่ (ปลดล็อกสิทธิ์เขียนชั่วคราว) แล้ว block
    รอจนกว่าจะได้รูปจริง (พร้อมค่าที่จับคู่ไว้ให้ในตัว — ดู
    SingleShotImageHandler.on_file_received) หรือหมดเวลา

    คืนค่าเป็น (image_path, value_x, value_y) — image_path เป็น None ได้ถ้า
    หมดเวลาโดยไม่มีรูปเข้ามาเลย (กรณีนี้ value_x/value_y เป็น None ไปด้วยเสมอ
    เพราะตอนนี้ค่าที่วัดมาพร้อมกับรูปเท่านั้น ไม่ได้ยิง GM แยกถามเองอีกต่อไป)
    ผู้เรียก (measurement_flow) ต้องเช็คว่า value_x/value_y เป็น None ไหมก่อน
    เอาไปใช้เสมอ
    """
    global _last_received_image_path, _last_result
    _last_received_image_path = None
    _last_result = None
    _image_received_event.clear()
    _ftp_authorizer.user_table[AGENT_FTP_USER]["perm"] = _FTP_ARMED_PERM
    print(f"🔓 พร้อมรับค่า+รูปจาก TM-X แล้ว (รอสูงสุด {timeout:.0f} วิ)...")
    got = _image_received_event.wait(timeout=timeout)
    if not got:
        _ftp_authorizer.user_table[AGENT_FTP_USER]["perm"] = _FTP_LOCKED_PERM
        print(f"⚠️ ไม่ได้รับค่า/รูปจาก TM-X ภายใน {timeout:.0f} วิ")
        return None, None, None
    value_x, value_y = _last_result if _last_result else (None, None)
    return _last_received_image_path, value_x, value_y


def upload_image_to_backend(measurement_id, image_path):
    """ส่งไฟล์รูปจริง (multipart) ให้ backend เก็บลง ALPL/<วันที่ DD-MM-YYYY พ.ศ.>/
    (backend เป็นคนแปลงเป็น .jpg เองด้วย Pillow — ดู POST
    /api/measurements/{id}/image-upload ใน main.py) ลบไฟล์ temp ทิ้ง
    เสมอไม่ว่าอัปโหลดจะสำเร็จหรือไม่ กัน Store_image_temporary เต็มดิสก์เรื่อยๆ
    """
    try:
        with open(image_path, "rb") as f:
            resp = httpx.post(
                f"{BACKEND_URL}/api/measurements/{measurement_id}/image-upload",
                files={"file": (os.path.basename(image_path), f, "image/jpeg")},
                timeout=30,
            )
        if resp.status_code == 200:
            print(f"🖼 อัปโหลดรูปให้ Backend สำเร็จ (measurement_id={measurement_id})")
        else:
            print(f"⚠️ อัปโหลดรูปไม่สำเร็จ (HTTP {resp.status_code}): {resp.text}")
    except Exception as exc:
        print(f"⚠️ อัปโหลดรูปไม่สำเร็จ: {exc}")
    finally:
        try:
            os.remove(image_path)
        except OSError:
            pass


def _clear_temp_dir():
    """ลบทุกอย่างใน Store_image_temporary ทิ้ง (ไม่ลบตัวโฟลเดอร์เอง) — เรียกทั้ง
    ตอนจบ session ปกติ (ครบ target_count/backend ตอบ complete) และตอนได้รับ
    คำสั่ง Stop จาก Backend (Ball ขอไว้) กันไฟล์ค้าง เช่น รูปที่ arm ไว้แล้ว
    TM-X ส่งมาไม่ทัน timeout, หรืออัปโหลดไป backend ไม่สำเร็จแล้วไม่ได้ถูกลบ
    (upload_image_to_backend ปกติลบไฟล์ทิ้งเองอยู่แล้วทุกครั้งหลังอัปโหลด แต่
    ฟังก์ชันนี้คือ safety net เพิ่มอีกชั้นตอนจบรอบ/หยุด ไม่ให้มีอะไรค้างเลย)

    รีเซ็ต _last_txt_path/_last_result ด้วยเสมอ — เพราะไฟล์ .txt ที่ path เดิม
    ชี้ไปถูกลบไปแล้วจริงๆ (เนื้อหาไฟล์ถูกลบทิ้งข้างบนนี้) ถ้าไม่รีเซ็ต รอบวัด
    ถัดไป (session ใหม่) ที่ยังไม่ทันได้ .txt ไฟล์ใหม่มาเลย แล้วดันได้รูปมาก่อน
    จะไปพยายามอ่าน path เก่าที่ไม่มีอยู่จริงแล้ว
    """
    global _last_txt_path, _last_result
    if os.path.isdir(TEMP_IMAGE_DIR):
        for entry in os.listdir(TEMP_IMAGE_DIR):
            path = os.path.join(TEMP_IMAGE_DIR, entry)
            try:
                if os.path.isdir(path):
                    shutil.rmtree(path)
                else:
                    os.remove(path)
            except OSError as exc:
                print(f"⚠️ เคลียร์ {path} ไม่สำเร็จ: {exc}")
        print(f"🧹 เคลียร์ {TEMP_IMAGE_DIR} เรียบร้อยแล้ว")
    _last_txt_path = None
    _last_result = None


def send_command(sock, command):
    """ส่งคำสั่งไปยัง TM-X และรอรับผลลัพธ์ตอบกลับ (ยกมาจาก tcp.py ตรงๆ)
    ไม่ print คำสั่ง/response แต่ละตัวแล้ว — Ball ขอให้ log แสดงแค่ค่า
    value_x/value_y สุดท้ายที่ถูกเลือกเท่านั้น
    """
    cmd_to_send = command + '\r'  # ต้องต่อท้ายด้วยตัวคั่น CR (\r) เสมอ
    sock.sendall(cmd_to_send.encode('ascii'))
    time.sleep(0.1)  # หน่วงเวลาให้กล้องประมวลผลเล็กน้อย
    response = sock.recv(BUFFER_SIZE).decode('ascii').strip()
    return response


def post_to_backend(session_id, number_alpl, value_x, value_y):
    """POST ค่าเข้า backend — format ตรงตาม MeasurementCreate ใน main.py"""
    resp = httpx.post(
        f"{BACKEND_URL}/api/measurements",
        json={
            "session_id":  session_id,
            "number_alpl": number_alpl,
            "value_x":     value_x,
            "value_y":     value_y,
            "client_uuid": str(uuid.uuid4()),
        },
        timeout=10,
    )
    return resp


def heartbeat_loop():
    """ยิง POST /api/heartbeat ทุก HB_INTERVAL วิ ตลอดเวลาที่ Agent รันอยู่
    (แนบ session_id ปัจจุบันไปด้วยถ้ากำลังวัดอยู่ — backend ใช้ต่ออายุ
    sessions.last_seen กัน heartbeat_checker mark session เป็น timeout)
    รันใน daemon thread แยก จึงไม่กวน measurement_flow และตายไปพร้อม process
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


def measurement_flow(session_id, template_name, number_alpl, target_count):
    """Flow หลัก — รันใน thread แยกเพื่อไม่ block FastAPI server"""
    global current_session_id, is_running, _tmx_sock
    current_session_id = session_id  # heartbeat จะเริ่มแนบ session นี้ทันที
    is_running = True

    print(f"\n✅ ได้รับคำสั่ง Start — template={template_name!r}, จำนวน {target_count} ชิ้น")

    client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client_socket.settimeout(5.0)
    client_socket.connect((TMX_IP, TMX_PORT))
    _tmx_sock = client_socket  # ให้ stop handler ยิง S0 ผ่าน socket นี้ได้

    # Reset (เข้าโหมดดำเนินงาน) — sleep 0.5 ตาม tcp.py ที่ทดสอบผ่านแล้ว
    send_command(client_socket, "R0")
    time.sleep(0.5)

    # Load Program ตาม template ที่ backend ส่งมา (zero-pad เป็น 3 หลัก)
    send_command(client_socket, f"PW,1,{str(template_name).zfill(3)}")
    time.sleep(1.0)

    for piece in range(1, (target_count or 1) + 1):
        if not is_running:
            print("⏹ ได้รับคำสั่ง Stop — หยุดการวัด")
            break

        # วนรอจนกว่าจะได้ทั้งค่าและรูปจริงของชิ้นนี้ — ถ้า arm_and_capture()
        # timeout (ไม่มีอะไรเข้ามาเลย หรือได้รูปแต่อ่านค่าจาก .txt ไม่สำเร็จ)
        # ให้ "ลองใหม่ชิ้นเดิม" ไม่ข้ามไปชิ้นถัดไปเฉยๆ เพราะจะทำให้
        # measured_count ไม่มีทางครบ target_count ได้เลยถ้าข้ามไปเรื่อยๆ
        image_path = value_x = value_y = None
        while is_running:
            # รอสัญญาณว่าชิ้นงานพร้อม (แทน trigger จาก Micro ด้วยการพิมพ์ไปก่อน)
            input(f"\nชิ้นที่ {piece}/{target_count} — พิมพ์เริ่ม: ")

            # เช็คอีกทีหลัง input — เผื่อ Stop มาถึงระหว่างที่กำลังรอพิมพ์อยู่
            # (input() เป็น blocking interrupt กลางคันไม่ได้ ต้องรอกด Enter
            # ก่อน ถึงจะเห็นว่าโดนสั่งหยุดไปแล้ว)
            if not is_running:
                break

            # เปิดรับค่า+รูปจาก TM-X พร้อมกัน ตรงจุด trigger นี้เดียวกัน (block
            # รอจนกว่าจะได้คู่ค่า/รูป หรือหมดเวลา IMAGE_WAIT_TIMEOUT) — ไม่ยิง
            # GM ถามค่าเองแล้ว ค่ามาพร้อมกับรูปจากไฟล์ .txt ของ TM-X เอง (ดู
            # arm_and_capture / SingleShotImageHandler.on_file_received)
            image_path, value_x, value_y = arm_and_capture()
            if value_x is not None and value_y is not None:
                break
            print("⚠️ ยังไม่ได้ค่าที่วัดสำหรับชิ้นนี้ — ลองใหม่อีกครั้ง (พิมพ์เริ่มใหม่)")

        if not is_running:
            print("⏹ ได้รับคำสั่ง Stop — หยุดการวัด")
            break

        print(f"Value X : {value_x}")
        print(f"Value Y : {value_y}")

        resp = post_to_backend(session_id, number_alpl, value_x, value_y)
        data = resp.json()
        print(f"→ ส่งให้ Backend แล้ว (result={data.get('result')}, {data.get('measured')}/{data.get('target')})")

        # มีรูปจากขั้นตอน trigger ด้านบน → อัปโหลดต่อให้ backend เก็บถาวร (ทำ
        # หลัง POST ค่าวัดสำเร็จเท่านั้น เพราะต้องรู้ measurement_id ก่อน)
        if image_path:
            upload_image_to_backend(data["measurement_id"], image_path)

        # backend ตอบ complete = วัดครบ session แล้ว หยุดเลย
        if data.get("status") == "complete":
            break

    # จบการทำงาน — กลับโหมดตั้งค่า แล้วปิด connection (S0 ยิงซ้ำกับตอน stop
    # handler ได้ไม่เป็นไร TM-X รับซ้ำได้)
    try:
        send_command(client_socket, "S0")
        time.sleep(0.5)
    except Exception:
        pass  # socket อาจถูกปิดไปแล้วจาก stop handler
    client_socket.close()
    _tmx_sock = None
    is_running = False
    current_session_id = None  # heartbeat กลับไปยิงแบบ idle (ไม่แนบ session)
    _clear_temp_dir()  # จบ session แล้ว (ครบ target หรือโดน Stop) เคลียร์ temp ให้สะอาด
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
            target=measurement_flow,
            args=(req.session_id, req.template_name, req.number_alpl, req.target_count),
            daemon=True,
        ).start()
    elif req.action == "stop":
        print("\n⏹ ได้รับคำสั่ง Stop จาก Backend")
        is_running = False  # loop ใน measurement_flow จะเห็นแล้วหยุดเอง
        # ยิง S0 ไป TM-X ทันทีเลยถ้ายังต่ออยู่ — ไม่ต้องรอ loop วนมาเช็ค flag
        # (ถ้ากำลังค้างรอ input() อยู่ จะหยุดสนิทตอนกด Enter ครั้งถัดไป)
        if _tmx_sock is not None:
            try:
                send_command(_tmx_sock, "S0")
                print("→ ส่ง S0 ไป TM-X แล้ว")
            except Exception:
                pass
        # เคลียร์ Store_image_temporary ทันทีตอนกด Stop (Ball ขอไว้) — ไม่ต้อง
        # รอให้ measurement_flow วนไปถึงท้าย loop ก่อน (อาจค้างอยู่ที่ input()
        # รอกด Enter ชิ้นถัดไปอีกนาน) measurement_flow จะเคลียร์ซ้ำอีกครั้งตอน
        # จบจริงๆ ก็ได้ ไม่มีปัญหาอะไร (โฟลเดอร์ว่างอยู่แล้ว)
        _clear_temp_dir()
    return {"status": "ok", "action": req.action}


if __name__ == "__main__":
    # heartbeat รันตลอดอายุโปรแกรมใน daemon thread — เริ่มก่อนเปิด server
    threading.Thread(target=heartbeat_loop, daemon=True).start()
    # FTP server (รับภาพจาก TM-X) รันใน daemon thread แยกเหมือนกัน — เริ่มพร้อม
    # โปรแกรม ไม่ต้องรอ Start session ก่อน (แต่ล็อกไม่ให้รับไฟล์อะไรจนกว่าจะ
    # trigger จริง — ดู arm_image_capture)
    threading.Thread(target=_run_ftp_server, daemon=True).start()
    # port ต้องตรงกับ AGENT_PORT ใน main.py ของ backend (default 9998)
    print("Agent (minimal) กำลังรอคำสั่ง Start จาก Backend ที่ port 9998...")
    uvicorn.run(http_app, host="0.0.0.0", port=9998)
