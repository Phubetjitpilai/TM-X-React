"""
Recieve_tm-x.py — รันบน PC (เครื่องเดียวกับ Backend)

TM-X ถูกตั้งค่าให้ส่งค่าที่วัดได้ (.txt) + รูป **ตรงมาที่ PC ผ่าน FTP** (ไม่ผ่าน
Pi — Pi มีหน้าที่แค่รับคำสั่ง Start/Stop จาก Backend แล้วสั่ง TM-X ผ่าน TCP
ดู send_command.py) สคริปต์นี้จึงมีหน้าที่แค่รับของ จับคู่ค่า+รูป แล้วส่งต่อ

── โครงสร้างจริงที่ TM-X ส่งมา (ยืนยันจากฮาร์ดแวร์จริงแล้ว) ──────────────────

  Store_image_temporary/
  ├── 260731/                                              ← YYMMDD
  │   ├── 260731_172842_0000000008_capture-image_OK.bmp     ← 2.3 MB ข้าม
  │   └── HEAD-A/
  │       └── 260731_172842_0000000008_HEAD-A_OK.bmp        ← 4.2 MB ★ ใช้ตัวนี้
  └── tm-x/result/SD1_021/                                 ← SD1_021 = ชื่อโปรแกรมวัด
      └── 260731_172518.txt                                ← 1 ไฟล์ต่อ session

**1 ครั้งที่ trigger ได้รูป 2 ใบ** — ใบที่อยู่ในโฟลเดอร์ HEAD-A เท่านั้นที่นับ
เป็นรูปของ measurement (ถ้านับทั้งคู่จะกลายเป็น 2 ชิ้นต่อการวัด 1 ครั้ง)

**ลำดับที่ TM-X ส่งของมา**: HEAD-A → .txt → capture-image
รูปที่เราใช้จึงมาถึง "ก่อน" ไฟล์ค่าเสมอ — ต้องรอไฟล์ .txt ตามมา ห้ามอ่านทันที

── รูปแบบข้อมูลในไฟล์ .txt ─────────────────────────────────────────────────

  +0005.047,+0005.045,+0000.003,26,07,31,17,28,42
  └─ x ──┘ └─ y ──┘ └─ z ──┘ └YY┘└MM┘└DD┘└HH┘└MM┘└SS┘

  - คั่นด้วย comma 9 ช่อง เอาแค่ 2 ช่องแรกเป็น value_x / value_y
  - ช่องที่ 3 (z) ยังไม่ได้ใช้กับอะไร เก็บไว้เผื่ออนาคต
  - 6 ช่องท้ายคือเวลาที่วัด — **ตรงกับเวลาในชื่อไฟล์รูปเป๊ะ** จึงใช้จับคู่
    "รูปใบนี้คู่กับค่าบรรทัดไหน" ได้แม่นกว่าการเดาจากลำดับที่ไฟล์มาถึง
  - ขึ้นบรรทัดใหม่ด้วย CR (\\r) ตัวเดียว ไม่ใช่ CRLF (Python อ่านได้อยู่แล้ว
    ด้วย universal newlines)
  - **-9999.999 = TM-X วัดไม่ติด** ต้องข้ามไป ไม่บันทึกลง DB

── flow ──────────────────────────────────────────────────────────────────

  1. เปิด FTP server รอรับค่า+รูปจาก TM-X
  2. ได้ไฟล์ .txt → จำ path ไว้เฉยๆ
  3. ได้รูป (ในโฟลเดอร์ HEAD-A) → แกะเวลาจากชื่อไฟล์ → หาบรรทัดใน .txt ที่
     เวลาตรงกัน (รอได้สูงสุด TXT_WAIT_TIMEOUT วิ เพราะรูปมาก่อน .txt)
  4. ถ้าค่าเป็น -9999.999 → ข้าม
  5. ถาม Backend ว่ามี session ไหน running อยู่ (GET /api/session/state)
     ถ้าไม่มีก็ทิ้งค่า+รูปนั้นไป (กันแปะผิด session ตอน TM-X ส่งมาช้าหลังจบ)
  6. POST ค่าเข้า /api/measurements แล้วอัปโหลดรูปต่อที่
     /api/measurements/{id}/image-upload — Backend เป็นคนแปลงเป็น .jpg แล้ว
     เก็บลง ALPL_IMAGE_DIR/<วันที่ DD-MM-YYYY พ.ศ.>/ เอง (ดู main.py)
"""
import os
import re
import shutil
import threading
import time

import httpx
from dotenv import load_dotenv
from pyftpdlib.authorizers import DummyAuthorizer
from pyftpdlib.handlers import FTPHandler
from pyftpdlib.servers import FTPServer
import uuid

