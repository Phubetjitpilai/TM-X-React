"""main.py (ฉบับแยกไฟล์) — สร้าง app แล้วประกอบ router เข้าด้วยกัน

รันเหมือนเดิมทุกตัวอักษร:  uvicorn main_split:app --reload --port 8000
(ต้อง cd Backend-server ก่อน ไม่งั้น import routers ไม่เจอ)
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from shared import *  # noqa: F401,F403
from routers import session, measurements, parts_register, lookups, export, deleted

app = FastAPI(title="TM-X Backend Server", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ⚠ ต้อง include_router "ก่อน" app.mount("/") เสมอ
#   StaticFiles ที่ mount ไว้ที่ราก "/" เป็น catch-all — จับทุก path ที่เข้ามา
#   ถ้าลงทะเบียน router ทีหลัง ทุก /api/* จะโดน static กลืนแล้วตอบ 404
#   (ใน main.py เดิมไม่เจอปัญหานี้เพราะ decorator ทำงานตอน import ซึ่งอยู่ก่อน
#    บรรทัด mount ท้ายไฟล์อยู่แล้ว — พอแยกไฟล์ ลำดับนี้ต้องเขียนเองให้ถูก)
for _m in (session, measurements, parts_register, lookups, export, deleted):
    app.include_router(_m.router)

os.makedirs(ALPL_IMAGE_DIR, exist_ok=True)

app.mount("/media/alpl", StaticFiles(directory=ALPL_IMAGE_DIR), name="alpl-images")

_frontend_dir = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "Frontend")
)

app.mount(
    "/",
    StaticFiles(directory=_frontend_dir, html=True),
    name="static",
)

