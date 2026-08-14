"""
Test_T1_GM.py — หลังยิง T1 ต้องรอกี่ ms ถึงจะดึงค่าด้วย GM ได้

ลำดับ:
    RM → R0 → [รอ RM=1] → PW,1,<template>
    ต่อชิ้น:  MRS (ล้างค่าเก่า) → T1 → วน GM,3,0 ทุก 20ms จนได้ค่า → จับเวลา

════════════════════════════════════════════════════════════════════════
❓ 3 คำถามที่สคริปต์นี้ตอบ

  1. ต้องรอกี่ ms หลัง T1  → เอาไปตั้ง GM_MAX_WAIT ใน send_command(Pi).py
  2. MRS ล้างค่าเก่าได้จริงไหม (คู่มือพิมพ์ชื่อไม่ตรงกันเอง — ดูด้านล่าง)
  3. GM,3,0 คืนค่ามาเรียงยังไง — ตัวไหนคือ x / y / offset

ข้อ 3 สำคัญที่สุด เพราะ Pi ต้องรู้ว่าจะหยิบค่าไหนไปเทียบกับ x_lo/x_hi
ถ้าหยิบสลับกัน ผลตัดสินจะผิดทุกชิ้นโดยไม่มี error อะไรเลย

════════════════════════════════════════════════════════════════════════
🔴 ทำไมต้อง MRS ก่อน T1 ทุกครั้ง

GM ดึง "ค่าของภาพล่าสุด" และ **ไม่มีเลขลำดับกำกับ** — มองไม่ออกว่าค่าที่ได้
เป็นของชิ้นใหม่หรือชิ้นก่อน ยิ่ง T1 ตอบกลับตอน *รับทริกเกอร์* ไม่ใช่ตอนวัดเสร็จ
(คู่มือหน้า 5-4: "เวลาในการประมวลผลการวัดจะไม่ได้รับผลกระทบ") ยิง GM ตามติดจึงได้

    ER,GM,03    ← ดี รู้ตัวว่าพลาด
    ค่าชิ้นก่อน  ← อันตราย ไม่มี error ไม่มีอะไรบอก บันทึกลง DB ไปเลย

MRS ล้างค่าเก่าทิ้งก่อน ทำให้ระหว่างรอ GM **ต้อง** ตอบ "ไม่มีค่า" เท่านั้น
พอได้ค่าจริงเมื่อไหร่ = ของชิ้นใหม่แน่นอน

⚠ คู่มือหน้า 5-9 พิมพ์ไม่ตรงกันเอง — หัวข้อเขียน "MRS" แต่ช่องส่ง/รับเขียน "MSR"
  สคริปต์นี้จึงลองยิงทั้งสองแบบตอนเริ่ม แล้วใช้ตัวที่ไม่ตอบ ER
  ถ้าไม่ผ่านทั้งคู่ → ตกไปใช้วิธีเทียบกับค่าของชิ้นก่อนหน้าแทน (แม่นน้อยกว่า)

════════════════════════════════════════════════════════════════════════
⏱ ทำไมไม่ใช้ send_command() แบบไฟล์อื่น

ไฟล์อื่นลอก tcp.py มา คือ sendall → time.sleep(0.1) → recv ครั้งเดียว
sleep นั้นทำให้ **วัดอะไรที่เร็วกว่า 100ms ไม่ได้เลย** ซึ่งคือสิ่งที่จะวัดพอดี
และ recv ครั้งเดียวก็ไม่ถูกต้องนัก — TCP เป็น stream ตัดมาครึ่งเดียวได้

ที่นี่จึงใช้ sendall → วน recv จนเจอ CR (\\r) แทน ไม่มี sleep เลย
recv() บล็อกรอข้อมูลอยู่แล้วโดยธรรมชาติ sleep ไม่ได้ช่วยอะไรตั้งแต่แรก

════════════════════════════════════════════════════════════════════════
📋 GM,3,0 — ดึงทุกเครื่องมือ พร้อมสถานะและผลตัดสิน (คู่มือหน้า 5-15)

    ส่ง : GM,o,t         o=3 (ค่า+สถานะ+ผลตัดสิน) · t=0 (ทุกเครื่องมือ)
    รับ : GM,t,m,i,j,…,m,i,j

        m = ค่าที่วัดได้
        i = สถานะ 0:ไม่ทำงาน 1:ค่าปกติ 2:แก้ตำแหน่งล้มเหลว
                  3:ข้อมูลไม่ถูกต้อง 4:รอตัดสิน
        j = ผลตัดสินของ TM-X เอง  0:OK  1:NG

⭐ j มีประโยชน์มาก — เอาไปเทียบกับที่ backend คำนวณจาก DB ได้
   ไม่ตรงกันเมื่อไหร่ = tolerance ในโปรแกรม TM-X กับใน DB เพี้ยนกันแล้ว

════════════════════════════════════════════════════════════════════════
วิธีใช้
    python Test_T1_GM.py                 # โปรแกรม 021 · 5 ชิ้น
    python Test_T1_GM.py 020             # เปลี่ยนโปรแกรม
    python Test_T1_GM.py 020 10          # 10 ชิ้น

⚠ ก่อนรัน
    1. ปิด send_command.py (กันแย่งคุยกับ TM-X — คุมได้ทีละอุปกรณ์)
    2. จะสั่งวัดจริงทุกชิ้น → TM-X ส่งไฟล์เข้า FTP ของ PC ด้วย
    3. ไม่ส่ง S0 ตอนจบ (ค้างในโหมดวัด ตั้งใจ) — ถ้าจะแก้โปรแกรมหน้าเครื่อง
       ให้รัน send_s0.py
"""
import os
import socket
import statistics
import sys
import time

