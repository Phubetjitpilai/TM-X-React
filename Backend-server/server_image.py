"""
server_image.py — เสิร์ฟรูปผลการวัดให้ Power BI ดึงไปแสดง

รันแยกจาก main_split.py คนละ process คนละพอร์ต (8080) เพราะ Power BI ต้องการ URL
ตรงๆ ของไฟล์รูป ไม่ได้เรียกผ่าน API ปกติ

⚠ เครื่องนี้เปิดพอร์ต 8080 ออกวงบริษัท จึงต้องถือว่า "ทุก request ที่เข้ามา
  อาจเป็นของคนที่ไม่หวังดี" — มีการป้องกัน 2 ชั้นคือกรอง IP กับกัน path traversal

⚠ **log ของไฟล์นี้เป็นร่องรอยความปลอดภัย ไม่ใช่แค่ตัวช่วยไล่บั๊ก** — คำตอบที่
  ส่งกลับไปให้คนยิงตั้งใจปิดบังข้อมูล (traversal ตอบ 404 เหมือนไฟล์หาย) แต่
  ฝั่งเราต้องเห็นความต่างนั้น ไม่งั้นวันที่มีคนลองเจาะจะไม่มีใครรู้เลย
"""
import ipaddress
import logging
import os
import socket

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse

# ── ตั้ง logging ─────────────────────────────────────────────────────────
# ป้าย [ImageServer] ไว้แยกจาก [Server] / [Pi] เวลาเอา log หลายตัวมาวางเทียบกัน
logging.basicConfig(level=logging.INFO, format="%(asctime)s [ImageServer] %(message)s")
log = logging.getLogger(__name__)

_PROJECT_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
)
load_dotenv(dotenv_path=os.path.join(_PROJECT_ROOT, ".env"))

# ⚠ อ่านจาก `.env` ตัวเดียวกับ backend — เดิม hardcode ไว้ที่ path ของเครื่อง dev
#   (`D:\All Work\TM-X_Project\image_ALPL`) ซึ่งบนเครื่องหน้างานไม่มีอยู่จริง
#   ทำให้หารูปไม่เจอทุกไฟล์ · ต้องเป็นโฟลเดอร์ **เดียวกัน** กับที่ backend เซฟรูปลง
IMAGE_DIR = os.getenv("ALPL_IMAGE_DIR", os.path.join(_PROJECT_ROOT, "image_ALPL"))
if not os.path.isabs(IMAGE_DIR):
    IMAGE_DIR = os.path.abspath(os.path.join(_PROJECT_ROOT, IMAGE_DIR))

SERVER_HOST = os.getenv("IMAGE_SERVER_HOST", "0.0.0.0")
SERVER_PORT = int(os.getenv("IMAGE_SERVER_PORT", 8080))

# URL ที่เอาไปแปะใน Power BI — ใช้ Hostname ของเครื่องเป็นค่าเริ่มต้น เพื่อป้องกันลิงก์พังเวลา IP เปลี่ยน
"""
server_image.py — เสิร์ฟรูปผลการวัดให้ Power BI ดึงไปแสดง

รันแยกจาก main_split.py คนละ process คนละพอร์ต (8080) เพราะ Power BI ต้องการ URL
ตรงๆ ของไฟล์รูป ไม่ได้เรียกผ่าน API ปกติ

⚠ เครื่องนี้เปิดพอร์ต 8080 ออกวงบริษัท จึงต้องถือว่า "ทุก request ที่เข้ามา
  อาจเป็นของคนที่ไม่หวังดี" — มีการป้องกัน 2 ชั้นคือกรอง IP กับกัน path traversal

⚠ **log ของไฟล์นี้เป็นร่องรอยความปลอดภัย ไม่ใช่แค่ตัวช่วยไล่บั๊ก** — คำตอบที่
  ส่งกลับไปให้คนยิงตั้งใจปิดบังข้อมูล (traversal ตอบ 404 เหมือนไฟล์หาย) แต่
  ฝั่งเราต้องเห็นความต่างนั้น ไม่งั้นวันที่มีคนลองเจาะจะไม่มีใครรู้เลย
"""
import ipaddress
import logging
import os
import socket

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse

