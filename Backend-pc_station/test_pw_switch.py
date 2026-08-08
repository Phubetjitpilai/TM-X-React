"""
test_pw_switch.py — ทดสอบการเปลี่ยนโปรแกรมวัด (PW) กลางคันบน TM-X

ลำดับ (กี่รอบก็ได้ ระบุจาก argv):
    RM → R0 → [รอ RM=1] → (PW,1,<X> → T1) × N → จบ

    ค่าเริ่มต้น: 021 → 020 → 021

⭐ ทำไมรอบที่ 3 ถึงวนกลับมา 021 อีกครั้ง
    เป็นตัวชี้ขาดว่า "PW ที่ช้า" เกิดจากอะไร เพราะรอบ 1 กับรอบ 3 เป็น
    โปรแกรมเดียวกัน ต่างกันแค่ตำแหน่ง (รอบ 3 ผ่านการวัดมาแล้ว 2 ชิ้น)

        PW(021) รอบ 3 เร็วเท่ารอบ 1  → ช้าเพราะ **ตัวโปรแกรม** (020 ใหญ่กว่า)
                                        ⇒ ตั้ง timeout ตามโปรแกรมที่ช้าสุดก็พอ
        PW(021) รอบ 3 ช้าเหมือน 020  → ช้าเพราะ **ตำแหน่ง** (ยิ่งวัดยิ่งช้า)
                                        ⇒ ของจริงวัดหลายสิบชิ้นจะช้าบานปลาย

⚠ ไม่ส่ง S0 ตอนจบ — TM-X ค้างอยู่ในโหมดดำเนินการวัด (Run) ตั้งใจให้เป็นแบบนั้น
  คำสั่งที่ระบบนี้ใช้ (R0/PW/T1/RM/GM) ทำงานในโหมดวัดได้หมด และ R0 สั่งได้จาก
  ทั้ง 2 โหมด รอบหน้าจึงเริ่มได้ตามปกติ (เร็วกว่าด้วยเพราะไม่ต้องสลับโหมด) —
  ในสายการผลิตจริง vision controller อยู่โหมดวัดตลอดอยู่แล้ว
  ถ้าต้องการกลับโหมดตั้งค่าเพื่อแก้โปรแกรมหน้าเครื่อง ให้รัน send_s0.py

ทำไมต้องรู้: แผนฟอร์มหลายกลุ่ม (วัดหลาย Package Size ในรอบเดียว) ต้องสลับ
โปรแกรมวัดระหว่างทางโดยไม่ส่ง S0 คั่น
    - ถ้าเปลี่ยนได้ → 1 session เดียวจบ คิวพก template ไปด้วย (แผนข้อ E)
    - ถ้าไม่ได้    → ต้องคั่น S0 → R0 → PW ระหว่างกลุ่ม (เท่ากับ 2 รอบแยก)

════════════════════════════════════════════════════════════════════════
⭐ เลิกเดาด้วย sleep() แล้ว — ใช้ RM ถามโหมดจริงแทน

    คู่มือ TM-X5000 หน้า 5-6 (หน้า 84 ของ PDF)

        RM: อ่านโหมดดำเนินการวัด/ตั้งค่า
        ส่ง : RM
        รับ : RM,n      n = 0 → โหมดตั้งค่า
                        n = 1 → โหมดดำเนินการวัด

    เดิมใช้ time.sleep() เดาเอาว่า "น่าจะสลับโหมดเสร็จแล้ว" ซึ่งเดาผิดได้
    ตอนนี้วนถาม RM จนได้โหมดที่ต้องการจริงถึงจะเดินต่อ

════════════════════════════════════════════════════════════════════════
🔑 สิ่งที่คู่มืออธิบาย และตรงกับอาการที่เจอหน้างานทุกอย่าง

  1. R0 กับ S0 ทำงานคนละจังหวะ (หน้า 5-4 หัวข้อ "สมรรถนะแบบเรียลไทม์")

        R0 : "เรียกใช้ข้อมูลคำสั่งทันที"
        S0 : "หากกำลังสั่งงานเครื่องมืออยู่ จะมีการเรียกใช้คำสั่งหลังจากที่
              การสั่งงานเครื่องมือเสร็จสมบูรณ์"

     ⇒ R0 ตอบทันทีแต่โหมดยังไม่เปลี่ยน — ต้องรอ RM=1 ยืนยันก่อนสั่งต่อ
     ⇒ S0 ต่อคิวรองานที่ค้างอยู่ จึงตอบช้ากว่ามาก settimeout(5.0) ไม่พอ

  2. ER,T1,03 ไม่ได้แปลว่า "ส่งผิด connection" (หน้า 5-4 ผลลัพธ์การสั่งงาน)

        03 = • ไม่สามารถยอมรับทริกเกอร์ได้ / ทริกเกอร์ถูกปิด (READY ไม่เปิด)
             • **เมื่อมีการออกคำสั่งในโหมดตั้งค่า**   ← สาเหตุที่เจอจริง
             • คำสั่งถูก "BLOCK"

     ⇒ ที่เจอ ER,T1,03 คือยิง T1 ตอนเครื่องยังอยู่โหมดตั้งค่า — แก้ด้วย RM
     ⇒ พอรอ RM=1 ก่อน T1 ผ่านฉลุยทั้งที่ใช้ connection หลัก (ยืนยัน 7 ส.ค. 2569)

  3. T1 ใช้ connection หลักได้ ไม่ต้องเปิดสายที่สอง
     การเปิดสายที่สองทำให้ TM-X ตัดสายเดิมทิ้ง (อุปกรณ์ควบคุมได้ทีละตัว)
     → เป็นสาเหตุที่ S0 ตอนจบ session ของ send_command(Pi).py ไม่เคยสำเร็จ

  4. PW พ่วง RESET มาด้วย (หน้า 5-79) → READY ปิดชั่วคราว
     → T1 ทันทีหลัง PW อาจได้ ER,03 → ระบบจริงควร retry

  5. คำสั่งที่ใช้ได้ในแต่ละโหมด (ตารางหน้า 5-3)

        T1  โหมดวัด ✅   โหมดตั้งค่า ✅(แต่ได้ ER,03)
        R0  โหมดวัด ✅   โหมดตั้งค่า ✅
        S0  โหมดวัด ✅   โหมดตั้งค่า ✅
        PW  โหมดวัด ✅   โหมดตั้งค่า ✅
        GM  โหมดวัด ✅   โหมดตั้งค่า ❌
        RM  โหมดวัด ✅   โหมดตั้งค่า ✅

  6. response format: สำเร็จ = echo ชื่อคำสั่ง (R0 → 'R0') · ผิด = ER,<cmd>,<code>

════════════════════════════════════════════════════════════════════════
วิธีสั่งคำสั่ง ลอกจาก send_command(Pi).py ทุกจุด
    ต่อท้าย "\\r" → sendall → sleep(0.1) → recv
    R0/PW/RM/T1 ผ่าน connection หลักทั้งหมด
    PW ใช้ str(tpl).zfill(3) → ใส่ "20" กลายเป็น "020"

วิธีใช้
    python test_pw_switch.py                  # 021 → 020 → 021 (ค่าเริ่มต้น)
    python test_pw_switch.py 021 020          # 2 รอบ
    python test_pw_switch.py 20 21 20 21      # 4 รอบ ใส่สั้นได้ zfill ให้เอง

⚠ ก่อนรัน
    1. ปิด send_command.py (กันแย่งคุยกับ TM-X)
    2. จะสั่งวัดจริง 1 ครั้งต่อรอบ → TM-X ส่งค่า+รูปเข้า FTP ของ PC ด้วย
    3. TM-X ให้มีอุปกรณ์ควบคุมได้ทีละตัว — ระหว่างสคริปต์รัน จอสัมผัสหน้าเครื่อง
       จะถูกล็อก ("Another device is currently in use.") พอสคริปต์จบและปิด
       connection สะอาดแล้วจะกลับมาใช้ได้ ถ้ายังล็อกอยู่กด [Close Other Device]
"""
import os
import socket
import sys
import time

