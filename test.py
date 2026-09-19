"""
export_tmx_to_sharepoint.py
---------------------------
ดึงข้อมูลจาก MySQL (tmx_db) มาเขียนเป็นไฟล์ Excel ในโฟลเดอร์ที่ซิงก์กับ
SharePoint / OneDrive for Business เพื่อให้ Power BI Service ตั้ง
Scheduled refresh ได้โดยไม่ต้องใช้ On-premises Data Gateway

รันด้วย Task Scheduler ตามรอบที่ต้องการ

ติดตั้ง dependency:
    pip install pandas sqlalchemy pymysql openpyxl python-dotenv
"""

import os
import sys
import logging
from datetime import datetime
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# CONFIG — แก้ 2 บรรทัดนี้ให้ตรงกับเครื่องคุณ
# ---------------------------------------------------------------------------

# โฟลเดอร์ปลายทางที่ซิงก์กับ SharePoint/OneDrive
# เปิด File Explorer → คลิกโฟลเดอร์ที่มีไอคอนตึกสีน้ำเงิน → copy path จาก address bar
OUTPUT_DIR = Path(r"C:\Users\YOURNAME\Analog Devices\TM-X Dashboard - Documents\data")

OUTPUT_FILENAME = "tmx_export.xlsx"

# ---------------------------------------------------------------------------
# ตารางที่จะ export — sheet name : SQL query
# ชื่อคอลัมน์ที่ออกมาต้องตรงกับที่ Power BI ใช้อยู่เดิม ไม่งั้น measure/DAX จะพัง
# ---------------------------------------------------------------------------

QUERIES = {
    "measurements": """
        SELECT *
        FROM measurements
        WHERE created_at >= DATE_SUB(CURDATE(), INTERVAL 180 DAY)
    """,
    "parts": """
        SELECT *
        FROM parts
    """,
}

# ---------------------------------------------------------------------------

load_dotenv(Path(__file__).with_name(".env"))

DB_HOST = os.getenv("TMX_DB_HOST", "localhost")
DB_PORT = os.getenv("TMX_DB_PORT", "3306")
DB_NAME = os.getenv("TMX_DB_NAME", "tmx_db")
DB_USER = os.getenv("TMX_DB_USER", "pc_user")
DB_PASS = os.getenv("TMX_DB_PASS")

LOG_PATH = Path(__file__).with_name("export_log.txt")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)


def build_engine():
    if not DB_PASS:
        raise RuntimeError(
            "ไม่พบรหัสผ่าน — สร้างไฟล์ .env ข้างๆ สคริปต์นี้ แล้วใส่ TMX_DB_PASS=..."
        )
    url = f"mysql+pymysql://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}?charset=utf8mb4"
    return create_engine(url, pool_pre_ping=True)


def main() -> int:
    started = datetime.now()
    log.info("=" * 60)
    log.info("เริ่ม export")

    if not OUTPUT_DIR.exists():
        log.error("ไม่พบโฟลเดอร์ปลายทาง: %s", OUTPUT_DIR)
        log.error("ตรวจว่า path ถูกต้อง และโฟลเดอร์ SharePoint sync อยู่")
        return 1

    engine = build_engine()

    frames = {}
    for sheet, sql in QUERIES.items():
        df = pd.read_sql(sql, engine)
        frames[sheet] = df
        log.info("  %-16s %7d rows  %3d cols", sheet, len(df), len(df.columns))

    # แผ่นบอกเวลาอัปเดตล่าสุด เอาไปโชว์เป็น card บน dashboard ได้
    frames["_meta"] = pd.DataFrame(
        [{"last_updated": started.strftime("%Y-%m-%d %H:%M:%S"),
          "source": f"{DB_HOST}/{DB_NAME}"}]
    )

    final_path = OUTPUT_DIR / OUTPUT_FILENAME
    temp_path = OUTPUT_DIR / f"~{OUTPUT_FILENAME}.tmp"

    # เขียนลงไฟล์ชั่วคราวก่อนแล้วค่อย replace
    # กัน OneDrive ซิงก์ไฟล์ที่เขียนยังไม่เสร็จขึ้นคลาวด์
    with pd.ExcelWriter(temp_path, engine="openpyxl") as writer:
        for sheet, df in frames.items():
            df.to_excel(writer, sheet_name=sheet[:31], index=False)

    os.replace(temp_path, final_path)

    elapsed = (datetime.now() - started).total_seconds()
    log.info("เขียนไฟล์สำเร็จ: %s  (%.1f วินาที)", final_path, elapsed)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        log.exception("export ล้มเหลว")
        sys.exit(1)