from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))

TMX_IP   = os.getenv("TMX_HOST", "192.168.10.11")
TMX_PORT = int(os.getenv("TMX_PORT", 8600))
BUFFER_SIZE = 1024

SOCKET_TIMEOUT = 5.0
TIMEOUT_PW     = 20.0      # PW ช้ากว่าคำสั่งอื่นมาก (วัดได้ 1.5-3.8 วิ)

MODE_WAIT_TIMEOUT  = 30.0
MODE_POLL_INTERVAL = 0.3

GM_POLL_INTERVAL = 0.02    # 20ms — ความละเอียดของการวัดเวลา
GM_MAX_WAIT      = 8.0     # รอค่าสูงสุดต่อชิ้น

# ── เทียบ GM กับไฟล์ .txt ที่ TM-X ส่งมาทาง FTP ────────────────────────────
# ต้องรัน Recieve_tm-x.py (โหมด FORWARD_TO_BACKEND=0) คู่กันถึงจะมีไฟล์ให้อ่าน
# ถ้าไม่ได้รัน ส่วนนี้จะข้ามไปเงียบๆ ไม่กระทบการวัดเวลา
#
# ทำไมต้องเทียบ: GM คืนมา 8 เครื่องมือ แต่ .txt มีแค่ 3 ช่อง (x, y, offset)
# ยังไม่รู้ว่า index ไหนของ GM ตรงกับช่องไหนของ .txt — และ offset อาจไม่ได้อยู่ใน
# GM เลยด้วยซ้ำ (อาจเป็นค่าที่ TM-X คำนวณตอนเขียนไฟล์) ซึ่งถ้าจริงจะกระทบแผน
# ที่จะให้ Pi ตัดสิน OK/NG เองครบ 3 ข้อ
TEMP_IMAGE_DIR = os.getenv("TEMP_IMAGE_DIR", "./Store_image_temporary")
if not os.path.isabs(TEMP_IMAGE_DIR):
    TEMP_IMAGE_DIR = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", TEMP_IMAGE_DIR.lstrip("./"))
    )
TXT_WAIT = 8.0             # รอไฟล์ .txt หลังได้ค่าจาก GM (รูปมาก่อน .txt เสมอ)

# ค่าที่ TM-X ใช้บอกว่า "ไม่มีค่า / วัดไม่ติด" (เจอจริงหน้างาน 31/07 — 7 ใน 8 ครั้ง)
NO_VALUE_ABS = 9999.0

MODE_NAME = {0: "โหมดตั้งค่า (Setting)", 1: "โหมดดำเนินการวัด (Run)"}
STATUS_NAME = {0: "ไม่ทำงาน", 1: "ค่าปกติ", 2: "แก้ตำแหน่งล้มเหลว",
               3: "ข้อมูลไม่ถูกต้อง", 4: "รอตัดสิน"}