from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))

TMX_IP   = os.getenv("TMX_HOST", "192.168.10.11")
TMX_PORT = int(os.getenv("TMX_PORT", 8600))
BUFFER_SIZE = 1024
SOCKET_TIMEOUT = 5.0       # ของจริงใช้ settimeout(5.0) กับ connection หลัก

TIMEOUT_PW = 20.0          # PW โหลดโปรแกรมจริง ใช้เวลานานกว่าคำสั่งอื่นมาก

MODE_WAIT_TIMEOUT  = 30.0  # รอให้ RM รายงานโหมดที่ต้องการ
MODE_POLL_INTERVAL = 0.3

WAIT_AFTER_T1 = 8.0        # ให้ TM-X วัด + ส่งไฟล์เข้า FTP เสร็จก่อนรอบถัดไป

DEFAULT_TEMPLATES = ["021", "020", "021"]

# ── บันทึกผลทดสอบ: ทำไม PW ตัวที่สองช้ากว่าตัวแรก ────────────────────────
# วัดได้ PW1 (โปรแกรม 021) = 1.55 วิ · PW2 (โปรแกรม 020) = 3.73 วิ → ต่าง 2.4 เท่า
#
# เคยสงสัย 3 สาเหตุ:
#   1. ตัวโปรแกรม 020 ใหญ่/ซับซ้อนกว่า 021
#   2. RESET ที่พ่วงมากับ PW มีงานมากกว่า (ล้างภาพประวัติ/บัฟเฟอร์จากการวัด)
#   3. TM-X ยังยุ่งกับการส่งไฟล์ FTP อยู่
#
# ทดสอบรอบที่ 1 (7 ส.ค. 2569): แทรก R0 ซ้ำ + หน่วง 5 วิ ก่อนยิง PW2
#   → PW2 ยังใช้ 3.73 วิ เท่าเดิมเป๊ะ ไม่ดีขึ้นเลย
#   ⇒ ตัดข้อ 3 ออก (หน่วงเวลาเท่าไหร่ก็ไม่ช่วย) เหลือข้อ 1 กับ 2 ที่ยังแยกไม่ออก
#
# ทดสอบรอบที่ 2 (7 ส.ค. 2569): วน 021 → 020 → 021 แล้วเทียบ 021 สองรอบ
#   ผลจริง   021 = 1.58 วิ · 020 = 3.72 วิ · 021 = 1.54 วิ
#   → 021 รอบ 3 (หลังวัดมาแล้ว 2 ชิ้น) เร็วเท่ารอบ 1 ต่างกันแค่ 0.04 วิ
#   ⇒ ตัดข้อ 2 ออกด้วย — **เป็นเพราะตัวโปรแกรมเอง (ข้อ 1) ล้วนๆ**
#
# 🔑 ข้อสรุปที่เอาไปใช้กับ send_command(Pi).py ได้เลย
#   • PW ช้าคงที่ตามโปรแกรม ไม่สะสมตามจำนวนชิ้นที่วัด — วัด 50 ชิ้นก็ไม่บานปลาย
#   • หน่วงเวลาก่อนยิง PW ไม่ช่วยอะไรเลย อย่าเสียเวลาใส่
#   • เพดานที่ต้องเผื่อ = โปรแกรมที่ช้าที่สุดในระบบ ไม่ใช่ค่าที่โตตาม session
#   • 020 ใช้ 3.72 วิ เหลือ margin แค่ 1.28 วิจาก settimeout(5.0) ของโค้ดจริง
#     → ยังไม่เคยวัดโปรแกรมอื่นครบ ควรตั้ง TIMEOUT_PW = 20 วิไปเลย
#       (timeout เป็นเพดาน ไม่ใช่การหน่วง ตอบเร็วก็ไม่ได้รอนาน = ไม่มีข้อเสีย)
WARN_PW_SECONDS = SOCKET_TIMEOUT   # PW เกินเท่านี้ = โค้ดจริงจะพัง
SAME_TPL_TOLERANCE = 0.5           # โปรแกรมเดียวกันต่างกันเกินนี้ = ไม่คงที่

