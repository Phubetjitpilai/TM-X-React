"""
power_bi_gateway.py
-------------------
ดึงข้อมูล **ทุกตาราง** จาก MySQL (tmx_db) มาเขียนเป็นไฟล์ Excel แผ่นละตาราง
ในโฟลเดอร์ที่ซิงก์กับ SharePoint / OneDrive for Business เพื่อให้ Power BI
Service ตั้ง Scheduled refresh ได้โดยไม่ต้องใช้ On-premises Data Gateway

รันด้วย Task Scheduler ตามรอบที่ต้องการ:
    python Backend-server\\power_bi_gateway.py

ติดตั้ง dependency:
    pip install pandas sqlalchemy pymysql openpyxl python-dotenv

⚠ สคริปต์นี้ **อ่านอย่างเดียว** ไม่เขียนอะไรลง DB เลย — ถ้าวันหลังมีคนจะเพิ่ม
  INSERT/UPDATE ที่นี่ ให้หยุดแล้วไปทำผ่าน Backend แทน (เป็น Single Source of
  Truth ตาม CLAUDE.md) ไม่งั้นจะมี 2 ทางที่เขียน DB ได้
"""

import os
import re
import sys
import time
import logging
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# ⚠ ใช้ `.env` **กลางของโปรเจกต์** (ที่ root) ตัวเดียวกับ Backend และ Pi
#   ห้ามสร้าง .env แยกไว้ข้างสคริปต์ — จะกลายเป็นแหล่งรหัสผ่าน 2 ที่ แล้ววันที่
#   ย้าย DB จะแก้ไม่ครบ เหลือตัวใดตัวหนึ่งชี้เครื่องเก่าค้างไว้
#
# ⚠ ชื่อตัวแปรต้องเป็น `DB_*` ให้ตรงกับ .env จริง โดยเฉพาะ **`DB_PASSWORD`
#   ไม่ใช่ `DB_PASS`**
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(dotenv_path=PROJECT_ROOT / ".env")

DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
DB_PORT = os.getenv("DB_PORT", "3306")
DB_NAME = os.getenv("DB_NAME", "tmx_db")
DB_USER = os.getenv("DB_USER", "pc_user")
DB_PASS = os.getenv("DB_PASSWORD")

# ---------------------------------------------------------------------------
# CONFIG — ตั้งทับได้จาก .env ทุกตัว จะได้ไม่ต้องแก้โค้ดตอนย้ายเครื่อง
# ---------------------------------------------------------------------------

# โฟลเดอร์ปลายทางที่ซิงก์กับ SharePoint/OneDrive
# เปิด File Explorer → คลิกโฟลเดอร์ที่มีไอคอนตึกสีน้ำเงิน → copy path จาก address bar
OUTPUT_DIR = Path(
    os.getenv("POWERBI_OUTPUT_DIR")
    or r"C:\Users\YOURNAME\Analog Devices\TM-X Dashboard - Documents\data"
)
OUTPUT_FILENAME = os.getenv("POWERBI_OUTPUT_FILENAME", "tmx_export.xlsx")

# ย้อนหลังกี่วัน — ใช้เฉพาะตารางใน `DATE_COLUMN` ข้างล่าง ตาราง lookup เอาทั้งหมด
EXPORT_DAYS = int(os.getenv("POWERBI_EXPORT_DAYS", "180"))

# ---------------------------------------------------------------------------
# ⚠⚠ **ไม่ hardcode รายชื่อตารางไว้ในสคริปต์** — อ่านจาก `information_schema`
#   ตอนรันจริงทุกครั้ง เหตุผล:
#     1. เพิ่มตารางใหม่ใน DB แล้วได้ออกมาเลย ไม่ต้องมาแก้ไฟล์นี้ตาม แล้วลืม
#     2. DB หน้างานอาจยังไม่ได้รัน migration ครบทุกตัวใน `sql-tools/` ถ้าปัก
#        ชื่อคอลัมน์ไว้ตายตัวจาก `init.sql` แล้วเครื่องจริงยังไม่มีคอลัมน์นั้น
#        จะได้ `ProgrammingError 1054` ทั้ง ๆ ที่ข้อมูลอื่นดึงได้ปกติ
#
#   แลกมาด้วยการที่ shape ของไฟล์ไม่คงที่ 100% — จึง **log ชื่อคอลัมน์ทุกตาราง
#   ทุกครั้งที่รัน** ถ้า Power BI พังหลัง refresh จะย้อนดู log ได้ทันทีว่ารอบไหน
#   คอลัมน์เปลี่ยน ไม่ต้องมานั่งเดา
# ---------------------------------------------------------------------------

