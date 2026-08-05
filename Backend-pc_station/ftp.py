"""
ftp.py — Agent เวอร์ชันใหม่ (active T1 trigger)

ต่างจาก agent.py เดิมตรงที่ตอน trigger แต่ละชิ้น จะ "สั่ง" ให้ TM-X ถ่าย/วัด
ด้วยคำสั่ง T1 ผ่าน TCP connection ใหม่แยกต่างหาก (ไม่ใช่ connection เดิมที่ค้าง
ไว้ส่ง R0/PW/S0) แทนที่จะรอเฉยๆ ให้ TM-X ส่งเข้ามาเอง — Ball ทดสอบกับฮาร์ดแวร์
จริงแล้วว่า T1 ใช้งานได้ถ้าส่งผ่าน connection ใหม่แบบนี้ (ต่างจากที่เคยลองส่ง
T1 ผ่าน connection เดิมที่ค้าง GM loop อยู่ตอนนั้น ซึ่งได้ ER,T1,03 กลับมา)

Flow:
  1. รับคำสั่ง Start + template จาก Backend ผ่าน POST /command
  2. ต่อ TM-X → ส่ง R0 (reset) → โหลดโปรแกรมวัด PW,1,<template>
  3. ต่อ 1 ชิ้นงาน (จนครบ target_count หรือโดนสั่ง Stop):
     - รอพิมพ์เริ่มที่ terminal (แทน trigger จาก MCU จริง)
     - ส่งคำสั่ง T1 ไปสั่ง TM-X ให้ถ่าย/วัดตอนนี้เลย (trigger_sensor)
     - TM-X ส่งค่าที่วัดได้ (ไฟล์ .txt ต่อท้ายเรื่อยๆ) + รูป กลับมาทาง FTP ใน
       คอนเนกชันเดียวกัน — Agent อ่านบรรทัดล่าสุดของ .txt ตอนที่ได้รูปจริงมา
       พอดี ถือเป็นค่าคู่กับรูปนี้ (ไม่ยิง GM ถามเองแล้ว)
  4. POST ค่าเข้า backend ที่ /api/measurements แล้วอัปโหลดรูปต่อที่
     /api/measurements/{id}/image-upload — backend เป็นคนแปลงเป็น .jpg แล้ว
     เก็บลง ALPL_IMAGE_DIR/<วันที่ DD-MM-YYYY พ.ศ.>/ เอง (ดู main.py)
  5. จบ session (ครบ target_count หรือโดนสั่ง Stop) → ส่ง S0 แล้วเคลียร์
     Store_image_temporary ทิ้งทั้งหมด

รับภาพ+ค่าจาก TM-X ยังไง: Agent รันเป็น FTP server ของตัวเอง ให้สิทธิ์เขียน
เต็ม (elradfmw) ตลอดเวลา ไม่มีการล็อก/ปลดล็อกสิทธิ์ระดับโปรโตคอล (กัน TM-X
ขึ้น error บนหน้าจอตัวเองเวลาโดนปฏิเสธ) แต่ใช้ "ธง" (_armed) ในโค้ด Python
แทน — ไฟล์รูปที่เข้ามาตอนไม่ได้ armed (เช่น TM-X ส่งซ้ำ/ผิดจังหวะ) จะถูกลบทิ้ง
เงียบๆ แทนที่จะถูกปฏิเสธที่ระดับ FTP
"""
import os
import shutil
import socket
import threading
import time
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

# ── TM-X (TCP) ────────────────────────────────────────────────────────────
TMX_IP = os.getenv("TMX_HOST", "192.168.10.11")
TMX_PORT = int(os.getenv("TMX_PORT", 8600))
BUFFER_SIZE = 1024
# คำสั่ง trigger แบบ active — ส่งผ่าน connection ใหม่แยกต่างหาก (ไม่ใช่ตัวที่
# ค้างไว้ส่ง R0/PW/S0) ไปสั่งให้ TM-X ถ่าย/วัด 1 ครั้งตอนกด Enter แต่ละชิ้น
TRIGGER_COMMAND = "T1\r"
TRIGGER_TIMEOUT = 2.0  # วินาที — รอ response จาก TM-X หลังส่ง trigger

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")
HB_INTERVAL = 5  # วินาที — ต้องน้อยกว่า HEARTBEAT_TIMEOUT ของ backend (15s) พอสมควร

