# Backend-server/main.py
# How to run:
#   cd Backend-server
#   pip install -r requirements.txt
#   uvicorn main:app --reload --host 0.0.0.0 --port 8000

import asyncio
import json
import logging
import os
import time
import re
import secrets
import shutil
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from decimal import Decimal
from io import BytesIO, StringIO
from typing import Any, Dict, List, Optional

import httpx
import pandas as pd
import pymysql
import pymysql.cursors
from pymysql.constants import CLIENT
from dotenv import load_dotenv
from fastapi import Body, Depends, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))

DB_CONFIG = dict(
    host=os.getenv("DB_HOST", "localhost"),
    user=os.getenv("DB_USER", "root"),
    password=os.getenv("DB_PASSWORD", ""),
    database=os.getenv("DB_NAME", "tmx_db"),
    # default 3306 = port ปกติของ MySQL ที่ติดตั้งบนเครื่องโดยตรง (เดิม 3307
    # คือ port ที่ map ออกมาจาก Docker container ซึ่งเลิกใช้แล้ว)
    port=int(os.getenv("DB_PORT", 3306)),
    cursorclass=pymysql.cursors.DictCursor,
    autocommit=True,
    # ⚠ ถ้าไม่ตั้ง pymysql ใช้ค่า default = 10 วินาที ซึ่งนานเกินไปมากเมื่อ MySQL
    #   ดับ/ต่อไม่ติด เพราะทุก endpoint ยังเป็น `async def` อยู่ → การรอ connect
    #   ค้าง **บล็อก event loop ทั้งเส้น** ไม่ใช่แค่ request ตัวเอง
    #   ผลคือ uvicorn เสิร์ฟอะไรไม่ได้เลยระหว่างนั้น รวมถึงไฟล์ static —
    #   หน้าเว็บกดเปลี่ยนหน้าไม่ไป ป้ายค้างที่ 'Connecting' (ทดสอบแล้วเกิดจริง
    #   ตอนสั่ง `docker compose stop mysql`)
    #
    #   3 วินาทีพอสำหรับ LAN/localhost — ต่อไม่ติดใน 3 วิก็คือต่อไม่ติดจริง
    #
    # 📌 นี่เป็นแค่การ "ลดความเสียหาย" ไม่ใช่ตัวแก้ — ตัวแก้จริงคือเปลี่ยน
    #    endpoint จาก `async def` เป็น `def` ให้ FastAPI รันใน threadpool
    #    (Handle_Pi_Error.md ข้อ 2.3) แล้ว event loop จะไม่ถูกบล็อกตั้งแต่แรก
    connect_timeout=3,
    # CLIENT.FOUND_ROWS: ค่า default ของ MySQL/pymysql คือ cur.rowcount หลัง UPDATE
    # จะนับเฉพาะ "แถวที่ค่าจริงเปลี่ยน" ไม่ใช่ "แถวที่ WHERE เจอ" — ทำให้กด Save โดย
    # ไม่แก้อะไรเลย (ส่ง payload ค่าเดิมกลับมา) แล้ว rowcount == 0 ทั้งที่แถวมีอยู่จริง
    # โค้ดที่เช็ค `if cur.rowcount == 0: raise 404 not found` (update_part,
    # update_measurement) เลยฟ้อง "not found" หลอกๆ ตั้ง flag นี้เพื่อให้ rowcount
    # นับจากแถวที่ WHERE จับคู่เจอแทน ทำให้เช็ค 404 เดิมถูกต้องอีกครั้ง
    client_flag=CLIENT.FOUND_ROWS,
)

# ── circuit breaker ของ get_db() ────────────────────────────────────────────
# ต่อไม่ติดครั้งหนึ่งแล้วหยุดลองกี่วินาที ก่อนยอมให้ลองใหม่ (ดู get_db)
#
# ตั้งสั้น ๆ พอ: จุดประสงค์คือกันไม่ให้ request ที่กองกันอยู่ต้องรอ connect_timeout
# ทุกตัว ไม่ใช่การ "ปิดระบบ" — MySQL กลับมาแล้วต้องเจอเร็วด้วย
#   2 วิ = แย่สุดคือหน้าเว็บช้ากว่าความจริง 2 วิหลัง MySQL ฟื้น ซึ่งไม่มีใครรู้สึก
#   ยาวกว่านี้เริ่มน่ารำคาญตอน start MySQL แล้วกดรีเฟรชแต่ยังขึ้น DB Offline
DB_BREAKER_COOLDOWN = float(os.getenv("DB_BREAKER_COOLDOWN", 2))

# เวลา (monotonic) ที่อนุญาตให้ลองต่อ DB ใหม่ได้ · 0 = breaker ปิดอยู่ ต่อได้ปกติ
#
# ⚠ ห้ามประกาศซ้ำในไฟล์อื่น ต้องมาจาก `from shared import *` เท่านั้น ไม่งั้นจะ
#   กลายเป็นคนละตัวแปรโดยไม่มี error — breaker จะไม่ทำงานเลยแบบเงียบ ๆ
_db_retry_after = 0.0

_PROJECT_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
)

ALPL_IMAGE_DIR = os.getenv("ALPL_IMAGE_DIR", os.path.join(_PROJECT_ROOT, "image_ALPL"))

if not os.path.isabs(ALPL_IMAGE_DIR):
    ALPL_IMAGE_DIR = os.path.abspath(os.path.join(_PROJECT_ROOT, ALPL_IMAGE_DIR))

_TOL_EPS = 1e-6

def _within_tolerance(value: float, nominal: float, upper_tol: float, lower_tol: float) -> bool:
    """เช็คว่าค่าที่วัดได้ของแกนหนึ่งอยู่ในช่วง nominal -lower_tol .. +upper_tol ไหม
    (นับค่าที่ตกขอบพอดีว่าผ่าน — ดู _TOL_EPS)
    """
    return (nominal - lower_tol - _TOL_EPS) <= value <= (nominal + upper_tol + _TOL_EPS)

# ══════════════════════════════════════════════════════════════════════════════
# เกณฑ์ตัดสิน OK/NG — แยกแหล่งตามโหมด
# ══════════════════════════════════════════════════════════════════════════════
# | โหมด        | nominal/tolerance จาก | offset นับเป็นเกณฑ์ |
# |-------------|-----------------------|---------------------|
# | IPM         | package_size          | ❌ เก็บค่าไว้ แต่ไม่ตัดสิน |
# | New/Rework  | part_number           | ✅ ใช้                |
#
# ทำไม IPM ต้องใช้ package_size: IPM คือการวัดซ้ำของ ALPL ที่ลงทะเบียนไว้แล้ว
# ซึ่ง "อาจยังไม่ได้ตั้ง part_number" (ฟอร์ม IPM กรอกแค่ ALPL + Package Size)
# ถ้าบังคับให้หาเกณฑ์ผ่าน part_number เหมือนโหมดอื่น ALPL พวกนี้จะวัดไม่ได้เลย
#
# ทำไม IPM ไม่เอา offset มาตัดสิน: offset เป็นค่าเฉพาะของ part นั้นๆ (ผูกกับ
# part_number) ไม่ใช่ค่าของ "ขนาด package" — เอา offset_tol ของ package_size
# มาตัดสินจะเป็นการเทียบกับเกณฑ์ที่ไม่ใช่ของชิ้นงานตัวนั้นจริง
#
# ⚠ ต้องตรงกับฝั่ง Pi ที่ตัดสินเองผ่าน GM (ดู PLAN_criteria_and_multigroup.md F2)
#   — Backend ส่ง `offset_max: null` ให้ Pi เมื่อไหร่ ที่นี่ก็ต้องไม่ตรวจเมื่อนั้น
#   ถ้าสองฝั่งไม่ตรงกัน จะเกิดสภาพ "Pi บอก MCU ว่า OK แต่ DB บันทึก NG"

def _offset_limit(measure_type: Optional[str], row) -> Optional[float]:
    """เพดาน offset ที่ต้องตรวจจริงของการวัดครั้งนี้ — `None` = ไม่นับเป็นเกณฑ์

    อย่าเรียก `_offset_ok(offset, row["offset_tol"])` ตรงๆ อีก ให้ผ่านฟังก์ชันนี้
    เสมอ เพราะ `_offset_ok` ผูกกับ "ตั้งค่าไว้ไหม" (NULL = ไม่ตรวจ) ไม่ได้ผูกกับ
    โหมด — ตัดสินใจเรื่องโหมดต้องเกิดที่นี่ที่เดียว
    """
    if (measure_type or "").upper() == "IPM":
        return None
    return row.get("offset_tol") if row else None