# รากโปรเจกต์ = โฟลเดอร์แม่ของ Backend-pc_station/ (ที่ .env กับ Store_image_temporary อยู่)
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

load_dotenv(dotenv_path=os.path.join(PROJECT_ROOT, ".env"))

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")

# ── โหมดการทำงาน ────────────────────────────────────────────────────────────
# FORWARD_TO_BACKEND=0 → "โหมดรับอย่างเดียว" รับไฟล์จาก TM-X มากองไว้ใน
#   TEMP_IMAGE_DIR เฉยๆ ไม่ยิงอะไรเข้า Backend และ **ไม่ลบไฟล์ทิ้ง** ใช้ตอน
#   เทสต์กับ TM-X ครั้งแรกเพื่อดูว่ามันส่งอะไรมาบ้าง ชื่อไฟล์หน้าตายังไง
# FORWARD_TO_BACKEND=1 → โหมดใช้งานจริง (จับคู่ค่า+รูป → POST เข้า Backend → ลบ temp)
FORWARD_TO_BACKEND = os.getenv("FORWARD_TO_BACKEND", "0").strip().lower() in ("1", "true", "yes", "on")

# ── FTP รับค่า+รูปจาก TM-X (ตอนนี้รันบน PC แทน Pi) ──────────────────────────
# ⚠ ต้องแปลงเป็น absolute path เทียบกับรากโปรเจกต์เสมอ — ค่าใน .env เป็น
#   "./Store_image_temporary" ซึ่งถ้าปล่อยไว้จะอิงกับโฟลเดอร์ที่รันคำสั่ง
#   พอสั่ง `cd Backend-pc_station` ก่อนรัน ไฟล์จะไปลงที่
#   Backend-pc_station/Store_image_temporary แทนที่จะเป็นของโปรเจกต์
TEMP_IMAGE_DIR = os.getenv("TEMP_IMAGE_DIR", "./Store_image_temporary")
if not os.path.isabs(TEMP_IMAGE_DIR):
    TEMP_IMAGE_DIR = os.path.abspath(os.path.join(PROJECT_ROOT, TEMP_IMAGE_DIR))

AGENT_FTP_HOST = os.getenv("AGENT_FTP_HOST", "0.0.0.0")
AGENT_FTP_PORT = int(os.getenv("AGENT_FTP_PORT", 21))
AGENT_FTP_USER = os.getenv("AGENT_FTP_USER", "INTERN_USER")
AGENT_FTP_PASS = os.getenv("AGENT_FTP_PASS", "123456")

os.makedirs(TEMP_IMAGE_DIR, exist_ok=True)

_ftp_authorizer = DummyAuthorizer()
_ftp_authorizer.add_user(AGENT_FTP_USER, AGENT_FTP_PASS, TEMP_IMAGE_DIR, perm="elradfmw")

# นามสกุลไฟล์ที่นับว่าเป็นรูป — TM-X ส่งไฟล์ .txt ผลวัดมาด้วย ต้องแยกให้ออก
_IMAGE_EXTS = {".bmp", ".jpg", ".jpeg", ".png", ".tif", ".tiff"}

# ── รูปใบไหนคือ "รูปของ measurement" ────────────────────────────────────────
# TM-X ส่งรูปมา 2 ใบต่อการวัด 1 ครั้ง:
#   260731/HEAD-A/260731_172842_..._HEAD-A_OK.bmp        4.2 MB  ★ ใช้ใบนี้
#   260731/260731_172842_..._capture-image_OK.bmp        2.3 MB     ข้าม
# ต้องเลือกเก็บใบเดียว ไม่งั้นวัด 1 ครั้งจะกลายเป็นบันทึก 2 ชิ้น
#
# ⚠ ลำดับที่ TM-X ส่งของมา (ยืนยันจากล็อกจริง): HEAD-A → .txt → capture-image
#   แปลว่ารูปที่เราใช้ "มาถึงก่อน" ไฟล์ค่าเสมอ — ต้องพึ่ง _find_measurement_for_image
#   ที่รอไฟล์ .txt ได้ถึง TXT_WAIT_TIMEOUT วินาที ห้ามเปลี่ยนเป็นอ่านทันทีเด็ดขาด
_IMAGE_DIR_NAME = "head-a"

# ค่าที่ TM-X ส่งมาเมื่อ "วัดไม่ติด" — ห้ามบันทึกลง DB
_ERROR_VALUE_THRESHOLD = -9000.0

