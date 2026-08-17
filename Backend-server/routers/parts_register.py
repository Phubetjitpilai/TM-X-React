"""routers/parts_register.py — ทะเบียน ALPL (parts_specifications) — ไม่ใช่ 'ชิ้นงานที่กำลังวัด'

ย้ายมาจาก main.py แบบยกก้อน ไม่ได้แก้ตรรกะใดๆ
⚠ ห้ามประกาศ session_queues / measure_timeouts / subscribers ซ้ำในไฟล์นี้
  ต้องดึงจาก shared.py เท่านั้น ไม่งั้นจะกลายเป็นคนละ object โดยไม่มี error
"""
from fastapi import APIRouter

from shared import *  # noqa: F401,F403

router = APIRouter()


@router.post("/api/parts/check")
def check_parts(body: PartsCheckRequest):
    """ถามทีเดียวว่า ALPL ชุดนี้ตัวไหน "มีอยู่แล้ว" / "ยังไม่มี" ในตาราง Parts

    ใช้ตอนกด Save ในฟอร์ม Part Entry — ทั้ง 3 โหมดใช้ endpoint เดียวกัน ต่างกัน
    แค่ว่าสนใจฝั่งไหนของคำตอบ (ดู PLAN_criteria_and_multigroup.md ข้อ D5/D6)

        IPM     ดู missing → ถามยืนยันว่าจะลงทะเบียนให้แล้ววัดต่อไหม
        Rework  ดู missing → บล็อก (Rework ต้องเคยวัดมาก่อนเท่านั้น)
        New     ดู exists  → บล็อก (ปล่อยผ่านจะเขียนทับ config เดิมที่มีประวัติ)

    ทำไมต้องมี endpoint นี้: ของเดิมหน้าเว็บโหลด Part **ทั้งตาราง** มาไว้ใน
    หน่วยความจำแล้วเทียบเอง (วนดึงทีละ 1000 จนหมด) — ยิ่ง Part เยอะยิ่งช้า
    ทั้งที่จะเช็คแค่ไม่กี่ตัว

    `detail` มีไว้ให้ข้อความเตือนของโหมด New โชว์ได้ว่า ALPL ที่ชนอยู่นั้น
    ปัจจุบันเป็นของ Part Number/Vendor อะไร — ผู้ใช้จะได้แยกออกว่า "พิมพ์เลขผิด"
    หรือ "เลือกโหมดผิด" ซึ่งเป็น 2 สาเหตุที่พบบ่อยที่สุด

    ╔═══ `conflicts` — ALPL ในกลุ่มเดียวกันต้องเข้าชุดกัน ═════════════════════╗
    ถ้าส่ง `groups` + `mode` มาด้วย จะตรวจเพิ่มว่า ALPL ที่ผู้ใช้จับใส่กลุ่ม
    เดียวกัน มี Package Size (และ Part Number ถ้าเป็น Rework) ตรงกันจริงไหม

    ทำไมสำคัญ: 1 กลุ่ม = ชิ้นงานที่ใช้ **config ชุดเดียวกัน** ถ้าในกลุ่มเดียวกัน
    มี ALPL ที่ผูก Package Size คนละอัน แปลว่าเกณฑ์ตัดสิน OK/NG ของแต่ละชิ้น
    ไม่เหมือนกันตั้งแต่ต้น — Pi จะคัดของด้วยเกณฑ์ของกลุ่ม (ชุดเดียว) แต่ backend
    บันทึกด้วยเกณฑ์รายตัว กลายเป็นตัดสินคนละมาตรฐานโดยไม่มีใครรู้จนกว่าจะไปนับ
    ของจริง (เป็นอาการเดียวกับที่ `_build_groups` กันไว้ตอนกด Start — ที่นี่แค่
    ดักให้เร็วขึ้นตั้งแต่ตอนกด Save จะได้แก้ก่อนที่จะเดินไปไกลกว่านั้น)

    ตรวจเฉพาะ ALPL ที่ **มีอยู่จริงใน DB** — ตัวที่ยังไม่ลงทะเบียนไม่มีอะไรให้
    เทียบ และจะถูกสร้างด้วย config ของกลุ่มอยู่แล้วตอนวัดจริง
    ╚═══════════════════════════════════════════════════════════════════════╝

    ⚠ **ห้ามใส่ `_block_if_session_running()`** — เป็นการอ่านอย่างเดียว และต้อง
      ใช้ได้ตอนที่ยังไม่ได้เริ่มวัด (ซึ่งคือตอนเดียวที่มีคนเรียกจริงๆ)
    """
    # รับได้ทั้ง 2 หน้าตา — ถ้ามี groups ให้คลี่เอา alpl ทั้งหมดออกมาเช็ค
    # มี/ไม่มี เหมือนเดิม แล้วเก็บโครงกลุ่มไว้ตรวจ conflicts ต่อ
    groups_in = body.groups or []
    flat: List[int] = list(body.alpl or [])
    for g in groups_in:
        flat.extend(int(a) for a in (g.get("alpl") or g.get("number_alpl") or []))

    # ตัดตัวซ้ำออกก่อน (ผู้ใช้พิมพ์ ALPL ซ้ำข้ามกลุ่มได้) แต่ยังคงลำดับเดิมไว้
    # เพื่อให้ข้อความเตือนบนหน้าเว็บเรียงตามที่ผู้ใช้กรอกมา ไม่ใช่เรียงเลข
    seen: set = set()
    wanted: List[int] = []
    for a in flat:
        if a not in seen:
            seen.add(a)
            wanted.append(a)

    if not wanted:
        return {"exists": [], "missing": [], "detail": {}, "conflicts": []}
    if len(wanted) > 500:
        raise HTTPException(400, "เช็คได้สูงสุด 500 ALPL ต่อครั้ง")

    db = get_db()
    try:
        with db.cursor() as cur:
            placeholders = ", ".join(["%s"] * len(wanted))
            # ดึง config ให้ครบทุก field ที่ฟอร์ม Part Entry มี — หน้าเว็บเอาไป
            # ทั้งเตือน (ข้อความ New/conflicts) และ **เติมช่องให้อัตโนมัติ**
            # ตอนผู้ใช้กรอก ALPL ที่เคยลงทะเบียนแล้ว (ดู prefillGroupFromAlpl)
            # ยิงทีเดียวได้ทั้งกลุ่ม แทนที่จะไล่ถาม /api/parts/{alpl} ทีละตัว
            cur.execute(
                "SELECT p.number_alpl, pn.part_number_name, ps.package_size, "
                "       v.vendor_name, o.owner_name, p.po_number, p.description "
                "FROM parts_specifications p "
                "LEFT JOIN part_number pn ON p.part_number_id = pn.part_number_id "
                "LEFT JOIN package_size ps "
                "       ON ps.package_size_id = COALESCE(p.package_size_id, pn.package_size_id) "
                "LEFT JOIN vendor v ON p.vendor_id = v.vendor_id "
                "LEFT JOIN owner o  ON p.owner_id  = o.owner_id "
                f"WHERE p.number_alpl IN ({placeholders})",
                wanted,
            )
            rows = cur.fetchall()
    finally:
        db.close()

    detail = {
        str(r["number_alpl"]): {
            "part_number":  r["part_number_name"],
            "package_size": r["package_size"],
            "vendor":       r["vendor_name"],
            "owner":        r["owner_name"],
            "po_number":    r["po_number"],
            "description":  r["description"],
        }
        for r in rows
    }
    found = {r["number_alpl"] for r in rows}

    # ── conflicts: ALPL ในกลุ่มเดียวกันต้องมีค่าตรงกันตามโหมด ────────────────
    conflicts: List[Dict[str, Any]] = []
    for field, label in _GROUP_MATCH_FIELDS.get((body.mode or "").strip(), []):
        for gi, g in enumerate(groups_in):
            alpls = [int(a) for a in (g.get("alpl") or g.get("number_alpl") or [])]
            # จับกลุ่มตามค่าที่ได้ — ใช้ dict เพื่อให้รู้ด้วยว่า "ค่าไหนมาจาก ALPL ตัวไหน"
            # (ข้อความเตือนต้องบอกเลขให้ครบ ไม่งั้นผู้ใช้ไม่รู้ว่าต้องไปแก้ตัวไหน)
            by_value: Dict[str, List[int]] = {}
            for a in alpls:
                if a not in found:
                    continue                      # ยังไม่ลงทะเบียน — ไม่มีอะไรให้เทียบ
                v = detail[str(a)].get(field)
                by_value.setdefault("—" if v is None else str(v), []).append(a)

            if len(by_value) > 1:
                parts = " · ".join(
                    f"{', '.join(map(str, ids))} = \"{v}\"" for v, ids in by_value.items()
                )
                conflicts.append({
                    "group":  gi,
                    "field":  field,
                    "label":  label,
                    "alpl":   alpls,
                    "values": by_value,
                    "message": (
                        f"กลุ่มที่ {gi + 1}: ALPL ในกลุ่มเดียวกันมี {label} ไม่ตรงกัน — "
                        f"{parts} · ชิ้นงานในกลุ่มเดียวกันต้องใช้ค่าเดียวกัน "
                        f"ให้แยกไปคนละกลุ่ม หรือแก้ให้ตรงกันที่หน้า Edit › Parts"
                    ),
                })

    return {
        "exists":    [a for a in wanted if a in found],
        "missing":   [a for a in wanted if a not in found],
        "detail":    detail,
        "conflicts": conflicts,
    }