def _load_criteria(cur, number_alpl: int, measure_type: str):
    """ดึง nominal/tolerance ที่จะใช้ตัดสิน ALPL ตัวนี้ ตามโหมดที่กำลังวัด

    คืน dict ที่มี nominal_x/nominal_y/upper_tol/lower_tol/offset_tol เหมือนกัน
    ทั้ง 2 โหมด ผู้เรียกจึงใช้ต่อได้โดยไม่ต้องรู้ว่ามาจากตารางไหน
    (offset_tol ที่คืนมาเป็นค่า "ตามตาราง" เฉยๆ — จะเอามาตัดสินจริงไหมให้ถาม
    `_offset_limit()` อีกที)

    ไม่พบ → raise HTTPException พร้อมบอกว่าขาดตรงไหนและไปแก้ที่หน้าไหน
    """
    if (measure_type or "").upper() == "IPM":
        # COALESCE: ALPL ที่ลงทะเบียนสมัยก่อนมีแต่ part_number_id ยังไม่มี
        # package_size_id ของตัวเอง — ยอมไล่ต่อผ่าน part_number ให้ ไม่งั้น
        # ข้อมูลเก่าทั้งหมดจะวัดไม่ได้ทันทีที่ deploy
        cur.execute(
            "SELECT ps.nominal_x, ps.nominal_y, ps.upper_tol, ps.lower_tol, ps.offset_tol, "
            "       ps.package_size "
            "FROM parts_specifications p "
            "LEFT JOIN part_number pn  ON p.part_number_id = pn.part_number_id "
            "JOIN package_size ps      ON ps.package_size_id = "
            "                             COALESCE(p.package_size_id, pn.package_size_id) "
            "WHERE p.number_alpl = %s",
            (number_alpl,),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(
                404,
                f"ALPL {number_alpl} หาเกณฑ์ตัดสินไม่เจอ — ยังไม่ได้ผูก Package Size "
                f"ให้ ALPL นี้ (แก้ที่หน้า Edit › Parts)",
            )
        return row

    cur.execute(
        "SELECT pn.nominal_x, pn.nominal_y, pn.upper_tol, pn.lower_tol, pn.offset_tol, "
        "       pn.part_number_name "
        "FROM parts_specifications p "
        "JOIN part_number pn ON p.part_number_id = pn.part_number_id "
        "WHERE p.number_alpl = %s",
        (number_alpl,),
    )
    row = cur.fetchone()
    if not row:
        raise HTTPException(
            404,
            f"ALPL {number_alpl} หาเกณฑ์ตัดสินไม่เจอ — ยังไม่ได้ตั้ง Part Number "
            f"ให้ ALPL นี้ (โหมด New/Rework ใช้เกณฑ์จาก Part Number)",
        )
    return row

def _thai_date_str(dt: Optional[datetime] = None) -> str:
    """คืนวันที่รูปแบบ DD-MM-YYYY โดยปีเป็น พ.ศ. (ค.ศ. + 543) เช่น 22-07-2569
    ใช้ตั้งชื่อโฟลเดอร์/ไฟล์รูปภาพแบบแยกตามวันที่ (ดู upload_measurement_image)
    ค่า default (dt=None) ใช้เวลาปัจจุบันของเครื่องที่รัน backend ณ ตอนที่รูป
    ถูกอัปโหลดเข้ามา (ไม่ใช่เวลาที่วัด — สองอย่างนี้ในทางปฏิบัติเป็นเวลาเดียวกัน
    เพราะ Agent อัปโหลดรูปทันทีหลัง trigger แต่ละชิ้น)
    """
    dt = dt or datetime.now()
    return f"{dt.day:02d}-{dt.month:02d}-{dt.year + 543}"

DELETED_DIR = os.getenv("DELETED_DIR", os.path.join(_PROJECT_ROOT, "Deleted"))

if not os.path.isabs(DELETED_DIR):
    DELETED_DIR = os.path.abspath(os.path.join(_PROJECT_ROOT, DELETED_DIR))

DELETED_RETENTION_DAYS = int(os.getenv("DELETED_RETENTION_DAYS", 30))

def _json_safe(value):
    """แปลงค่าจาก DB ให้ json.dumps ได้ — datetime/date/Decimal ไม่ใช่ชนิดมาตรฐาน"""
    if isinstance(value, (datetime, date)):
        return value.isoformat(sep=" ")
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, timedelta):
        return str(value)
    return value