# เวลาที่ยอมรอไฟล์ .txt หลังได้รูปมาแล้ว (วินาที) — ปกติ .txt มาก่อนรูป แต่
# ไม่รับประกันลำดับ จึงเผื่อไว้แทนที่จะทิ้งรูปทันที
TXT_WAIT_TIMEOUT = 5.0

# ความถี่ที่เธรด session_watcher ถามสถานะ session (วินาที) — ไม่ต้องถี่ เพราะ
# หน้าที่มันคือ "รู้ว่าจบแล้วช้าไม่กี่วินาที" ไม่ใช่งาน realtime
SESSION_POLL_INTERVAL = 3.0

# ชื่อไฟล์รูปของ TM-X: 260731_172842_0000000008_capture-image_OK.bmp
#                      └YYMMDD┘ └HHMMSS┘
_IMG_TS_RE = re.compile(r"^(\d{6})_(\d{6})_")

# path ของไฟล์ .txt ที่ได้รับมาแล้ว (ใหม่สุดอยู่ท้ายลิสต์) — TM-X สร้างไฟล์ใหม่
# ทุก session แล้วต่อท้ายทีละบรรทัดต่อการวัด 1 ครั้ง
_txt_paths = []
_txt_lock = threading.Lock()

# ── ตัวนับงานที่กำลังประมวลผลอยู่ ──────────────────────────────────────────
# นับตั้งแต่ "ได้รูปมา" จนถึง "อัปโหลดเสร็จ/ทิ้งไปแล้ว" — clear_temp_dir ต้องรอ
# จนตัวนับเป็น 0 ก่อนลบเสมอ
#
# ทำไมจำเป็น: backend สั่ง state='stopped' ทันทีที่ measured_count ครบ target
# ซึ่งเกิด "ระหว่าง" ที่ _handle_capture ยังอัปโหลดรูปชิ้นสุดท้ายไม่เสร็จ
#   POST /api/measurements  → measured 4/4 → backend ปิด session ทันที
#   upload รูป 4 MB ...        ← session_watcher ตื่นมาเห็น stopped แล้วลบไฟล์กลางคัน
# ผลคือชิ้นสุดท้ายของทุก session เสี่ยงไม่มีรูป แบบสุ่มๆ หาสาเหตุยากมาก
_jobs_in_flight = 0
_jobs_lock = threading.Lock()


def _job_begin():
    global _jobs_in_flight
    with _jobs_lock:
        _jobs_in_flight += 1


def _job_end():
    global _jobs_in_flight
    with _jobs_lock:
        _jobs_in_flight -= 1


def _jobs_count():
    with _jobs_lock:
        return _jobs_in_flight


def _is_error_value(v: float) -> bool:
    """ค่าที่ TM-X ส่งมาตอนวัดไม่ติดคือ -9999.999 ทั้งสามช่อง"""
    return v <= _ERROR_VALUE_THRESHOLD


def _parse_measurement_line(line: str):
    """แปลง 1 บรรทัดของไฟล์ผลวัด (.txt) → (value_x, value_y, ts_key)

    รูปแบบจริง 9 ช่อง: "+0005.047,+0005.045,+0000.003,26,07,31,17,28,42"
    เอาแค่ 2 ช่องแรก ส่วน 6 ช่องท้ายประกอบเป็น ts_key "260731_172842" ไว้
    จับคู่กับชื่อไฟล์รูป — คืน None ถ้ารูปแบบไม่ตรง (ไม่ throw เพราะไฟล์อาจมี
    บรรทัดหัว/ท้ายแปลกๆ ปนมา ไม่ควรทำให้ทั้งไฟล์ใช้ไม่ได้)
    """
    parts = [p.strip() for p in line.strip().split(",")]
    if len(parts) < 2:
        return None
    try:
        value_x = float(parts[0])
        value_y = float(parts[1])
    except ValueError:
        return None

    ts_key = None
    if len(parts) >= 9:
        try:
            yy, mm, dd, hh, mi, ss = (int(p) for p in parts[3:9])
            ts_key = f"{yy:02d}{mm:02d}{dd:02d}_{hh:02d}{mi:02d}{ss:02d}"
        except ValueError:
            pass
    return value_x, value_y, ts_key


def _read_lines(path: str):
    """อ่านทุกบรรทัดที่ไม่ว่างของไฟล์ .txt — TM-X ขึ้นบรรทัดด้วย CR ตัวเดียว
    ซึ่ง Python จัดการให้แล้วด้วย universal newlines (ไม่ต้องแปลงเอง)
    """
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return [ln.strip() for ln in f if ln.strip()]
    except OSError:
        return []