MODE_NAME = {0: "โหมดตั้งค่า (Setting)", 1: "โหมดดำเนินการวัด (Run)"}


# ══════════════════════════════════════════════════════════════════════
# ชั้นสื่อสาร — ลอกจาก send_command(Pi).py
# ══════════════════════════════════════════════════════════════════════
def send_command(sock, command, timeout=SOCKET_TIMEOUT, label="", quiet=False):
    """ส่ง 1 คำสั่งแล้วคืน (response, status, วินาทีที่ใช้)

    status: ok / error (ER,...) / timeout

    ⚠ เวลาที่คืนรวม sleep(0.1) เข้าไปด้วย (ลอกจากโค้ดจริง) เวลาที่ TM-X ใช้จริง
      ≈ ค่านี้ − 0.1 · ค่า 0.10 เป๊ะ = ตอบเร็วกว่า 0.1 วิ วัดละเอียดกว่านี้ไม่ได้
    """
    sock.settimeout(timeout)
    t0 = time.time()
    sock.sendall((command + "\r").encode("ascii"))   # ต้องต่อท้ายด้วย CR เสมอ
    time.sleep(0.1)                                   # หน่วงให้กล้องประมวลผล
    try:
        response = sock.recv(BUFFER_SIZE).decode("ascii").strip()
    except socket.timeout:
        dt = time.time() - t0
        print(f"  ⏱ TO  {command:<12} → ไม่ตอบใน {timeout:.0f} วิ   ({dt:.2f}s) {label}")
        return "<timeout>", "timeout", dt
    except Exception as exc:
        dt = time.time() - t0
        print(f"  ❌ ??  {command:<12} → {type(exc).__name__}: {exc}   {label}")
        return f"<{type(exc).__name__}>", "timeout", dt

    dt = time.time() - t0
    status = "error" if response.upper().startswith("ER") else "ok"
    if not quiet:
        print(f"  {'❌ ER' if status == 'error' else '✅'}  {command:<12} → "
              f"{response!r}   ({dt:.2f}s) {label}")
    if status == "error" and ",03" in response:
        print("        ↑ 03 = ไม่อยู่โหมดวัด / READY ไม่เปิด / ถูก BLOCK")
    return response, status, dt


