"""main.py (ฉบับแยกไฟล์) — สร้าง app แล้วประกอบ router เข้าด้วยกัน

รันได้ 2 แบบ (ต้อง `cd Backend-server` ก่อนทั้งคู่ ไม่งั้น import routers ไม่เจอ):

    python main_split.py                              ← หน้างานใช้ตัวนี้
    uvicorn main_split:app --reload --port 8000       ← ตอน dev (มี hot reload)

ดูบล็อก `if __name__ == "__main__"` ท้ายไฟล์
"""
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

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

class SPAStaticFiles(StaticFiles):
    """StaticFiles ที่ตกกลับไปที่ index.html เมื่อหา path ไม่เจอ

    จำเป็นตั้งแต่ย้ายมาเสิร์ฟ React (Frontend-react/dist) เพราะ React Router
    ใช้ **path เปล่า** (`/edit`, `/export`) ซึ่งไม่มีไฟล์จริงอยู่บนดิสก์ ต่างจาก
    `Frontend/` เดิมที่ลิงก์ชี้ไปหาไฟล์ตรงๆ (`/edit.html`) จึงไม่เคยต้องมีตัวนี้

    อาการถ้าไม่มี: กดเมนูในเว็บได้ปกติ (Router จัดการในเบราว์เซอร์ ไม่ได้ยิง
    request ออกมาเลย) แต่ **กด F5 ค้างอยู่หน้านั้น หรือเปิด URL ตรงๆ จะ 404**
    — เป็นบั๊กที่หลุดการทดสอบง่ายมากเพราะเดินเมนูปกติไม่มีทางเจอ

    ⚠ ผลข้างเคียงที่ต้องรู้: path มั่วๆ ที่ไม่มีจริง (เช่น `/assets/xxx.js`
      ที่พิมพ์ผิด) จะได้ index.html กลับไปพร้อม **status 200 แทน 404** ยอมรับ
      ได้เพราะ `/api/*` ถูก include_router ไว้ก่อนหน้าแล้ว ไม่มีทางตกมาถึงนี่
      (ดูคำเตือนเรื่องลำดับข้างบน) — แต่เวลาไล่บั๊กเรื่องไฟล์ static หาย
      ต้องระวังว่าจะไม่เห็น 404 ให้จับ
    """

    async def get_response(self, path, scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code == 404:
                return await super().get_response("index.html", scope)
            raise


# ⚠ ชี้ไปที่ผลลัพธ์ของ `npm run build` ไม่ใช่ซอร์ส — ต้อง build ใหม่ทุกครั้ง
#   ที่แก้โค้ด React ไม่งั้นจะไม่เห็นการเปลี่ยนแปลง (ระหว่าง dev ให้ใช้
#   `npm run dev` ที่ port 5173 แทน จะได้ hot reload)
#
#   ถอยกลับของเดิมได้ทันทีถ้าอะไรพังหน้างาน: เปลี่ยนเป็น "Frontend" แล้ว
#   สลับ SPAStaticFiles กลับเป็น StaticFiles — โฟลเดอร์เดิมยังอยู่ครบ
_frontend_dir = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "Frontend-react", "dist")
)

app.mount(
    "/",
    SPAStaticFiles(directory=_frontend_dir, html=True),
    name="static",
)


if __name__ == "__main__":
    # ── รันตรงจากไฟล์นี้ได้เลย: `python main_split.py` ────────────────────
    # มีไว้ให้หน้างานไม่ต้องจำคำสั่ง uvicorn ยาว ๆ (แบบเดียวกับ Pi.py)
    #
    # ⚠⚠ **ห้ามใส่ `reload=True` ที่นี่เด็ดขาด** — reload จ้องดูไฟล์แล้วรีสตาร์ท
    #   เองเมื่อมีอะไรเปลี่ยน ซึ่งจะทำให้ **SSE ของทุกเครื่องที่เปิดหน้าเว็บอยู่
    #   หลุดพร้อมกัน** กลางรอบการวัด · ตอน dev ให้ใช้คำสั่ง uvicorn ข้างบนแทน
    #
    # ⚠ ส่ง `app` เป็น object ตรง ๆ ไม่ใช่สตริง "main_split:app" — เพราะ
    #   ตอนรันแบบนี้ module ชื่อ `__main__` ไม่ใช่ `main_split` uvicorn จะ
    #   import ซ้ำแล้วได้ app คนละตัวกับที่ router ลงทะเบียนไว้
    #   (แลกกับการที่ reload/workers ใช้ไม่ได้ ซึ่งเราไม่ต้องการอยู่แล้ว)
    #
    # host 0.0.0.0 = รับจากเครื่องอื่นในวง LAN ด้วย — จำเป็น เพราะ Pi ต้องยิง
    # heartbeat/measurement กลับมา และ Operator เปิดหน้าเว็บจากเครื่องอื่น
    _host = os.getenv("BACKEND_HOST", "0.0.0.0")
    _port = int(os.getenv("BACKEND_PORT", 8000))

    print("=" * 62)
    print("  TM-X Backend Server")
    print(f"  ฟังที่        : {_host}:{_port}   (.env: BACKEND_HOST / BACKEND_PORT)")
    print(f"  เปิดหน้าเว็บ  : http://localhost:{_port}")
    print(f"  รูปถาวร       : {ALPL_IMAGE_DIR}")
    print(f"  หน้าเว็บจาก   : {_frontend_dir}")
    if not os.path.isdir(_frontend_dir):
        print("  ⚠ ไม่พบโฟลเดอร์ dist — ต้อง `npm run build` แล้วเอามาวางก่อน")
        print("    ไม่งั้นเปิดหน้าเว็บจะได้ 404 ทุกหน้า (API ยังใช้ได้ปกติ)")
    print("=" * 62)

    uvicorn.run(app, host=_host, port=_port,access_log=False)