# ชื่อคำสั่งล้างค่า — คู่มือพิมพ์ 2 แบบ ต้องลองเอง (ดู docstring)
CLEAR_CANDIDATES = ["MRS", "MSR"]
# None = ยังไม่ได้ลอง · "MRS"/"MSR" = ตัวที่ใช้ได้ · False = ลองแล้วไม่ผ่านทั้งคู่
# (แยก False ออกจาก None เพื่อไม่ให้ไปลองซ้ำทุกชิ้น — รกและเปลืองเวลาเปล่า)
_clear_cmd = None


# ══════════════════════════════════════════════════════════════════════
# ชั้นสื่อสาร — ไม่มี sleep(0.1) เพื่อให้วัดเวลาได้ละเอียดพอ
# ══════════════════════════════════════════════════════════════════════
def send_recv(sock, command, timeout=SOCKET_TIMEOUT):
    """ส่ง 1 คำสั่ง วน recv จนเจอ CR — คืน (response, status, วินาที)

    status: ok / error (ER,...) / timeout
    """
    sock.settimeout(timeout)
    deadline = time.time() + timeout
    t0 = time.time()
    sock.sendall((command + "\r").encode("ascii"))

    buf = b""
    while b"\r" not in buf:
        remain = deadline - time.time()
        if remain <= 0:
            return "<timeout>", "timeout", time.time() - t0
        sock.settimeout(remain)
        try:
            chunk = sock.recv(BUFFER_SIZE)
        except socket.timeout:
            return "<timeout>", "timeout", time.time() - t0
        if not chunk:                       # อีกฝั่งปิดสาย
            return "<closed>", "timeout", time.time() - t0
        buf += chunk

    dt = time.time() - t0
    resp = buf.split(b"\r", 1)[0].decode("ascii", "replace").strip()
    return resp, ("error" if resp.upper().startswith("ER") else "ok"), dt


def log_cmd(command, resp, status, dt, note=""):
    icon = {"ok": "✅", "error": "❌ ER", "timeout": "⏱ TO"}[status]
    print(f"  {icon}  {command:<10} → {resp!r}   ({dt*1000:.0f} ms) {note}")
    if status == "error" and ",03" in resp:
        print("        ↑ 03 = ไม่อยู่โหมดวัด / READY ไม่เปิด / ยังไม่ได้ทริกเกอร์")


# ══════════════════════════════════════════════════════════════════════
# โหมด (RM) — แทนการเดาด้วย sleep()
# ══════════════════════════════════════════════════════════════════════
def read_mode(sock):
    resp, status, _ = send_recv(sock, "RM")
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
    deadline, t0, last = time.time() + timeout, time.time(), None
    while time.time() < deadline:
        m = read_mode(sock)
        if m == want:
            print(f"     ✅ ยืนยันแล้ว: {MODE_NAME[want]}   ({time.time()-t0:.2f}s)")
            return True
        if m != last:
            print(f"     ... ตอนนี้ {MODE_NAME.get(m, f'อ่านไม่ได้ ({m})')} — รอต่อ")
            last = m
        time.sleep(MODE_POLL_INTERVAL)
    print(f"     ❌ รอ {timeout:.0f} วิแล้วยังไม่เป็น {MODE_NAME[want]}")
    return False


# ══════════════════════════════════════════════════════════════════════
# GM — ดึงค่าที่วัดได้
# ══════════════════════════════════════════════════════════════════════
def parse_gm(resp):
    """แยก 'GM,t,m,i,j,...' เป็น [(m, i, j), ...] — คืน None ถ้ารูปแบบไม่ตรง

    ไม่ยึดว่าต้องมีกี่เครื่องมือ เพราะยังไม่รู้ว่าโปรแกรมวัดตั้งไว้กี่ตัว
    (นี่คือสิ่งที่สคริปต์นี้จะบอก)
    """
    parts = [p.strip() for p in resp.split(",")]
    if len(parts) < 2 or parts[0].upper() != "GM":
        return None
    try:
        count = int(parts[1])
    except ValueError:
        return None
    body = parts[2:]
    if count == 0:
        count = len(body) // 3          # t=0 คือ "ทุกเครื่องมือ" TM-X บอกจำนวนจริงกลับมา
    if len(body) < count * 3:
        return None

    tools = []
    for k in range(count):
        m_s, i_s, j_s = body[k*3:k*3+3]
        try:
            m = float(m_s)
        except ValueError:
            m = None
        tools.append((m, _to_int(i_s), _to_int(j_s)))
    return tools