@router.get("/api/parts")
def list_parts(
    limit:  int = Query(10, ge=1, le=1000),   # มีเพดาน กันยิง limit=999999 ดึงทั้งตาราง
    offset: int = Query(0, ge=0),
    search: Optional[str] = None,
):
    """คืน config ของ parts แบบ "แบ่งหน้า" (server-side pagination)

    ทำไมเปลี่ยนจากเดิมที่คืน array ของ parts ทั้งหมดทีเดียว มาเป็น object
    {items, total}: ตาราง parts มีแนวโน้มโตขึ้นเรื่อยๆ ตามการใช้งานจริง การ
    ดึงมาทั้งหมดทุกครั้งจะกินแบนด์วิดท์และหน่วยความจำ frontend โดยเปล่าประโยชน์
    จึงให้ดึงมาทีละหน้า (limit/offset) แทน — frontend ของ edit.html แสดงทีละ 10 แถว

    `total` มาจาก COUNT(*) ที่ใช้ WHERE ชุดเดียวกับ query หลัก (ไม่ใช่นับจาก
    items ของหน้าปัจจุบัน) เพื่อให้ frontend คำนวณจำนวนหน้า/ปิดปุ่ม Next ได้ถูก

    `search` (optional) — กรองด้วย number_alpl หรือ part_number แบบ LIKE
    เหตุผลที่ทำ search ฝั่ง server ไม่ใช่ฝั่ง client: เพื่อให้ค้นหาเจอ "ข้ามทุก
    หน้า" ไม่ใช่แค่ 10 แถวของหน้าที่โหลดมาแสดงอยู่ number_alpl เป็น INT จึงต้อง
    CAST เป็น CHAR ก่อนเทียบ LIKE เพื่อให้ค้นหาบางส่วนของตัวเลขได้ (เช่นพิมพ์
    "10" แล้วเจอทั้ง 1011, 1002 ที่ขึ้นต้นด้วย 10)

    หมายเหตุ: เพิ่ม ORDER BY number_alpl เพื่อให้ลำดับของหน้าคงที่ (stable) —
    ถ้าไม่กำหนด ORDER BY การไล่ LIMIT/OFFSET อาจได้ลำดับไม่แน่นอนข้ามหน้า
    """
    conditions, params = [], []
    if search:
        conditions.append("(CAST(p.number_alpl AS CHAR) LIKE %s OR pn.part_number_name LIKE %s)")
        like = f"%{search}%"
        params.extend([like, like])
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute(
                f"SELECT COUNT(*) AS total FROM parts_specifications p "
                f"LEFT JOIN part_number pn ON p.part_number_id = pn.part_number_id {where}",
                params,
            )
            total = cur.fetchone()["total"]
            cur.execute(
                f"{PARTS_SELECT} {where} ORDER BY p.number_alpl LIMIT %s OFFSET %s",
                (*params, limit, offset),
            )
            items = cur.fetchall()
        return {"items": items, "total": total}
    finally:
        db.close()