def _image_ts_key(image_path: str):
    """แกะ "260731_172842" ออกจากชื่อไฟล์รูป — คืน None ถ้าชื่อไม่ตรงรูปแบบ"""
    m = _IMG_TS_RE.match(os.path.basename(image_path))
    return f"{m.group(1)}_{m.group(2)}" if m else None


def _find_measurement_for_image(ts_key: str, timeout: float = TXT_WAIT_TIMEOUT):
    """หาบรรทัดใน .txt ที่เวลาตรงกับรูปใบนี้ — ไล่จากไฟล์ที่ได้รับล่าสุดก่อน

    ถ้ายังไม่เจอจะวนรอจนครบ timeout (เผื่อกรณี .txt มาถึงช้ากว่ารูป) คืน
    (value_x, value_y) หรือ None ถ้าหมดเวลาแล้วยังไม่เจอ
    """
    deadline = time.time() + timeout
    while True:
        with _txt_lock:
            paths = list(reversed(_txt_paths))
        for path in paths:
            for line in _read_lines(path):
                parsed = _parse_measurement_line(line)
                if parsed and parsed[2] == ts_key:
                    return parsed[0], parsed[1]
        if time.time() >= deadline:
            return None
        time.sleep(0.3)


def _fallback_last_line():
    """แผนสำรองตอนแกะเวลาจากชื่อไฟล์รูปไม่ได้ — ใช้บรรทัดล่าสุดของ .txt ที่
    ได้รับล่าสุด (วิธีเดิมก่อนรู้ว่าชื่อไฟล์มีเวลาให้จับคู่)
    """
    with _txt_lock:
        path = _txt_paths[-1] if _txt_paths else None
    if not path:
        return None
    lines = _read_lines(path)
    if not lines:
        return None
    parsed = _parse_measurement_line(lines[-1])
    return (parsed[0], parsed[1]) if parsed else None


def get_current_session():
    """ถาม Backend ว่าตอนนี้มี session ไหน 'running' อยู่ไหม — คืน
    (session_id, number_alpl) หรือ (None, None) ถ้าไม่มี (เช่นค่า/รูปมาถึงช้า
    เกินไปหลัง session จบไปแล้ว) ผู้เรียกต้องเช็ค None ก่อนใช้เสมอ
    """
    try:
        resp = httpx.get(f"{BACKEND_URL}/api/session/state", timeout=5)
        data = resp.json()
        if data.get("state") == "running":
            return data.get("session_id"), data.get("number_alpl")
    except Exception as exc:
        print(f"⚠️ query /api/session/state ไม่สำเร็จ: {exc}")
    return None, None


