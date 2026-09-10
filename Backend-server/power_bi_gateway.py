"""
power_bi_gateway.py
-------------------
ดึงข้อมูลจาก MySQL (tmx_db) มาเขียนเป็นไฟล์ Excel ในโฟลเดอร์ที่ซิงก์กับ
SharePoint / OneDrive for Business เพื่อให้ Power BI Service ตั้ง
Scheduled refresh ได้โดยไม่ต้องใช้ On-premises Data Gateway

รันด้วย Task Scheduler ตามรอบที่ต้องการ:
    python Backend-server\\power_bi_gateway.py

ติดตั้ง dependency:
    pip install pandas sqlalchemy pymysql openpyxl python-dotenv

⚠ สคริปต์นี้ **อ่านอย่างเดียว** ไม่เขียนอะไรลง DB เลย — ถ้าวันหลังมีคนจะเพิ่ม
  INSERT/UPDATE ที่นี่ ให้หยุดแล้วไปทำผ่าน Backend แทน (`main_split.py` เป็น
  Single Source of Truth ตาม CLAUDE.md) ไม่งั้นจะมี 2 ทางที่เขียน DB ได้
"""

import os
import sys
import time
import logging
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# CONFIG — แก้บรรทัดนี้ให้ตรงกับเครื่องคุณ
# ---------------------------------------------------------------------------

# โฟลเดอร์ปลายทางที่ซิงก์กับ SharePoint/OneDrive
# เปิด File Explorer → คลิกโฟลเดอร์ที่มีไอคอนตึกสีน้ำเงิน → copy path จาก address bar
# ตั้งทับได้จาก .env ด้วย `POWERBI_OUTPUT_DIR=...` จะได้ไม่ต้องแก้โค้ดตอนย้ายเครื่อง
OUTPUT_DIR = Path(
    os.getenv("POWERBI_OUTPUT_DIR")
    or r"C:\Users\YOURNAME\Analog Devices\TM-X Dashboard - Documents\data"
)

OUTPUT_FILENAME = os.getenv("POWERBI_OUTPUT_FILENAME", "tmx_export.xlsx")

# ย้อนหลังกี่วัน — ตั้งทับได้จาก .env
EXPORT_DAYS = int(os.getenv("POWERBI_EXPORT_DAYS", "180"))

# ---------------------------------------------------------------------------
# ตารางที่จะ export — sheet name : SQL query
#
# ⚠⚠ **ห้ามใช้ `SELECT *`** — ชื่อคอลัมน์ที่ออกมาเป็นสัญญากับ Power Query/DAX
#   ฝั่ง Power BI ถ้าวันหลังมีคนเพิ่มคอลัมน์ใน `measurements` แล้วใช้ `*`
#   คอลัมน์ใหม่จะโผล่เข้าไปเงียบ ๆ ทำให้ Power Query ที่ตั้ง type ไว้ต่อคอลัมน์
#   เออเรอร์ตอน refresh บนคลาวด์ ซึ่งเป็นที่ที่ debug ยากที่สุด
#   ปักชื่อไว้ตรงนี้แปลว่า schema ขยับแล้วสคริปต์นี้ยังส่งของหน้าตาเดิม
#
# ⚠ ชื่อตาราง/คอลัมน์ยืนยันจาก `mysql-init/init.sql` แล้ว **อย่าเดาจากชื่อเล่น**
#   - ตาราง Part ชื่อจริงคือ `parts_specifications` (ไม่ใช่ `parts`)
#   - คอลัมน์เวลาของ measurements ชื่อ `timestamp` (ไม่ใช่ `created_at` —
#     ตัวนั้นอยู่ตาราง `export_template` คนละตารางกัน)
# ---------------------------------------------------------------------------

QUERIES = {
    "measurements": f"""
        SELECT
            measurement_id, session_id, number_alpl,
            value_x, value_y,
            offset_opx, offset_opy, offset_pos_op,
            result, measure_type,
            operator_id, note,
            timestamp
        FROM measurements
        WHERE timestamp >= DATE_SUB(CURDATE(), INTERVAL {EXPORT_DAYS} DAY)
        ORDER BY timestamp
    """,
    # ตัดคอลัมน์รูป (`image_path`, `image_upload_failed`) ออกโดยตั้งใจ —
    # dashboard ไม่ได้ใช้ และ path รูปเป็นเรื่องภายในของเครื่อง PC
    "parts": """
        SELECT
            part_id, number_alpl,
            part_number_id, package_size_id, handler_id,
            vendor_id, owner_id,
            po_number, description, recieve_date
        FROM parts_specifications
    """,
}

# ---------------------------------------------------------------------------
# ⚠ ใช้ `.env` **กลางของโปรเจกต์** (ที่ root) ตัวเดียวกับ Backend และ Pi
#   ห้ามสร้าง .env แยกไว้ข้างสคริปต์ — จะกลายเป็นแหล่งรหัสผ่าน 2 ที่
#   แล้ววันที่ย้าย DB จะแก้ไม่ครบ เหลือตัวใดตัวหนึ่งชี้เครื่องเก่าค้างไว้
#
# ⚠ ชื่อตัวแปรต้องเป็น `DB_*` ให้ตรงกับ .env จริง — โดยเฉพาะ **`DB_PASSWORD`
#   ไม่ใช่ `DB_PASS`**
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(dotenv_path=PROJECT_ROOT / ".env")

DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
DB_PORT = os.getenv("DB_PORT", "3306")
DB_NAME = os.getenv("DB_NAME", "tmx_db")
DB_USER = os.getenv("DB_USER", "pc_user")
DB_PASS = os.getenv("DB_PASSWORD")

LOG_PATH = Path(__file__).with_name("power_bi_gateway_log.txt")

# ⚠ ต้อง rotate — สคริปต์นี้รันวนด้วย Task Scheduler ไม่มีใครมานั่งลบ log ให้
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [PowerBI] %(levelname)-7s %(message)s",
    handlers=[
        RotatingFileHandler(LOG_PATH, maxBytes=2_000_000, backupCount=3, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)


def build_engine():
    if not DB_PASS:
        raise RuntimeError(
            f"ไม่พบรหัสผ่าน — ต้องมี `DB_PASSWORD=...` ใน {PROJECT_ROOT / '.env'}"
        )
    url = f"mysql+pymysql://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}?charset=utf8mb4"
    return create_engine(url, pool_pre_ping=True)


def replace_with_retry(temp_path: Path, final_path: Path, attempts: int = 4, wait: float = 2.0):
    """ย้ายไฟล์ทับของเดิม พร้อม retry เผื่อ OneDrive ถือ handle ค้างอยู่

    OneDrive อาจกำลังอัปโหลดไฟล์เดิมอยู่พอดีตอนที่สคริปต์จะเขียนทับ ซึ่งบน
    Windows จะได้ `PermissionError [WinError 32]` — เป็นภาวะชั่วคราว รอสักครู่
    แล้วลองใหม่ก็ผ่าน ไม่ควรปล่อยให้ Task Scheduler ตีเป็น fail ทั้งรอบ
    """
    for attempt in range(1, attempts + 1):
        try:
            os.replace(temp_path, final_path)
            return
        except PermissionError as exc:
            if attempt == attempts:
                raise
            log.warning(
                "เขียนทับไฟล์ไม่ได้ (ครั้งที่ %s/%s) — น่าจะโดน OneDrive ล็อกอยู่ "
                "รอ %.0f วิแล้วลองใหม่: %s", attempt, attempts, wait, exc
            )
            time.sleep(wait)


def main() -> int:
    started = datetime.now()
    log.info("=" * 60)
    log.info("เริ่ม export (ย้อนหลัง %s วัน)", EXPORT_DAYS)

    if not OUTPUT_DIR.exists():
        log.error("ไม่พบโฟลเดอร์ปลายทาง: %s", OUTPUT_DIR)
        log.error("ตรวจว่า path ถูกต้อง และโฟลเดอร์ SharePoint sync อยู่")
        return 1

    engine = build_engine()

    # ⚠ ดึงให้ครบทุก query ก่อน แล้วค่อยเขียนไฟล์ — ถ้า query ตัวหลังพัง
    #   ไฟล์เดิมบน SharePoint ต้องยังอยู่ครบ ห้ามเหลือไฟล์ที่มีแค่บางแผ่น
    frames = {}
    for sheet, sql in QUERIES.items():
        df = pd.read_sql(sql, engine)
        frames[sheet] = df
        log.info("  %-16s %7d rows  %3d cols", sheet, len(df), len(df.columns))

    # แผ่นบอกเวลาอัปเดตล่าสุด เอาไปโชว์เป็น card บน dashboard ได้
    frames["_meta"] = pd.DataFrame(
        [{"last_updated": started.strftime("%Y-%m-%d %H:%M:%S"),
          "source": f"{DB_HOST}/{DB_NAME}",
          "export_days": EXPORT_DAYS}]
    )

    final_path = OUTPUT_DIR / OUTPUT_FILENAME
    # ⚠ ต้องขึ้นต้นด้วย `~$` — OneDrive ข้ามไฟล์ pattern นี้ให้ (เป็นชื่อไฟล์
    #   temp ของ Office) ถ้าใช้ `~` ตัวเดียวมันจะพยายามอัปโหลดไฟล์ระหว่างทาง
    #   ขึ้นคลาวด์ด้วย · และต้องอยู่ **ไดรฟ์เดียวกับปลายทาง** ไม่งั้น
    #   `os.replace` ข้ามโวลุ่มไม่ได้
    temp_path = OUTPUT_DIR / f"~${OUTPUT_FILENAME}.tmp"

    with pd.ExcelWriter(temp_path, engine="openpyxl") as writer:
        for sheet, df in frames.items():
            df.to_excel(writer, sheet_name=sheet[:31], index=False)

    replace_with_retry(temp_path, final_path)

    elapsed = (datetime.now() - started).total_seconds()
    log.info("เขียนไฟล์สำเร็จ: %s  (%.1f วินาที)", final_path, elapsed)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        log.exception("export ล้มเหลว")
        sys.exit(1)
