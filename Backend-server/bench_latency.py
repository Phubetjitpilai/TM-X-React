#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""วัดว่าเวลาที่หายไปในแต่ละคำขอ ไปอยู่ตรงไหน

ใช้ตอนสงสัยว่า "ทำไมเว็บช้า" — แยกให้เห็นว่าเป็นที่ MySQL, ที่ FastAPI
หรือที่ Vite proxy โดยวัดทีละชั้นแล้วเทียบกัน

    cd Backend-server
    python bench_latency.py

ไม่ต้องมีอะไรรันอยู่ก็วัด MySQL ได้ · ถ้าอยากวัดชั้น HTTP ด้วยให้เปิด
uvicorn ทิ้งไว้ก่อน (และเปิด npm run dev ถ้าอยากวัดชั้น Vite)
"""
import os
import statistics
import sys
import time

try:
    import pymysql
except ImportError:
    sys.exit("ต้องรันในโฟลเดอร์ Backend-server ที่มี pymysql ติดตั้งแล้ว")

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
except ImportError:
    print("⚠ ไม่มี python-dotenv — จะอ่านจาก environment variable ที่ตั้งไว้แล้วแทน\n")

ROUNDS = 7

DB = dict(
    host=os.getenv("DB_HOST", "127.0.0.1"),
    port=int(os.getenv("DB_PORT", 3306)),
    user=os.getenv("DB_USER", "root"),
    password=os.getenv("DB_PASSWORD", ""),
    database=os.getenv("DB_NAME", "tmx_db"),
    connect_timeout=3,
)


def report(label, samples, note=""):
    """สรุปเป็น median ไม่ใช่ค่าเฉลี่ย — ค่าผิดปกติหนึ่งครั้งไม่ควรลากทั้งชุด"""
    if not samples:
        print(f"  {label:38} —  (วัดไม่ได้)  {note}")
        return None
    med = statistics.median(samples)
    print(f"  {label:38} {med:7.1f} ms   "
          f"(ต่ำสุด {min(samples):.1f} · สูงสุด {max(samples):.1f}){note}")
    return med


def timed(fn):
    t0 = time.perf_counter()
    fn()
    return (time.perf_counter() - t0) * 1000


print("=" * 72)
print(f"วัดความหน่วงทีละชั้น — {ROUNDS} ครั้งต่อชั้น")
print(f"MySQL ที่ {DB['host']}:{DB['port']} · ฐาน {DB['database']}")
print("=" * 72)

# ── ชั้นที่ 1: เปิด connection ใหม่อย่างเดียว ────────────────────────────
# นี่คือราคาที่ get_db() จ่ายทุก request เพราะไม่ใช้ pool โดยตั้งใจ
print("\n[1] เปิด MySQL connection ใหม่ (สิ่งที่ get_db ทำทุก request)")
connect_only = []
for _ in range(ROUNDS):
    try:
        connect_only.append(timed(lambda: pymysql.connect(**DB).close()))
    except Exception as exc:
        print(f"  ต่อ MySQL ไม่ได้: {exc}")
        break
med_connect = report("connect + close", connect_only)

# ── ชั้นที่ 2: เปิด + query จริง ─────────────────────────────────────────
print("\n[2] เปิด connection + SELECT จริง (เหมือน /api/session/state)")
query_all = []
for _ in range(ROUNDS):
    def one():
        c = pymysql.connect(**DB)
        try:
            with c.cursor() as cur:
                cur.execute("SELECT session_id, state, target_count, measured_count "
                            "FROM sessions ORDER BY session_id DESC LIMIT 1")
                cur.fetchone()
        finally:
            c.close()
    try:
        query_all.append(timed(one))
    except Exception as exc:
        print(f"  query ไม่ได้: {exc}")
        break
med_query = report("connect + SELECT + close", query_all)

if med_connect and med_query:
    print(f"\n  → ตัว SELECT เองใช้เวลาแค่ {med_query - med_connect:.1f} ms "
          f"· ที่เหลือคือค่าเปิดสาย")

# ── ชั้นที่ 3 กับ 4: ผ่าน HTTP ───────────────────────────────────────────
try:
    import httpx
except ImportError:
    httpx = None
    print("\n⚠ ไม่มี httpx — ข้ามการวัดชั้น HTTP")

if httpx:
    for label, url in (("[3] ยิงตรงไป uvicorn", "http://127.0.0.1:8000/api/session/state"),
                       ("[4] ผ่าน Vite proxy",  "http://127.0.0.1:5173/api/session/state")):
        print(f"\n{label}  {url}")
        samples = []
        with httpx.Client(timeout=10) as cl:
            for _ in range(ROUNDS):
                try:
                    samples.append(timed(lambda: cl.get(url)))
                except Exception as exc:
                    print(f"  เรียกไม่ได้ ({type(exc).__name__}) — ตัวนี้รันอยู่หรือเปล่า")
                    break
        report("GET /api/session/state", samples)

# ── สรุป ─────────────────────────────────────────────────────────────────
print("\n" + "=" * 72)
print("อ่านผลยังไง")
print("=" * 72)
print("""
  [1] สูง (> 30 ms)   → ค่าเปิดสาย MySQL คือตัวปัญหา
                        ถ้าใช้ Docker (port 3307) ลองลง MySQL ตรงเหมือนหน้างาน
                        เพราะ port proxy ของ Docker Desktop บน Windows หน่วงมาก

  [2] − [1] สูง       → ตัว query เองช้า → ขาด INDEX (ดู sql-tools/)

  [3] − [2] สูง       → FastAPI เองช้า ไม่ใช่ DB
                        มักเกิดจาก endpoint ที่เป็น async แต่ทำงาน DB แบบบล็อก

  [4] − [3] สูง       → Vite proxy กิน — เช็คว่า target เป็น 127.0.0.1
                        ไม่ใช่ localhost (Node ลอง IPv6 ก่อนแล้วเสียเวลา)
""")