@router.get("/api/parts/{part_id}")
def get_part(part_id: int):
    """คืน config ของ part 1 ตัวตาม ALPL number (รวมชื่อ handler/vendor/
    owner/package_size ที่ join มาจาก lookup table แล้ว ไม่ใช่แค่ id)"""
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute(f"{PARTS_SELECT} WHERE p.number_alpl = %s", (part_id,))
            row = cur.fetchone()
        if not row:
            raise HTTPException(404, "Part not found")
        return row
    finally:
        db.close()

@router.post("/api/parts", status_code=201)
def create_part(part: PartCreate):
    """ลงทะเบียน ALPL part ใหม่: nominal X/Y, tolerance แยกแกน, และ template ของ TM-X ที่ใช้

    ทำไมต้องแยก endpoint นี้ออกจาก start_session: parts/templates ถูก config
    ไว้ล่วงหน้า (เป็นขั้นตอน setup) เพื่อให้ start_session แค่ lookup template
    จาก number_alpl ได้เลย ไม่ต้องให้ผู้ปฏิบัติงานพิมพ์เองทุกครั้งที่รัน
    """
    db = get_db()
    try:
        with db.cursor() as cur:
            _insert_part_row(cur, part.number_alpl, part.dict())
        return {"number_alpl": part.number_alpl}
    finally:
        db.close()