def _to_int(s):
    try:
        return int(s)
    except (ValueError, TypeError):
        return None


def has_real_value(tools):
    """ค่าที่ได้เป็นของจริงหรือยัง — ต้องมีอย่างน้อย 1 เครื่องมือที่ไม่ใช่ 9999.999"""
    if not tools:
        return False
    return any(m is not None and abs(m) < NO_VALUE_ABS for m, _, _ in tools)


def clear_measurement(sock, quiet=True):
    """ล้างค่าที่วัดได้ของโปรแกรมปัจจุบัน — คืน True ถ้าสั่งสำเร็จ

    ครั้งแรกจะไล่ลองทั้ง MRS และ MSR แล้วจำตัวที่ใช้ได้ไว้ (ดู docstring บนสุด)
    """
    global _clear_cmd
    if _clear_cmd is False:                 # ลองแล้วไม่ผ่าน ไม่ต้องลองซ้ำ
        return False
    if _clear_cmd is not None:
        resp, status, dt = send_recv(sock, _clear_cmd)
        if not quiet:
            log_cmd(_clear_cmd, resp, status, dt)
        return status == "ok"

    for cand in CLEAR_CANDIDATES:
        resp, status, dt = send_recv(sock, cand)
        log_cmd(cand, resp, status, dt, "(ลองหาตัวที่ TM-X รู้จัก)")
        if status == "ok":
            _clear_cmd = cand
            print(f"     ✅ ใช้ {cand} ล้างค่าเก่าได้ — จะใช้ตัวนี้ตลอดการทดสอบ")
            return True
    _clear_cmd = False
    print("     ⚠️ ทั้ง MRS และ MSR ใช้ไม่ได้")
    print("        → ตกไปใช้วิธีเทียบกับค่าตั้งต้นก่อนยิง T1 แทน")
    print("        → แม่นน้อยกว่า: ถ้า 2 ชิ้นติดกันวัดได้เท่ากันเป๊ะทุกค่า จะแยกไม่ออก")
    return False