def post_to_backend(session_id, number_alpl, value_x, value_y):
    """POST ค่าเข้า backend — format ตรงตาม MeasurementCreate ใน main.py
    (number_alpl ตรงนี้ไม่จำเป็นต้องตรงเป๊ะ — session แบบคิว IPM/New/Rework
    ฝั่ง main.py จะเพิกเฉยค่านี้แล้วใช้ตำแหน่งปัจจุบันในคิวของตัวเองแทนอยู่แล้ว)
    """
    return httpx.post(
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


def upload_image_to_backend(measurement_id, image_path):
    """ส่งไฟล์รูป (multipart) ให้ backend เก็บลง ALPL_IMAGE_DIR/<วันที่ พ.ศ.>/
    (backend เป็นคนแปลงเป็น .jpg เองด้วย Pillow — ดู POST
    /api/measurements/{id}/image-upload ใน main.py) ลบไฟล์ temp ทิ้งเสมอไม่ว่า
    อัปโหลดจะสำเร็จหรือไม่ กัน Store_image_temporary บวมเรื่อยๆ
    """
    try:
        with open(image_path, "rb") as f:
            resp = httpx.post(
                f"{BACKEND_URL}/api/measurements/{measurement_id}/image-upload",
                files={"file": (os.path.basename(image_path), f, "image/bmp")},
                timeout=60,
            )
        if resp.status_code == 200:
            print(f"   🖼 อัปโหลดรูปสำเร็จ (measurement_id={measurement_id})")
        else:
            print(f"   ⚠️ อัปโหลดรูปไม่สำเร็จ (HTTP {resp.status_code}): {resp.text[:200]}")
    except Exception as exc:
        print(f"   ⚠️ อัปโหลดรูปไม่สำเร็จ: {exc}")
    finally:
        _remove_quietly(image_path)


def _remove_quietly(path):
    try:
        os.remove(path)
    except OSError:
        pass


def clear_temp_dir(wait_timeout: float = 30.0):
    """ล้างทุกอย่างใน TEMP_IMAGE_DIR แต่เก็บตัวโฟลเดอร์ไว้

    รอจนไม่มีงานค้างก่อนเสมอ (ดู _jobs_in_flight) — กันลบรูปที่กำลังอัปโหลดอยู่
    30 วินาทีเผื่อไว้เหลือเฟือ ของจริงอัปโหลด 4 MB ในเครื่องเดียวกันใช้ ~1 วิ

    TM-X สร้างโฟลเดอร์ย่อยเองเรื่อยๆ (260731/, 260731/HEAD-A/, tm-x/result/<โปรแกรม>/)
    จึงต้องลบทั้ง tree ไม่ใช่แค่ไฟล์ชั้นบนสุด — ตัวโฟลเดอร์แม่ต้องคงอยู่เพราะ
    FTP server ผูก home directory ของ user ไว้กับ path นี้ตั้งแต่ตอน start
    ถ้าลบทิ้งทั้งอันแล้ว TM-X ล็อกอินเข้ามาใหม่จะเจอ error

    ⚠ ยึด TEMP_IMAGE_DIR เป็น absolute path ที่ resolve แล้วเสมอ ไม่รับ path
      จากที่อื่นมาลบ — พลาดตรงนี้ทีเดียวคือลบผิดโฟลเดอร์บนเครื่องจริง
    """
    # ── รอให้งานที่ค้างอยู่เสร็จก่อน ────────────────────────────────────
    deadline = time.time() + wait_timeout
    if _jobs_count() > 0:
        print(f"⏳ รองาน {_jobs_count()} รายการที่ค้างอยู่ให้เสร็จก่อนล้าง...")
    while _jobs_count() > 0 and time.time() < deadline:
        time.sleep(0.3)
    if _jobs_count() > 0:
        print(f"⚠️ ยังมีงานค้าง {_jobs_count()} รายการหลังรอ {wait_timeout:.0f} วิ — ล้างต่อไป")

    removed_files = removed_dirs = 0
    for name in os.listdir(TEMP_IMAGE_DIR):
        path = os.path.join(TEMP_IMAGE_DIR, name)
        try:
            if os.path.isdir(path):
                shutil.rmtree(path); removed_dirs += 1
            else:
                os.remove(path);     removed_files += 1
        except OSError as exc:
            print(f"⚠️ ลบ {name} ไม่สำเร็จ: {exc}")

    with _txt_lock:
        _txt_paths.clear()   # path ที่จำไว้ชี้ไปยังไฟล์ที่ไม่มีแล้ว

    if removed_files or removed_dirs:
        print(f"🧹 ล้าง {os.path.basename(TEMP_IMAGE_DIR)} แล้ว "
              f"(ไฟล์ {removed_files} · โฟลเดอร์ {removed_dirs})")


def session_watcher():
    """เฝ้าดูสถานะ session แล้วล้างโฟลเดอร์พักไฟล์ทันทีที่ session จบ

    ทำไมต้องมีเธรดนี้: สคริปต์นี้ไม่มีแนวคิด session ของตัวเอง มันรู้จัก session
    เฉพาะตอนที่ "ได้รูปมาแล้วไปถาม Backend" เท่านั้น — ซึ่งจังหวะจบ session ไม่มี
    ไฟล์อะไรส่งมาให้เลย ถ้าไม่เฝ้าดูเอง จะไม่มีวันรู้ว่าจบแล้ว

    จับ 2 กรณีที่ถือว่า "จบรอบ":
      - session ที่เคย running อยู่ เปลี่ยนเป็นสถานะอื่น (stopped/timeout/complete)
      - session_id เปลี่ยนไปเป็นตัวใหม่ (เริ่มรอบใหม่ทั้งที่ยังไม่ทันล้างของเก่า)
    """
    last_running_sid = None
    while True:
        time.sleep(SESSION_POLL_INTERVAL)
        try:
            data = httpx.get(f"{BACKEND_URL}/api/session/state", timeout=5).json()
        except Exception:
            continue  # backend ล่มชั่วคราว รอบหน้าค่อยเช็คใหม่ ไม่ต้องล้างอะไร

        sid     = data.get("session_id")
        running = data.get("state") == "running"

        if running:
            if last_running_sid is not None and sid != last_running_sid:
                print(f"\n🔄 session เปลี่ยนจาก {last_running_sid} → {sid}")
                clear_temp_dir()
            last_running_sid = sid
        elif last_running_sid is not None:
            print(f"\n🏁 session {last_running_sid} จบแล้ว (state={data.get('state')})")
            clear_temp_dir()
            last_running_sid = None


def _handle_capture(image_path, t_recv=None):
    """รันในเธรดแยกทุกครั้งที่ได้รูปที่ "นับเป็นชิ้นงาน" มา 1 ใบ

    ทำ 4 ด่านตามลำดับ — ตกด่านไหนก็ทิ้งรูปแล้วจบ:
      1. หาค่าคู่กับรูปนี้ให้เจอ (จับคู่ด้วยเวลาในชื่อไฟล์)
      2. ค่าต้องไม่ใช่ -9999.999 (TM-X วัดไม่ติด)
      3. ต้องมี session ที่ running อยู่ตอนนี้
      4. POST ค่า + อัปโหลดรูป
    """
    try:
        _handle_capture_inner(image_path, t_recv)
    finally:
        _job_end()   # ต้องลดตัวนับเสมอ ไม่ว่าจะจบทางไหน ไม่งั้น clear_temp_dir รอค้างตลอด


def _handle_capture_inner(image_path, t_recv):
    name = os.path.basename(image_path)
    t_recv = t_recv or time.time()
    try:
        size_mb = os.path.getsize(image_path) / 1_048_576
    except OSError:
        size_mb = 0.0

    # ── ด่าน 1: จับคู่ค่ากับรูป ──────────────────────────────────────────
    ts_key = _image_ts_key(image_path)
    if ts_key:
        pair = _find_measurement_for_image(ts_key)
        if pair is None:
            print(f"⚠️ {name}: หาบรรทัดใน .txt ที่เวลาตรงกับรูปนี้ไม่เจอ (รอ {TXT_WAIT_TIMEOUT:.0f} วิแล้ว) — ทิ้งรูป")
            _remove_quietly(image_path)
            return
    else:
        print(f"⚠️ {name}: ชื่อไฟล์ไม่มีเวลาให้จับคู่ — ใช้บรรทัดล่าสุดของ .txt แทน")
        pair = _fallback_last_line()
        if pair is None:
            print(f"⚠️ {name}: ยังไม่มีไฟล์ .txt ให้อ่านเลย — ทิ้งรูป")
            _remove_quietly(image_path)
            return

    value_x, value_y = pair
    t_txt = time.time()   # จับเวลาหลังได้ค่าคู่กับรูปแล้ว

    # ── ด่าน 2: ค่าที่วัดไม่ติด ──────────────────────────────────────────
    if _is_error_value(value_x) or _is_error_value(value_y):
        print(f"⏭ {name}: TM-X วัดไม่ติด ({value_x}, {value_y}) — ข้าม ไม่บันทึกลง DB")
        _remove_quietly(image_path)
        return

    # ── ด่าน 3: ต้องมี session ที่ running อยู่ ─────────────────────────
    session_id, number_alpl = get_current_session()
    if session_id is None:
        print(f"⚠️ {name}: ไม่มี session ที่ running อยู่ตอนนี้ — ทิ้งค่า/รูปนี้ไป")
        _remove_quietly(image_path)
        return
    t_session = time.time()

    # ── ด่าน 4: ส่งเข้า Backend ─────────────────────────────────────────
    print(f"✅ {name}  ({size_mb:.1f} MB)  →  value_x={value_x}  value_y={value_y}")
    try:
        resp = post_to_backend(session_id, number_alpl, value_x, value_y)
    except Exception as exc:
        print(f"   ⚠️ POST /api/measurements ไม่สำเร็จ: {exc} — เก็บรูปไว้ไม่ลบ")
        return
    t_post = time.time()

    # ⚠ ต้องเช็ค status ก่อนแตะ data["measurement_id"] — ถ้า backend ตอบ
    #   error (400 session ไม่ running / 409 duplicate / 404 part not found)
    #   body จะเป็น {"detail": ...} ไม่มีคีย์ measurement_id → KeyError ใน
    #   เธรด daemon = ตายเงียบ ไม่มีใครเห็น แล้วรูปค้างในโฟลเดอร์ temp
    if resp.status_code != 200:
        detail = ""
        try:
            detail = resp.json().get("detail", "")
        except Exception:
            detail = resp.text[:200]
        print(f"   ⚠️ Backend ปฏิเสธค่านี้ (HTTP {resp.status_code}): {detail}")
        _remove_quietly(image_path)
        return

    data = resp.json()
    print(f"   → บันทึกแล้ว: result={data.get('result')}  ({data.get('measured')}/{data.get('target')})")
    upload_image_to_backend(data["measurement_id"], image_path)
    t_done = time.time()

    # ── สรุปเวลาแต่ละขั้น ───────────────────────────────────────────────
    # นับตั้งแต่ "FTP ส่งรูปเสร็จ" เท่านั้น — เวลาที่ TM-X ใช้วัดเองกับเวลาที่
    # ใช้ส่งไฟล์ผ่าน FTP อยู่ก่อนหน้านี้ ดูได้จากบรรทัด STOR ... seconds=X.XX
    # ที่ pyftpdlib พิมพ์ให้เอง (เอามาบวกกันถึงจะได้เวลารวมตั้งแต่กด Enter)
    print(f"   ⏱ รอ .txt {t_txt-t_recv:.2f}s · ถาม session {t_session-t_txt:.2f}s · "
          f"POST ค่า {t_post-t_session:.2f}s · อัปโหลดรูป {t_done-t_post:.2f}s "
          f"· รวม {t_done-t_recv:.2f}s")


def _log_received_file(path: str, note: str = ""):
    """โหมดรับอย่างเดียว — รายงานไฟล์ที่เพิ่งได้มา ไม่แตะต้องไฟล์เลย

    ตั้งใจให้พิมพ์ข้อมูลที่ "ต้องรู้ตอนต่อ TM-X" ออกมาให้ครบ: ชื่อไฟล์จริงที่
    TM-X ตั้งมา, ขนาด, และถ้าเป็นไฟล์ข้อความก็ลองแปลงค่าให้ดูด้วยว่ารูปแบบตรง
    กับที่โค้ดคาดไว้จริงไหม
    """
    rel  = os.path.relpath(path, TEMP_IMAGE_DIR)
    ext  = os.path.splitext(path)[1].lower()
    when = time.strftime("%H:%M:%S")
    try:
        size = os.path.getsize(path)
    except OSError:
        size = -1

    kind = "รูป" if ext in _IMAGE_EXTS else "ข้อความ"
    print(f"[{when}] ได้ไฟล์ ({kind}): {rel}  ({size:,} bytes){note}")

    if ext in _IMAGE_EXTS:
        return

    lines = _read_lines(path)
    print(f"           มีทั้งหมด {len(lines)} บรรทัด")
    if not lines:
        return
    print(f"           บรรทัดล่าสุด: {lines[-1]!r}")
    parsed = _parse_measurement_line(lines[-1])
    if parsed is None:
        print("           ⚠️ แปลงค่าไม่ได้ — รูปแบบไม่ตรงกับที่โค้ดคาดไว้")
    elif _is_error_value(parsed[0]) or _is_error_value(parsed[1]):
        print(f"           ⏭ TM-X วัดไม่ติด ({parsed[0]}, {parsed[1]}) — โหมดจริงจะข้ามบรรทัดนี้")
    else:
        print(f"           แปลงค่าได้: value_x={parsed[0]}  value_y={parsed[1]}  (เวลา {parsed[2]})")


class ReceiverFTPHandler(FTPHandler):
    """TM-X ส่งของมาเป็นชุด: ไฟล์ .txt ผลวัด (ต่อท้ายทีละบรรทัด) + รูป 2 ใบ
    (ใบหลักกับใบใน HEAD-A) — ตรงนี้แยกประเภทแล้วจัดการต่างกัน

    ไม่มีแนวคิด "armed" ต่อชิ้นเหมือน agent.py เดิม เพราะสคริปต์นี้ไม่รู้จัก
    session/trigger ของตัวเอง (Pi เป็นคนสั่ง trigger ตรงนี้แค่รับของที่เข้ามา)
    """

    def on_file_received(self, file):
        ext = os.path.splitext(file)[1].lower()

        # ── ไฟล์ข้อความ (.txt ผลวัด) → จำ path ไว้ ────────────────────────
        if ext not in _IMAGE_EXTS:
            with _txt_lock:
                if file not in _txt_paths:
                    _txt_paths.append(file)
            if not FORWARD_TO_BACKEND:
                _log_received_file(file)
            return

        # ── รูปที่ไม่ได้อยู่ในโฟลเดอร์ HEAD-A → ข้าม (เป็นรูปใบที่สองของการวัด
        # ครั้งเดียวกัน) โหมดจริงต้อง "ลบทิ้งด้วย" ไม่ใช่แค่ข้าม — ใบละ ~2 MB
        # ถ้าปล่อยไว้ Store_image_temporary จะบวมขึ้นเรื่อยๆ จนเต็มดิสก์
        # (ไม่มีใครมาลบให้ เพราะไม่เคยถูกอัปโหลดเข้า Backend)
        parent = os.path.basename(os.path.dirname(file)).lower()
        if parent != _IMAGE_DIR_NAME:
            if FORWARD_TO_BACKEND:
                _remove_quietly(file)
            else:
                _log_received_file(file, note="   ← ไม่ได้อยู่ใน HEAD-A โหมดจริงจะข้าม+ลบทิ้ง")
            return

        # ── รูปใน HEAD-A → นับเป็นชิ้นงาน 1 ชิ้น ──────────────────────────
        if not FORWARD_TO_BACKEND:
            _log_received_file(file, note="   ← รูปหลัก (HEAD-A) โหมดจริงจะบันทึกใบนี้")
            return

        # แตกเธรดเพราะ on_file_received วิ่งบนเธรดหลักของ FTP server — ถ้ายิง
        # HTTP รอ Backend ตรงนี้เลย FTP จะค้าง รับไฟล์ชิ้นถัดไปไม่ได้
        # ⚠ ต้อง _job_begin() "ก่อน" แตกเธรด ไม่ใช่ข้างในเธรด — ไม่งั้นมีช่องว่าง
        #   ที่ clear_temp_dir มองว่าไม่มีงานค้างทั้งที่เธรดกำลังจะเริ่มทำงานพอดี
        _job_begin()
        # ส่งเวลาที่ไฟล์มาถึงไปด้วย เพื่อจับเวลาแต่ละขั้นตอน (ดู _handle_capture_inner)
        threading.Thread(target=_handle_capture, args=(file, time.time()), daemon=True).start()


def start_ftp_server():
    handler = ReceiverFTPHandler
    handler.authorizer = _ftp_authorizer
    handler.passive_ports = range(60000, 60100)
    server = FTPServer((AGENT_FTP_HOST, AGENT_FTP_PORT), handler)

    # ⚠ timeout=1 จำเป็นบน Windows — ห้ามเอาออก
    #   ค่า default ของ serve_forever() คือ timeout=None ซึ่งทำให้ ioloop ไปนั่ง
    #   บล็อกอยู่ใน select() ระดับ C แบบไม่มีกำหนด Python จึงไม่มีจังหวะกลับมา
    #   ประมวลผล signal เลย → **กด Ctrl+C แล้วไม่มีอะไรเกิดขึ้น** จนกว่าจะมี
    #   คอนเนกชันเข้ามาปลุก loop (บน Linux ไม่เจอ เพราะ signal ตัด select() ให้)
    #   ใส่ timeout=1 = ตื่นมาเช็คทุก 1 วินาที กด Ctrl+C แล้วหยุดภายใน 1 วิ
    try:
        server.serve_forever(timeout=1)
    except KeyboardInterrupt:
        print("\nได้รับ Ctrl+C — กำลังปิด FTP server...")
    finally:
        server.close_all()
        print("ปิด FTP server เรียบร้อย")


if __name__ == "__main__":
    mode = ("ส่งต่อเข้า Backend (ใช้งานจริง)" if FORWARD_TO_BACKEND
            else "รับอย่างเดียว — ไม่ยิง Backend / ไม่ลบไฟล์")
    print("=" * 70)
    print("Recieve_tm-x.py (PC) — รอรับค่า+รูปจาก TM-X ผ่าน FTP")
    print(f"  โหมด          : {mode}")
    print(f"                  (.env: FORWARD_TO_BACKEND={'1' if FORWARD_TO_BACKEND else '0'})")
    print(f"  FTP รออยู่ที่   : {AGENT_FTP_HOST}:{AGENT_FTP_PORT}   (.env: AGENT_FTP_HOST/PORT)")
    print(f"  บัญชี FTP      : {AGENT_FTP_USER} / {'*' * len(AGENT_FTP_PASS)}   (.env: AGENT_FTP_USER/PASS)")
    print(f"  เก็บไฟล์ลงที่   : {TEMP_IMAGE_DIR}")
    if FORWARD_TO_BACKEND:
        print(f"  Backend ที่    : {BACKEND_URL}   (.env: BACKEND_URL)")
        print("  กติกา         : ใช้รูปนอกโฟลเดอร์ HEAD-A · ข้ามค่า -9999.999")
    else:
        print("  ** ไฟล์จะกองอยู่ในโฟลเดอร์ข้างบน ไม่ถูกลบ — ตรวจแล้วลบเองด้วย **")
    print("=" * 70)

    # เฝ้าดูสถานะ session เพื่อล้างโฟลเดอร์พักไฟล์ตอนจบรอบ — เฉพาะโหมดใช้งานจริง
    # โหมด "รับอย่างเดียว" ตั้งใจให้ไฟล์กองไว้ให้ตรวจ จึงต้องไม่ไปล้างทิ้ง
    if FORWARD_TO_BACKEND:
        threading.Thread(target=session_watcher, daemon=True).start()

    start_ftp_server()