# ตารางที่โตเรื่อย ๆ ตามการใช้งาน → ตัดด้วยช่วงวันที่ ไม่งั้นไฟล์บวมไม่มีเพดาน
# ตารางที่ไม่อยู่ในนี้ (lookup ทั้งหลาย) ดึงทั้งตาราง
DATE_COLUMN = {
    "measurements": "timestamp",     # ⚠ ชื่อคอลัมน์คือ `timestamp` ไม่ใช่ `created_at`
    "sessions":     "started_at",
    "edit_history": "edited_at",
}

# ตารางที่ไม่อยากได้ — ใส่ชื่อคั่นด้วยคอมมาใน .env เช่น POWERBI_SKIP=edit_history
SKIP_TABLES = {
    t.strip() for t in os.getenv("POWERBI_SKIP", "").split(",") if t.strip()
}

# ชื่อแผ่นที่อยากให้ต่างจากชื่อตาราง — Power BI ที่ตั้งไว้แล้วอ้างแผ่น `parts`
# ⚠ ถ้าเปลี่ยนตรงนี้ Power Query ฝั่ง Power BI จะหาแผ่นไม่เจอทันที
SHEET_ALIAS = {"parts_specifications": "parts"}

# Excel เก็บได้ 32,767 ตัวอักษรต่อเซลล์ · คอลัมน์ JSON อย่าง `queue_state`
# กับ `layout_json` ยาวเกินนี้ได้สบาย ต้องตัดก่อนไม่งั้น openpyxl โยน error
# แล้วไฟล์ทั้งไฟล์ไม่ถูกเขียนเลย
_CELL_LIMIT = 32_000
# openpyxl ปฏิเสธอักขระควบคุม (นอกจาก \t \n \r) — TEXT ที่หลุดมาจาก log
# อาจมีปนได้ ล้างทิ้งก่อนเขียน
_CTRL_RE = re.compile(r"[\000-\010\013\014\016-\037]")

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


def list_tables(conn) -> list[str]:
    """รายชื่อตารางจริงทั้งหมดใน schema นี้ (ไม่เอา VIEW)"""
    rows = conn.execute(text(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = :db AND table_type = 'BASE TABLE' "
        "ORDER BY table_name"
    ), {"db": DB_NAME}).fetchall()
    return [r[0] for r in rows]


def list_columns(conn, table: str) -> list[str]:
    """คอลัมน์ของตาราง เรียงตามลำดับจริงใน DB"""
    rows = conn.execute(text(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = :db AND table_name = :t "
        "ORDER BY ordinal_position"
    ), {"db": DB_NAME, "t": table}).fetchall()
    return [r[0] for r in rows]


def build_query(table: str, columns: list[str]) -> str:
    """ประกอบ SELECT โดยระบุชื่อคอลัมน์ตรง ๆ (ไม่ใช้ `SELECT *`)

    ชื่อคอลัมน์มาจาก `information_schema` ไม่ได้มาจาก input ผู้ใช้ แต่ยัง
    ครอบ backtick ให้อยู่ดี เพราะบางชื่ออย่าง `timestamp` เป็น reserved word
    ของ MySQL ถ้าไม่ครอบจะ syntax error
    """
    cols = ", ".join(f"`{c}`" for c in columns)
    sql = f"SELECT {cols} FROM `{table}`"

    date_col = DATE_COLUMN.get(table)
    if date_col and date_col in columns:
        sql += f" WHERE `{date_col}` >= DATE_SUB(CURDATE(), INTERVAL {EXPORT_DAYS} DAY)"
        sql += f" ORDER BY `{date_col}`"
    return sql