# ══════════════════════════════════════════════════════════════════════
def measure_one(sock, piece, total):
    """วัด 1 ชิ้น — คืน dict ผลของชิ้นนี้"""
    r = {"piece": piece, "cleared": False, "wait_ms": None,
         "tools": None, "raw": None, "note": ""}

    print(f"\n── ชิ้นที่ {piece}/{total} ─────────────────────────────────────")

    # ── 1. ล้างค่าเก่า ────────────────────────────────────────────────
    r["cleared"] = clear_measurement(sock, quiet=(piece > 1))

    # ── 2. อ่านค่าตั้งต้น "ก่อน" ยิง T1 เสมอ ──────────────────────────
    # ทำ 2 หน้าที่ในตัวเดียว:
    #   ล้างสำเร็จ  → ยืนยันว่าล้างได้ผลจริง (ต้องไม่มีค่า)
    #   ล้างไม่ได้  → ได้ค่าเก่าไว้เป็นฐานเทียบ ("ค่าใหม่" = ค่าที่ต่างจากนี้)
    # ต้องอ่าน ณ จุดนี้ ไม่ใช่ใช้ค่าของชิ้นก่อนหน้า เพราะระหว่างที่รอวางชิ้นงาน
    # อาจมีค่าของชิ้นเก่าที่มาช้าหลุดเข้ามาได้ (TM-X วัดไม่ติดบ่อยตามข้อมูลหน้างาน)
    resp, status, _ = send_recv(sock, "GM,3,0")
    baseline = parse_gm(resp) if status == "ok" else None

    if r["cleared"]:
        if has_real_value(baseline):
            r["note"] = "⚠️ ล้างแล้วแต่ GM ยังคืนค่าอยู่ — คำสั่งล้างไม่ได้ผลจริง"
            print(f"     {r['note']}")
            print(f"        {resp!r}")
            r["cleared"] = False
        else:
            print(f"     ✅ ล้างแล้ว GM ไม่มีค่าจริง ({resp!r})")
    else:
        print(f"     ค่าตั้งต้นก่อนวัด (ไว้เทียบว่าค่าใหม่มาหรือยัง): {resp!r}")

    # ── 3. รอให้วางชิ้นงาน ────────────────────────────────────────────
    input(f"     วางชิ้นงานใต้กล้องแล้วกด Enter เพื่อยิง T1 (Ctrl+C ยกเลิก): ")

    # ── 4. T1 แล้วจับเวลาทันที ────────────────────────────────────────
    t0 = time.time()
    resp, status, dt = send_recv(sock, "T1")
    log_cmd("T1", resp, status, dt)
    if status != "ok":
        r["note"] = f"T1 ไม่ผ่าน ({resp})"
        return r

    # ── 5. วน GM จนได้ค่าใหม่ ─────────────────────────────────────────
    # เงื่อนไข "ค่าใหม่มาแล้ว" ต้องมี has_real_value เสมอ ไม่ใช่แค่ "ต่างจากฐาน"
    # — ระหว่างที่ TM-X ยังวัดไม่เสร็จ GM คืน 9999.999 ซึ่งก็ต่างจากฐานเหมือนกัน
    #   ถ้าเช็คแค่ "ต่าง" จะนับว่าได้ค่าแล้วตั้งแต่ยังไม่วัดเสร็จ (เวลาที่วัดได้จะเพี้ยน)
    deadline = t0 + GM_MAX_WAIT
    polls = 0
    while time.time() < deadline:
        polls += 1
        resp, status, _ = send_recv(sock, "GM,3,0", timeout=2.0)
        if status == "ok":
            tools = parse_gm(resp)
            fresh = has_real_value(tools) and (r["cleared"] or tools != baseline)
            if fresh:
                r["wait_ms"] = (time.time() - t0) * 1000
                r["tools"] = tools
                r["raw"] = resp
                print(f"     ✅ ได้ค่าหลัง {r['wait_ms']:.0f} ms (ถาม GM {polls} ครั้ง)")
                print(f"        {resp!r}")
                show_tools(tools)
                return r
        time.sleep(GM_POLL_INTERVAL)

    r["note"] = f"รอ {GM_MAX_WAIT:.0f} วิแล้วยังไม่ได้ค่า (ถาม GM {polls} ครั้ง)"
    print(f"     ⏱ {r['note']}")
    print("        อาจเป็นเพราะ TM-X วัดไม่ติดชิ้นนี้ — ลองใหม่ชิ้นถัดไป")
    return r


def show_tools(tools):
    """แสดงค่าที่ได้แยกทีละเครื่องมือ — ใช้ระบุว่าตัวไหนคือ x / y / offset"""
    print("        ┌──────┬────────────┬──────────────────┬──────────┐")
    print("        │ ตัวที่ │    ค่า (m)   │     สถานะ (i)     │ ตัดสิน (j) │")
    print("        ├──────┼────────────┼──────────────────┼──────────┤")
    for k, (m, i, j) in enumerate(tools):
        m_s = "ไม่มีค่า" if (m is None or abs(m) >= NO_VALUE_ABS) else f"{m:+.3f}"
        i_s = STATUS_NAME.get(i, f"? ({i})")
        j_s = {0: "OK", 1: "NG"}.get(j, f"? ({j})")
        print(f"        │  {k:<3} │ {m_s:>10} │ {i_s:<16} │ {j_s:<8} │")
    print("        └──────┴────────────┴──────────────────┴──────────┘")


