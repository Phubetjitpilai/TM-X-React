"""
server_image.py — เสิร์ฟรูปผลการวัดให้ Power BI ดึงไปแสดง

รันแยกจาก main.py คนละ process คนละพอร์ต (8080) เพราะ Power BI ต้องการ URL
ตรงๆ ของไฟล์รูป ไม่ได้เรียกผ่าน API ปกติ

⚠ เครื่องนี้เปิดพอร์ต 8080 ออกวงบริษัท จึงต้องถือว่า "ทุก request ที่เข้ามา
  อาจเป็นของคนที่ไม่หวังดี" — มีการป้องกัน 2 ชั้นคือกรอง IP กับกัน path traversal
"""
import os

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse

ALLOWED_SUBNET_PREFIX = "172.20.10."          # อนุญาตเฉพาะเครื่องในวงนี้
IMAGE_DIR = r"D:\All Work\TM-X_Project\image_ALPL"
SERVER_HOST = "0.0.0.0"
SERVER_PORT = 8080
PUBLIC_BASE_URL = "http://172.20.10.5:8080"   # ต้องเป็น IP จริงของเครื่องนี้ (เช็คด้วย ipconfig ถ้า IP เปลี่ยน)

# resolve ครั้งเดียวตอนเริ่ม แล้วใช้ตัวนี้เทียบทุกครั้ง — เก็บเป็น absolute path
# ที่คลี่ symlink แล้ว เพื่อให้เทียบกับ path ปลายทางได้อย่างถูกต้อง
_IMAGE_ROOT = os.path.realpath(IMAGE_DIR)

app = FastAPI(title="TM-X Image Server")


def check_subnet(request: Request):
    client_ip = request.client.host
    if not client_ip.startswith(ALLOWED_SUBNET_PREFIX) and client_ip != "127.0.0.1":
        raise HTTPException(status_code=403, detail="Forbidden: IP not allowed")


def _safe_path(filepath: str) -> str:
    """แปลง filepath จาก URL เป็น path จริงบนดิสก์ โดยบังคับว่าต้องอยู่ใน IMAGE_DIR

    ⚠⚠ ห้ามเอา os.path.join(IMAGE_DIR, filepath) มาใช้ตรงๆ เด็ดขาด
    เดิมโค้ดเป็นแบบนั้นแล้วเปิดช่องให้อ่านไฟล์อะไรก็ได้บนเครื่อง — ทดสอบแล้วว่า
    ยิงแบบนี้ได้ไฟล์ .env ที่มีรหัสผ่าน DB กลับไปเลย:

        GET /images/..%2F.env        →  200  DB_PASSWORD=...

    ที่ `../` ธรรมดาไม่ผ่านเพราะ Starlette normalize ให้ แต่ `%2F` (สแลชเข้ารหัส)
    ถูก decode "หลัง" การ normalize จึงรอดเข้ามาถึง os.path.join ได้

    วิธีกันที่ถูกต้องคือ resolve ให้เป็น absolute path จริงก่อน แล้วเทียบว่ายังอยู่
    ใต้ราก IMAGE_DIR ไหม — ครอบคลุมทุกรูปแบบการเข้ารหัส ไม่ต้องไล่ blacklist
    """
    target = os.path.realpath(os.path.join(_IMAGE_ROOT, filepath))
    if target != _IMAGE_ROOT and not target.startswith(_IMAGE_ROOT + os.sep):
        # ตอบ 404 เหมือนไฟล์ไม่มีจริง ไม่บอกว่า "ห้ามออกนอกโฟลเดอร์"
        # เพื่อไม่ให้คนลองยิงรู้ว่าเดามาถูกทางแล้ว
        raise HTTPException(status_code=404, detail="File not found")
    return target


@app.get("/images/{filepath:path}")
async def get_image(filepath: str, request: Request):
    check_subnet(request)
    file_path = _safe_path(filepath)
    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(file_path)


@app.get("/generate-link")
async def generate_link(filepath: str, request: Request):
    check_subnet(request)
    # ตรวจด้วยกฎเดียวกัน ไม่งั้นจะกลายเป็นตัวช่วยสร้าง URL โจมตีให้เสียเอง
    _safe_path(filepath)
    return {"url": f"{PUBLIC_BASE_URL}/images/{filepath}"}


if __name__ == "__main__":
    print("=" * 66)
    print("TM-X Image Server (สำหรับ Power BI)")
    print(f"  ฟังที่        : {SERVER_HOST}:{SERVER_PORT}")
    print(f"  เสิร์ฟรูปจาก   : {_IMAGE_ROOT}")
    print(f"  อนุญาตเฉพาะ IP : {ALLOWED_SUBNET_PREFIX}* และ 127.0.0.1")
    print("=" * 66)
    uvicorn.run(app, host=SERVER_HOST, port=SERVER_PORT)