# ══════════════════════════════════════════════════════════════════════
# ⭐ RM — ถามโหมดจริงแทนการเดาด้วย sleep()
# ══════════════════════════════════════════════════════════════════════
def read_mode(sock, quiet=True):
    """อ่านโหมดปัจจุบันด้วย RM — คืน 0 (ตั้งค่า) / 1 (ดำเนินการวัด) / None

    รูปแบบตอบกลับตามคู่มือหน้า 5-6: "RM,n"
    เป็นคำสั่งอ่านอย่างเดียว ยิงกี่ครั้งก็ได้ ไม่กระทบเวลาประมวลผลการวัด
    """
    resp, status, _ = send_command(sock, "RM", quiet=quiet)
    if status != "ok":
        return None
    parts = resp.split(",")
    if len(parts) >= 2:
        try:
            return int(parts[1].strip())
        except ValueError:
            pass
    return None


def wait_for_mode(sock, want, timeout=MODE_WAIT_TIMEOUT):
    """วนถาม RM จนกว่าโหมดจะเป็น `want` — คืน True/False

    นี่คือสิ่งที่มาแทน time.sleep() แบบเดาๆ ทั้งหมด
    """
    deadline, t0, last = time.time() + timeout, time.time(), None
    while time.time() < deadline:
        m = read_mode(sock)
        if m == want:
            print(f"     ✅ ยืนยันแล้ว: {MODE_NAME[want]}   (ใช้เวลา {time.time()-t0:.2f}s)")
            return True
        if m != last:
            print(f"     ... ตอนนี้ {MODE_NAME.get(m, f'อ่านไม่ได้ ({m})')} — รอต่อ")
            last = m
        time.sleep(MODE_POLL_INTERVAL)
    print(f"     ❌ รอ {timeout:.0f} วิแล้วยังไม่เป็น {MODE_NAME[want]}")
    return False


# ══════════════════════════════════════════════════════════════════════
def run_rounds(sock, templates):
    """วน PW → T1 ทีละรอบ คืน list ของผลแต่ละรอบ

    หยุดทันทีถ้า PW ไม่ผ่าน หรือ connection ตาย — ผลที่เก็บมาแล้วยังใช้สรุปได้
    """
    rounds = []
    n = len(templates)
    for i, tpl in enumerate(templates, start=1):
        r = {"no": i, "tpl": tpl}
        rounds.append(r)
        print(f"\n── รอบที่ {i}/{n} · โปรแกรม {tpl} ────────────────────────────")

        _, r["pw"], r["pw_s"] = send_command(sock, f"PW,1,{tpl}", timeout=TIMEOUT_PW)
        if r["pw"] != "ok":
            print(f"     ⛔ โหลดโปรแกรม {tpl} ไม่สำเร็จ — หยุด")
            break

        # PW ไม่ควรเตะเรากลับโหมดตั้งค่า — เช็คไว้ให้แน่ใจ
        r["mode_after_pw"] = read_mode(sock)
        if r["mode_after_pw"] != 1:
            print(f"     ⚠️ หลัง PW ไม่ได้อยู่โหมดวัดแล้ว "
                  f"({MODE_NAME.get(r['mode_after_pw'], r['mode_after_pw'])})")

        _, r["t1"], _ = send_command(sock, "T1", label=f"(โปรแกรม {tpl})")

        if i < n:
            print(f"     รอ {WAIT_AFTER_T1:.0f} วิให้วัด+ส่งไฟล์เข้า FTP เสร็จ...")
            time.sleep(WAIT_AFTER_T1)
            if read_mode(sock) is None:
                print("     🔴 connection หลักตายแล้ว — หยุด")
                r["conn_died"] = True
                break
    return rounds