@router.patch("/api/parts/{part_id}")
def update_part(part_id: int, data: Dict[str, Any] = Body(...)):
    """อัปเดต config ของ part แบบ partial (เฉพาะ field ที่ส่งมาใน body)

    ทำไมต้องมี whitelist (`allowed`): เพื่อไม่ให้ request body ไปเขียนทับ column
    ที่ไม่ควรแก้ผ่าน endpoint นี้ได้โดยไม่ตั้งใจ (หรือถูกใช้ในทางที่ไม่ดี)

    `number_alpl` แก้ไขได้ (จาก edit.html — Edit Part) แม้จะเป็น "business key"
    หลักที่ sessions/measurements อ้างอิงถึงก็ตาม — ถ้า ALPL ตัวนี้มีประวัติ
    session/measurement ผูกอยู่แล้ว MySQL จะปฏิเสธด้วย FK constraint error
    (เพราะ FOREIGN KEY ไม่มี ON UPDATE CASCADE) เราจับ error นั้นแล้วแปลงเป็น
    409 ที่อ่านง่ายแทนที่จะปล่อยให้เป็น 500 ดิบๆ
    """
    # field ที่แก้ตรงๆ ได้เลย ไม่ต้อง resolve ผ่าน lookup table
    direct_fields = {"number_alpl", "description", "po_number", "recieve_date"}
    # field ที่เป็น "ชื่อ" จาก dropdown — ต้อง resolve เป็น id ก่อน (key ที่รับจาก
    # request → (คอลัมน์จริงใน parts_specifications, ตาราง lookup, id column,
    # name column)) — part_number ย้ายมาอยู่ตรงนี้แล้ว (ไม่ใช่ direct_fields
    # อีกต่อไป) เพราะตอนนี้ต้อง resolve เป็น part_number_id ก่อน ไม่ใช่คอลัมน์
    # VARCHAR ตรงๆ — handler/package_size ไม่มีในนี้แล้ว เพราะ derive มาจาก
    # part_number_id ทั้งคู่ ไม่ได้เก็บที่ parts_specifications โดยตรง
    lookup_fields = {
        "part_number": ("part_number_id", "part_number", "part_number_id", "part_number_name"),
        "vendor":      ("vendor_id",      "vendor",      "vendor_id",      "vendor_name"),
        "owner":       ("owner_id",       "owner",       "owner_id",       "owner_name"),
    }
    db = get_db()
    try:
        with db.cursor() as cur:
            _block_if_session_running(cur, "แก้ไข")
            set_parts, values = [], []
            for k, v in data.items():
                if k in direct_fields:
                    set_parts.append(f"{k} = %s")
                    values.append(v)
                elif k in lookup_fields:
                    col, table, id_col, name_col = lookup_fields[k]
                    set_parts.append(f"{col} = %s")
                    values.append(_lookup_id(cur, table, id_col, name_col, v))
            if not set_parts:
                raise HTTPException(400, "No valid fields provided")
            set_clause = ", ".join(set_parts)
            try:
                cur.execute(
                    f"UPDATE parts_specifications SET {set_clause} WHERE number_alpl = %s",
                    (*values, part_id),
                )
            except pymysql.MySQLError as exc:
                raise HTTPException(
                    409,
                    f"บันทึกไม่สำเร็จ — ALPL ใหม่อาจซ้ำกับ part อื่น หรือ ALPL เดิมมี "
                    f"session/measurement ผูกอยู่แล้ว (เปลี่ยน ALPL ที่มีประวัติไม่ได้): {exc}",
                )
            if cur.rowcount == 0:
                raise HTTPException(404, "Part not found")
        return {"ok": True}
    finally:
        db.close()