# ── FTP รับค่า+รูปจาก TM-X ────────────────────────────────────────────────
TEMP_IMAGE_DIR = os.getenv("TEMP_IMAGE_DIR", "./Store_image_temporary")
AGENT_FTP_HOST = os.getenv("AGENT_FTP_HOST", "0.0.0.0")
# port 21 ตรงๆ (ไม่ใช่ 2121) — ทดสอบกับฮาร์ดแวร์จริงแล้วว่า TM-X ต่อเข้าพอร์ตนี้
AGENT_FTP_PORT = int(os.getenv("AGENT_FTP_PORT", 21))
AGENT_FTP_USER = os.getenv("AGENT_FTP_USER", "INTERN_USER")
AGENT_FTP_PASS = os.getenv("AGENT_FTP_PASS", "123456")
# เวลารอค่า+รูปสูงสุดหลัง trigger ก่อนจะถือว่าไม่ได้ (วินาที)
IMAGE_WAIT_TIMEOUT = float(os.getenv("AGENT_IMAGE_WAIT_TIMEOUT", 10))

os.makedirs(TEMP_IMAGE_DIR, exist_ok=True)

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
# FTP: รับ "ค่า + รูป" จาก TM-X ได้ "1 คู่ต่อ 1 trigger"
# ══════════════════════════════════════════════════════════════════════════
# ให้สิทธิ์เขียนเต็ม (elradfmw) กับ user FTP ตลอดเวลา ไม่มีการล็อก/ปลดล็อก
# สิทธิ์ระดับโปรโตคอลแบบ agent.py เดิม (ที่ทำให้ TM-X ขึ้น error บนหน้าจอ
# ตัวเองเวลาโดนปฏิเสธ 550) — ใช้ธง _armed ในโค้ด Python แทน ไฟล์ที่เข้ามาตอน
# ไม่ armed จะถูกลบทิ้งเงียบๆ
_ftp_authorizer = DummyAuthorizer()
_ftp_authorizer.add_user(AGENT_FTP_USER, AGENT_FTP_PASS, TEMP_IMAGE_DIR, perm="elradfmw")

_armed = False
_image_received_event = threading.Event()
_last_received_image_path = None
# path ของไฟล์ .txt ผลวัดล่าสุดที่ TM-X อัปโหลด/ต่อท้ายมา (ก่อนรูป) — TM-X
# เขียนไฟล์นี้ต่อท้ายเรื่อยๆ ตลอด session (ไม่ใช่ไฟล์ใหม่ทุกรอบ) ดังนั้น "ค่า
# ของชิ้นนี้" คือบรรทัดล่าสุดของไฟล์นี้ ณ จังหวะที่ได้รูปจริงมาพอดี
_last_txt_path = None
# (value_x, value_y) ที่จับคู่กับรูปล่าสุดที่ arm_and_capture() ได้มา
_last_result = None

# นามสกุลไฟล์ที่นับว่าเป็น "รูปจริง" ของ measurement — TM-X อัปโหลดไฟล์ .txt
# ผลวัดมาด้วยในคอนเนกชันเดียวกัน ซึ่งไม่ใช่รูป เลยต้องกรองด้วยนามสกุลก่อน
_IMAGE_EXTS = {".bmp", ".jpg", ".jpeg", ".png", ".tif", ".tiff"}


def _parse_measurement_line(line: str):
    """แปลง 1 บรรทัดจากไฟล์ผลวัด (.txt) ของ TM-X เป็น (value_x, value_y)

    รูปแบบจริงที่ TM-X ส่งมา: "+0005.017,+0005.029" — คั่นด้วย comma มี
    เครื่องหมาย +/- นำหน้าเสมอ — float() ของ Python แปลงตรงๆ ได้อยู่แล้ว
    """
    x_str, y_str = line.strip().split(",")
    return float(x_str), float(y_str)


