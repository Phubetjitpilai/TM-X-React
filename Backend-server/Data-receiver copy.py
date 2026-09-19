import logging
import os
import shutil
import threading
import time

import httpx
from dotenv import load_dotenv
from pyftpdlib.authorizers import DummyAuthorizer
from pyftpdlib.handlers import FTPHandler
from pyftpdlib.servers import FTPServer
import edit_image

# ── ตั้ง logging ─────────────────────────────────────────────────────────
# ทุกบรรทัดมี timestamp นำหน้า จำเป็นตอนรันเป็น service แบบไม่มีหน้าต่างแล้ว
# มาเปิดไฟล์ log อ่านทีหลัง — ไม่มีเวลากำกับจะไล่ลำดับเหตุการณ์ไม่ได้เลย
#
# ⚠ ป้าย [Recv] ไว้แยกจาก [Pi] ของ Pi.py และ [Server] ของ Backend เวลาเอา log
#   ของ 3 ตัวมาวางเทียบกันตอนไล่ว่าค่าหายไปช่วงไหน
#
# ⚠⚠ **ต้องปิดเสียง httpx ด้วยเสมอ** — `basicConfig(level=INFO)` เปิด logger
#   ของทุกไลบรารีพร้อมกัน ไม่ใช่แค่ของไฟล์นี้ · `session_watcher()` ยิง
#   `GET /api/session/state` ทุก SESSION_POLL_INTERVAL วิ ถ้าไม่ปิด httpx จะพ่น
#   `HTTP Request: GET ... "200 OK"` ทุกครั้งจน log ของจริงจมหายหมด
logging.basicConfig(level=logging.INFO, format="%(asctime)s [Recv] %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger(__name__)

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
load_dotenv(dotenv_path=os.path.join(PROJECT_ROOT, ".env"))
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")
FORWARD_TO_BACKEND = os.getenv("FORWARD_TO_BACKEND", "0").strip().lower() in ("1", "true", "yes", "on")
TEMP_IMAGE_DIR = os.getenv("TEMP_IMAGE_DIR", "./Store_image_temporary")
if not os.path.isabs(TEMP_IMAGE_DIR):
    TEMP_IMAGE_DIR = os.path.abspath(os.path.join(PROJECT_ROOT, TEMP_IMAGE_DIR))

DATA_RECEIVER_FTP_HOST = os.getenv("DATA_RECEIVER_FTP_HOST", "0.0.0.0")
DATA_RECEIVER_FTP_PORT = int(os.getenv("DATA_RECEIVER_FTP_PORT", 21))
DATA_RECEIVER_FTP_USER = os.getenv("DATA_RECEIVER_FTP_USER", "INTERN_USER")
DATA_RECEIVER_FTP_PASS = os.getenv("DATA_RECEIVER_FTP_PASS", "123456")

os.makedirs(TEMP_IMAGE_DIR, exist_ok=True)

_ftp_authorizer = DummyAuthorizer()
_ftp_authorizer.add_user(DATA_RECEIVER_FTP_USER, DATA_RECEIVER_FTP_PASS, TEMP_IMAGE_DIR, perm="elradfmw")

# นามสกุลไฟล์ที่นับว่าเป็นรูป — TM-X ส่งไฟล์ .txt ผลวัดมาด้วย ต้องแยกให้ออก
_IMAGE_EXTS = {".bmp"}
_IMAGE_DIR_NAME = "head-a"

TXT_WAIT_TIMEOUT = 5.0
SESSION_POLL_INTERVAL = 3.0

# ── รวมหลายทริกเกอร์ให้เป็นค่าเดียว (trimmed mean) ─────────────────────────
# Pi ยิง T1 ซ้ำ `SAMPLES_PER_PIECE` ครั้งต่อชิ้นงาน 1 ชิ้น → TM-X เขียน .txt
# เท่ากับจำนวนครั้งและส่งรูปตามมาทุกครั้ง · ไฟล์นี้สะสมไว้เป็น "กอง" แล้วค่อย
# ตัดหัวท้ายทิ้งอย่างละ `TRIM_EACH_SIDE` ก่อนเฉลี่ย แล้วส่งเข้า Backend
# **ครั้งเดียวต่อชิ้น** — Backend จึงไม่ต้องแก้อะไรเลย ยังเห็น 1 POST = 1 ชิ้น
SAMPLES_PER_PIECE = int(os.getenv("SAMPLES_PER_PIECE", 16))
TRIM_EACH_SIDE    = int(os.getenv("TRIM_EACH_SIDE", 1))
# เหลือค่าที่ใช้ได้น้อยกว่านี้ = ไม่เชื่อถือ ทิ้งทั้งกอง
MIN_SAMPLES       = int(os.getenv("MIN_SAMPLES", 10))
# กองที่ค้างเกินกี่วินาทีถือว่าจบชิ้นแล้ว (ปิดแบบไม่ครบ)
BATCH_IDLE_GAP    = float(os.getenv("BATCH_IDLE_GAP", 2.0))
# รอบการตรวจกองค้าง — ต้องถี่กว่า BATCH_IDLE_GAP พอสมควร
BATCH_WATCH_TICK  = float(os.getenv("BATCH_WATCH_TICK", 0.3))

# ⚠⚠ **ปิดกอง 2 ทาง ต้องมีทั้งคู่ ห้ามเอาอันใดอันหนึ่งออก**
#   1. ครบ `SAMPLES_PER_PIECE` → ปิดทันที (ทางปกติ เร็วสุด ไม่ต้องรอ)
#   2. เงียบเกิน `BATCH_IDLE_GAP` → ปิดเท่าที่มี (ทางกันเหนียว)
#
#   ถ้ามีแค่ข้อ 1 แล้วแถวหายกลางทาง (FTP หลุด / รูปส่งไม่ถึง) กองนั้นจะค้าง
#   รออีกไม่กี่แถวตลอดไป แล้ว **ชิ้นถัดไปจะมาเติมให้ครบพอดี** → ค่าของ 2 ชิ้น
#   ปนกันโดยไม่มี error ใด ๆ ให้เห็น และเพี้ยนลามไปทุกชิ้นที่เหลือ
#
#   ถ้ามีแค่ข้อ 2 ก็ต้องรอ `BATCH_IDLE_GAP` ทุกชิ้น ซึ่งกินงบเวลาของ
#   `MEASURE_TIMEOUT` ฝั่ง Pi ไปเปล่า ๆ
_batch_lock    = threading.Lock()
_batch_rows    = []      # ค่าที่ parse ได้ (tuple ละ 8 ตัว)
_batch_images  = []      # path ของรูปตามลำดับที่มาถึง
_batch_last_at = 0.0     # เวลาที่มีของเข้ากองล่าสุด

# ── ตำแหน่งของแต่ละค่าในบรรทัดของไฟล์ .txt ────────────────────────────────
# ⚠⚠ **ใช้คีย์ชุดเดียวกับ `Pi.py` (`GM_IDX_*`) โดยตั้งใจ ห้ามแยกเป็นคีย์ของตัวเอง**
#   TM-X เรียงค่าตามลำดับเครื่องมือชุดเดียวกันทั้งตอนตอบ `GM` ทาง TCP (Pi อ่าน)
#   และตอนเขียนไฟล์ `.txt` ทาง FTP (ไฟล์นี้อ่าน) — ถ้าแยกเป็นคนละคีย์ จะมีวันที่
#   คนแก้ไปแค่ฝั่งเดียว แล้วชิ้นเดียวกันที่เข้ามาคนละเส้นทางจะได้ TOP/BOTTOM
#   สลับกันโดยไม่มี error ให้เห็นเลย (เคยเกิดมาแล้วตอนที่ไฟล์นี้ hardcode index ไว้)
#
# ⚠ ค่า default ข้างล่างนี้ **ไม่ใช่ค่าที่ใช้จริง** ถ้า `.env` ตั้งไว้ — `.env` ชนะเสมอ
#   ไล่บั๊กเรื่องตำแหน่งเมื่อไหร่ให้เปิด `.env` ดูก่อนอ่านบรรทัดพวกนี้
def _idx(name: str, default: str) -> int:
    return int(os.getenv(name, default))


IDX_X               = _idx("GM_IDX_X", "0")
IDX_Y               = _idx("GM_IDX_Y", "1")
IDX_HORIZON_LEFT    = _idx("GM_IDX_HORIZON_LEFT", "2")
IDX_HORIZON_RIGHT   = _idx("GM_IDX_HORIZON_RIGHT", "3")
IDX_VERTICAL_TOP    = _idx("GM_IDX_VERTICAL_TOP", "4")
IDX_VERTICAL_BOTTOM = _idx("GM_IDX_VERTICAL_BOTTOM", "5")
IDX_OFFSET_X        = _idx("GM_IDX_OFFSET_X", "6")
IDX_OFFSET_Y        = _idx("GM_IDX_OFFSET_Y", "7")

# บรรทัดต้องมีอย่างน้อยกี่ช่องถึงจะอ่านได้ครบ — คิดจาก index ที่ตั้งไว้จริง
# ⚠ ห้าม hardcode 8 กลับมา ถ้ามีคนย้าย index ไปช่องที่ 9 แล้วบรรทัดมี 9 ช่องพอดี
#   การเช็ค `< 8` จะผ่านแล้วไประเบิด IndexError ตอน index จริงแทน
_MIN_FIELDS = max(
    IDX_X, IDX_Y, IDX_HORIZON_LEFT, IDX_HORIZON_RIGHT,
    IDX_VERTICAL_TOP, IDX_VERTICAL_BOTTOM, IDX_OFFSET_X, IDX_OFFSET_Y,
) + 1

_txt_paths = []
_txt_lock = threading.Lock()

_jobs_in_flight = 0
_jobs_lock = threading.Lock()

_txt_cursor_path = None
_txt_cursor_rows = 0
count_lock = threading.Lock()  # คุม _txt_cursor_path / _txt_cursor_rows

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


def _parse_measurement_line(line: str):
    items = [item.strip() for item in line.split(",")]

    # แก้ไข: เทียบเป็น String หรือ แปลงเป็น float เพื่อเปรียบเทียบ
    filtered_items = [item for item in items if not item.startswith("-")]

    if len(filtered_items) < _MIN_FIELDS:
        #clear_temp_dir(wait_timeout=0)
        return None

    try:
        value_x = float(filtered_items[IDX_X])
        value_y = float(filtered_items[IDX_Y])
        horizon_left = float(filtered_items[IDX_HORIZON_LEFT])
        horizon_right = float(filtered_items[IDX_HORIZON_RIGHT])
        vertical_top = float(filtered_items[IDX_VERTICAL_TOP])
        vertical_bottom = float(filtered_items[IDX_VERTICAL_BOTTOM])
        offset_opx = float(filtered_items[IDX_OFFSET_X])
        offset_opy = float(filtered_items[IDX_OFFSET_Y])
    except (ValueError, IndexError):
        return None

    # ⚠ ลำดับของ tuple นี้เรียง `vertical_bottom` มาก่อน `vertical_top`
    #   ซึ่ง **กลับกับ `get_measurement_tmx` ใน Pi.py** ที่เรียง top ก่อน
    #   ทั้งคู่ถูกในตัวเอง (ผู้เรียกแกะตรงลำดับกัน) แต่ห้ามก๊อป tuple ข้ามไฟล์
    return (
        value_x,
        value_y,
        horizon_left,
        horizon_right,
        vertical_bottom,
        vertical_top,
        offset_opx,
        offset_opy,
    )


def _read_lines(path: str):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return [ln.strip() for ln in f if ln.strip()]
    except OSError:
        return []

def trimmed_mean(values, trim: int = TRIM_EACH_SIDE):
    """ตัดหัวท้ายอย่างละ `trim` ตัว แล้วเฉลี่ยที่เหลือ — คืน `None` ถ้าทำไม่ได้

    ⚠ **ผู้เรียกต้องกรอง sentinel ออกมาก่อน** ฟังก์ชันนี้ไม่รู้จัก 9999.999
      การหวังให้ "ตัดตัวมากสุดทิ้ง" จัดการ sentinel ให้เอง ใช้ได้เฉพาะตอนมัน
      โผล่มาตัวเดียว · ถ้าโผล่ 2 ตัวจะเหลือรอด 1 ตัวเข้าไปในค่าเฉลี่ย แล้วผลลัพธ์
      กระโดดไปหลักร้อยโดยไม่มี error ให้เห็น (ทดสอบแล้วได้ 721 จากค่าจริง 8.05)
    """
    vals = sorted(values)
    if len(vals) <= trim * 2:
        return None
    kept = vals[trim:len(vals) - trim] if trim > 0 else vals
    return sum(kept) / len(kept)


def _aggregate(rows):
    """ยุบหลายทริกเกอร์ให้เหลือชุดเดียว — คืน `(ค่า 8 ตัว, ข้อความสรุป)` หรือ `(None, เหตุผล)`

    ตัดหัวท้าย **แยกทีละฟิลด์** ไม่ใช่ตัดทั้งแถว — ค่าแต่ละตัวที่ TM-X วัดมา
    เป็นอิสระต่อกัน ตัวที่เพี้ยนของ X ไม่จำเป็นต้องอยู่แถวเดียวกับตัวที่เพี้ยน
    ของ Y การตัดทั้งแถวจะทิ้งค่าดีของฟิลด์อื่นไปด้วยโดยไม่จำเป็น
    """
    n_fields = len(rows[0])
    out, kept_counts = [], []

    for i in range(n_fields):
        # กรอง sentinel ทิ้งก่อนเสมอ — ตรงกับ NO_VALUE_ABS = 9999.0 ฝั่ง Pi
        usable = [r[i] for r in rows if abs(r[i]) < 9999.0]
        if len(usable) < MIN_SAMPLES:
            return None, (f"ฟิลด์ที่ {i} เหลือค่าที่ใช้ได้ {len(usable)}/{len(rows)} "
                          f"ตัว (ต้องการอย่างน้อย {MIN_SAMPLES})")
        m = trimmed_mean(usable)
        if m is None:
            return None, f"ฟิลด์ที่ {i} มีค่าน้อยเกินกว่าจะตัดหัวท้ายได้"
        out.append(m)
        kept_counts.append(len(usable) - TRIM_EACH_SIDE * 2)

    lo, hi = min(kept_counts), max(kept_counts)
    span = f"{lo}" if lo == hi else f"{lo}-{hi}"
    return tuple(out), f"เฉลี่ยจาก {span} ค่า (เก็บมา {len(rows)} · ตัดหัวท้ายข้างละ {TRIM_EACH_SIDE})"


def _batch_add(rows=None, image=None):
    """ใส่ของเข้ากอง แล้วบอกว่าถึงเวลาปิดกองหรือยัง (ครบจำนวน)"""
    global _batch_last_at
    with _batch_lock:
        if rows:
            _batch_rows.extend(rows)
        if image:
            _batch_images.append(image)
        _batch_last_at = time.time()
        return len(_batch_rows) >= SAMPLES_PER_PIECE


def _batch_take():
    """ดึงของออกจากกองแล้วเคลียร์ — คืน `(rows, images)`

    ⚠ ต้องดึงออกมาทั้งก้อนใต้ล็อกเดียว เพราะมีคนเรียกปิดกองได้ 2 ทางพร้อมกัน
      (เธรดที่รับรูป กับเธรดจับเวลา) ถ้าไม่กันไว้จะ POST ซ้ำสองครั้ง
    """
    global _batch_last_at
    with _batch_lock:
        rows, images = list(_batch_rows), list(_batch_images)
        _batch_rows.clear()
        _batch_images.clear()
        _batch_last_at = 0.0
        return rows, images


def batch_watcher():
    """ปิดกองที่ค้างเกิน BATCH_IDLE_GAP — ทางกันเหนียวของการปิดกอง"""
    while True:
        time.sleep(BATCH_WATCH_TICK)
        with _batch_lock:
            idle = _batch_last_at and (time.time() - _batch_last_at) >= BATCH_IDLE_GAP
            pending = len(_batch_rows)
        if idle and pending:
            log.info("⏱ กองค้าง %s แถวมา %.1f วิแล้ว — ปิดกองเท่าที่มี",
                     pending, BATCH_IDLE_GAP)
            flush_batch("เงียบเกินกำหนด")


def _collect_new_rows(timeout: float = TXT_WAIT_TIMEOUT):
    """รอจนมีบรรทัดใหม่ใน .txt แล้วคืน **ทุกบรรทัดที่เพิ่มมา** (ไม่ใช่แค่บรรทัดล่าสุด)

    ต่างจาก `_find_measurement_for_image()` เดิมที่คืนบรรทัดเดียว เพราะโหมดนี้
    ต้องเก็บให้ครบทุกทริกเกอร์ · ถ้า FTP ส่งรวดเดียวมา 2 บรรทัดแล้วเราหยิบแค่
    บรรทัดล่าสุด ค่าที่หายไปจะทำให้กองไม่มีวันครบ `SAMPLES_PER_PIECE`

    บรรทัดที่ parse ไม่ผ่านถูกข้ามแต่ยังนับ cursor ไปแล้ว — ไม่ย้อนกลับมาอ่านซ้ำ
    """
    global _txt_cursor_path, _txt_cursor_rows
    deadline = time.time() + timeout

    while True:
        with _txt_lock:
            path = _txt_paths[-1] if _txt_paths else None

        if path:
            with count_lock:
                if path != _txt_cursor_path:
                    log.info(f"📄 .txt ไฟล์ใหม่ → {os.path.basename(path)} (เริ่มนับบรรทัดใหม่)")
                    _txt_cursor_path = path
                    _txt_cursor_rows = 0

                lines  = _read_lines(path)
                before = _txt_cursor_rows
                after  = len(lines)

                if after > before:
                    _txt_cursor_rows = after
                    fresh = lines[before:after]
                    parsed = [p for p in (_parse_measurement_line(ln) for ln in fresh)
                              if p is not None]
                    if len(parsed) != len(fresh):
                        log.warning("   ⚠️ .txt %s → %s บรรทัด · parse ผ่าน %s/%s",
                                    before, after, len(parsed), len(fresh))
                    else:
                        log.info(f"   📈 .txt {before} → {after} บรรทัด")
                    return parsed

        if time.time() >= deadline:
            return []
        time.sleep(0.1)


def _find_measurement_for_image(timeout: float = TXT_WAIT_TIMEOUT):
    """⚠ ของเดิม เก็บไว้อ้างอิงเฉย ๆ — โหมดรวมกองใช้ `_collect_new_rows()` แทน"""
    global _txt_cursor_path, _txt_cursor_rows
    deadline = time.time() + timeout

    while True:
        with _txt_lock:
            path = _txt_paths[-1] if _txt_paths else None   # ไฟล์ .txt ที่ได้รับล่าสุด

        if path:
            with count_lock:
                if path != _txt_cursor_path:
                    log.info(f"📄 .txt ไฟล์ใหม่ → {os.path.basename(path)} (เริ่มนับบรรทัดใหม่)")
                    _txt_cursor_path = path
                    _txt_cursor_rows = 0

                lines  = _read_lines(path)
                before = _txt_cursor_rows
                after  = len(lines)

                if after > before:
                    _txt_cursor_rows = after
                    log.info(f"   📈 .txt {before} → {after} บรรทัด")
                    parsed = _parse_measurement_line(lines[-1])
                    if parsed is not None:
                        return parsed
                    else:
                        return None

        if time.time() >= deadline:
            return None
        time.sleep(0.3)

def get_current_session():
    try:
        resp = httpx.get(f"{BACKEND_URL}/api/session/state", timeout=5)
        data = resp.json()
        if data.get("state") == "running":
            return data.get("session_id")
    except Exception as exc:
        log.warning(f"⚠️ query /api/session/state ไม่สำเร็จ: {exc}")
    return None

def post_to_backend(
    session_id,
    value_x, value_y,
    horizon_left, horizon_right, vertical_bottom, vertical_top,
    offset_opx, offset_opy
):
    """POST ค่าเข้า backend — format ตรงตาม MeasurementCreate ใน main.py

    ไม่ส่ง number_alpl แล้ว — backend เลือก ALPL จากตำแหน่งปัจจุบันในคิวของ
    ตัวเองเสมอ (session_queues[session_id]["queue"][position]) เพราะสคริปต์นี้
    ไม่มีทางรู้ว่ากำลังรับค่าของชิ้นที่เท่าไหร่ในคิว
    """
    return httpx.post(
        f"{BACKEND_URL}/api/measurements",
        json={
            "session_id":  session_id,
            "value_x":     value_x,
            "value_y":     value_y,

            # ── กลุ่มค่าตัวเทียบ Pos OP ──
            "horizon_left":       horizon_left,
            "horizon_right":       horizon_right,
            "vertical_bottom":       vertical_bottom,
            "vertical_top":       vertical_top,

            # ── กลุ่มค่า Offset ──
            "offset_opx":  offset_opx,
            "offset_opy":  offset_opy,
        },
        timeout=5,
    )

def _exc_line(exc: BaseException) -> str:
    """ย่อ exception ให้เหลือบรรทัดเดียว สำหรับส่งเข้า `report()`

    `last_event_detail` เป็นคอลัมน์ใน DB และถูก broadcast เป็น toast บนหน้าเว็บ
    ด้วย จะยัด traceback ทั้งดุ้นลงไปไม่ได้ — ตัวเต็มให้ใช้ `log.exception()`
    ซึ่งลงเฉพาะ log ของเครื่อง PC

    ⚠ ต้องเอา `__module__` มาประกอบด้วย เพราะ `type(cv2.error).__name__` คืนแค่
      `"error"` เฉย ๆ อ่านแล้วไม่รู้เลยว่ามาจาก OpenCV
    """
    cls = type(exc)
    name = f"{cls.__module__}.{cls.__name__}" if cls.__module__ != "builtins" else cls.__name__
    msg = (str(exc) or "ไม่มีรายละเอียด").splitlines()[-1].strip()
    return f"{name}: {msg[:160]}"


def report(event: str, detail: str, *, persist: bool = True):
    log.info(f"   📣 {event}: {detail}")
    try:
        httpx.post(
            f"{BACKEND_URL}/api/session/event",
            json={"event": event, "detail": detail, "persist": persist},
            timeout=2,
        )
    except Exception as exc:
        log.warning(f"   ⚠️ แจ้ง Backend ไม่สำเร็จ: {exc}")

def upload_image_to_backend(measurement_id, image_path):
    try:
        with open(image_path, "rb") as f:
            resp = httpx.post(
                f"{BACKEND_URL}/api/measurements/{measurement_id}/image-upload",
                files={"file": (os.path.basename(image_path), f, "image/bmp")},
                timeout=60,
            )
        if resp.status_code == 200:
            log.info(f"   🖼 อัปโหลดรูปสำเร็จ (measurement_id={measurement_id})")
        else:
            report("IMAGE_UPLOAD_FAILED",
                   f"รูปของ measurement {measurement_id} อัปโหลดไม่สำเร็จ "
                   f"(HTTP {resp.status_code}): {resp.text[:120]}",
                   persist=False)
    except Exception as exc:
        report("IMAGE_UPLOAD_FAILED",
               f"รูปของ measurement {measurement_id} อัปโหลดไม่สำเร็จ: {exc}",
               persist=False)
    finally:
        _remove_quietly(image_path)

def _remove_quietly(path):
    try:
        os.remove(path)
    except OSError:
        pass

def clear_temp_dir(wait_timeout: float = 5.0):
    """ล้างทุกอย่างใน TEMP_IMAGE_DIR แต่เก็บตัวโฟลเดอร์ไว้

    wait_timeout = 0 → ลบทันที ไม่รองานที่ค้าง
      ใช้ตอนถูกเรียก **จากในเธรด capture เอง** (เช่นด่าน NO_SESSION) เพราะงานที่
      ค้างอยู่คือตัวผู้เรียกเอง รอไปก็ไม่มีวันเป็น 0 ได้ครบ timeout แล้วลบอยู่ดี

    ⚠ ยึด TEMP_IMAGE_DIR เป็น absolute path ที่ resolve แล้วเสมอ ไม่รับ path
      จากที่อื่นมาลบ — พลาดตรงนี้ทีเดียวคือลบผิดโฟลเดอร์บนเครื่องจริง
    """
    global _txt_cursor_path, _txt_cursor_rows

    # ── รอให้งานที่ค้างอยู่เสร็จก่อน (ข้ามได้ถ้า wait_timeout = 0) ──────────
    if wait_timeout > 0:
        deadline = time.time() + wait_timeout
        if _jobs_count() > 0:
            log.info(f"⏳ รองาน {_jobs_count()} รายการที่ค้างอยู่ให้เสร็จก่อนล้าง...")
        while _jobs_count() > 0 and time.time() < deadline:
            time.sleep(0.3)
        if _jobs_count() > 0:
            log.warning(f"⚠️ ยังมีงานค้าง {_jobs_count()} รายการหลังรอ {wait_timeout:.0f} วิ — ล้างต่อไป")

    # ── ลบไฟล์และโฟลเดอร์ข้างใน ────────────────────────────────────────
    removed_files = removed_dirs = 0
    for name in os.listdir(TEMP_IMAGE_DIR):
        path = os.path.join(TEMP_IMAGE_DIR, name)
        try:
            if os.path.isdir(path):
                shutil.rmtree(path); removed_dirs += 1
            else:
                os.remove(path);     removed_files += 1
        except OSError as exc:
            log.warning(f"⚠️ ลบ {name} ไม่สำเร็จ: {exc}")

    with _txt_lock:
        _txt_paths.clear()   # path ที่จำไว้ชี้ไปยังไฟล์ที่ไม่มีแล้ว

    with count_lock:
        # ไฟล์ที่หมุดชี้อยู่ถูกลบไปกับโฟลเดอร์ temp แล้ว ต้องล้างด้วย
        _txt_cursor_path = None
        _txt_cursor_rows = 0

    # ⚠ ต้องทิ้งกองที่ค้างด้วย — รูปในกองชี้ไปยังไฟล์ที่เพิ่งถูกลบไปเมื่อกี้
    #   ถ้าปล่อยไว้ พอ session ใหม่เริ่ม กองเก่าจะเอาค่าของ session ก่อนหน้า
    #   ไปปนกับชิ้นแรกของรอบใหม่
    dropped, _ = _batch_take()
    if dropped:
        log.info("🗑 ทิ้งกองที่ค้างอยู่ %s แถว (ล้างโฟลเดอร์พัก)", len(dropped))

    log.info("🔄 รีเซ็ตตำแหน่งอ่าน .txt เรียบร้อย")

    if removed_files or removed_dirs:
        log.info(f"🧹 ล้าง {os.path.basename(TEMP_IMAGE_DIR)} แล้ว "
                 f"(ไฟล์ {removed_files} · โฟลเดอร์ {removed_dirs})")
        
#Clear เมื่อ Session_id เปลี่ยน และ จบแล้ว
def session_watcher():
    last_running_sid = None
    while True:
        time.sleep(SESSION_POLL_INTERVAL)
        try:
            data = httpx.get(f"{BACKEND_URL}/api/session/state", timeout=5).json()
        except Exception:
            continue  # backend ล่มชั่วคราว รอบหน้าค่อยเช็คใหม่ ไม่ต้องล้างอะไร

        session_id     = data.get("session_id")
        is_running = data.get("state") == "running"

        if is_running: #Session_id เปลี่ยน
            if last_running_sid is not None and session_id != last_running_sid:
                log.info(f"🔄 session เปลี่ยนจาก {last_running_sid} → {session_id}")
                clear_temp_dir()
            last_running_sid = session_id
        elif last_running_sid is not None: #Run จบแล้ว
            log.info(f"🏁 session {last_running_sid} จบแล้ว (state={data.get('state')})")
            clear_temp_dir()
            last_running_sid = None
        
def _handle_capture(image_path):
    try:
        _handle_capture_inner(image_path)
    finally:
        _job_end()   # ต้องลดตัวนับเสมอ ไม่ว่าจะจบทางไหน ไม่งั้น clear_temp_dir รอค้างตลอด

def _handle_capture_inner(image_path):
    """รูป 1 ใบมาถึง = 1 ทริกเกอร์ — **แค่เก็บเข้ากอง ยังไม่ส่งอะไรทั้งนั้น**

    ⚠ ของเดิมที่นี่คือ "ได้รูป 1 ใบ = POST 1 ครั้ง" ซึ่งใช้ไม่ได้แล้วในโหมดรวมกอง
      เพราะ Pi ยิง `SAMPLES_PER_PIECE` ครั้งต่อชิ้น ถ้า POST ทุกใบจะได้ 16 แถว
      ต่อชิ้นใน DB · คิว ALPL ฝั่ง Backend เดินไป 16 ตัว · `measured_count`
      ถึง `target_count` ตั้งแต่ชิ้นแรก
    """
    name = os.path.basename(image_path)

    # ── ด่าน 1: ดึงบรรทัดใหม่ทั้งหมดใน .txt เข้ากอง ────────────────────
    rows = _collect_new_rows()
    if not rows:
        report("TXT_NOT_FOUND", f"ไม่พบค่าการวัดของ {name} "
                                f"(รอ {TXT_WAIT_TIMEOUT:.0f} วิแล้ว)")
        # ยังเก็บรูปเข้ากองอยู่ดี — ถ้า .txt ตามมาทีหลัง กองจะยังมีรูปให้ใช้
        _batch_add(image=image_path)
        return

    full = _batch_add(rows=rows, image=image_path)
    with _batch_lock:
        have = len(_batch_rows)
    log.info("   📦 เข้ากองแล้ว %s/%s แถว (+%s จาก %s)",
             have, SAMPLES_PER_PIECE, len(rows), name)

    if full:
        flush_batch("ครบจำนวน")


def flush_batch(reason: str):
    """ปิดกอง → กรอง sentinel → trim → mean → POST ครั้งเดียว → อัปโหลดรูปใบสุดท้าย

    ⚠ ต้องทนต่อการถูกเรียกซ้อนจาก 2 เธรด (ตัวรับรูป กับ `batch_watcher`)
      — `_batch_take()` ดึงของออกใต้ล็อกเดียว คนที่มาทีหลังจะได้กองว่างแล้วเลิก
    """
    rows, images = _batch_take()
    if not rows and not images:
        return

    for extra in images[:-1]:      # เก็บเฉพาะใบสุดท้าย ที่เหลือลบทิ้งกันดิสก์เต็ม
        _remove_quietly(extra)
    image_path = images[-1] if images else None
    name = os.path.basename(image_path) if image_path else "(ไม่มีรูป)"

    log.info("📦 ปิดกอง (%s): %s แถว · %s รูป", reason, len(rows), len(images))

    if not rows:
        report("BATCH_NO_ROWS", f"ปิดกองแล้วแต่ไม่มีค่าเลย (มีแต่รูป {len(images)} ใบ) — ทิ้ง",
               persist=False)
        if image_path:
            _remove_quietly(image_path)
        return

    # ── ด่าน 2: ยุบหลายทริกเกอร์ให้เหลือชุดเดียว ────────────────────────
    pair, note = _aggregate(rows)
    if pair is None:
        report("BATCH_TOO_FEW", f"ค่าที่ใช้ได้ไม่พอ — {note}")
        if image_path:
            _remove_quietly(image_path)
        return
    log.info("   🧮 %s", note)

    (
    value_x, value_y,
    horizon_left, horizon_right, vertical_bottom, vertical_top,
    offset_opx, offset_opy
    ) = pair

    # ── ด่าน 3: ต้องมี session ที่ running อยู่ ─────────────────────────
    session_id = get_current_session()
    if session_id is None:
        report("NO_SESSION",
               f"ได้ค่า/รูป {name} มาแต่ไม่มี session ที่ running อยู่ — ทิ้งไป")
        clear_temp_dir(wait_timeout=0)
        return

    if image_path is None:
        report("IMAGE_MISSING",
               f"กองนี้ไม่มีรูปเลย ({len(rows)} แถว) — ส่งเฉพาะค่า", persist=False)

    # ── ด่าน 4 วาดรูปใหม่ ──────────────────────────────────────────
    # ⚠ การวาดเส้นเป็น "ของแถม" **ห้ามให้มันบล็อกการส่งค่าเด็ดขาด** — ค่าที่วัดได้
    #   ผ่านด่าน 1 มาครบถูกต้องแล้ว วาดไม่ได้ก็ส่งรูปดิบไปแทน ดีกว่าทิ้งทั้งชิ้น
    #
    #   เคยพังมาแล้ว: `cv2.imread` คืน `None` เงียบ ๆ ตอนไฟล์ยังเขียนไม่เสร็จ
    #   แล้วไประเบิดที่ `cvtColor` — ฟังก์ชันนี้ถูกเรียกจาก daemon thread
    #   (ดู `on_file_received`) exception จึงหลุดออกไปตายเงียบ ๆ ผลคือไม่ POST
    #   ไม่ report รูปค้างใน temp และ Pi ไปนับถอยหลังจน measure_timeout
    #   โดยไม่มีใครรู้สาเหตุ
    #
    # ⚠ `persist=False` **ห้ามเปลี่ยนเป็น True** — `last_event` มีช่องเดียว
    #   ค่าใหม่ทับค่าเก่า (ดู `session_event` ใน routers/session.py) ต้องสงวนไว้
    #   ให้เรื่องที่ "ค่าไม่ลง DB แล้ว Pi กำลังรอคำตอบ" เท่านั้น · เคสนี้ค่ายังลง
    #   DB ปกติ ถ้า persist ไปจะทับสาเหตุจริงที่ Backend ต้องหยิบไปตอบ Pi
    #   ตอน measure-timeout — เหตุผลเดียวกับ IMAGE_UPLOAD_FAILED
    if image_path is not None:
        try:
            edit_image.process_and_save_image(image_path, pair)
        except Exception as exc:
            log.exception("วาดเส้นบนรูป %s ไม่สำเร็จ", name)   # traceback เต็มลง log เครื่อง PC
            report("IMAGE_EDIT_FAILED",
                   f"วาดเส้นบนรูป {name} ไม่สำเร็จ ({_exc_line(exc)}) — ส่งรูปดิบไปแทน",
                   persist=False)

    # ── ด่าน 5: ส่งเข้า Backend ─────────────────────────────────────────
    log.info(
    f"✅ {name} → "
    f"value_x={value_x:.3f} value_y={value_y:.3f} "
    f"horizon_left={horizon_left:.3f} horizon_right={horizon_right:.3f} vertical_bottom={vertical_bottom:.3f} vertical_top={vertical_top:.3f} "
    f"offset_opx={offset_opx:.3f} offset_opy={offset_opy:.3f}"
    )
    try:
        resp = post_to_backend(
        session_id,
        value_x, value_y,
        horizon_left, horizon_right, vertical_bottom, vertical_top,
        offset_opx, offset_opy
        )
    except Exception as exc:
        report("BACKEND_REJECT",
               f"POST /api/measurements ไม่สำเร็จ: {exc} — เก็บรูปไว้ไม่ลบ")
        return
    
    if resp.status_code != 200:
        detail = ""
        try:
            detail = resp.json().get("detail", "")
        except Exception:
            detail = resp.text[:200]
        report("BACKEND_REJECT",
               f"Backend ปฏิเสธค่านี้ (HTTP {resp.status_code}): {detail}")
        if image_path:
            _remove_quietly(image_path)
        return

    data = resp.json()
    log.info(f"   → บันทึกแล้ว: result={data.get('result')}  ({data.get('measured')}/{data.get('target')})")
    if image_path:
        upload_image_to_backend(data["measurement_id"], image_path)

# ทำงานเมื่อ FORWARD_TO_BACKEND = 0 ใช้สำหรับการ Debug

def _log_received_file(path: str, note: str = ""):
    """โหมดรับอย่างเดียว — รายงานไฟล์ที่เพิ่งได้มา ไม่แตะต้องไฟล์เลย

    ⚠ ต้องตอบให้ตรงกับสิ่งที่โหมดจริงจะทำ ไม่งั้นหมดประโยชน์ —
      บรรทัดที่โหมดจริงจะข้าม ตรงนี้ก็ต้องบอกว่าจะข้าม
    """
    rel  = os.path.relpath(path, TEMP_IMAGE_DIR)
    ext  = os.path.splitext(path)[1].lower()
    when = time.strftime("%H:%M:%S")
    try:
        size = os.path.getsize(path)
    except OSError:
        size = -1

    kind = "รูป" if ext in _IMAGE_EXTS else "ข้อความ"
    log.info(f"[{when}] ได้ไฟล์ ({kind}): {rel}  ({size:,} bytes){note}")

    if ext in _IMAGE_EXTS:
        return

    lines = _read_lines(path)
    log.info(f"           มีทั้งหมด {len(lines)} บรรทัด")
    if not lines:
        return

    last = lines[-1]
    log.info(f"           บรรทัดล่าสุด: {last!r}")

    parsed = _parse_measurement_line(last)
    if parsed is None:
        n = len(last.split(","))
        log.warning(f"           ⚠️ แปลงค่าไม่ได้ — ได้ {n} ช่อง (ต้องการ = 8) ")
        return

    log.info(f"           แปลงค่าได้: value_x={parsed[0]}  value_y={parsed[1]}  "
             f"offset_opx={parsed[6]}  offset_opy={parsed[7]}")
  
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
            if FORWARD_TO_BACKEND :
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
        threading.Thread(target=_handle_capture, args=(file,), daemon=True).start()

def start_ftp_server():
    handler = ReceiverFTPHandler
    handler.authorizer = _ftp_authorizer
    handler.passive_ports = range(60000, 60100)
    handler.dtp_handler.ac_in_buffer_size = 1048576
    handler.dtp_handler.ac_out_buffer_size = 1048576
    server = FTPServer((DATA_RECEIVER_FTP_HOST, DATA_RECEIVER_FTP_PORT), handler)

    # ⚠ timeout=1 จำเป็นบน Windows — ห้ามเอาออก
    #   ค่า default ของ serve_forever() คือ timeout=None ซึ่งทำให้ ioloop ไปนั่ง
    #   บล็อกอยู่ใน select() ระดับ C แบบไม่มีกำหนด Python จึงไม่มีจังหวะกลับมา
    #   ประมวลผล signal เลย → **กด Ctrl+C แล้วไม่มีอะไรเกิดขึ้น** จนกว่าจะมี
    #   คอนเนกชันเข้ามาปลุก loop (บน Linux ไม่เจอ เพราะ signal ตัด select() ให้)
    #   ใส่ timeout=1 = ตื่นมาเช็คทุก 1 วินาที กด Ctrl+C แล้วหยุดภายใน 1 วิ
    try:
        server.serve_forever(timeout=1)
    except KeyboardInterrupt:
        log.info("ได้รับ Ctrl+C — กำลังปิด FTP server...")
    finally:
        server.close_all()
        log.info("ปิด FTP server เรียบร้อย")


if __name__ == "__main__":
    mode = ("ส่งต่อเข้า Backend (ใช้งานจริง)" if FORWARD_TO_BACKEND
            else "รับอย่างเดียว — ไม่ยิง Backend / ไม่ลบไฟล์")
    log.info("=" * 70)
    log.info("Recieve_tm-x.py (PC) — รอรับค่า+รูปจาก TM-X ผ่าน FTP")
    log.info(f"  โหมด          : {mode}")
    log.info(f"                  (.env: FORWARD_TO_BACKEND={'1' if FORWARD_TO_BACKEND else '0'})")
    log.info(f"  FTP รออยู่ที่   : {DATA_RECEIVER_FTP_HOST}:{DATA_RECEIVER_FTP_PORT}   (.env: AGENT_FTP_HOST/PORT)")
    log.info(f"  บัญชี FTP      : {DATA_RECEIVER_FTP_USER} / {'*' * len(DATA_RECEIVER_FTP_PASS)}   (.env: AGENT_FTP_USER/PASS)")
    log.info(f"  เก็บไฟล์ลงที่   : {TEMP_IMAGE_DIR}")
    if FORWARD_TO_BACKEND:
        log.info(f"  Backend ที่    : {BACKEND_URL}   (.env: BACKEND_URL)")
        log.info("  กติกา         : ใช้รูปนอกโฟลเดอร์ HEAD-A · ข้ามค่า -9999.999")
        log.info(f"  รวมกอง        : {SAMPLES_PER_PIECE} ทริกเกอร์/ชิ้น · ตัดหัวท้ายข้างละ "
                 f"{TRIM_EACH_SIDE} · อย่างน้อย {MIN_SAMPLES} ค่า · ปิดกองเมื่อเงียบ "
                 f"{BATCH_IDLE_GAP:.1f} วิ")
    else:
        log.info("  ** ไฟล์จะกองอยู่ในโฟลเดอร์ข้างบน ไม่ถูกลบ — ตรวจแล้วลบเองด้วย **")
    log.info("=" * 70)

    # เฝ้าดูสถานะ session เพื่อล้างโฟลเดอร์พักไฟล์ตอนจบรอบ — เฉพาะโหมดใช้งานจริง
    # โหมด "รับอย่างเดียว" ตั้งใจให้ไฟล์กองไว้ให้ตรวจ จึงต้องไม่ไปล้างทิ้ง
    if FORWARD_TO_BACKEND:
        threading.Thread(target=session_watcher, daemon=True).start()
        threading.Thread(target=batch_watcher, daemon=True).start()
    clear_temp_dir(wait_timeout=0)
    start_ftp_server()