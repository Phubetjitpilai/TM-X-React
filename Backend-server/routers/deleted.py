"""routers/deleted.py — ถังขยะ — กู้คืน/ลบถาวร

ย้ายมาจาก main.py แบบยกก้อน ไม่ได้แก้ตรรกะใดๆ
⚠ ห้ามประกาศ session_queues / measure_timeouts / subscribers ซ้ำในไฟล์นี้
  ต้องดึงจาก shared.py เท่านั้น ไม่งั้นจะกลายเป็นคนละ object โดยไม่มี error
"""
from fastapi import APIRouter

from shared import *  # noqa: F401,F403

router = APIRouter()


def _deleted_files():
    """ไล่หาไฟล์ .json ทุกอันในถังขยะ — คืน (โฟลเดอร์วัน, ชื่อไฟล์, path เต็ม)"""
    if not os.path.isdir(DELETED_DIR):
        return []
    out = []
    for day in sorted(os.listdir(DELETED_DIR), reverse=True):
        day_dir = os.path.join(DELETED_DIR, day)
        if not os.path.isdir(day_dir):
            continue
        for name in sorted(os.listdir(day_dir), reverse=True):
            if name.endswith(".json"):
                out.append((day, name, os.path.join(day_dir, name)))
    return out

def _deleted_summary(payload: Dict[str, Any]) -> str:
    """ข้อความสรุปสั้นๆ ให้คนอ่านออกว่าแถวที่ลบไปคืออะไร โดยไม่ต้องเปิดไฟล์ดู"""
    kind, row = payload.get("kind"), payload.get("row", {})
    if kind == "measurement":
        vx, vy = row.get("value_x"), row.get("value_y")
        return (f"ALPL {row.get('number_alpl')} · {vx} / {vy} · {row.get('result')}"
                f" · {str(row.get('timestamp') or '')[:19]}")
    if kind == "part":
        n = len(payload.get("related", {}).get("sessions", []))
        return f"ALPL {row.get('number_alpl')}" + (f" (+ {n} sessions)" if n else "")
    # lookup ทั้งหมดมีคอลัมน์ชื่อลงท้ายด้วย _name
    for k, v in row.items():
        if k.endswith("_name") or k == "package_size":
            return str(v)
    return ", ".join(f"{k}={v}" for k, v in list(row.items())[:3])

@router.get("/api/deleted")
def list_deleted():
    """รายการทุกอย่างที่อยู่ในถังขยะ เรียงจากลบล่าสุดก่อน"""
    items = []
    for day, name, path in _deleted_files():
        try:
            with open(path, encoding="utf-8") as f:
                payload = json.load(f)
        except Exception as exc:
            log.warning("อ่านไฟล์ถังขยะ %s ไม่สำเร็จ: %s", name, exc)
            continue
        kind = payload.get("kind", "?")
        items.append({
            "id":         f"{day}/{name}",          # ใช้เป็นตัวอ้างตอนกู้คืน
            "deleted_at": payload.get("deleted_at"),
            "kind":       kind,
            "kind_label": _DELETED_KIND_LABEL.get(kind, kind),
            "summary":    _deleted_summary(payload),
            "has_image":  bool(payload.get("image_file")),
            # เหลืออีกกี่วันก่อนโดนลบถาวรอัตโนมัติ (None = คำนวณไม่ได้)
            #
            # คำนวณที่ backend ไม่ใช่ฝั่ง JS โดยตั้งใจ — ต้องใช้ตรรกะเดียวกับ
            # _purge_old_deleted() เป๊ะ (อ่านวันจาก "ชื่อโฟลเดอร์" ไม่ใช่ mtime
            # และแปลง พ.ศ. → ค.ศ.) ถ้าให้ JS คำนวณเองจะเพี้ยนจากตัวลบจริงได้
            # โดยไม่มีใครรู้ แล้วผู้ใช้จะเห็นว่า "เหลือ 3 วัน" ทั้งที่ของหายไปแล้ว
            "days_left":  _days_left(day),
        })
    return {"items": items, "total": len(items), "retention_days": DELETED_RETENTION_DAYS}


def _days_left(day: str):
    """เหลืออีกกี่วันก่อนโฟลเดอร์วันนี้จะถูกลบถาวร — คืน None ถ้าชื่อไม่ใช่รูปแบบวันที่

    ต้องใช้ตรรกะเดียวกับ _purge_old_deleted() ใน shared.py เป๊ะ:
      - อ่านวันจาก "ชื่อโฟลเดอร์" (DD-MM-YYYY พ.ศ.) ไม่ใช่ mtime ของไฟล์
        เพราะ mtime เปลี่ยนได้ง่ายเวลาก๊อป/ย้ายไฟล์ ส่วนชื่อโฟลเดอร์คือวันที่ลบจริงเสมอ
      - แปลง พ.ศ. → ค.ศ. ด้วย -543
      - ตัวลบใช้เงื่อนไข `day_date < cutoff` โดย cutoff = วันนี้ - RETENTION

    ⚠ ถ้าวันหนึ่งแก้ตรรกะฝั่ง _purge_old_deleted ต้องมาแก้ตรงนี้คู่กันเสมอ
      ไม่งั้นตัวเลขบนหน้าเว็บจะโกหก (บอกว่าเหลือ 3 วันทั้งที่ของหายไปแล้ว)

    คืน 0 = จะโดนลบในรอบตรวจถัดไป (loop ทำงานวันละครั้ง + ตอนบูต)
    """
    try:
        d, m, y = day.split("-")
        day_date = date(int(y) - 543, int(m), int(d))
    except (ValueError, TypeError):
        return None
    left = DELETED_RETENTION_DAYS - (date.today() - day_date).days
    return max(left, 0)