def _read_last_measurement_line(path: str):
    """อ่านบรรทัดที่ไม่ว่างบรรทัดสุดท้ายของไฟล์ .txt ผลวัด แล้ว parse เป็น
    (value_x, value_y) — คืน None ถ้าอ่าน/parse ไม่สำเร็จ
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


class SingleShotFTPHandler(FTPHandler):
    """หมายเหตุสำคัญ (สืบทอดมาจากการทดสอบฮาร์ดแวร์จริงรอบก่อนๆ):

    TM-X ทำหลายสเต็ปใน 1 คอนเนกชันเดียว (อัปโหลด/ต่อท้าย .txt ผลวัดก่อน แล้ว
    ค่อยส่งรูปจริงตามมา) — จำ path ของ .txt ไว้เฉยๆ ไม่ทำอะไรพิเศษ พอได้รูป
    จริง (นามสกุลอยู่ใน _IMAGE_EXTS) ถ้า armed อยู่ → อ่านค่าล่าสุดจาก .txt
    คู่กับรูปนี้เลย แล้วปิด armed ทันที (กันรับซ้ำ) — ถ้าไม่ได้ armed (ไฟล์เข้า
    มาผิดจังหวะ) ลบทิ้งเงียบๆ ไม่ให้ค้างใน Store_image_temporary
    """

    def on_file_received(self, file):
        global _last_received_image_path, _last_txt_path, _last_result, _armed
        if os.path.splitext(file)[1].lower() in _IMAGE_EXTS:
            if _armed:
                _last_received_image_path = file
                _last_result = _read_last_measurement_line(_last_txt_path) if _last_txt_path else None
                _armed = False
                _image_received_event.set()
                print(f"📸 ได้รูป+ค่าแล้ว: {file} (ค่า={_last_result})")
            else:
                # รูปเข้ามาตอนไม่ได้ armed (เช่น TM-X ส่งซ้ำ/ผิดจังหวะ) — ลบทิ้ง
                # เงียบๆ กัน Store_image_temporary รก ไม่ต้องรอ trigger รอบหน้า
                try:
                    os.remove(file)
                except OSError:
                    pass
        else:
            # ไฟล์ที่ไม่ใช่รูป (ไฟล์ .txt ผลวัด) — จำ path ไว้เฉยๆ
            _last_txt_path = file

    def on_disconnect(self):
        global _armed
        # safety net เฉยๆ — เผื่อ TM-X ตัดสายไปเองโดยยังไม่ได้ส่งรูปเลย
        _armed = False


def _run_ftp_server():
    """รันใน daemon thread แยก — pyftpdlib เป็น synchronous/blocking (serve_forever)"""
    handler = SingleShotFTPHandler
    handler.authorizer = _ftp_authorizer
    handler.passive_ports = range(60000, 60100)
    server = FTPServer((AGENT_FTP_HOST, AGENT_FTP_PORT), handler)
    print(f"FTP: กำลังรอรับค่า+รูปจาก TM-X ที่ {AGENT_FTP_HOST}:{AGENT_FTP_PORT} (เก็บที่ {TEMP_IMAGE_DIR})")
    server.serve_forever()


def trigger_sensor(timeout=TRIGGER_TIMEOUT):
    """ส่งคำสั่ง T1 ไปสั่งให้ TM-X ถ่าย/วัด 1 ครั้ง ผ่าน connection ใหม่แยก
    ต่างหาก (ไม่ใช่ connection เดิมที่เปิดค้างไว้ส่ง R0/PW/S0) — ทดสอบกับ
    ฮาร์ดแวร์จริงแล้วว่าใช้งานได้จริงด้วยวิธีนี้ คืน True/False ว่าส่งคำสั่ง
    สำเร็จไหม (แค่ส่งสำเร็จ ไม่ได้การันตีว่า TM-X ถ่ายจริง — ต้องรอดูที่
    arm_and_capture ว่าได้ค่า+รูปกลับมาไหมอีกที)
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