# ── ตั้ง logging ─────────────────────────────────────────────────────────
# ป้าย [ImageServer] ไว้แยกจาก [Server] / [Pi] เวลาเอา log หลายตัวมาวางเทียบกัน
logging.basicConfig(level=logging.INFO, format="%(asctime)s [ImageServer] %(message)s")
log = logging.getLogger(__name__)

_PROJECT_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
)
load_dotenv(dotenv_path=os.path.join(_PROJECT_ROOT, ".env"))

# ⚠ อ่านจาก `.env` ตัวเดียวกับ backend — เดิม hardcode ไว้ที่ path ของเครื่อง dev
#   (`D:\All Work\TM-X_Project\image_ALPL`) ซึ่งบนเครื่องหน้างานไม่มีอยู่จริง
#   ทำให้หารูปไม่เจอทุกไฟล์ · ต้องเป็นโฟลเดอร์ **เดียวกัน** กับที่ backend เซฟรูปลง
IMAGE_DIR = os.getenv("ALPL_IMAGE_DIR", os.path.join(_PROJECT_ROOT, "image_ALPL"))
if not os.path.isabs(IMAGE_DIR):
    IMAGE_DIR = os.path.abspath(os.path.join(_PROJECT_ROOT, IMAGE_DIR))

SERVER_HOST = os.getenv("IMAGE_SERVER_HOST", "0.0.0.0")
SERVER_PORT = int(os.getenv("IMAGE_SERVER_PORT", 8080))

# URL ที่เอาไปแปะใน Power BI — ใช้ Hostname ของเครื่องเป็นค่าเริ่มต้น เพื่อป้องกันลิงก์พังเวลา IP เปลี่ยน
default_hostname = socket.gethostname()
PUBLIC_BASE_URL = os.getenv(
    "IMAGE_PUBLIC_BASE_URL", 
    f"http://{default_hostname}:{SERVER_PORT}"
)

# resolve ครั้งเดียวตอนเริ่ม แล้วใช้ตัวนี้เทียบทุกครั้ง — เก็บเป็น absolute path
# ที่คลี่ symlink แล้ว เพื่อให้เทียบกับ path ปลายทางได้อย่างถูกต้อง
_IMAGE_ROOT = os.path.realpath(IMAGE_DIR)

app = FastAPI(title="TM-X Image Server")


def check_subnet(request: Request):
    """ผ่านเฉพาะ IP ในวง LAN (RFC 1918) — ครอบคลุมทุกซับเน็ตในบริษัท

    ⚠ เดิมล็อกไว้ที่ prefix เดียว (`"172.20.10."`) ซึ่งพังทันทีที่ Power BI ไปอยู่
      คนละวง หรือ IT เปลี่ยน DHCP scope · เปลี่ยนมาถามว่า "เป็น IP ภายในไหม"
      แทนการเทียบตัวเลขตายตัว

    ⚠⚠ **ห้ามถอดด่านนี้ออกให้ผ่านทุก IP** — ไฟล์นี้เสิร์ฟไฟล์จากดิสก์ตรง ๆ และ
      เคยมีช่องโหว่ path traversal มาแล้ว (ดู `_safe_path`) ด่านนี้คือเกราะชั้นสอง
      ที่เหลืออยู่ถ้าชั้นแรกพลาดอีก

    ⚠ `request.client` เป็น `None` ได้ — เดิมเขียน `request.client.host` ตรง ๆ
      แล้วจะระเบิดเป็น AttributeError → ตอบ 500 พร้อม traceback ซึ่งอาจเผย path
      ภายในเครื่องให้คนยิงเห็น (อันตรายเป็นพิเศษเพราะพอร์ตนี้เปิดออกวงบริษัท)
    """
    client_ip = request.client.host if request.client else None
    if client_ip is None:
        log.warning("ปฏิเสธ: ไม่ทราบ IP ต้นทาง")
        raise HTTPException(status_code=403, detail="Forbidden: IP not allowed")

    try:
        ip = ipaddress.ip_address(client_ip)
    except ValueError:
        log.warning("ปฏิเสธ: IP ต้นทางผิดรูปแบบ (%s)", client_ip)
        raise HTTPException(status_code=403, detail="Forbidden: IP not allowed")

    if not (ip.is_private or ip.is_loopback):
        # ⚠ เหตุการณ์นี้บอก 2 อย่างพร้อมกัน — Power BI ตั้งค่าผิดวง (config พัง)
        #    หรือมีคนนอกวงมาลอง · ทั้งคู่ต้องรู้ ไม่ควรเงียบ
        log.warning("ปฏิเสธ: IP นอกวง LAN (%s)", client_ip)
        raise HTTPException(status_code=403, detail="Forbidden: IP not allowed")

    return client_ip