def summarize(rounds, templates):
    n = len(templates)
    print("\n" + "=" * 72)
    print("สรุปผล")
    print("=" * 72)

    ok_pw = [r for r in rounds if r.get("pw") == "ok"]
    ok_t1 = [r for r in rounds if r.get("t1") == "ok"]
    print(f"  ทำได้ {len(rounds)}/{n} รอบ · PW ผ่าน {len(ok_pw)} · T1 ผ่าน {len(ok_t1)}")

    # ── เปลี่ยนโปรแกรมกลางคันได้ไหม ────────────────────────────────────
    print()
    if len(ok_pw) >= 2:
        print("✅ เปลี่ยนโปรแกรมวัดกลางคัน **ได้** — ไม่ต้องคั่นด้วย S0/R0")
        print("   → แผนข้อ E ใช้ได้: 1 session เดียว คิวพก template ไปด้วย")
        if all(r.get("mode_after_pw") == 1 for r in ok_pw):
            print("   และอยู่ในโหมดดำเนินการวัดตลอด (PW ไม่เตะกลับโหมดตั้งค่า)")
    else:
        print("❌ ยังสรุปไม่ได้ — PW ผ่านไม่ถึง 2 รอบ")

    if any(r.get("conn_died") for r in rounds):
        print("\n🔴 connection หลักถูกตัดกลางทาง — ต้องต่อใหม่ก่อนสั่งคำสั่งถัดไป")
    elif len(ok_t1) >= 1:
        print("\n✅ connection หลักอยู่รอดตลอด — T1 ไม่ต้องเปิดสายที่สอง")

    fail_t1 = [r for r in rounds if r.get("t1") not in (None, "ok")]
    if fail_t1:
        print(f"\n⚠️ T1 ไม่ผ่าน {len(fail_t1)} รอบ: "
              + ", ".join(f"รอบ {r['no']} ({r['tpl']})" for r in fail_t1))
        print("   ถ้าเป็น ER,03 → READY ยังไม่เปิดหลัง PW ทำ RESET (กติกาข้อ 4)")
        print("   → ระบบจริงควร retry T1 เมื่อเจอ ER,03 (ปลอดภัย: 03 = ไม่ได้วัดเลย)")

    # ── ⭐ เวลา PW: ตัวชี้ขาดว่าช้าเพราะโปรแกรม หรือเพราะตำแหน่ง ─────────
    if not ok_pw:
        print("=" * 72)
        return

    print("\n" + "-" * 72)
    print("⏱ เวลาที่ PW ใช้ (รวม sleep(0.1) แล้ว · โค้ดจริงตั้ง settimeout(5.0))")
    for r in ok_pw:
        flag = "  ⚠️ เกิน 5 วิ!" if r["pw_s"] > WARN_PW_SECONDS else ""
        print(f"     รอบ {r['no']}  โปรแกรม {r['tpl']}  :  {r['pw_s']:.2f} วิ{flag}")

    by_tpl = {}
    for r in ok_pw:
        by_tpl.setdefault(r["tpl"], []).append(r["pw_s"])
    repeated = {t: v for t, v in by_tpl.items() if len(v) >= 2}

    if repeated:
        print("\n⭐ ตัวชี้ขาด — โปรแกรมเดียวกันที่โหลดซ้ำหลายรอบ")
        positional = False
        for t, times in repeated.items():
            spread = max(times) - min(times)
            marks = " · ".join(f"{v:.2f}" for v in times)
            verdict = ("คงที่ ✅" if spread <= SAME_TPL_TOLERANCE
                       else f"ต่างกัน {spread:.2f} วิ ⚠️")
            print(f"     {t} : {marks} วิ   → {verdict}")
            if spread > SAME_TPL_TOLERANCE:
                positional = True
        print()
        if positional:
            print("   ⚠️ โปรแกรมเดิมใช้เวลาไม่เท่ากันในแต่ละรอบ")
            print("      → PW ช้าขึ้นตาม **ตำแหน่ง** (ยิ่งวัดไปเยอะยิ่งช้า)")
            print("      → ของจริงที่วัดหลายสิบชิ้นจะช้ากว่านี้อีก ต้องเผื่อ timeout เยอะมาก")
        else:
            print("   ✅ โปรแกรมเดิมใช้เวลาเท่าเดิมทุกรอบ ไม่ว่าจะวัดมาแล้วกี่ชิ้น")
            print("      → PW ช้าเพราะ **ตัวโปรแกรมเอง** ไม่ใช่การสะสมจากการวัด")
            print("      → ตั้ง timeout ตามโปรแกรมที่ช้าที่สุดก็พอ ไม่บานปลาย")
    else:
        print("\n   (ใส่โปรแกรมเดิมซ้ำอย่างน้อย 2 รอบ เพื่อแยกว่าช้าเพราะโปรแกรมหรือตำแหน่ง")
        print(f"    เช่น: python test_pw_switch.py "
              f"{templates[0]} {templates[-1]} {templates[0]})")

    slowest = max(r["pw_s"] for r in ok_pw)
    print()
    if slowest > WARN_PW_SECONDS:
        print(f"🔴 PW ช้าสุด {slowest:.2f} วิ — เกิน settimeout(5.0) ของโค้ดจริง")
        print("   send_command(Pi).py จะโยน socket.timeout → 'session พังกลางทาง'")
        print("   → ต้องเพิ่ม timeout ให้ PW ใน send_command(Pi).py")
    else:
        print(f"✅ PW ช้าสุด {slowest:.2f} วิ (เหลือ margin "
              f"{WARN_PW_SECONDS - slowest:.2f} วิจาก 5 วิของโค้ดจริง)")
        if slowest > WARN_PW_SECONDS * 0.6:
            print("   ⚠️ แต่เฉียดแล้ว — โปรแกรมที่ใหญ่กว่านี้อาจเกิน ควรเพิ่ม timeout เผื่อไว้")

    print("=" * 72)