def arm_and_capture(timeout=IMAGE_WAIT_TIMEOUT):
    """เปิดรับค่า+รูปจาก TM-X ได้ 1 คู่ (ตั้งธง _armed) แล้วสั่ง T1 ทันที จาก
    นั้น block รอจนกว่าจะได้รูปจริง (พร้อมค่าที่จับคู่ไว้ให้ในตัว — ดู
    SingleShotFTPHandler.on_file_received) หรือหมดเวลา

    คืนค่าเป็น (image_path, value_x, value_y) — เป็น (None, None, None) ถ้า
    หมดเวลาโดยไม่ได้อะไรเลย หรือได้รูปแต่อ่านค่าจาก .txt ไม่สำเร็จ
    """
    global _last_received_image_path, _last_result, _armed
    _last_received_image_path = None
    _last_result = None
    _image_received_event.clear()
    _armed = True
    print(f"🔓 พร้อมรับค่า+รูปจาก TM-X แล้ว (รอสูงสุด {timeout:.0f} วิ)...")
    trigger_sensor()
    got = _image_received_event.wait(timeout=timeout)
    _armed = False
    if not got:
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
    คำสั่ง Stop จาก Backend กันไฟล์ค้าง เช่น รูปที่ arm ไว้แล้ว TM-X ส่งมาไม่
    ทัน timeout, หรืออัปโหลดไป backend ไม่สำเร็จแล้วไม่ได้ถูกลบ

    รีเซ็ต _last_txt_path/_last_result ด้วยเสมอ — เพราะไฟล์ .txt ที่ path เดิม
    ชี้ไปถูกลบไปแล้วจริงๆ ถ้าไม่รีเซ็ต รอบวัดถัดไป (session ใหม่) ที่ยังไม่ทัน
    ได้ .txt ไฟล์ใหม่มาเลย แล้วดันได้รูปมาก่อน จะไปพยายามอ่าน path เก่าที่ไม่มี
    อยู่จริงแล้ว
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
    """ส่งคำสั่งไปยัง TM-X และรอรับผลลัพธ์ตอบกลับ — ใช้กับ connection หลักที่
    เปิดค้างไว้ตลอด session (R0/PW/S0 เท่านั้น ไม่ใช้กับ T1 อีกต่อไป — T1 ส่ง
    ผ่าน trigger_sensor() ด้วย connection ใหม่แยกต่างหากเสมอ)
    """
    cmd_to_send = command + "\r"  # ต้องต่อท้ายด้วยตัวคั่น CR (\r) เสมอ
    sock.sendall(cmd_to_send.encode("ascii"))
    time.sleep(0.1)  # หน่วงเวลาให้กล้องประมวลผลเล็กน้อย
    response = sock.recv(BUFFER_SIZE).decode("ascii").strip()
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

    # Reset (เข้าโหมดดำเนินงาน)
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
        # timeout ให้ "ลองใหม่ชิ้นเดิม" ไม่ข้ามไปชิ้นถัดไปเฉยๆ เพราะจะทำให้
        # measured_count ไม่มีทางครบ target_count ได้เลยถ้าข้ามไปเรื่อยๆ
        image_path = value_x = value_y = None
        while is_running:
            # รอสัญญาณว่าชิ้นงานพร้อม (แทน trigger จาก Micro ด้วยการพิมพ์ไปก่อน)
            input(f"\nชิ้นที่ {piece}/{target_count} — พิมพ์เริ่ม: ")

            # เช็คอีกทีหลัง input — เผื่อ Stop มาถึงระหว่างที่กำลังรอพิมพ์อยู่
            if not is_running:
                break

            # ส่ง T1 สั่งให้ TM-X ถ่าย/วัดตอนนี้เลย แล้วรอค่า+รูปกลับมาทาง FTP
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
        if _tmx_sock is not None:
            try:
                send_command(_tmx_sock, "S0")
                print("→ ส่ง S0 ไป TM-X แล้ว")
            except Exception:
                pass
        # เคลียร์ Store_image_temporary ทันทีตอนกด Stop — ไม่ต้องรอให้
        # measurement_flow วนไปถึงท้าย loop ก่อน (อาจค้างอยู่ที่ input() รอกด
        # Enter ชิ้นถัดไปอีกนาน) measurement_flow จะเคลียร์ซ้ำอีกครั้งตอนจบ
        # จริงๆ ก็ได้ ไม่มีปัญหาอะไร (โฟลเดอร์ว่างอยู่แล้ว)
        _clear_temp_dir()
    return {"status": "ok", "action": req.action}


if __name__ == "__main__":
    # heartbeat รันตลอดอายุโปรแกรมใน daemon thread — เริ่มก่อนเปิด server
    threading.Thread(target=heartbeat_loop, daemon=True).start()
    # FTP server (รับค่า+รูปจาก TM-X) รันใน daemon thread แยกเหมือนกัน — เริ่ม
    # พร้อมโปรแกรม ไม่ต้องรอ Start session ก่อน
    threading.Thread(target=_run_ftp_server, daemon=True).start()
    # port ต้องตรงกับ AGENT_PORT ใน main.py ของ backend (default 9998)
    print("Agent (ftp.py) กำลังรอคำสั่ง Start จาก Backend ที่ port 9998...")
    uvicorn.run(http_app, host="0.0.0.0", port=9998)