def _archive_before_delete(
    kind: str,
    table: str,
    pk: Dict[str, Any],
    row: Dict[str, Any],
    related: Optional[Dict[str, List[Dict]]] = None,
    image_path: Optional[str] = None,
) -> Optional[str]:
    """เก็บข้อมูลที่กำลังจะถูกลบไว้ใน Deleted/ — คืนชื่อไฟล์ JSON ที่สร้าง

    ⚠ ต้องเรียก "ก่อน" คำสั่ง DELETE เสมอ เพราะต้องอ่านค่าจากแถวที่ยังอยู่
    ⚠ ห้ามโยน exception ออกไป — ถ้าสำรองไม่สำเร็จก็ยังต้องยอมให้ลบต่อได้
      (ผู้ใช้สั่งลบแล้ว การไปขวางเพราะเขียนไฟล์สำรองไม่ได้จะงงกว่า) แต่ต้อง
      log ไว้ให้เห็นชัดว่ารอบนี้ไม่มีตัวสำรอง

    kind ใช้เป็นทั้งชื่อไฟล์และตัวบอกประเภทตอนกู้คืน:
      measurement | part | operator | owner | vendor | handler |
      template | package_size | part_number
    """
    try:
        day_dir = os.path.join(DELETED_DIR, _thai_date_str())
        os.makedirs(day_dir, exist_ok=True)

        pk_value = "_".join(str(v) for v in pk.values())
        stem = f"{kind}_{pk_value}"

        # ── ย้ายไฟล์รูปมาเก็บคู่กับ JSON (ไม่ลบทิ้ง) ────────────────────────
        image_file = None
        if image_path and "://" not in image_path:
            src = os.path.realpath(os.path.join(ALPL_IMAGE_DIR, image_path))
            base = os.path.realpath(ALPL_IMAGE_DIR)
            # กัน path ที่หลุดออกนอกโฟลเดอร์รูป (ค่าใน DB อาจถูกแก้มาก่อน)
            if (src == base or src.startswith(base + os.sep)) and os.path.isfile(src):
                image_file = f"{stem}_{os.path.basename(image_path)}"
                try:
                    shutil.move(src, os.path.join(day_dir, image_file))
                except OSError as exc:
                    log.warning("ย้ายไฟล์รูปเข้าถังขยะไม่สำเร็จ (%s): %s", image_path, exc)
                    image_file = None

        payload = {
            "deleted_at": datetime.now().isoformat(sep=" ", timespec="seconds"),
            "kind":       kind,
            "table":      table,
            "pk":         {k: _json_safe(v) for k, v in pk.items()},
            "row":        {k: _json_safe(v) for k, v in row.items()},
            "related":    {
                t: [{k: _json_safe(v) for k, v in r.items()} for r in rows]
                for t, rows in (related or {}).items()
            },
            "image_file": image_file,
        }

        # กันชื่อชนกันถ้าลบ id เดิมซ้ำในวันเดียวกัน (ลบ → กู้ → ลบอีก)
        json_name = f"{stem}.json"
        n = 2
        while os.path.exists(os.path.join(day_dir, json_name)):
            json_name = f"{stem}({n}).json"
            n += 1

        with open(os.path.join(day_dir, json_name), "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

        log.info("เก็บเข้าถังขยะแล้ว: %s/%s", _thai_date_str(), json_name)
        return json_name
    except Exception as exc:
        log.error("สำรองข้อมูลก่อนลบไม่สำเร็จ (%s %s): %s — ลบต่อโดยไม่มีตัวสำรอง", kind, pk, exc)
        return None

def _fetch_one(cur, sql: str, params) -> Optional[Dict[str, Any]]:
    cur.execute(sql, params)
    return cur.fetchone()

AGENT_HOST      = os.getenv("AGENT_HOST", "localhost")

AGENT_PORT      = int(os.getenv("AGENT_PORT", 9998))

AGENT_BASE_URL  = f"http://{AGENT_HOST}:{AGENT_PORT}"

# หน้าเว็บ poll /api/session/state ทุกกี่วินาที — ส่งให้ frontend ผ่าน
# GET /api/config เพราะเบราว์เซอร์อ่าน .env เองไม่ได้
#
# ตัวนี้เป็น "เพดาน" ของความไวที่ผู้ใช้เห็น: เวลาที่ชิป PI เปลี่ยน =
# HEARTBEAT_TIMEOUT + UI_POLL_INTERVAL (สูงสุด) — ลด TIMEOUT อย่างเดียว
# ไม่ช่วยถ้าตัวนี้ยังใหญ่
UI_POLL_INTERVAL = float(os.getenv("UI_POLL_INTERVAL", 5))

# เงียบเกินนี้ = ชิป PI ขึ้น Offline + ล็อกปุ่ม Start — แยกจาก HEARTBEAT_TIMEOUT
# เพราะตัวนั้นฆ่า session ทิ้งคิว (ราคาแพง) ส่วนตัวนี้แค่แสดงผล (ราคาถูก)
# ⚠ ต้อง ≤ HEARTBEAT_TIMEOUT เสมอ ไม่งั้นชิปจะเขียวทั้งที่ session ตายไปแล้ว
PI_ONLINE_TIMEOUT = float(os.getenv("PI_ONLINE_TIMEOUT", 5))

# เวลาที่ Backend "เห็น Pi" ครั้งล่าสุด (None = ยังไม่เคยเห็นเลยตั้งแต่บูต)
# เป็นแหล่งความจริงของชิป PI — ฝั่งอ่านไม่แตะ DB เลย (ดู read_pi_status)
#
# ⚠ ห้ามประกาศซ้ำในไฟล์อื่นเด็ดขาด ต้อง `from shared import *` เท่านั้น
#   ไม่งั้นจะกลายเป็นคนละตัวแปรโดยไม่มี error ให้เห็น — heartbeat เขียนตัวหนึ่ง
#   ชิปอ่านอีกตัวหนึ่ง แล้วชิปจะขึ้น "ไม่ทราบ" ตลอดกาล (ปัญหาเดียวกับ
#   session_queues ที่เตือนไว้ตอนแยกไฟล์)
_pi_last_seen = None

HEARTBEAT_INTERVAL = int(os.getenv("HEARTBEAT_INTERVAL", 5))

HEARTBEAT_TIMEOUT  = int(os.getenv("HEARTBEAT_TIMEOUT", 15))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [Server] %(message)s")

log = logging.getLogger(__name__)

CORS_ORIGINS = [
    o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()
]

subscribers: List[asyncio.Queue] = []

session_queues: Dict[int, Dict[str, Any]] = {}

async def push_event(event_type: str, data: dict) -> None:
    """กระจาย (broadcast) เหตุการณ์ SSE หนึ่งรายการไปให้ทุก client ที่เปิดหน้า dashboard อยู่

    ทำไมต้องทำแบบนี้: backend คือ Single Source of Truth ของสถานะ session/measurement
    ดังนั้นเมื่อสถานะมีการเปลี่ยนแปลง (เริ่ม session, มี measurement ใหม่, timeout ฯลฯ)
    ทุกแท็บ dashboard ที่เปิดอยู่ต้องรู้ทันที แต่ละ subscriber มี asyncio.Queue ของตัวเอง
    (ดู sse_stream ด้านล่าง) เราแค่ส่ง payload เดียวกันลงไปในทุกคิว SSE ไหลทางเดียวจาก
    server ไป client เท่านั้น (ไม่ใช่ request/response แบบ 2 ทาง)
    """
    payload = json.dumps(data, default=str)
    for q in subscribers:
        await q.put({"event": event_type, "data": payload})
    log.info("SSE ▶ %s: %s", event_type, payload)

# ── DB helpers ───────────────────────────────────────────────────────────────
def get_db():
    """เปิด MySQL connection ใหม่สำหรับ 1 request

    ทำไมต้องเปิดใหม่ทุกครั้งแทนใช้ connection pool: นี่คือระบบที่ deploy บน PC เดียว
    มี concurrency ต่ำ ความเรียบง่ายของ "connect → ใช้งาน → close" จึงคุ้มกว่าความซับซ้อน
    ของการทำ pool ทุก endpoint ด้านล่างจะเปิด connection นี้ใน try/finally แล้วปิดเมื่อใช้เสร็จ

    หมายเหตุ (เพิ่มเข้ามาทีหลัง): endpoint ทุกตัวเรียก get_db() "ก่อน" เข้า try/finally
    ของตัวเอง ถ้า MySQL server ล่ม/ต่อไม่ติดเลย pymysql.connect() จะ raise
    OperationalError ซึ่งเป็น raw exception ที่ FastAPI ไม่รู้จัก — หลุดออกไปกลายเป็น
    500 ดิบไม่มี CORS header แนบมา (ปัญหาเดียวกับที่ _notify_agent_start เจอกับ Agent)
    จับไว้ตรงนี้ที่เดียวแล้ว raise เป็น HTTPException(503) แทน เพื่อให้ CORS header
    ยังติดมาด้วยเสมอ ไม่ต้องไปแก้ทุก endpoint

    ── circuit breaker: ไม่ลองต่อซ้ำถ้าเพิ่งต่อไม่ติดไปเมื่อกี้ ──────────────
    ปัญหาที่แก้: `connect_timeout=3` เป็นราคาที่จ่าย **ต่อ request** ไม่ใช่ต่อ
    เหตุการณ์ — MySQL ดับทีเดียวแต่ทุก endpoint ที่เรียก get_db() ต้องไปนั่งรอ
    ครบ 3 วิของตัวเองเหมือนกันหมด (get_db ไม่มี pool เปิดใหม่ทุกครั้งโดยตั้งใจ)
    เปิดหน้าเว็บ 1 ครั้งยิงหลาย request + poll ทุก 2 วิ → กองสะสมจนเว็บเหมือนค้าง

    ⚠ ที่ต้องเข้าใจ: "ต่อไม่ติด" มี 2 แบบ ราคาต่างกันมาก
        ปฏิเสธทันที (RST)  พอร์ตปิดสนิท → เคอร์เนลตอบกลับเลย    ~1 ms
        เงียบไม่ตอบ        พอร์ตเปิดแต่ไม่มีใครรับสาย → ต้องรอ  เต็ม 3 วิ
      แบบหลังเจอบ่อยตอน `docker compose stop mysql` บน Windows เพราะ port proxy
      ของ Docker Desktop ยังจองพอร์ตค้างไว้ TCP จึงต่อติดแต่ handshake ไม่มา

    วิธีทำงาน: ต่อไม่ติดครั้งหนึ่ง → จำเวลาไว้ → request ที่เข้ามาภายใน
    DB_BREAKER_COOLDOWN วิถัดไปโยน 503 ทันทีโดย **ไม่ลองต่อเลย** (0 ms) พอพ้น
    cooldown ค่อยปล่อยให้ลองใหม่ ต่อติดเมื่อไหร่ล้างสถานะทิ้ง กลับสู่ปกติทันที

        ไม่มี breaker   ทุก request → รอ 3 วิ → 503
        มี breaker      ตัวแรก      → รอ 3 วิ → 503 แล้วจำไว้
                        ที่เหลือ     → 503 ทันที จนกว่าจะพ้น cooldown

    ผลพลอยได้: log เลิกท่วม — เดิม heartbeat_checker ยิงทุก 2 วิ แล้วพิมพ์
    "Database connection failed" ทุกรอบจนหา error อื่นไม่เจอ

    ไม่ใช้ lock: ตัวแปรตัวเดียวเป็น float การอ่าน/เขียนเป็น atomic ใต้ GIL อยู่แล้ว
    กรณีแย่สุดคือมี request 2-3 ตัวหลุดไปลองต่อพร้อมกันตอน cooldown เพิ่งหมด
    ซึ่งไม่มีผลเสีย (แค่เสียเวลา connect เพิ่มไม่กี่ครั้ง) — แลกกับการไม่ต้องมี
    lock บนเส้นทางที่ร้อนที่สุดของทั้งระบบ
    """
    global _db_retry_after

    # breaker เปิดอยู่ = เพิ่งรู้มาว่าต่อไม่ติด ไม่ต้องไปเสียเวลาลองใหม่
    # ใช้ monotonic ไม่ใช่ time.time() — ภูมิคุ้มกันการปรับนาฬิกาเครื่อง/DST
    # ถ้าใช้ time.time() แล้วนาฬิกาถูกเลื่อนถอยหลัง breaker จะค้างเปิดยาว
    if time.monotonic() < _db_retry_after:
        raise HTTPException(503, "เชื่อมต่อฐานข้อมูลไม่สำเร็จ (เพิ่งลองไปเมื่อครู่ "
                                 "— จะลองใหม่อัตโนมัติ)")

    try:
        conn = pymysql.connect(**DB_CONFIG)
    except pymysql.MySQLError as exc:
        _db_retry_after = time.monotonic() + DB_BREAKER_COOLDOWN
        log.error("Database connection failed: %s (หยุดลองต่อ %.0f วิ)",
                  exc, DB_BREAKER_COOLDOWN)
        raise HTTPException(503, f"เชื่อมต่อฐานข้อมูลไม่สำเร็จ: {exc}")

    _db_retry_after = 0.0   # ต่อติดแล้ว ปิด breaker ทันที
    return conn

# ── Lifespan ─────────────────────────────────────────────────────────────────
async def _reload_session_queues() -> None:
    """โหลด session_queues กลับเข้า memory จากคอลัมน์ sessions.queue_state

    ทำไมต้องมี: session_queues เดิมอยู่ใน memory ของ backend ล้วนๆ ถ้า backend
    ถูก restart (reload ตอน dev, crash แล้ว auto-restart, deploy ใหม่) ระหว่างที่
    มี session แบบ IPM/New กำลัง running อยู่ คิวจะหายไปจาก memory ทันที —
    create_measurement หลังจากนั้นจะไม่มีทางรู้ว่ากำลังวัด ALPL ตัวไหนอยู่

    เดิมกรณีนั้นจะ fallback ไปใช้ req.number_alpl ที่ Agent ส่งมา ซึ่งเป็น ALPL
    ตัวแรกในคิวเสมอ (อ่านมาจาก sessions.number_alpl ที่ไม่เคยถูก UPDATE) ทำให้ทุก
    measurement ที่เหลือถูกบันทึกผิด ALPL แบบไม่มี error เตือนเลย — ตอนนี้ถอด
    fallback นั้นออกแล้ว เปลี่ยนเป็นตอบ 409 ปฏิเสธไปเลย ฟังก์ชันนี้จึงเป็นด่าน
    เดียวที่กันไม่ให้ session ที่กำลังวัดอยู่ต้องล้มทั้งรอบเวลา backend restart

    จึงต้องรันตรงนี้ (ก่อน yield ให้แอปเริ่มรับ request) — ต้อง await ตรงๆ ไม่ใช่
    fire-and-forget แบบ _init_bucket_bg เพราะต้องมั่นใจว่า session_queues ถูก
    เติมกลับให้ครบก่อนที่ request แรกจาก Agent จะเข้ามาได้
    """
    try:
        db = get_db()
        try:
            with db.cursor() as cur:
                cur.execute(
                    "SELECT session_id, queue_state FROM sessions "
                    "WHERE state = 'running' AND queue_state IS NOT NULL"
                )
                rows = cur.fetchall()
        finally:
            db.close()

        for row in rows:
            try:
                session_queues[row["session_id"]] = json.loads(row["queue_state"])
                log.info("Restored queue_state for session %s from DB", row["session_id"])
            except Exception as exc:
                log.warning("Failed to parse queue_state for session %s: %s", row["session_id"], exc)
    except Exception as exc:
        # DB อาจยังไม่พร้อมตอน boot — อย่าทำให้แอปบูตไม่ขึ้นเพราะเรื่องนี้ แค่
        # log ไว้ (session ที่ running อยู่ตอน restart แบบนี้จะพลาดการกู้คืนคิว
        # แต่ยังใช้งานต่อได้ปกติถ้าไม่ใช่ queue-based หรือกด Stop แล้วเริ่มใหม่)
        log.warning("Reload session_queues failed: %s", exc)

async def heartbeat_checker() -> None:
    """ตรวจเป็นระยะว่า session ที่ 'running' ยังได้ heartbeat จาก Agent ต่อเนื่องไหม

    หมายเหตุ: ก่อนหน้านี้เคยถอดกลไกนี้ออกไปเพราะตอนนั้น Agent/Backend/Web รันอยู่
    บนเครื่องเดียวกันหมด คิดว่าไม่จำเป็น — ตอนนี้เอากลับมาใหม่ตามที่ตกลงกันไว้
    เป็น safety net เผื่อ Agent process ตาย/แฮงค์กลาง session (ไม่ใช่แค่ network
    หลุดข้ามเครื่องเหมือนเหตุผลเดิม) ถ้าเงียบเกิน HEARTBEAT_TIMEOUT วิ จะ mark
    session เป็น 'timeout' อัตโนมัติ แล้วแจ้ง web ผ่าน SSE (`session_timeout` —
    index.html มี handler นี้อยู่แล้ว แค่ก่อนหน้านี้ไม่มีใคร emit ให้)
    """
    while True:
        await asyncio.sleep(HEARTBEAT_INTERVAL)
        try:
            db = get_db()
        except HTTPException as exc:
            log.warning("heartbeat_checker: DB unreachable, skip this round: %s", exc.detail)
            continue

        timed_out: List[int] = []
        try:
            with db.cursor() as cur:
                cur.execute(
                    "SELECT session_id FROM sessions "
                    "WHERE state = 'running' AND last_seen < NOW() - INTERVAL %s SECOND",
                    (HEARTBEAT_TIMEOUT,),
                )
                timed_out = [row["session_id"] for row in cur.fetchall()]
                for sid in timed_out:
                    cur.execute(
                        "UPDATE sessions SET state = 'timeout', ended_at = NOW() "
                        "WHERE session_id = %s",
                        (sid,),
                    )
        except Exception as exc:
            log.warning("heartbeat_checker: check failed: %s", exc)
            timed_out = []
        finally:
            db.close()

        for sid in timed_out:
            session_queues.pop(sid, None)
            measure_timeouts.pop(sid, None)  # คำถามค้างของ session ที่ตายไปแล้ว ไม่มีใครตอบได้อีก
            log.warning("Session %s: ไม่ได้ heartbeat เกิน %ss — mark เป็น 'timeout'", sid, HEARTBEAT_TIMEOUT)
            await push_event("session_timeout", {"session_id": sid})

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Hook ตอน FastAPI เริ่มทำงาน (startup) และตอนปิด (shutdown)

    ทำไม: ตรงนี้คือจุดที่ background task (heartbeat_checker) ถูกสั่งให้เริ่ม
    ทำงานตอนแอป boot แทนที่จะไปสั่งเริ่มภายใน request handler ส่วน
    _reload_session_queues() ต้อง await ให้เสร็จก่อน yield เพราะต้องกู้คืนคิว
    ให้ครบก่อนรับ request
    """
    asyncio.create_task(heartbeat_checker())     # fire-and-forget, never blocks
    asyncio.create_task(_deleted_purge_loop())   # ล้างถังขยะที่เกินอายุ
    await _reload_session_queues()               # ต้องเสร็จก่อนรับ request
    yield




def mark_pi_seen():
    """บันทึกว่า "เพิ่งเห็น Pi เดี๋ยวนี้" — เรียกจาก POST /api/heartbeat ทุกครั้ง

    เก็บใน memory ล้วน **ไม่แตะ DB เลย** ทั้งฝั่งเขียน (ตรงนี้) และฝั่งอ่าน
    (read_pi_status)

    ── ทำไมไม่เก็บลง DB ─────────────────────────────────────────────────────
    ค่านี้ตอบคำถาม "Pi ยังอยู่ไหม ณ วินาทีนี้" ซึ่ง **หมดอายุใน PI_ONLINE_TIMEOUT
    วินาที** โดยธรรมชาติ — last_seen ของเมื่อ 5 นาทีที่แล้วบอกอะไรไม่ได้เลย
    ต่างจากผลการวัด/ทะเบียน ALPL ที่หายไม่ได้ ของที่ตายเองอยู่แล้วไม่ต้องจดใส่
    กระดาษถาวร

    เคยมีตาราง `pi_status` เก็บสำเนาไว้ (แถวเดียว UPDATE ทับไปเรื่อยๆ) ประโยชน์
    มีอย่างเดียวคือกู้ค่ากลับตอน Backend restart เพื่อไม่ให้ชิปกระพริบ 🟡 ราว 2 วิ
    ต้นทุนคือ UPDATE 1 แถวทุก HEARTBEAT_INTERVAL = 43,200 ครั้ง/วัน ซึ่งลง binary
    log ทั้งหมด (~200-300 MB/เดือน) แลกกับความสบายตาตอน `--reload` เท่านั้น —
    หน้างานจริง Backend รันยาว แทบไม่รีสตาร์ทเลย จึงถอดออก
    (ลบตารางทิ้งด้วย sql-tools/drop_pi_status.sql ถ้า DB เก่ายังมีอยู่)

    ผลพลอยได้: หมดปัญหานาฬิกา MySQL vs Python เพราะทั้งเขียนและอ่านอยู่ฝั่ง
    Python ทั้งคู่ (เดิมต้องระวังว่า MySQL ใน Docker คนละโซนกับ host)
    """
    global _pi_last_seen
    _pi_last_seen = datetime.now()


def read_pi_status():
    """คืน True/False/None — Pi ยัง heartbeat เข้ามาภายใน PI_ONLINE_TIMEOUT ไหม

    อ่านจาก memory ล้วน ไม่แตะ DB เลย จึงเรียกถี่แค่ไหนก็ได้

        True  = เห็น Pi ภายใน PI_ONLINE_TIMEOUT
        False = เงียบเกินเกณฑ์แล้ว
        None  = **ไม่ทราบ** — ยังไม่เคยเห็น Pi เลยตั้งแต่ Backend บูต

    None ต่างจาก False ตรงที่ "เราไม่มีข้อมูล" ไม่ใช่ "รู้แน่ว่าตาย" — หน้าเว็บ
    ต้องแสดงคนละแบบ และปุ่ม Start ล็อกทั้งคู่

    หลัง Backend restart จะเป็น None อยู่ไม่เกิน HEARTBEAT_INTERVAL วิ แล้วหายเอง
    ตอน heartbeat ตัวถัดไปมาถึง — ระหว่างนั้นชิปขึ้น 🟡 และปุ่ม Start ล็อก ซึ่ง
    **ถูกต้องตามความหมาย** เพราะในวินาทีนั้นเราไม่รู้จริงๆ ว่า Pi เป็นยังไง
    (เดิมมีการกู้ค่าจากตาราง pi_status เพื่อข้ามช่วงนี้ ถอดออกแล้ว — ดู mark_pi_seen)
    """
    if _pi_last_seen is None:
        return None
    return (datetime.now() - _pi_last_seen).total_seconds() <= PI_ONLINE_TIMEOUT



async def _deleted_purge_loop():
    """ล้างถังขยะที่เกินอายุ — ทำทันทีตอนเริ่ม แล้ววนซ้ำวันละครั้ง

    ทำตอนเริ่มด้วยเพราะเครื่องหน้างานมักถูกปิดกลางคืน ถ้ารอครบ 24 ชั่วโมงอย่างเดียว
    อาจไม่มีวันได้ทำเลย
    """
    while True:
        try:
            _purge_old_deleted()
        except Exception as exc:
            log.warning("ล้างถังขยะไม่สำเร็จ: %s", exc)
        await asyncio.sleep(24 * 60 * 60)

# ══════════════════════════════════════════════════════════════════════════════
# Session endpoints
# ══════════════════════════════════════════════════════════════════════════════
class StopSessionRequest(BaseModel):
    session_id: int
    # Pi ส่งมาตอนล้มเลิกเอง (ER,PW / T1 retry ครบ / สาย TM-X ขาด) — หน้าเว็บไม่ส่ง
    reason: str | None = None

def _get_template_name_for_alpl(cur, first_alpl: int) -> str:
    """Query หา template_name (ชื่อโปรแกรมวัดของ TM-X) ของ ALPL ที่จะเริ่มวัด
    — ใช้ทั้งโหมด IPM และ Rework (New ส่ง template_name มาใน payload เอง)

    **template ผูกกับ `package_size` ไม่ใช่ `part_number`** — ตัวกำหนดโปรแกรม
    วัดคือขนาดของ package ไม่ใช่รุ่นของ part ดังนั้นสายที่ถูกต้องคือ

        parts_specifications.package_size_id → package_size.template_id → template

    เดิมโค้ดนี้เดินอ้อมผ่าน `part_number` ทั้งที่ปลายทางคือ `package_size` อยู่ดี
    ผลคือ ALPL ที่ลงทะเบียนแบบ IPM (กรอกแค่ ALPL + Package Size ไม่มี Part
    Number) เริ่มวัดไม่ได้เลยทั้งที่ข้อมูลครบพอจะหา template ได้แล้ว

    ยังเก็บทางอ้อมผ่าน `part_number` ไว้เป็น fallback (COALESCE) เพราะ Part ที่
    ลงทะเบียนไว้ก่อนมีคอลัมน์ `parts_specifications.package_size_id` จะมีแต่
    part_number_id — ถ้าตัดทิ้งเลย ข้อมูลเก่าทั้งหมดจะวัดไม่ได้ทันทีที่ deploy

    ใช้ LEFT JOIN ทุกทอดเพื่อ "วินิจฉัย" ได้ว่าสายขาดตรงข้อไหน ของเดิมใช้ INNER
    JOIN แล้วได้ 0 แถว จึงบอกได้แค่ว่า "ยังไม่ได้ตั้ง part_number" ซึ่งชี้ผิดจุด
    บ่อย เพราะจริงๆ อาจตั้งไว้แล้วแต่ Package Size ยังไม่ได้ผูก Template
    """
    cur.execute(
        "SELECT p.part_number_id, p.package_size_id AS part_pkg_id, "
        "       pn.package_size_id AS pn_pkg_id, "
        "       COALESCE(p.package_size_id, pn.package_size_id) AS pkg_id, "
        "       ps.package_size, ps.template_id, t.template_name "
        "FROM parts_specifications p "
        "LEFT JOIN part_number pn  ON p.part_number_id = pn.part_number_id "
        "LEFT JOIN package_size ps ON ps.package_size_id = "
        "                             COALESCE(p.package_size_id, pn.package_size_id) "
        "LEFT JOIN template t      ON ps.template_id = t.template_id "
        "WHERE p.number_alpl = %s",
        (first_alpl,),
    )
    row = cur.fetchone()

    head = f"เริ่มวัด ALPL {first_alpl} ไม่ได้ —"
    if row is None:
        raise HTTPException(404, f"{head} ยังไม่ได้ลงทะเบียน ALPL นี้ในตาราง Parts")
    if row["pkg_id"] is None:
        raise HTTPException(
            404,
            f"{head} ยังไม่ได้ผูก Package Size ให้ ALPL นี้ "
            f"(แก้ที่หน้า Edit › Parts — จะตั้งผ่าน Part Number ก็ได้)",
        )
    if row["package_size"] is None:
        raise HTTPException(
            404,
            f"{head} Package Size ที่ผูกไว้ถูกลบไปแล้ว (package_size_id = {row['pkg_id']}) "
            f"— เลือกใหม่ที่หน้า Edit › Parts",
        )
    if row["template_id"] is None:
        raise HTTPException(
            404,
            f"{head} Package Size \"{row['package_size']}\" ยังไม่ได้ตั้ง Template ของเครื่อง TM-X "
            f"(แก้ที่หน้า Edit › Lookup Tables › Package Size) — ไม่เกี่ยวกับ Part Number",
        )
    if row["template_name"] is None:
        raise HTTPException(
            404,
            f"{head} Template ที่ Package Size \"{row['package_size']}\" ผูกไว้ถูกลบไปแล้ว "
            f"(template_id = {row['template_id']})",
        )
    return row["template_name"]

measure_timeouts: dict[int, dict] = {}

class MeasureTimeoutRequest(BaseModel):
    session_id: int
    piece: int | None = None
    target: int | None = None

class SessionEventRequest(BaseModel):
    """Recieve_tm-x.py แจ้งสาเหตุที่มัน "ทิ้งค่า" ไปโดยไม่บันทึกลง DB

    ไม่มี session_id — Recieve ไม่รู้ในบางด่าน (ด่าน 1-2 เกิดก่อนด่าน 3 ที่เป็น
    ตัวถาม session) Backend จึงแนบเข้ากับ session ที่ running อยู่ตอนนั้นเอง

    persist=False → ยิง SSE เตือนอย่างเดียว ไม่เขียนลง last_event
                    ใช้กับเรื่องที่ "ค่าลง DB ไปแล้ว" เช่นรูปอัปโหลดไม่สำเร็จ
    """
    event:   str
    detail:  str | None = None
    persist: bool = True

class SessionContinueRequest(BaseModel):
    session_id: int

LAST_EVENT_FRESH_SEC = 30

class HeartbeatRequest(BaseModel):
    session_id: Optional[int] = None

_TABLE_DISPLAY_NAME = {
    "parts_specifications": "Part",
    "measurements":         "Measurement",
    "part_number":          "Part Number",
    "package_size":         "Package Size",
}

class LookupCreate(BaseModel):
    name: str

class LookupUpdate(BaseModel):
    name: str

# nominal/tolerance ทั้ง 5 ตัวเป็น FLOAT NOT NULL ใน DB (ดู init.sql) จึงบังคับ
# ให้ส่งมาครบตอน Create — ต่างจาก template_name ที่ nullable ได้
class PackageSizeCreate(BaseModel):
    package_size:  str
    nominal_x:     float
    nominal_y:     float
    upper_tol:     float
    lower_tol:     float
    offset_tol:    float
    template_name: Optional[str] = None

class PackageSizeUpdate(BaseModel):
    package_size:  Optional[str] = None
    nominal_x:     Optional[float] = None
    nominal_y:     Optional[float] = None
    upper_tol:     Optional[float] = None
    lower_tol:     Optional[float] = None
    offset_tol:    Optional[float] = None
    template_name: Optional[str] = None

_PKG_NUM_FIELDS = ("nominal_x", "nominal_y", "upper_tol", "lower_tol", "offset_tol")

class PartNumberCreate(BaseModel):
    part_number_name: str
    package_size:     str
    handler:          str
    nominal_x:        float
    nominal_y:        float
    upper_tol:        float
    lower_tol:        float
    # มี default 0 เพื่อให้ payload เก่าที่ยังไม่ส่ง offset_tol มา ยัง POST ผ่านได้
    offset_tol:       float = 0

class PartNumberUpdate(BaseModel):
    part_number_name: Optional[str] = None
    package_size:     Optional[str] = None
    handler:          Optional[str] = None
    nominal_x:        Optional[float] = None
    nominal_y:        Optional[float] = None
    upper_tol:        Optional[float] = None
    lower_tol:        Optional[float] = None
    offset_tol:       Optional[float] = None

PARTS_SELECT = """
    SELECT p.part_id, p.number_alpl, pn.part_number_name AS part_number,
           p.description, p.po_number,
           p.recieve_date   AS recieve_date,
           h.handler_name   AS handler,
           v.vendor_name    AS vendor,
           o.owner_name     AS owner,
           ps.package_size  AS package_size,
           pn.nominal_x     AS nominal_x,
           pn.nominal_y     AS nominal_y,
           pn.upper_tol     AS upper_tol,
           pn.lower_tol     AS lower_tol,
           pn.offset_tol    AS offset_tol,
           ps.nominal_x     AS nominal_x_pkg,
           ps.nominal_y     AS nominal_y_pkg,
           ps.upper_tol     AS upper_tol_pkg,
           ps.lower_tol     AS lower_tol_pkg,
           ps.offset_tol    AS offset_tol_pkg,
           t.template_name  AS template_name
    FROM parts_specifications p
    LEFT JOIN part_number pn  ON p.part_number_id = pn.part_number_id
    LEFT JOIN handler h       ON pn.handler_id = h.handler_id
    LEFT JOIN vendor v        ON p.vendor_id = v.vendor_id
    LEFT JOIN owner o         ON p.owner_id = o.owner_id
    LEFT JOIN package_size ps ON ps.package_size_id =
                                 COALESCE(p.package_size_id, pn.package_size_id)
    LEFT JOIN template t      ON ps.template_id = t.template_id
"""

def _lookup_id(cur, table: str, id_col: str, name_col: str, value: Optional[str]) -> Optional[int]:
    """แปลงชื่อ (เช่น vendor_name ที่ frontend ส่งมาจาก dropdown) เป็น id
    (เช่น vendor_id) จากตาราง lookup ที่เกี่ยวข้อง

    ทำไม: dropdown ฝั่ง frontend (Operator/Owner/Vendor/Handler/
    Package Size) เป็น dropdown "ปิด" — เลือกได้เฉพาะค่าที่มีอยู่แล้วใน DB
    เท่านั้น ไม่มีช่องพิมพ์ค่าใหม่ ดังนั้นค่าที่ส่งเข้ามาควรมีอยู่จริงเสมอ แต่ยัง
    defensive เช็คไว้กันกรณี frontend ค้างข้อมูลเก่า/ผิดพลาด — ถ้าหาไม่เจอ
    ให้ 400 ชัดเจนแทนที่จะปล่อยให้ FK constraint error กลายเป็น 500 ตอน insert
    """
    if value in (None, ""):
        return None
    cur.execute(f"SELECT {id_col} FROM {table} WHERE {name_col} = %s", (value,))
    row = cur.fetchone()
    if not row:
        raise HTTPException(400, f"ไม่พบค่า '{value}' ใน {table} (เลือกจาก dropdown เท่านั้น)")
    return row[id_col]

def _block_if_session_running(cur, action: str) -> None:
    """เช็คว่ามี session ไหนกำลัง running อยู่ไหม — ถ้ามี ปฏิเสธการแก้ไข/ลบ Part
    หรือ Measurement ทันที (ทั้งคู่ ไม่ว่า ALPL ไหน) เพราะข้อมูลกำลังถูกวัดอยู่จริง

    ทำไมต้อง block กว้างขนาดนี้ (ไม่ใช่แค่ ALPL ที่กำลังวัดอยู่): ผู้ใช้เลือกไว้
    ชัดเจนว่าอยากให้ Edit/Delete กดไม่ได้เลยทั้ง Part และ Measurement ตราบใดที่
    ยังมี session running อยู่ — เพื่อความคาดเดาได้ง่าย ไม่ต้องตามว่า ALPL ไหน
    "ปลอดภัย" ไหม (ระบบรัน session พร้อมกันได้แค่ 1 อันเสมออยู่แล้ว — ดู
    Button Guard ใน start_session — เช็คแค่ "มี session running อยู่ไหม" จึง
    เทียบเท่ากับ "session ปัจจุบันกำลังวัดอยู่ไหม")

    ╔═══ เพิ่ม Export เข้ามาด้วย — 7 ส.ค. 2569 ════════════════════════════════╗
    เดิมกันแค่ Edit/Delete ส่วน Export กดได้ตลอดเวลา — แต่ endpoint ของ export
    เป็น `async def` ที่เรียก pymysql (sync ล้วน ไม่คืน control) จึง **บล็อก event
    loop ทั้งเส้นระหว่างทำงาน** และ export มีเพดานถึง REPORT_MAX_ROWS แถว

        มีคนกด Export XLSX ระหว่างวัด ใช้ 20 วิ
        → event loop ค้าง → heartbeat ของ Pi เข้าไม่ได้เลย 4 รอบติด
        → loop คลาย → heartbeat_checker เห็น last_seen เก่า 20 วิ
        → session ที่วัดอยู่ดีๆ กลายเป็น 'timeout' ทั้งที่ Pi ปกติทุกอย่าง

    ล็อก Export ตอนวัดปิดช่องนี้ได้หมด โดยไม่ต้องไล่แก้ endpoint อีก 56 ตัวที่เป็น
    `async def` แต่ไม่มี `await` (ตัวอื่น query เล็กระดับมิลลิวินาที ไม่เป็นปัญหา)

    ⚠ ห้ามใส่ guard นี้ใน endpoint ที่ต้องใช้ได้ตอนยังไม่เริ่มวัด เช่น
      /api/parts/check (ดู PLAN_criteria_and_multigroup.md ข้อ D6)
    ╚═══════════════════════════════════════════════════════════════════════╝
    """
    cur.execute("SELECT 1 FROM sessions WHERE state = 'running' LIMIT 1")
    if cur.fetchone():
        raise HTTPException(
            409,
            f"ไม่สามารถ{action}ข้อมูลได้ขณะนี้ — กำลังมีการวัดอยู่ "
            f"กรุณากด Stop ก่อนแล้วค่อยดำเนินการ",
        )

class PartCreate(BaseModel):
    # schema: parts_specifications ไม่เก็บ handler/package_size/nominal/
    # tolerance/template_name ตรงๆ เลย — ทั้งหมด derive มาจาก part_number_id
    # ตัวเดียว (ดู init.sql: part_number ผูก package_size_id + handler_id +
    # nominal/tolerance ของตัวเองไว้แล้ว) เลือก part_number ก็ map ค่าพวกนี้
    # ให้อัตโนมัติหมด ไม่ต้องส่ง handler/package_size แยกมาที่ endpoint นี้อีก
    # (frontend ยังส่ง package_size มาด้วยเพื่อใช้ cascade dropdown Part Number
    # เฉยๆ — เป็นแค่ field ส่วนเกินที่ endpoint นี้เพิกเฉยไม่ได้ใช้)
    #
    # part_number เป็น Optional เพราะตอน IPM เจอ ALPL ที่ยังไม่เคยลงทะเบียน
    # (ดู POST /api/session/start) จะลงทะเบียน part ใหม่แบบขั้นต่ำผ่าน endpoint
    # นี้ — อาจมีแค่ number_alpl เท่านั้น ยังไม่รู้ part_number จริง (แต่ถ้าไม่รู้
    # part_number จะหา template_name ไม่เจอตอน start_session — ต้องตั้งให้
    # ครบก่อนถึงจะเริ่มวัดได้จริง)
    #
    # vendor/owner ยังเป็น FK ไป lookup table เหมือนเดิม — frontend ส่งมาเป็น
    # "ชื่อ" (string จาก dropdown) แล้ว backend resolve เป็น id เอง (ดู _lookup_id)
    #
    # recieve_date เป็น Optional — ถ้าไม่ส่งมา/ส่งค่าว่าง จะถูกบันทึกเป็น NULL
    # ตรงๆ (เว้นว่างแล้วว่างจริง ไม่เติมวันที่ปัจจุบันให้อัตโนมัติ — ดู
    # _insert_part_row)
    number_alpl:   int
    part_number:   Optional[str] = None
    description:   Optional[str] = None
    vendor:        Optional[str] = None
    po_number:     Optional[int] = None
    package_size:  Optional[str] = None  # ไม่ได้ใช้ resolve อะไรที่นี่ (เก็บไว้เผื่อ frontend ส่งมา)
    owner:         Optional[str] = None
    recieve_date:  Optional[str] = None

class PartsCheckRequest(BaseModel):
    # แบบเดิม: ลิสต์แบนๆ ไม่รู้ว่าตัวไหนอยู่กลุ่มไหน — ยังใช้ได้ (เช็คแค่ มี/ไม่มี)
    alpl: List[int] = []
    # แบบใหม่: ส่งเป็นกลุ่มมาด้วย เพื่อให้ตรวจ "ในกลุ่มเดียวกันต้องเข้าชุดกัน" ได้
    #   groups: [{"alpl": [400, 401]}, {"alpl": [402]}]
    #   mode:   IPM | New | Rework — ตัวกำหนดว่าต้องตรงกันกี่ field
    groups: Optional[List[Dict[str, Any]]] = None
    mode: Optional[str] = None

_GROUP_MATCH_FIELDS = {
    "IPM":    [("package_size", "Package Size")],
    "Rework": [("package_size", "Package Size"), ("part_number", "Part Number")],
    "New":    [],
}

def _insert_part_row(cur, number_alpl: int, config: Dict[str, Any]) -> None:
    """Insert 1 row ลง table `parts_specifications` โดยใช้ number_alpl ที่ระบุ
    + field อื่นจาก `config` (dict ของ field part_number/vendor/owner ฯลฯ) —
    part_number/vendor/owner รับมาเป็น "ชื่อ" (ตรงกับค่าที่เลือกจาก dropdown
    ฝั่ง frontend) แล้ว resolve เป็น id ก่อน insert

    หมายเหตุ: handler/package_size ไม่ได้ resolve/insert ตรงนี้แล้ว เพราะ
    schema ใหม่ derive ค่าพวกนี้มาจาก part_number_id ทั้งหมด (part_number
    catalog ผูก package_size_id + handler_id ของตัวเองไว้แล้ว — ดู init.sql)

    ใช้ร่วมกันทั้งจาก endpoint POST /api/parts ปกติ, จาก flow ของ New queue ที่
    ALPL หลายตัวใช้ config เดียวกันซ้ำ, และจากการลงทะเบียน part แบบขั้นต่ำตอน
    IPM เจอ ALPL ที่ยังไม่เคยลงทะเบียน (ดู start_session / create_measurement)
    """
    part_number_id = _lookup_id(cur, "part_number", "part_number_id", "part_number_name", config.get("part_number"))
    vendor_id      = _lookup_id(cur, "vendor",      "vendor_id",      "vendor_name",      config.get("vendor"))
    owner_id       = _lookup_id(cur, "owner",       "owner_id",       "owner_name",       config.get("owner"))
    # package_size_id เก็บตรงที่ Part ด้วย (ไม่ derive ผ่าน part_number อย่างเดียว
    # เหมือนเดิม) เพราะโหมด IPM ลงทะเบียน Part จากฟอร์มที่มีแค่ ALPL + Package Size
    # ยังไม่รู้ Part Number — ถ้าไม่เก็บไว้ตรงนี้จะหา template/เกณฑ์ให้มันไม่ได้เลย
    package_size_id = _lookup_id(cur, "package_size", "package_size_id", "package_size", config.get("package_size"))

    # recieve_date: ใส่คอลัมน์นี้ใน INSERT เสมอ แม้จะเป็นค่าว่าง (จะได้ NULL) —
    # ตั้งใจให้ "เว้นว่างแล้วว่างจริง" ไม่ใช่เติมวันที่ปัจจุบันให้อัตโนมัติ
    # (ถ้าไม่ใส่คอลัมน์นี้เลย DEFAULT CURRENT_TIMESTAMP ของ schema จะทำงานแทน
    # ซึ่งไม่ใช่พฤติกรรมที่ต้องการ)
    columns = [
        "number_alpl", "part_number_id", "package_size_id", "description",
        "vendor_id", "po_number", "owner_id", "recieve_date",
    ]
    values: List[Any] = [
        number_alpl, part_number_id, package_size_id, config.get("description"),
        vendor_id, config.get("po_number"), owner_id,
        config.get("recieve_date") or None,
    ]

    placeholders = ", ".join(["%s"] * len(values))
    cur.execute(
        f"INSERT INTO parts_specifications ({', '.join(columns)}) VALUES ({placeholders})",
        tuple(values),
    )

MEASUREMENTS_SELECT = """
    SELECT m.*, op.operator_name AS operator_name,
           CASE WHEN m.measure_type = 'IPM' THEN ips.nominal_x  ELSE pn.nominal_x  END AS nominal_x,
           CASE WHEN m.measure_type = 'IPM' THEN ips.nominal_y  ELSE pn.nominal_y  END AS nominal_y,
           CASE WHEN m.measure_type = 'IPM' THEN ips.upper_tol  ELSE pn.upper_tol  END AS upper_tol,
           CASE WHEN m.measure_type = 'IPM' THEN ips.lower_tol  ELSE pn.lower_tol  END AS lower_tol,
           CASE WHEN m.measure_type = 'IPM' THEN NULL           ELSE pn.offset_tol END AS offset_tol
    FROM measurements m
    LEFT JOIN operator op ON m.operator_id = op.operator_id
    LEFT JOIN parts_specifications p ON m.number_alpl = p.number_alpl
    LEFT JOIN part_number pn ON p.part_number_id = pn.part_number_id
    LEFT JOIN package_size ips
           ON ips.package_size_id = COALESCE(p.package_size_id, pn.package_size_id)
"""

# main.py

class MeasurementCreate(BaseModel):
    session_id:  Optional[int] = None
    number_alpl: Optional[int] = None
    value_x:     float
    value_y:     float

    # ── ค่า Offset แต่ละแกน ──────────────────────────
    offset_ghx:  float = 0.0
    offset_ghy:  float = 0.0
    offset_opx:  float = 0.0
    offset_opy:  float = 0.0

    # ── ค่า Offset 4 มุมของ GH ───────────────────────
    tr_gh:       float = 0.0
    tl_gh:       float = 0.0
    br_gh:       float = 0.0
    bl_gh:       float = 0.0

    # ── ค่า Offset 4 มุมของ OP ───────────────────────
    tr_op:       float = 0.0
    tl_op:       float = 0.0
    br_op:       float = 0.0
    bl_op:       float = 0.0

    note:        Optional[str] = None
    client_uuid: Optional[str] = None

class ImageUpdate(BaseModel):
    # image_path เป็น Optional แล้ว — กรณี Agent จัดการรูปไม่สำเร็จ
    # จะ PATCH มาด้วย image_path=None,
    # upload_failed=True แทน เพื่อให้ backend รู้ว่า "พยายามแล้วแต่ไม่สำเร็จ"
    # ต่างจาก "ยังไม่เคยพยายามเลย" (NULL เฉยๆ ตอน insert)
    image_path:    Optional[str] = None
    upload_failed: bool = False

# ⚠⚠ FROM + JOIN ของหน้า Export มีที่เดียวคือตรงนี้ — EXPORT_SELECT (ดึงข้อมูล)
#     กับ query ที่ใช้ COUNT/กรอง ต้องใช้ก้อนเดียวกันเสมอ
#
#     เดิมประกาศแยกกัน 2 ที่แล้วเนื้อในไม่ตรงกัน: ตัวดึงข้อมูล join package_size
#     ด้วย COALESCE(p.package_size_id, pn.package_size_id) แต่ตัวนับ join ด้วย
#     pn.package_size_id อย่างเดียว ผลคือ **ชิ้นงานโหมด IPM หายจากการกรอง
#     Package Size ทั้งหมด** เพราะ IPM ลงทะเบียนโดยไม่มี part_number (part_number_id
#     เป็น NULL ได้ — ดู CLAUDE.md หัวข้อ Database Schema) พอ pn เป็น NULL แล้ว
#     ps ก็ NULL ตาม ทั้งที่ Part ตัวนั้นมี package_size ของตัวเองอยู่
#     อาการที่เห็น: กรอง Package Size แล้วได้แต่รายการโหมด New
COALESCE_PKG = "COALESCE(p.package_size_id, pn.package_size_id)"

_EXPORT_FROM = f"""
    FROM measurements m
    LEFT JOIN operator op             ON m.operator_id = op.operator_id
    LEFT JOIN parts_specifications p  ON m.number_alpl = p.number_alpl
    LEFT JOIN part_number pn          ON p.part_number_id = pn.part_number_id
    LEFT JOIN handler h               ON pn.handler_id = h.handler_id
    LEFT JOIN package_size ps         ON ps.package_size_id = {COALESCE_PKG}
    LEFT JOIN template t              ON ps.template_id = t.template_id
    LEFT JOIN vendor v                ON p.vendor_id = v.vendor_id
    LEFT JOIN owner o                 ON p.owner_id = o.owner_id
"""

EXPORT_SELECT = """
    SELECT m.measurement_id, m.session_id, m.number_alpl, m.value_x, m.value_y,
           m.`offset` AS `offset`,
           m.result, m.note, m.measure_type, m.timestamp,
           op.operator_name,
           pn.part_number_name,
           CASE WHEN m.measure_type = 'IPM' THEN ps.nominal_x  ELSE pn.nominal_x  END AS nominal_x,
           CASE WHEN m.measure_type = 'IPM' THEN ps.nominal_y  ELSE pn.nominal_y  END AS nominal_y,
           CASE WHEN m.measure_type = 'IPM' THEN ps.upper_tol  ELSE pn.upper_tol  END AS upper_tol,
           CASE WHEN m.measure_type = 'IPM' THEN ps.lower_tol  ELSE pn.lower_tol  END AS lower_tol,
           CASE WHEN m.measure_type = 'IPM' THEN NULL          ELSE pn.offset_tol END AS offset_tol,
           h.handler_name, ps.package_size, t.template_name,
           v.vendor_name, o.owner_name,
           p.po_number, p.description, p.recieve_date
""" + _EXPORT_FROM

def _fmt_num(v, digits: int = 3):
    return "" if v is None else f"{float(v):.{digits}f}"

def _fmt_timestamp(r, fmt: str = "datetime") -> str:
    """วันเวลาของการวัด — เลือกได้ว่าจะเอาอะไรบ้าง (ผู้ใช้ติ๊กในหน้าแก้ผังรายงาน)
    date      → 30/07/2569 แบบ DD/MM/YYYY
    time      → 14:23:11
    datetime  → ทั้งคู่
    """
    ts = r["timestamp"]
    if not ts:
        return ""
    if fmt == "time":
        return ts.strftime("%H:%M:%S")
    if fmt == "date":
        return ts.strftime("%d/%m/%Y")
    return ts.strftime("%d/%m/%Y %H:%M:%S")

_TIME_FORMATS = [
    {"key": "date",     "label": "Date"},
    {"key": "time",     "label": "Time"},
    {"key": "datetime", "label": "Date & Time"},
]

def _axis_state(r, axis: str) -> str:
    """ค่าที่วัดได้ของแกนนี้ อยู่ในสเปกไหม — คืน "OK"/"NG" ("" ถ้าเทียบไม่ได้)

    ต่างจาก Result ที่เป็นค่าดิบใน DB อยู่แล้ว — อันนี้ต้องคำนวณเทียบสเปกทีละแกน
    เพราะ Result เป็นผลรวมของทั้ง X และ Y (X ผ่านแต่ Y ไม่ผ่าน → Result = NG
    ทั้งที่ตัวเลข X เองอยู่ในสเปก) ถ้าเอา Result มาใช้ระบายสีช่อง X จะสีผิด
    """
    val = r[f"value_{axis}"]
    nom = r[f"nominal_{axis}"]
    if val is None or nom is None or r["upper_tol"] is None or r["lower_tol"] is None:
        return ""
    return "OK" if _within_tolerance(val, nom, r["upper_tol"], r["lower_tol"]) else "NG"

def _tolerance_spec(r) -> str:
    """สเปกขนาดชิ้นงานแบบย่อบรรทัดเดียว — ใช้ในรายงาน PDF/Excel เท่านั้น

    รูปแบบ: "<nominal>  +<upper>  -<lower>" เช่น "9.02  +0.03  -0.01"
    ถ้า nominal X กับ Y ไม่เท่ากัน (package ไม่ใช่ทรงจัตุรัส) จะคั่นด้วย "/"
    เป็น "3.28/7.43  +0.02  -0.01" — ที่ยุบเลขเดียวตอน X=Y เพราะรายงาน
    ที่ห้อง PM Kit ใช้อยู่เขียนแบบนั้น (ดูตัวอย่างที่ผู้ใช้ให้มา)

    ทศนิยม 2 ตำแหน่งเท่านั้น (ไม่ใช่ 3 ตำแหน่งแบบ _fmt_num ปกติ) เพราะสเปก
    บนแบบชิ้นงานเขียนแค่ 2 ตำแหน่ง — ส่วนค่าที่วัดได้จริง (value_x/value_y)
    ยังใช้ 3 ตำแหน่งเหมือนเดิม เพราะต้องเห็นความละเอียดของการวัด

    หมายเหตุ: หน้า Export CSV ยังใช้คอลัมน์แยก (nominal_x/nominal_y/
    upper_tol/lower_tol) เหมือนเดิม ไม่ได้ถูกยุบตาม — ตั้งใจให้ CSV แยกช่อง
    เพื่อเอาไปคำนวณต่อได้ ส่วนรายงานเน้นอ่านง่ายบนกระดาษ
    """
    d = 2
    nx, ny = r["nominal_x"], r["nominal_y"]
    if nx is None and ny is None:
        nom = ""
    elif nx is None or ny is None:
        nom = _fmt_num(nx if nx is not None else ny, d)
    elif abs(float(nx) - float(ny)) < _TOL_EPS:
        nom = _fmt_num(nx, d)
    else:
        nom = f"{_fmt_num(nx, d)}/{_fmt_num(ny, d)}"

    parts = [p for p in (nom,
                         f"+{_fmt_num(r['upper_tol'], d)}" if r["upper_tol"] is not None else "",
                         f"-{_fmt_num(r['lower_tol'], d)}" if r["lower_tol"] is not None else "") if p]
    return "  ".join(parts)

EXPORT_COLUMNS: Dict[str, Dict[str, Any]] = {
    # row_number = ไม่ได้มาจาก DB — _render_report นับลำดับแถวให้ตอนคลี่ผัง
    # scope=report เพราะ CSV ไม่ต้องมีเลขลำดับ (Excel/โปรแกรมอื่นใส่เองได้)
    "item":          {"label": "Item",          "group": "ข้อมูลการวัด", "scope": "report",
                      "row_number": True, "get": lambda r: ""},
    "number_alpl":   {"label": "ALPL",          "group": "ข้อมูลการวัด",
                      "header": "Number ALPL", "get": lambda r: r["number_alpl"]},
    # Value X/Y เป็น scope=csv เพราะในรายงานมันไม่ยืนเดี่ยว — เป็นส่วนหนึ่งของ
    # บล็อก Tolerance เสมอ (ดู tolerance_spec ด้านล่าง)
    # values/state = ใช้ตั้ง "หน้าตาแยกตามค่า" ในรายงาน (เช่น เกินสเปกให้พื้นแดง)
    # state ของแกนต้องคำนวณเอง ไม่ใช้ Result เพราะ Result เป็นผลรวมของทั้ง X และ Y
    "value_x":       {"label": "Value X",       "group": "ข้อมูลการวัด", "scope": "csv",
                      "values": ["OK", "NG"], "state": lambda r: _axis_state(r, "x"),
                      "get": lambda r: _fmt_num(r["value_x"])},
    "value_y":       {"label": "Value Y",       "group": "ข้อมูลการวัด", "scope": "csv",
                      "values": ["OK", "NG"], "state": lambda r: _axis_state(r, "y"),
                      "get": lambda r: _fmt_num(r["value_y"])},
    # offset ไม่ได้เทียบกับช่วง nominal ± tol เหมือน X/Y แต่เทียบกับเพดาน
    # offset_tol ตัวเดียว จึงมี state เป็นของตัวเองไม่ใช้ _axis_state
    "offset":        {"label": "Offset",        "group": "ข้อมูลการวัด", "scope": "csv",
                      "values": ["OK", "NG"],
                      "state": lambda r: (
                          "" if r.get("offset") is None or r.get("offset_tol") is None
                          else ("OK" if _offset_ok(r.get("offset"), r.get("offset_tol")) else "NG")),
                      "get": lambda r: _fmt_num(r.get("offset"))},
    # ── บล็อก Tolerance (รายงานเท่านั้น) ────────────────────────────────
    # ลากครั้งเดียวได้ผังกว้าง 2 คอลัมน์ สูง 3 แถว:
    #   แถว 1  [        Tolerance        ]   ผสาน 2 คอลัมน์ — หัวตาราง
    #   แถว 2  [   ข้อมูล Tolerance      ]   ผสาน 2 คอลัมน์ — สเปกของกลุ่ม
    #   แถว 3   ข้อมูล Value X | ข้อมูล Value Y  แถวที่ทำซ้ำต่อ 1 การวัด
    # แถว 2 พิมพ์ครั้งเดียวต่อกลุ่ม เพราะรายงานถูกแบ่งกลุ่มด้วยสเปกนี้เสมอ
    #
    # label  = ชื่อชิปในแผงซ้าย (บอกว่าลากแล้วได้อะไรบ้าง)
    # header = ข้อความที่พิมพ์เป็นหัวตารางจริงในรายงาน — คนละอันกับ label
    #          เพราะหัวตารางบนกระดาษต้องสั้นว่า "Tolerance" เฉยๆ
    "tolerance_spec": {
        "label": "Tolerance + Value X/Y", "group": "ข้อมูลการวัด", "scope": "report",
        "get": _tolerance_spec,
        "block": {
            "cols": 2,
            "header": "Tolerance",
            "data": [{"key": "value_x", "label": "Value X"},
                     {"key": "value_y", "label": "Value Y"}],
        },
    },
    "result":        {"label": "Result",        "group": "ข้อมูลการวัด", "values": ["OK", "NG"],
                      "state": lambda r: r["result"] or "",
                      "get": lambda r: r["result"]},
    "note":          {"label": "Note",          "group": "ข้อมูลการวัด", "get": lambda r: r["note"] or ""},
    "operator":      {"label": "Operator",      "group": "ข้อมูลการวัด", "get": lambda r: r["operator_name"] or ""},
    "measure_type":  {"label": "Measure Type",  "group": "ข้อมูลการวัด", "get": lambda r: r["measure_type"] or ""},
    # header = ข้อความหัวตารางเริ่มต้นในรายงาน (ต่างจาก label ที่เป็นชื่อชิป/หัว CSV)
    # formats = รูปแบบที่ติ๊กเลือกได้บนเซลล์ — ค่าเริ่มต้นคือตัวแรกในลิสต์ (date)
    "timestamp":     {"label": "Date",          "csv_label": "Timestamp",
                      "group": "ข้อมูลการวัด",
                      "header": "Date", "formats": _TIME_FORMATS,
                      "get": lambda r: _fmt_timestamp(r, "datetime"),
                      "get_fmt": _fmt_timestamp},
    "session_id":    {"label": "Session",       "group": "ข้อมูลการวัด", "get": lambda r: r["session_id"]},

    "part_number":   {"label": "Part Number",   "group": "ข้อมูลชิ้นงาน", "get": lambda r: r["part_number_name"] or ""},
    "handler":       {"label": "Handler",       "group": "ข้อมูลชิ้นงาน", "get": lambda r: r["handler_name"] or ""},
    "package_size":  {"label": "Package Size",  "group": "ข้อมูลชิ้นงาน", "get": lambda r: r["package_size"] or ""},
    "template_name": {"label": "Template",      "group": "ข้อมูลชิ้นงาน", "get": lambda r: r["template_name"] or ""},
    # ── สเปกขนาด: CSV ใช้ 4 ช่องแยก / รายงาน PDF-Excel ใช้ช่องรวมช่องเดียว ──
    # scope บอกว่าคอลัมน์นี้โผล่ในหน้าไหน (ไม่ใส่ = โผล่ทั้งสองหน้า)
    "nominal_x":     {"label": "Nominal X",     "group": "ข้อมูลชิ้นงาน", "scope": "csv", "get": lambda r: _fmt_num(r["nominal_x"])},
    "nominal_y":     {"label": "Nominal Y",     "group": "ข้อมูลชิ้นงาน", "scope": "csv", "get": lambda r: _fmt_num(r["nominal_y"])},
    "upper_tol":     {"label": "Upper Tol",     "group": "ข้อมูลชิ้นงาน", "scope": "csv", "get": lambda r: _fmt_num(r["upper_tol"])},
    "lower_tol":     {"label": "Lower Tol",     "group": "ข้อมูลชิ้นงาน", "scope": "csv", "get": lambda r: _fmt_num(r["lower_tol"])},
    "vendor":        {"label": "Vendor",        "group": "ข้อมูลชิ้นงาน", "get": lambda r: r["vendor_name"] or ""},
    "owner":         {"label": "Owner",         "group": "ข้อมูลชิ้นงาน", "get": lambda r: r["owner_name"] or ""},
    "po_number":     {"label": "PO Number",     "group": "ข้อมูลชิ้นงาน", "get": lambda r: r["po_number"] if r["po_number"] is not None else ""},
    "description":   {"label": "Description",   "group": "ข้อมูลชิ้นงาน", "get": lambda r: r["description"] or ""},
    "recieve_date":  {"label": "Receive Date",  "group": "ข้อมูลชิ้นงาน", "get": lambda r: r["recieve_date"].strftime("%d/%m/%Y") if r["recieve_date"] else ""},
}

_LEGACY_COLUMN_ALIASES = {
    "nominal_xy": ["nominal_x", "nominal_y"],
    "tolerance":  ["upper_tol", "lower_tol"],
}

class ExportTemplateBody(BaseModel):
    name: str
    # เทมเพลต CSV ใช้ columns ส่วนเทมเพลตรายงาน (PDF/Excel) ใช้ layout
    # อย่างใดอย่างหนึ่งต้องมี (ดู _validate_template_body)
    columns: Optional[List[str]] = None
    layout:  Optional[Dict[str, Any]] = None
    kind:    str = "csv"

_RANGE_PART_RE = re.compile(r"^\s*(\d+)\s*(?:-\s*(\d+)\s*)?$")

_DATE_ONLY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

def _day_end(v):
    """ครอบปลายช่วงให้เต็มวัน — "2026-07-30" → "2026-07-30 23:59:59"

    ถ้าไม่ทำ MySQL จะตีค่าเป็น 00:00:00 แล้ว `timestamp <= ...` จะตัดการวัด
    ของวันสุดท้ายที่ผู้ใช้เลือกทิ้งทั้งวัน หน้าเว็บเติมเวลาให้อยู่แล้ว แต่ย้าย
    มาบังคับที่ backend ด้วย เพราะเป็นกติกาที่หน้าใหม่ (หรือคนที่ยิง API ตรงๆ)
    ไม่มีทางรู้ แล้วจะเจอบั๊กเดิมซ้ำ
    """
    return f"{v} 23:59:59" if isinstance(v, str) and _DATE_ONLY_RE.match(v.strip()) else v

def _day_start(v):
    return f"{v} 00:00:00" if isinstance(v, str) and _DATE_ONLY_RE.match(v.strip()) else v

REPORT_GROUP_BY = "tolerance_spec"

# พารามิเตอร์ filter ที่ /api/export/preview กับ /api/export/csv รับเหมือนกันทุกตัว
# (ประกาศเป็น Pydantic model แล้วใช้ Depends เพื่อไม่ต้องเขียนซ้ำ 2 ที่ และกัน
#  ลืมเพิ่มข้างใดข้างหนึ่งจนตัวอย่างกับไฟล์จริงไม่ตรงกัน)
def export_filters_dep(
    # ALPL เป็น str ไม่ใช่ int — รับได้ทั้ง "400", "400,500,600" และ
    # "400-407,500-507" (ดู _parse_int_ranges)
    number_alpl:  Optional[str] = None,
    date_from:    Optional[str] = None,
    date_to:      Optional[str] = None,
    recv_from:    Optional[str] = None,
    recv_to:      Optional[str] = None,
    session_id:   Optional[int] = None,
    po_number:    Optional[int] = None,
    description:  Optional[str] = None,
    # ── ช่องแบบเลือกได้หลายค่า (multi-select) ────────────────────────────
    # ส่งมาเป็น query param ซ้ำๆ เช่น ?vendor=A&vendor=B → กลายเป็น IN ('A','B')
    # ต้องประกาศเป็น dependency แบบฟังก์ชัน ไม่ใช่ Pydantic model + Depends()
    # เพราะ field ชนิด List ใน model ไม่ผูกกับ query param (ทดสอบแล้ว)
    result:       Optional[List[str]] = Query(None),
    operator:     Optional[List[str]] = Query(None),
    measure_type: Optional[List[str]] = Query(None),
    vendor:       Optional[List[str]] = Query(None),
    owner:        Optional[List[str]] = Query(None),
    part_number:  Optional[List[str]] = Query(None),
    handler:      Optional[List[str]] = Query(None),
    package_size: Optional[List[str]] = Query(None),
    # ค่าเริ่มต้นเป็น True — หน้า Export ต้องการ "สถานะล่าสุดของแต่ละ ALPL"
    # เป็นหลัก ไม่ใช่ประวัติทุกครั้งที่เคยวัด (ติ๊กออกได้ถ้าอยากได้ทั้งหมด)
    latest_only:  bool = True,
) -> Dict[str, Any]:
    """พารามิเตอร์ filter ที่ /api/export/preview กับ /api/export/csv รับเหมือนกัน
    ประกาศไว้ที่เดียวแล้วใช้ร่วมกันผ่าน Depends — กันลืมเพิ่มข้างใดข้างหนึ่ง
    จนตัวอย่างบนหน้าจอกับไฟล์ที่ดาวน์โหลดจริงไม่ตรงกัน
    """
    return {
        "number_alpl": number_alpl, "date_from": date_from, "date_to": date_to,
        "recv_from": recv_from, "recv_to": recv_to, "session_id": session_id,
        "po_number": po_number, "description": description,
        "result": result, "operator": operator, "measure_type": measure_type,
        "vendor": vendor, "owner": owner, "part_number": part_number,
        "handler": handler, "package_size": package_size,
        "latest_only": latest_only,
    }

REPORT_PREVIEW_LIMIT = 300

REPORT_MAX_ROWS = int(os.getenv("REPORT_MAX_ROWS", 20000))

# ชื่อที่โชว์ในคอลัมน์ "ประเภท" ของถังขยะ — **ใช้ชื่อตารางตามที่ผู้ใช้เห็นในหน้า Edit**
#
# ตั้งใจให้ตรงกับ dropdown "Lookup Tables" และหัวการ์ดในหน้า Edit เป๊ะ ๆ
# (Operator · Owner · Vendor · Handler · Template · Package Size · Part Number)
# เพื่อให้อ่านแล้วรู้ทันทีว่า "ลบมาจากตารางไหน" แล้วเดินไปกู้/ตรวจที่ตารางนั้นได้เลย
#
# เดิมใช้คำอธิบายผสมภาษาไทย ("ผลการวัด" · "Part (ALPL)") ซึ่งผู้ใช้ต้องแปลในหัวว่า
# มันคือตารางไหน — ตอนนี้เอาชื่อตารางมาตรงๆ ไม่ต้องเดา
_DELETED_KIND_LABEL = {
    "measurement":  "Measurement",
    "part":         "Part",
    "operator":     "Operator",
    "owner":        "Owner",
    "vendor":       "Vendor",
    "handler":      "Handler",
    "template":     "Template",
    "package_size": "Package Size",
    "part_number":  "Part Number",
}

def _purge_old_deleted() -> int:
    """ลบโฟลเดอร์ในถังขยะที่เก่ากว่า DELETED_RETENTION_DAYS วัน — คืนจำนวนที่ลบ

    อ่านวันจาก "ชื่อโฟลเดอร์" (DD-MM-YYYY พ.ศ.) ไม่ใช่ mtime ของไฟล์ เพราะ mtime
    เปลี่ยนได้ง่ายเวลาก๊อป/ย้ายไฟล์ ส่วนชื่อโฟลเดอร์คือวันที่ลบจริงเสมอ
    """
    if not os.path.isdir(DELETED_DIR):
        return 0
    cutoff = datetime.now().date() - timedelta(days=DELETED_RETENTION_DAYS)
    removed = 0
    for day in os.listdir(DELETED_DIR):
        day_dir = os.path.join(DELETED_DIR, day)
        if not os.path.isdir(day_dir):
            continue
        try:
            d, m, y = day.split("-")
            day_date = date(int(y) - 543, int(m), int(d))   # แปลง พ.ศ. → ค.ศ.
        except (ValueError, TypeError):
            log.warning("ข้ามโฟลเดอร์ในถังขยะที่ชื่อไม่ใช่รูปแบบวันที่: %s", day)
            continue
        if day_date < cutoff:
            try:
                shutil.rmtree(day_dir)
                removed += 1
                log.info("ลบถังขยะของวันที่ %s (เกิน %s วัน)", day, DELETED_RETENTION_DAYS)
            except OSError as exc:
                log.warning("ลบโฟลเดอร์ถังขยะ %s ไม่สำเร็จ: %s", day, exc)
    return removed


# ── ชื่อที่ router ทุกไฟล์ดึงไปใช้ผ่าน `from shared import *` ──
# ต้องมี __all__ เพราะ import * จะข้ามชื่อที่ขึ้นต้นด้วย _ ทั้งหมด
__all__ = [
    "AGENT_BASE_URL",
    "AGENT_HOST",
    "AGENT_PORT",
    "ALPL_IMAGE_DIR",
    "Any",
    "BaseModel",
    "Body",
    "BytesIO",
    "CLIENT",
    "CORSMiddleware",
    "CORS_ORIGINS",
    "DB_CONFIG",
    "DELETED_DIR",
    "DELETED_RETENTION_DAYS",
    "Decimal",
    "Depends",
    "Dict",
    "EXPORT_COLUMNS",
    "EXPORT_SELECT",
    "EventSourceResponse",
    "ExportTemplateBody",
    "FastAPI",
    "File",
    "HEARTBEAT_INTERVAL",
    "UI_POLL_INTERVAL",
    "HEARTBEAT_TIMEOUT",
    "HTTPException",
    "HeartbeatRequest",
    "Image",
    "DB_BREAKER_COOLDOWN",
    "ImageUpdate",
    "JSONResponse",
    "LAST_EVENT_FRESH_SEC",
    "List",
    "LookupCreate",
    "LookupUpdate",
    "MEASUREMENTS_SELECT",
    "MeasureTimeoutRequest",
    "MeasurementCreate",
    "Optional",
    "PARTS_SELECT",
    "PackageSizeCreate",
    "PackageSizeUpdate",
    "PartCreate",
    "PartNumberCreate",
    "PartNumberUpdate",
    "PartsCheckRequest",
    "Query",
    "REPORT_GROUP_BY",
    "REPORT_MAX_ROWS",
    "REPORT_PREVIEW_LIMIT",
    "Request",
    "SessionContinueRequest",
    "SessionEventRequest",
    "StaticFiles",
    "StopSessionRequest",
    "StreamingResponse",
    "StringIO",
    "UploadFile",
    "_DATE_ONLY_RE",
    "_DELETED_KIND_LABEL",
    "_EXPORT_FROM",
    "_GROUP_MATCH_FIELDS",
    "_LEGACY_COLUMN_ALIASES",
    "_PKG_NUM_FIELDS",
    "_PROJECT_ROOT",
    "_RANGE_PART_RE",
    "_TABLE_DISPLAY_NAME",
    "_TIME_FORMATS",
    "_TOL_EPS",
    "_archive_before_delete",
    "_axis_state",
    "_block_if_session_running",
    "_day_end",
    "_day_start",
    "_deleted_purge_loop",
    "_fetch_one",
    "_fmt_num",
    "_fmt_timestamp",
    "_get_template_name_for_alpl",
    "_insert_part_row",
    "_json_safe",
    "_load_criteria",
    "_lookup_id",
    "_offset_limit",
    "_purge_old_deleted",
    "_reload_session_queues",
    "_thai_date_str",
    "_tolerance_spec",
    "_within_tolerance",
    "asynccontextmanager",
    "asyncio",
    "date",
    "datetime",
    "export_filters_dep",
    "get_db",
    "heartbeat_checker",
    "httpx",
    "json",
    "lifespan",
    "load_dotenv",
    "log",
    "logging",
    "measure_timeouts",
    "os",
    "pd",
    "push_event",
    "read_pi_status",
    "mark_pi_seen",
    "PI_ONLINE_TIMEOUT",
    "pymysql",
    "re",
    "secrets",
    "session_queues",
    "shutil",
    "subscribers",
    "timedelta",
]