def main():
    templates = [str(a).zfill(3) for a in sys.argv[1:]] or DEFAULT_TEMPLATES
    n = len(templates)

    print("=" * 72)
    print("ทดสอบ: เปลี่ยนโปรแกรมวัด (PW) กลางคัน")
    print("  (ใช้ RM ยืนยันโหมดจริง แทนการเดาด้วย sleep)")
    print(f"  TM-X  : {TMX_IP}:{TMX_PORT}")
    print("  ลำดับ : RM → R0 → "
          + " → ".join(f"PW,1,{t} → T1" for t in templates) + "   (ไม่ส่ง S0)")
    print("=" * 72)
    print(f"⚠ จะสั่งวัดจริง {n} ครั้ง — วางชิ้นงานใต้กล้องให้พร้อม")
    input("  กด Enter เพื่อเริ่ม (Ctrl+C ยกเลิก): ")

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(SOCKET_TIMEOUT)
        sock.connect((TMX_IP, TMX_PORT))
    except Exception as exc:
        print(f"\n❌ ต่อ TM-X ไม่ได้ — {type(exc).__name__}: {exc}")
        print("   ตรวจ: สาย LAN · TM-X เปิดอยู่ไหม · send_command.py ปิดแล้วยัง")
        return

    rounds = []
    try:
        print("\n── 0. ถามโหมดปัจจุบันก่อน ─────────────────────────────────")
        m0 = read_mode(sock, quiet=False)
        print(f"     → {MODE_NAME.get(m0, f'อ่านไม่ได้ ({m0})')}")
        if m0 is None:
            print("\n⛔ อ่านโหมดไม่ได้ — RM ไม่ตอบ หยุดตรงนี้")
            return

        print("\n── 1. R0 เข้าโหมดดำเนินการวัด ─────────────────────────────")
        _, st_r0, _ = send_command(sock, "R0")
        if st_r0 != "ok" or not wait_for_mode(sock, 1):
            print("\n⛔ เข้าโหมดดำเนินการวัดไม่สำเร็จ — หยุด")
            return

        rounds = run_rounds(sock, templates)

    except Exception as exc:
        print(f"\n❌ พังกลางทาง — {type(exc).__name__}: {exc}")
    finally:
        # ปิดสะอาด — ไม่งั้น TM-X ยังคิดว่ามีอุปกรณ์ควบคุมเชื่อมอยู่ จอจะล็อกต่อ
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            sock.close()
        except Exception:
            pass

    if rounds:
        summarize(rounds, templates)

    print()
    print("ℹ️  ไม่ได้ส่ง S0 — TM-X ยังอยู่ในโหมดดำเนินการวัด (Run)")
    print("   ปกติสำหรับการใช้งานจริง · ถ้าจะแก้โปรแกรมหน้าเครื่อง รัน send_s0.py")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nยกเลิก")