# ══════════════════════════════════════════════════════════════════════
def summarize(results, template):
    print("\n" + "=" * 72)
    print("สรุปผล")
    print("=" * 72)

    got = [r for r in results if r["wait_ms"] is not None]
    print(f"  ได้ค่า {len(got)}/{len(results)} ชิ้น")

    failed = [r for r in results if r["wait_ms"] is None]
    if failed:
        print(f"  ไม่ได้ค่า {len(failed)} ชิ้น: "
              + " · ".join(f"ชิ้น {r['piece']} ({r['note']})" for r in failed))

    # ── คำถามที่ 2: ล้างค่าได้ไหม ────────────────────────────────────
    print()
    if _clear_cmd and all(r["cleared"] for r in results):
        print(f"✅ ใช้ `{_clear_cmd}` ล้างค่าเก่าก่อน T1 ได้ทุกชิ้น")
        print("   → Pi แยก 'ค่าชิ้นใหม่' ออกจาก 'ค่าชิ้นเก่าค้าง' ได้แน่นอน")
    elif _clear_cmd:
        print(f"⚠️ `{_clear_cmd}` สั่งผ่าน แต่บางชิ้น GM ยังคืนค่าเก่าอยู่")
        print("   → ล้างไม่ได้ผลจริง ต้องใช้วิธีอื่นแยกค่าใหม่/เก่า")
    else:
        print("❌ ล้างค่าเก่าไม่ได้ (ทั้ง MRS และ MSR)")
        print("   → เวลาที่วัดได้ด้านล่างเชื่อได้น้อยลง เพราะตัดสิน 'ค่าใหม่' จาก")
        print("     การเทียบกับชิ้นก่อน ซึ่งพลาดได้ถ้า 2 ชิ้นวัดได้เท่ากันเป๊ะ")

    if not got:
        print("=" * 72)
        return

    # ── คำถามที่ 1: ต้องรอกี่ ms ─────────────────────────────────────
    waits = [r["wait_ms"] for r in got]
    print("\n" + "-" * 72)
    print("⏱ เวลาตั้งแต่ยิง T1 จนดึงค่าได้")
    for r in got:
        print(f"     ชิ้น {r['piece']}  :  {r['wait_ms']:7.0f} ms")
    print(f"\n     เร็วสุด {min(waits):.0f} ms · กลาง {statistics.median(waits):.0f} ms "
          f"· ช้าสุด {max(waits):.0f} ms")

    slowest = max(waits)
    suggest = max(2.0, round(slowest * 3 / 1000 + 0.4, 1))
    print()
    print(f"👉 แนะนำตั้ง GM_MAX_WAIT ใน send_command(Pi).py = {suggest:.1f} วิ")
    print(f"   (ช้าสุดที่วัดได้ × 3 — เผื่อชิ้นที่ยากกว่านี้และโปรแกรมวัดตัวอื่น)")
    print("   ⚠ เป็นเพดาน ไม่ใช่การหน่วง — ตอบเร็วก็ไม่ได้รอนาน ตั้งเผื่อไว้ไม่มีข้อเสีย")
    if len(got) < 5:
        print(f"   ℹ️ วัดมาแค่ {len(got)} ชิ้น ควรรันซ้ำสัก 10 ชิ้นก่อนยึดเป็นค่าจริง")

    # ── คำถามที่ 3: ค่าเรียงยังไง ────────────────────────────────────
    counts = {len(r["tools"]) for r in got}
    print("\n" + "-" * 72)
    if len(counts) == 1:
        n = counts.pop()
        print(f"📋 GM,3,0 คืนมา {n} เครื่องมือทุกชิ้น (โปรแกรม {template})")
        print()
        print("   ค่าที่ได้ของแต่ละชิ้น เรียงตามลำดับที่ TM-X ส่งมา:")
        for r in got:
            vals = " · ".join(
                "ไม่มีค่า" if (m is None or abs(m) >= NO_VALUE_ABS) else f"{m:+.3f}"
                for m, _, _ in r["tools"])
            print(f"     ชิ้น {r['piece']}  :  {vals}")
        print()
        print("   👉 ดูตัวเลขข้างบนแล้วเทียบกับชิ้นงานจริง เพื่อระบุว่า")
        print("      ตัวไหนคือ value_x · value_y · offset")
        if n >= 3:
            print(f"      ({n} ค่า — ถ้าเรียงเป็น x, y, offset ก็ตรงกับที่ออกแบบไว้)")
        else:
            print(f"      ⚠️ ได้แค่ {n} ค่า — ถ้าไม่มี offset มาด้วย แผนให้ Pi ตัดสิน")
            print("         New/Rework จะใช้ไม่ได้ (ตัดสินได้ไม่ครบ 3 ข้อ)")
    else:
        print(f"⚠️ จำนวนเครื่องมือที่ได้ไม่คงที่: {sorted(counts)}")
        print("   ต้องดูว่าทำไมบางชิ้นได้ไม่ครบก่อนเอาไปใช้จริง")

    # ── ของแถม: ผลตัดสินของ TM-X เอง ────────────────────────────────
    print("\n" + "-" * 72)
    print("⭐ ผลตัดสิน (j) ที่ TM-X ให้มาเอง")
    for r in got:
        js = " · ".join({0: "OK", 1: "NG"}.get(j, f"?({j})") for _, _, j in r["tools"])
        print(f"     ชิ้น {r['piece']}  :  {js}")
    print()
    print("   เอาไปเทียบกับที่ backend คำนวณจาก nominal±tol ใน DB ได้")
    print("   ไม่ตรงกันเมื่อไหร่ = tolerance ในโปรแกรม TM-X กับใน DB เพี้ยนกันแล้ว")
    print("   → เป็นตัวจับ config drift ที่ตอนนี้ระบบยังไม่มีเลย")

    print("=" * 72)