def _safe_path(filepath: str, client_ip: str) -> str:
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
        # ⚠⚠ **ตอบ 404 ให้คนยิง แต่บันทึกเป็น warning ฝั่งเรา** — สองอย่างนี้ต้อง
        #    แยกกันโดยตั้งใจ · ถ้าตอบ 403 คนยิงจะรู้ว่าเดามาถูกทางแล้ว ส่วนถ้าไม่
        #    บันทึกเลย เหตุการณ์นี้จะกลืนไปกับ 404 ปกติจนมองไม่เห็น
        #
        #    ในการใช้งานปกติเหตุการณ์นี้ **ไม่ควรเกิดเลยสักครั้ง** — Power BI ขอ
        #    เฉพาะ path ที่ backend สร้างให้ เจอเมื่อไหร่คือมีอะไรผิดปกติแน่นอน
        log.warning("⛔ พยายามออกนอกโฟลเดอร์รูป: ip=%s path=%r", client_ip, filepath)
        raise HTTPException(status_code=404, detail="File not found")
    return target


@app.get("/images/{filepath:path}")
async def get_image(filepath: str, request: Request):
    client_ip = check_subnet(request)
    file_path = _safe_path(filepath, client_ip)

    if not os.path.isfile(file_path):
        # ⚠ คนละเรื่องกับ traversal ข้างบน — อันนี้คือ path ถูกต้องแต่ไฟล์หายไป
        #    แปลว่ารูปถูกลบจาก image_ALPL ทั้งที่ DB ยังเก็บ image_path อยู่
        #    (เช่นมีคนลบไฟล์เองด้วยมือ) ระดับ info เพราะเป็นเรื่องข้อมูล ไม่ใช่ภัย
        log.info("ไม่พบไฟล์: %s (ขอโดย %s)", filepath, client_ip)
        raise HTTPException(status_code=404, detail="File not found")

    # ⚠ ตั้งใจ **ไม่** log ตอนเสิร์ฟสำเร็จ — Power BI refresh ครั้งเดียวดึงรูป
    #    หลายร้อยรูป จะท่วม log จนหา warning ไม่เจอ · ถ้าอยากได้ให้เปิด access log
    #    ของ uvicorn แทน (ค่า default เปิดอยู่แล้ว)
    return FileResponse(file_path)


