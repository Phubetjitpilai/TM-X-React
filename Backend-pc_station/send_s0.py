"""
send_s0.py — ส่ง S0 ให้ TM-X กลับเข้าโหมดตั้งค่า (Setting mode) อย่างเดียว

ใช้ตอนไหน: TM-X ค้างอยู่ในโหมดดำเนินงาน (Run mode) เพราะสคริปต์ก่อนหน้าพัง
กลางทางแล้วไม่ได้ส่ง S0 ปิดท้าย — อาการคือแตะหน้าจอเครื่องแก้โปรแกรมไม่ได้
และเครื่องยังเปิดรับ T1 อยู่

    R0 → โหมดดำเนินงาน (Run)   พร้อมรับ trigger วัดงาน
    S0 → โหมดตั้งค่า (Setting)  วัดไม่ได้ แต่แก้โปรแกรมหน้าเครื่องได้

S0 เป็น idempotent — ยิงซ้ำกี่ครั้งก็ไม่มีผลข้างเคียง ถ้าอยู่โหมดตั้งค่าอยู่แล้ว
ก็แค่ตอบกลับมาเฉยๆ

════════════════════════════════════════════════════════════════════════
🔴 เรื่องที่ต้องรู้: TM-X ให้มี "อุปกรณ์ควบคุม" ได้ทีละตัวเดียว

    พอสคริปต์ต่อ TCP เข้าไป TM-X ถือว่าสคริปต์คือผู้ควบคุม → **จอสัมผัส
    หน้าเครื่องถูกล็อก** ขึ้นข้อความ:

        "Another device is currently in use.
         Operation through this device is not available."

    ยืนยันจากหน้างาน 6 ส.ค. 2569: กด [Close Other Device] ที่มุมล่างซ้ายของจอ
    แล้วเห็นว่าเครื่องอยู่ในโหมด Setup จริง — **แปลว่า S0 ทำงานสำเร็จตั้งแต่แรก
    แล้ว ปัญหาคือ TM-X ไม่ปล่อยสิทธิ์ควบคุมคืนให้จอต่างหาก**

    จึงต้องปิด connection ให้ "สะอาด" ด้วย shutdown(SHUT_RDWR) ก่อน close()
    — close() เฉยๆ แค่คืน handle ให้ OS ไม่ได้ส่ง FIN บอก TM-X ทันทีเสมอไป
    ทำให้ TM-X ยังเห็นว่ามีอุปกรณ์เชื่อมอยู่

    ถ้าจอยังล็อกอยู่หลังรันสคริปต์นี้ → กด [Close Other Device] ที่จอเครื่อง
════════════════════════════════════════════════════════════════════════

วิธีสั่ง ลอกจาก send_command(Pi).py: ต่อท้าย "\\r" → sendall → sleep(0.1)
→ recv บน connection หลัก (S0 ไม่ต้องใช้ connection แยกแบบ T1)

    python send_s0.py

⚠ ปิด send_command.py ก่อน ไม่งั้นแย่งคุยกับ TM-X
"""
import os
import socket
import time

from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))

TMX_IP   = os.getenv("TMX_HOST", "192.168.10.11")
TMX_PORT = int(os.getenv("TMX_PORT", 8600))
BUFFER_SIZE = 1024
TIMEOUT = 5.0          # เท่ากับ settimeout(5.0) ของ send_command(Pi).py


def main():
    print(f"→ ต่อ TM-X ที่ {TMX_IP}:{TMX_PORT} ...")
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(TIMEOUT)
        sock.connect((TMX_IP, TMX_PORT))
    except Exception as exc:
        print(f"❌ ต่อไม่ได้ — {type(exc).__name__}: {exc}")
        print("   ตรวจ: สาย LAN · TM-X เปิดอยู่ไหม · send_command.py ปิดแล้วยัง")
        return

    try:
        t0 = time.time()
        sock.sendall(b"S0\r")          # ต้องต่อท้ายด้วยตัวคั่น CR (\r) เสมอ
        time.sleep(0.1)                # หน่วงให้กล้องประมวลผลเล็กน้อย
        resp = sock.recv(BUFFER_SIZE).decode("ascii").strip()
        dt = time.time() - t0

        if resp.upper().startswith("ER"):
            print(f"❌ TM-X ปฏิเสธ: {resp!r}   ({dt:.2f}s)")
            print("   รหัส 03 = TM-X ไม่ว่าง (อาจกำลังวัด/ส่งไฟล์อยู่)")
            print("   → รอสัก 10 วิแล้วรันใหม่")
        else:
            print(f"✅ TM-X ตอบ: {resp!r}   ({dt:.2f}s)")
            print("   กลับเข้าโหมดตั้งค่าแล้ว — แตะหน้าจอเครื่องแก้โปรแกรมได้")

    except socket.timeout:
        print(f"⏱ ไม่ตอบกลับใน {TIMEOUT:.0f} วิ")
        print("   S0 อาจถูกส่งไปแล้วแต่ตอบช้า — ลองดูที่หน้าจอเครื่องว่าเปลี่ยนโหมดไหม")
    except Exception as exc:
        print(f"❌ {type(exc).__name__}: {exc}")
    finally:
        # ── ปิดให้สะอาด: บอก TM-X ตรงๆ ว่าจบแล้ว ก่อนคืน handle ────────────
        # close() เฉยๆ ไม่พอ — TM-X จะยังเห็นว่ามีอุปกรณ์ควบคุมเชื่อมอยู่
        # ทำให้จอสัมผัสหน้าเครื่องถูกล็อกต่อไป (ต้องไปกด Close Other Device เอง)
        # shutdown(SHUT_RDWR) ส่ง FIN ทันที = "จบแล้ว ตัดได้เลย"
        try:
            time.sleep(0.5)                    # ให้ TM-X ประมวลผล S0 ให้เสร็จก่อน
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass                               # อีกฝั่งตัดไปก่อนแล้ว ไม่เป็นไร
        try:
            sock.close()
        except Exception:
            pass
        print("   (ปิดการเชื่อมต่อแล้ว — ถ้าจอยังล็อก กด [Close Other Device] ที่เครื่อง)")


if __name__ == "__main__":
    main()