def sanitize(df: pd.DataFrame, table: str) -> pd.DataFrame:
    """ทำให้ทุกคอลัมน์เขียนลง Excel ได้

    คอลัมน์ JSON (`queue_state`, `changes_json`, `layout_json`, ...) กลับมาเป็น
    str หรือ dict แล้วแต่ driver — ถ้าเป็น dict openpyxl เขียนไม่ได้เลย
    ต้องแปลงเป็นข้อความก่อน แล้วตัดความยาวตามลิมิตของ Excel
    """
    # ⚠ เงื่อนไข "ต้องซ่อม" กับตัวซ่อมต้องดูของชุดเดียวกันเป๊ะ — เคยพลาดมาแล้ว
    #   ตอนที่เช็คแค่ dict/bytes/สตริงยาว แต่ลืมอักขระควบคุม ผลคือคอลัมน์
    #   `last_event_detail` ที่สั้นแต่มี \x07 ปนหลุดไปถึง openpyxl แล้วโยน
    #   `IllegalCharacterError` ทำให้ไฟล์ทั้งไฟล์เขียนไม่ออก
    def needs_fix(v):
        if isinstance(v, (dict, list, bytes)):
            return True
        if isinstance(v, str):
            return len(v) > _CELL_LIMIT or bool(_CTRL_RE.search(v))
        return False

    for col in df.columns:
        if df[col].dtype != object:
            continue
        s = df[col]
        if not s.map(needs_fix).any():
            continue

        def fix(v):
            if v is None:
                return None
            if isinstance(v, bytes):
                v = v.decode("utf-8", "replace")
            elif not isinstance(v, str):
                v = str(v)
            if len(v) > _CELL_LIMIT:
                v = v[:_CELL_LIMIT] + " …[ตัดแล้ว]"
            return _CTRL_RE.sub("", v)

        df[col] = s.map(fix)
        log.warning("  %-22s คอลัมน์ `%s` มีค่ายาว/ไม่ใช่ข้อความ — แปลงเป็นข้อความแล้ว",
                    table, col)
    return df


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
    log.info("=" * 70)
    log.info("เริ่ม export — ทุกตารางใน %s (ตารางที่มีวันที่ ย้อนหลัง %s วัน)",
             DB_NAME, EXPORT_DAYS)

    if not OUTPUT_DIR.exists():
        log.error("ไม่พบโฟลเดอร์ปลายทาง: %s", OUTPUT_DIR)
        log.error("ตรวจว่า path ถูกต้อง และโฟลเดอร์ SharePoint sync อยู่")
        return 1

    engine = build_engine()

    # ⚠ ดึงให้ครบทุกตารางก่อน แล้วค่อยเขียนไฟล์ — ถ้าตารางท้าย ๆ พัง ไฟล์เดิม
    #   บน SharePoint ต้องยังอยู่ครบ ห้ามเหลือไฟล์ที่มีแค่บางแผ่น
    frames: dict[str, pd.DataFrame] = {}
    skipped: list[str] = []

    with engine.connect() as conn:
        tables = list_tables(conn)
        log.info("เจอ %s ตาราง: %s", len(tables), ", ".join(tables))

        for table in tables:
            if table in SKIP_TABLES:
                skipped.append(table)
                continue

            columns = list_columns(conn, table)
            if not columns:
                log.warning("  %-22s ไม่มีคอลัมน์ — ข้าม", table)
                skipped.append(table)
                continue

            df = pd.read_sql(text(build_query(table, columns)), conn)
            df = sanitize(df, table)

            sheet = SHEET_ALIAS.get(table, table)[:31]
            if sheet in frames:
                log.warning("  ชื่อแผ่น %r ซ้ำ — ข้ามตาราง %s", sheet, table)
                skipped.append(table)
                continue

            frames[sheet] = df
            # log ชื่อคอลัมน์ทุกครั้ง เพื่อให้ย้อนดูได้ว่ารอบไหน shape เปลี่ยน
            log.info("  %-22s → แผ่น %-22s %7d rows  %2d cols  [%s]",
                     table, sheet, len(df), len(df.columns), ", ".join(df.columns))

    if skipped:
        log.info("ข้ามไป %s ตาราง: %s", len(skipped), ", ".join(skipped))

    # แผ่นบอกเวลาอัปเดตล่าสุด เอาไปโชว์เป็น card บน dashboard ได้
    frames["_meta"] = pd.DataFrame([{
        "last_updated": started.strftime("%Y-%m-%d %H:%M:%S"),
        "source":       f"{DB_HOST}/{DB_NAME}",
        "export_days":  EXPORT_DAYS,
        "sheets":       len(frames),
        "skipped":      ", ".join(skipped) or "—",
    }])

    final_path = OUTPUT_DIR / OUTPUT_FILENAME
    # ⚠ ต้องขึ้นต้นด้วย `~$` — OneDrive ข้ามไฟล์ pattern นี้ให้ (เป็นชื่อไฟล์
    #   temp ของ Office) ถ้าใช้ `~` ตัวเดียวมันจะพยายามอัปโหลดไฟล์ระหว่างทาง
    #   ขึ้นคลาวด์ด้วย · และต้องอยู่ **ไดรฟ์เดียวกับปลายทาง** ไม่งั้น
    #   `os.replace` ข้ามโวลุ่มไม่ได้
    temp_path = OUTPUT_DIR / f"~${OUTPUT_FILENAME}.tmp"

    with pd.ExcelWriter(temp_path, engine="openpyxl") as writer:
        for sheet, df in frames.items():
            df.to_excel(writer, sheet_name=sheet, index=False)

    replace_with_retry(temp_path, final_path)

    elapsed = (datetime.now() - started).total_seconds()
    total_rows = sum(len(d) for k, d in frames.items() if k != "_meta")
    log.info("เขียนไฟล์สำเร็จ: %s", final_path)
    log.info("รวม %s แผ่น · %s แถว · %.1f วินาที", len(frames), f"{total_rows:,}", elapsed)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        log.exception("export ล้มเหลว")
        sys.exit(1)