if __name__ == "__main__":
    log.info("=" * 66)
    log.info("TM-X Image Server (สำหรับ Power BI)")
    log.info("  ฟังที่         : %s:%s", SERVER_HOST, SERVER_PORT)
    log.info("  URL สำหรับ Power BI : %s/images/<path>", PUBLIC_BASE_URL)
    log.info("  เสิร์ฟรูปจาก   : %s", _IMAGE_ROOT)
    log.info("  อนุญาตเฉพาะ IP : วง LAN (10.x / 172.16-31.x / 192.168.x) และ localhost")
    if not os.path.isdir(_IMAGE_ROOT):
        log.warning("  ⚠ ไม่พบโฟลเดอร์รูป — ทุก request จะได้ 404")
        log.warning("    ตรวจ ALPL_IMAGE_DIR ใน .env ให้ตรงกับที่ backend เซฟรูปลง")
    if PUBLIC_BASE_URL.startswith(("http://127.0.0.1", "http://localhost")):
        log.warning("  ⚠ PUBLIC_BASE_URL ยังเป็น localhost — Power BI บนเครื่องอื่นจะดึงรูปไม่ได้")
        log.warning("    ตั้ง IMAGE_PUBLIC_BASE_URL ใน .env เป็น Hostname หรือ IP จริงของเครื่องนี้")
    log.info("=" * 66)
    uvicorn.run(app, host=SERVER_HOST, port=SERVER_PORT)
PUBLIC_BASE_URL = os.getenv(
    "IMAGE_PUBLIC_BASE_URL", 
    f"http://{default_hostname}:{SERVER_PORT}"
)

# resolve ครั้งเดียวตอนเริ่ม แล้วใช้ตัวนี้เทียบทุกครั้ง — เก็บเป็น absolute path
# ที่คลี่ symlink แล้ว เพื่อให้เทียบกับ path ปลายทางได้อย่างถูกต้อง
_IMAGE_ROOT = os.path.realpath(IMAGE_DIR)

app = FastAPI(title="TM-X Image Server")


def check_subnet(request: Request):
    """ผ่านเฉพาะ IP ในวง LAN (RFC 1918) — ครอบคลุมทุกซับเน็ตในบริษัท

    ⚠ เดิมล็อกไว้ที่ prefix เดียว (`"172.20.10."`) ซึ่งพังทันทีที่ Power BI ไปอยู่
      คนละวง หรือ IT เปลี่ยน DHCP scope · เปลี่ยนมาถามว่า "เป็น IP ภายในไหม"
      แทนการเทียบตัวเลขตายตัว

    ⚠⚠ **ห้ามถอดด่านนี้ออกให้ผ่านทุก IP** — ไฟล์นี้เสิร์ฟไฟล์จากดิสก์ตรง ๆ และ
      เคยมีช่องโหว่ path traversal มาแล้ว (ดู `_safe_path`) ด่านนี้คือเกราะชั้นสอง
      ที่เหลืออยู่ถ้าชั้นแรกพลาดอีก

    ⚠ `request.client` เป็น `None` ได้ — เดิมเขียน `request.client.host` ตรง ๆ
      แล้วจะระเบิดเป็น AttributeError → ตอบ 500 พร้อม traceback ซึ่งอาจเผย path
      ภายในเครื่องให้คนยิงเห็น (อันตรายเป็นพิเศษเพราะพอร์ตนี้เปิดออกวงบริษัท)
    """
    client_ip = request.client.host if request.client else None
    if client_ip is None:
        log.warning("ปฏิเสธ: ไม่ทราบ IP ต้นทาง")
        raise HTTPException(status_code=403, detail="Forbidden: IP not allowed")

    try:
        ip = ipaddress.ip_address(client_ip)
    except ValueError:
        log.warning("ปฏิเสธ: IP ต้นทางผิดรูปแบบ (%s)", client_ip)
        raise HTTPException(status_code=403, detail="Forbidden: IP not allowed")

    if not (ip.is_private or ip.is_loopback):
        # ⚠ เหตุการณ์นี้บอก 2 อย่างพร้อมกัน — Power BI ตั้งค่าผิดวง (config พัง)
        #    หรือมีคนนอกวงมาลอง · ทั้งคู่ต้องรู้ ไม่ควรเงียบ
        log.warning("ปฏิเสธ: IP นอกวง LAN (%s)", client_ip)
        raise HTTPException(status_code=403, detail="Forbidden: IP not allowed")

    return client_ip