def _deleted_path(item_id: str) -> str:
    """แปลง id ("<วัน>/<ไฟล์>.json") เป็น path จริง พร้อมกันหลุดออกนอกถังขยะ"""
    base = os.path.realpath(DELETED_DIR)
    target = os.path.realpath(os.path.join(base, item_id))
    if not target.startswith(base + os.sep) or not target.endswith(".json"):
        raise HTTPException(404, "ไม่พบรายการนี้ในถังขยะ")
    if not os.path.isfile(target):
        raise HTTPException(404, "ไม่พบรายการนี้ในถังขยะ")
    return target

@router.post("/api/deleted/restore")
def restore_deleted(body: Dict[str, str] = Body(...)):
    """กู้คืน 1 รายการจากถังขยะ — insert แถวกลับ + ย้ายไฟล์รูปกลับที่เดิม

    ทำเป็น transaction เดียว ถ้าขั้นไหนพังจะ rollback ทั้งหมด แล้วไฟล์ JSON
    ยังอยู่ในถังขยะเหมือนเดิม (ลองใหม่ได้)

    ⚠ ลำดับการกู้สำคัญ: ถ้าแถวนี้อ้าง FK ไปหาของที่ถูกลบไปแล้วเหมือนกัน
      (เช่นกู้ measurement ที่อ้าง operator ที่โดนลบไป) MySQL จะปฏิเสธ
      ต้องกู้ตัวที่ถูกอ้างก่อน — ข้อความ error จะบอกให้ผู้ใช้รู้
    """
    item_id = (body or {}).get("id", "")
    path = _deleted_path(item_id)
    with open(path, encoding="utf-8") as f:
        payload = json.load(f)

    table   = payload["table"]
    row     = payload["row"]
    related = payload.get("related") or {}

    db = get_db()
    try:
        db.autocommit(False)
        with db.cursor() as cur:
            _block_if_session_running(cur, "กู้คืน")

            def insert(tbl: str, data: Dict[str, Any]):
                cols = ", ".join(f"`{c}`" for c in data)
                marks = ", ".join(["%s"] * len(data))
                cur.execute(f"INSERT INTO `{tbl}` ({cols}) VALUES ({marks})", list(data.values()))

            try:
                insert(table, row)
                # sessions ต้องเข้าหลัง parts_specifications เสมอ (FK ชี้ไปหา)
                for tbl, rows in related.items():
                    for r in rows:
                        insert(tbl, r)
            except pymysql.err.IntegrityError as exc:
                db.rollback()
                code = exc.args[0] if exc.args else 0
                if code == 1062:
                    raise HTTPException(409, "กู้คืนไม่ได้ — มีข้อมูล id นี้อยู่ในระบบแล้ว")
                if code == 1452:
                    raise HTTPException(
                        409,
                        "กู้คืนไม่ได้ — ข้อมูลนี้อ้างอิงถึงรายการอื่นที่ถูกลบไปแล้ว "
                        "กรุณากู้คืนรายการที่ถูกอ้างถึงก่อน (เช่น Operator / Part Number)",
                    )
                raise HTTPException(409, f"กู้คืนไม่สำเร็จ: {exc}")

        # ── ย้ายไฟล์รูปกลับที่เดิม (หลัง DB สำเร็จแล้วเท่านั้น) ──────────────
        image_file  = payload.get("image_file")
        image_path  = row.get("image_path")
        if image_file and image_path:
            src = os.path.join(os.path.dirname(path), image_file)
            dst = os.path.join(ALPL_IMAGE_DIR, image_path)
            try:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.move(src, dst)
            except OSError as exc:
                # DB กู้แล้วแต่รูปย้ายไม่สำเร็จ — ไม่ rollback เพราะข้อมูลสำคัญกว่ารูป
                log.warning("กู้ข้อมูลสำเร็จแต่ย้ายรูปกลับไม่ได้ (%s): %s", image_file, exc)

        db.commit()
        os.remove(path)   # ออกจากถังขยะแล้ว
        log.info("กู้คืนจากถังขยะ: %s", item_id)
        return {"ok": True, "kind": payload.get("kind"), "table": table}
    finally:
        db.autocommit(True)
        db.close()

@router.post("/api/deleted/remove")
def remove_deleted(body: Dict[str, str] = Body(...)):
    """ลบ 1 รายการออกจากถังขยะ **ถาวร** — กู้คืนไม่ได้อีก

    ลบทั้งไฟล์ .json และไฟล์รูปที่เก็บคู่กัน ไม่แตะฐานข้อมูลเลย (แถวนั้นถูกลบ
    ไปตั้งแต่ตอนกดลบครั้งแรกแล้ว ตรงนี้แค่ทิ้งตัวสำรอง)
    """
    path = _deleted_path((body or {}).get("id", ""))
    try:
        with open(path, encoding="utf-8") as f:
            image_file = json.load(f).get("image_file")
    except Exception:
        image_file = None

    if image_file:
        # ยึด "โฟลเดอร์ของไฟล์ json" เป็นฐานเสมอ + เอาเฉพาะชื่อไฟล์ กัน image_file
        # ที่มี path ปนมาพาไปลบไฟล์นอกถังขยะ
        img = os.path.join(os.path.dirname(path), os.path.basename(image_file))
        try:
            os.remove(img)
        except OSError:
            pass

    os.remove(path)
    log.info("ลบถาวรจากถังขยะ: %s", (body or {}).get("id"))
    return {"ok": True}

@router.delete("/api/deleted")
def purge_deleted_now():
    """สั่งลบของในถังขยะที่เกินอายุทันที (ปกติทำอัตโนมัติตอน backend เริ่ม)"""
    return {"ok": True, "removed_days": _purge_old_deleted()}