@router.delete("/api/parts/{part_id}")
def delete_part(part_id: int):
    """ลบ Part 1 row ออกจากตาราง `parts_specifications`

    **กฎการลบ (ตามที่ตกลงกันไว้)**: ลบได้ต่อเมื่อ ALPL นี้ "ไม่มีข้อมูลการวัด
    (Measurement) เหลืออยู่เลย" เท่านั้น — ถ้ายังมี Measurement อยู่จะปฏิเสธ
    ทันทีด้วย 409 พร้อมข้อความบอกจำนวนรายการที่ติดอยู่ (frontend เอาไปโชว์เป็น
    popup เตือน) ไม่มีโหมด cascade ที่ลบ Measurement ตามไปด้วยอีกต่อไป —
    ประวัติการวัดถือเป็นข้อมูลจริงที่ห้ามหายไปโดยไม่ตั้งใจ ถ้าผู้ใช้ต้องการลบ
    จริงๆ ต้องไปลบ Measurement ทีละรายการเองที่ตาราง Measurements ก่อน

    ทำทั้งหมดเป็น transaction เดียว (ปิด autocommit ชั่วคราว) กัน DB ค้างครึ่งๆ
    กลางๆ ถ้ามีขั้นไหนพังกลางทาง

    ╔═══ บั๊ก HTTP 500 ที่เพิ่งแก้ (13 ส.ค. 2569) ══════════════════════════╗
    ที่นี่เคยมีอีก 2 คำสั่งที่ยุ่งกับ `sessions`:
        SELECT * FROM sessions WHERE number_alpl = %s     ← สำรองก่อนลบ
        DELETE   FROM sessions WHERE number_alpl = %s     ← เคลียร์ให้ FK ไม่ block
    ทั้งคู่ตกค้างมาจากสมัยที่ `sessions` ยังมีคอลัมน์ `number_alpl` + FK ไป
    `parts_specifications` — คอลัมน์นั้นถูกถอดออกไปแล้ว (ดู init.sql) MySQL จึง
    ตอบ `1054 Unknown column 'number_alpl' in 'where clause'` ซึ่งเป็น
    pymysql.MySQLError ที่ไม่มีใคร catch → หลุดออกไปเป็น **HTTP 500** ทุกครั้ง
    ที่กดลบ Part จากหน้า Edit

    ตอนนี้ `sessions` ไม่ได้อ้างถึง Part ตัวไหนแล้ว (คิว ALPL อยู่ใน
    `queue_state` ซึ่งเป็น JSON ไม่ใช่ FK) จึงไม่มีอะไรต้องเคลียร์ก่อนลบ
    และไม่มี FK ตัวไหนมา block ด้วย — ลบ 2 บรรทัดนั้นทิ้งได้เลย
    ╚═══════════════════════════════════════════════════════════════════════╝
    """
    db = get_db()
    try:
        db.autocommit(False)
        with db.cursor() as cur:
            _block_if_session_running(cur, "ลบ")

            # เช็คก่อนเลยว่ามี Measurement ของ ALPL นี้เหลืออยู่ไหม — ถ้ามี ปฏิเสธ
            # ทันที ไม่แตะอะไรใน DB เลย (ตรวจเองแทนที่จะรอ FK error เพื่อให้ได้
            # ข้อความบอกจำนวนที่ติดอยู่ชัดเจน ผู้ใช้จะได้รู้ว่าต้องไปจัดการอะไรต่อ)
            cur.execute("SELECT COUNT(*) AS n FROM measurements WHERE number_alpl = %s", (part_id,))
            measurement_count = cur.fetchone()["n"]
            if measurement_count:
                db.rollback()
                raise HTTPException(
                    409,
                    f"ลบไม่ได้ — ALPL {part_id} ยังมีข้อมูลการวัด (Measurement) อยู่ "
                    f"{measurement_count} รายการ กรุณาลบ Measurement ของ ALPL นี้ให้หมดก่อน "
                    f"แล้วค่อยลบ Part",
                )

            # ── สำรองก่อนลบ ── เก็บ Part row ไว้ในถังขยะเผื่อกดผิด
            part_row = _fetch_one(
                cur, "SELECT * FROM parts_specifications WHERE number_alpl = %s", (part_id,)
            )
            if part_row is None:
                db.rollback()
                raise HTTPException(404, "Part not found")
            _archive_before_delete(
                kind="part", table="parts_specifications",
                pk={"number_alpl": part_id}, row=part_row,
            )

            try:
                cur.execute("DELETE FROM parts_specifications WHERE number_alpl = %s", (part_id,))
            except pymysql.MySQLError as exc:
                db.rollback()
                raise HTTPException(409, f"ลบ ALPL {part_id} ไม่สำเร็จ: {exc}")
            if cur.rowcount == 0:
                db.rollback()
                raise HTTPException(404, "Part not found")
        db.commit()
        return {"ok": True}
    finally:
        db.autocommit(True)
        db.close()