def _safe_path(filepath: str, client_ip: str) -> str:
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
        # ⚠⚠ **ตอบ 404 ให้คนยิง แต่บันทึกเป็น warning ฝั่งเรา** — สองอย่างนี้ต้อง
        #    แยกกันโดยตั้งใจ · ถ้าตอบ 403 คนยิงจะรู้ว่าเดามาถูกทางแล้ว ส่วนถ้าไม่
        #    บันทึกเลย เหตุการณ์นี้จะกลืนไปกับ 404 ปกติจนมองไม่เห็น
        #
        #    ในการใช้งานปกติเหตุการณ์นี้ **ไม่ควรเกิดเลยสักครั้ง** — Power BI ขอ
        #    เฉพาะ path ที่ backend สร้างให้ เจอเมื่อไหร่คือมีอะไรผิดปกติแน่นอน
        log.warning("⛔ พยายามออกนอกโฟลเดอร์รูป: ip=%s path=%r", client_ip, filepath)
        raise HTTPException(status_code=404, detail="File not found")
    return target


@app.get("/images/{filepath:path}")
async def get_image(filepath: str, request: Request):
    client_ip = check_subnet(request)
    file_path = _safe_path(filepath, client_ip)

    if not os.path.isfile(file_path):
        # ⚠ คนละเรื่องกับ traversal ข้างบน — อันนี้คือ path ถูกต้องแต่ไฟล์หายไป
        #    แปลว่ารูปถูกลบจาก image_ALPL ทั้งที่ DB ยังเก็บ image_path อยู่
        #    (เช่นมีคนลบไฟล์เองด้วยมือ) ระดับ info เพราะเป็นเรื่องข้อมูล ไม่ใช่ภัย
        log.info("ไม่พบไฟล์: %s (ขอโดย %s)", filepath, client_ip)
        raise HTTPException(status_code=404, detail="File not found")

    # ⚠ ตั้งใจ **ไม่** log ตอนเสิร์ฟสำเร็จ — Power BI refresh ครั้งเดียวดึงรูป
    #    หลายร้อยรูป จะท่วม log จนหา warning ไม่เจอ · ถ้าอยากได้ให้เปิด access log
    #    ของ uvicorn แทน (ค่า default เปิดอยู่แล้ว)
    return FileResponse(file_path)


if __name__ == "__main__":
    log.info("=" * 66)
    log.info("TM-X Image Server (สำหรับ Power BI)")
    log.info("  ฟังที่         : %s:%s", SERVER_HOST, SERVER_PORT)
    log.info("  URL สำหรับ Power BI : %s/images/<path>", PUBLIC_BASE_URL)
    log.info("  เสิร์ฟรูปจาก   : %s", _IMAGE_ROOT)
    log.info("  อนุญาตเฉพาะ IP : วง LAN (10.x / 172.16-31.x / 192.168.x) และ localhost")
    if not os.path.isdir(_IMAGE_ROOT):
        log.warning("  ⚠ ไม่พบโฟลเดอร์รูป — ทุก request จะได้ 404")
        log.warning("    ตรวจ ALPL_IMAGE_DIR ใน .env ให้ตรงกับที่ backend เซฟรูปลง")
    if PUBLIC_BASE_URL.startswith(("http://127.0.0.1", "http://localhost")):
        log.warning("  ⚠ PUBLIC_BASE_URL ยังเป็น localhost — Power BI บนเครื่องอื่นจะดึงรูปไม่ได้")
        log.warning("    ตั้ง IMAGE_PUBLIC_BASE_URL ใน .env เป็น Hostname หรือ IP จริงของเครื่องนี้")
    log.info("=" * 66)
    uvicorn.run(app, host=SERVER_HOST, port=SERVER_PORT)