def main():
    template = str(sys.argv[1] if len(sys.argv) > 1 else "021").zfill(3)
    pieces   = int(sys.argv[2]) if len(sys.argv) > 2 else 5

    print("=" * 72)
    print("ทดสอบ: หลังยิง T1 ต้องรอกี่ ms ถึงจะดึงค่าด้วย GM ได้")
    print(f"  TM-X    : {TMX_IP}:{TMX_PORT}")
    print(f"  โปรแกรม : {template}")
    print(f"  จำนวน   : {pieces} ชิ้น")
    print(f"  ต่อชิ้น  : MRS → T1 → วน GM,3,0 ทุก {GM_POLL_INTERVAL*1000:.0f} ms")
    print("=" * 72)
    print(f"⚠ จะสั่งวัดจริง {pieces} ครั้ง — เตรียมชิ้นงานให้พร้อม")
    input("  กด Enter เพื่อเริ่ม (Ctrl+C ยกเลิก): ")

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(SOCKET_TIMEOUT)
        sock.connect((TMX_IP, TMX_PORT))
    except Exception as exc:
        print(f"\n❌ ต่อ TM-X ไม่ได้ — {type(exc).__name__}: {exc}")
        print("   ตรวจ: สาย LAN · TM-X เปิดอยู่ไหม · send_command.py ปิดแล้วยัง")
        return

    results = []
    try:
        print("\n── 0. ถามโหมดปัจจุบัน ─────────────────────────────────────")
        m0 = read_mode(sock)
        print(f"     → {MODE_NAME.get(m0, f'อ่านไม่ได้ ({m0})')}")
        if m0 is None:
            print("\n⛔ RM ไม่ตอบ — หยุด")
            return

        print("\n── 1. R0 เข้าโหมดดำเนินการวัด ─────────────────────────────")
        resp, status, dt = send_recv(sock, "R0")
        log_cmd("R0", resp, status, dt)
        if status != "ok" or not wait_for_mode(sock, 1):
            print("\n⛔ เข้าโหมดดำเนินการวัดไม่สำเร็จ — หยุด")
            return

        print(f"\n── 2. โหลดโปรแกรม {template} ───────────────────────────────")
        resp, status, dt = send_recv(sock, f"PW,1,{template}", timeout=TIMEOUT_PW)
        log_cmd(f"PW,1,{template}", resp, status, dt)
        if status != "ok":
            print("\n⛔ โหลดโปรแกรมไม่สำเร็จ — หยุด")
            return

        for piece in range(1, pieces + 1):
            results.append(measure_one(sock, piece, pieces))

    except KeyboardInterrupt:
        print("\n\n⚠️ ยกเลิกกลางคัน — สรุปเท่าที่วัดได้")
    except Exception as exc:
        print(f"\n❌ พังกลางทาง — {type(exc).__name__}: {exc}")
    finally:
        # ปิดสะอาด ไม่งั้น TM-X ยังคิดว่ามีอุปกรณ์ควบคุมเชื่อมอยู่ จอหน้าเครื่องจะล็อกต่อ
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            sock.close()
        except Exception:
            pass

    if results:
        summarize(results, template)

    print()
    print("ℹ️  ไม่ได้ส่ง S0 — TM-X ยังอยู่ในโหมดดำเนินการวัด (Run)")
    print("   ปกติสำหรับการใช้งานจริง · ถ้าจะแก้โปรแกรมหน้าเครื่อง รัน send_s0.py")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nยกเลิก")
