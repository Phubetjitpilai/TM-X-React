"""routers/measurements.py — ผลการวัดรายชิ้น + รูปภาพ

ย้ายมาจาก main.py แบบยกก้อน ไม่ได้แก้ตรรกะใดๆ
⚠ ห้ามประกาศ session_queues / measure_timeouts / subscribers ซ้ำในไฟล์นี้
  ต้องดึงจาก shared.py เท่านั้น ไม่งั้นจะกลายเป็นคนละ object โดยไม่มี error
"""
from fastapi import APIRouter

from shared import *  # noqa: F401,F403

router = APIRouter()


def _offset_ok(offset: Optional[float], offset_tol: Optional[float]) -> bool:
    """offset ผ่านเกณฑ์ไหม — เทียบกับ offset_tol ของ part_number

    ต่างจาก value_x/value_y ที่เทียบกับช่วง nominal ± tolerance — offset เป็น
    "ค่าความเยื้อง" ที่ยิ่งน้อยยิ่งดี จึงเทียบแค่ว่าไม่เกินเพดานที่ตั้งไว้
    ใช้ abs() เผื่อ TM-X ส่งค่าติดลบมา (เยื้องคนละทิศก็ถือว่าเยื้องเท่ากัน)

    ถ้ายังไม่ได้ตั้ง offset_tol (NULL) ถือว่า "ไม่ตรวจข้อนี้" → ผ่านเสมอ
    ไม่งั้น Part เก่าที่ยังไม่ได้กรอกค่านี้จะกลายเป็น NG ทั้งหมดทันทีที่ deploy
    """
    if offset is None or offset_tol is None:
        return True
    return abs(offset) <= offset_tol + _TOL_EPS

def _judge(value_x: float, value_y: float, offset: Optional[float],
           crit, measure_type: str) -> dict:
    """ตัดสิน OK/NG ครั้งเดียวจบ — ใช้ร่วมกันทั้งตอนวัดจริงและตอนคำนวณใหม่หลังแก้ไข

    คืน dict ที่เอาไปแนบ SSE ได้เลย เพื่อให้ "สิ่งที่บันทึก" กับ "สิ่งที่หน้าเว็บ
    เห็น" มาจากการคำนวณชุดเดียวกันเสมอ (เคยแยกกันแล้วเพี้ยนกันเงียบๆ)
    """
    ok_x = _within_tolerance(value_x, crit["nominal_x"], crit["upper_tol"], crit["lower_tol"])
    ok_y = _within_tolerance(value_y, crit["nominal_y"], crit["upper_tol"], crit["lower_tol"])

    limit = _offset_limit(measure_type, crit)
    offset_counts = limit is not None
    # ok_offset = None (ไม่ใช่ True) เมื่อไม่นับเป็นเกณฑ์ — หน้าเว็บจะได้แยกออก
    # ระหว่าง "ผ่าน" กับ "ไม่ได้ตรวจ" แล้วไม่ติดป้ายเขียวให้ค่าที่ไม่เคยถูกตรวจ
    ok_offset = _offset_ok(offset, limit) if offset_counts else None

    passed = ok_x and ok_y and (ok_offset is not False)
    return {
        "result":        "OK" if passed else "NG",
        "ok_x":          ok_x,
        "ok_y":          ok_y,
        "ok_offset":     ok_offset,
        "offset_counts": offset_counts,
        "offset_tol":    limit,
    }

def _delete_image_file(image_path: Optional[str]) -> bool:
    """ลบไฟล์รูปที่ image_path (path สัมพัทธ์ต่อ ALPL_IMAGE_DIR) ชี้อยู่

    คืน True เฉพาะตอนลบได้จริง และ **ไม่ throw ไม่ว่ากรณีไหน** เพราะทุกจุดที่
    เรียกใช้ถือว่า "ลบไฟล์ไม่ได้" ไม่ใช่เหตุให้ request ทั้งก้อนพัง (แถวใน DB
    ถูกลบ/อัปเดตไปแล้ว จะ rollback เพราะไฟล์ค้างไม่คุ้ม)

    กันไว้ 2 กรณีที่ห้ามแตะไฟล์เด็ดขาด:
      1. **ค่าที่เป็น URL เต็ม** — ข้อมูลตกค้างจากยุค MinIO ที่เก็บทั้ง URL ลง
         คอลัมน์นี้ (เจอจริงในแถว measurement_id=10:
         "http://172.20.10.4:8080/images/test.png") ไม่ใช่ path บนดิสก์เครื่องนี้
         ถ้าเอาไป join กับ ALPL_IMAGE_DIR จะได้ path มั่วๆ ที่ไม่ควรไปยุ่งด้วย
      2. **path ที่หลุดออกนอก ALPL_IMAGE_DIR** — ถ้าค่าใน DB มี ".." ปนมา
         (พลาดเองหรือถูกยัดมา) ต้องไม่ทำให้ลบไฟล์นอกโฟลเดอร์รูปได้
    """
    if not image_path:
        return False

    if "://" in image_path:
        log.warning(
            "ข้ามการลบไฟล์รูป: image_path เป็น URL ไม่ใช่ path บนดิสก์ (%s)", image_path
        )
        return False

    base = os.path.realpath(ALPL_IMAGE_DIR)
    target = os.path.realpath(os.path.join(base, image_path))
    if target != base and not target.startswith(base + os.sep):
        log.warning(
            "ข้ามการลบไฟล์รูป: path หลุดออกนอก ALPL_IMAGE_DIR (%s)", image_path
        )
        return False

    try:
        os.remove(target)
        return True
    except OSError:
        return False  # ไฟล์อาจถูกลบไปแล้ว/หาไม่เจอ — ไม่ใช่เรื่องผิดปกติ

def _group_config_for(qstate: Dict[str, Any], pos: int) -> Optional[Dict[str, Any]]:
    """config ของกลุ่มที่ชิ้นตำแหน่ง `pos` ในคิวสังกัดอยู่

    รองรับ `queue_state` รุ่นเก่าที่ค้างอยู่ใน DB ด้วย (มีแต่ `new_part_config`
    ก้อนเดียว ไม่มี `groups`) — สำคัญตอน backend restart ระหว่างที่ session เก่า
    ยังวัดอยู่ ถ้าอ่านไม่ออกจะไม่มี Part ถูกสร้างให้ ALPL ที่เหลือทั้งคิว
    """
    groups = qstate.get("groups")
    if groups:
        gof = qstate.get("group_of") or []
        gi = gof[pos] if pos < len(gof) else 0
        return groups[gi] if 0 <= gi < len(groups) else groups[0]
    return qstate.get("new_part_config")

def _update_part_row(cur, number_alpl: int, config: Dict[str, Any]) -> None:
    """Update 1 row ที่มีอยู่แล้วใน table `parts_specifications` (ตรงข้ามกับ
    _insert_part_row)

    ใช้เฉพาะกรณี Rework: ALPL นี้เคยผ่าน New มาแล้ว (มี Part row อยู่จริง) แต่
    งานไม่ผ่าน ถูกส่งไป Rework แล้วส่งกลับมาวัดใหม่ — ฟอร์ม Rework auto-fill
    ทุกช่องด้วยข้อมูลเดิมของ ALPL นี้ไว้ให้แล้ว (ดู GET /api/parts/{part_id})
    ยกเว้น recieve_date ที่ผู้ใช้ต้องกรอกวันที่รับกลับมาใหม่เอง — Save จึง
    เขียนทับ row เดิม (WHERE number_alpl = %s) แทนที่จะ insert row ใหม่ซ้อน
    ขึ้นมา ซึ่งจะชนกับ UNIQUE constraint ของ number_alpl ทันที
    """
    part_number_id = _lookup_id(cur, "part_number", "part_number_id", "part_number_name", config.get("part_number"))
    vendor_id      = _lookup_id(cur, "vendor",      "vendor_id",      "vendor_name",      config.get("vendor"))
    owner_id       = _lookup_id(cur, "owner",       "owner_id",       "owner_name",       config.get("owner"))
    package_size_id = _lookup_id(cur, "package_size", "package_size_id", "package_size", config.get("package_size"))
    cur.execute(
        "UPDATE parts_specifications SET part_number_id = %s, package_size_id = %s, "
        "description = %s, vendor_id = %s, po_number = %s, owner_id = %s, "
        "recieve_date = %s "
        "WHERE number_alpl = %s",
        (
            part_number_id, package_size_id, config.get("description"),
            vendor_id, config.get("po_number"), owner_id,
            config.get("recieve_date") or None, number_alpl,
        ),
    )

@router.get("/api/measurements")
def list_measurements(
    number_alpl: Optional[int] = None,
    result:      Optional[str] = None,
    date_from:   Optional[str] = None,
    date_to:     Optional[str] = None,
    session_id:  Optional[int] = None,
    limit:  int = Query(100, le=1000),
    offset: int = Query(0, ge=0),
):
    """Query ประวัติ measurement พร้อม filter ที่เลือกได้ — ใช้ทั้งโดยตาราง dashboard
    (renderTable) และเป็นฐานของ /api/export/csv filter ทุกตัวเป็น optional
    และรวมกันด้วย AND

    เปลี่ยน response shape เป็น object {items, total} เหมือน /api/parts เพื่อรองรับ
    server-side pagination (เพิ่ม offset เข้ามาคู่กับ limit ที่มีอยู่เดิม) — measurements
    โตเร็วกว่า parts มาก จึงไม่ควรโหลดทั้งหมดมา slice ฝั่ง client

    `total` ใช้ COUNT(*) บน WHERE ชุดเดียวกับ query หลัก (filter เดียวกัน) เพื่อให้
    frontend รู้จำนวนทั้งหมดที่ตรงกับ filter ปัจจุบัน ไว้คำนวณหน้า/ปิดปุ่ม Next

    หมายเหตุ: /api/export/csv เป็น endpoint แยกที่ "ไม่" reuse ฟังก์ชันนี้ (มันสร้าง
    WHERE ของตัวเองและคืนไฟล์ CSV ไม่ใช่ JSON) — การเปลี่ยน shape ตรงนี้จึงไม่กระทบ export
    """
    conditions, params = [], []
    if number_alpl is not None:
        conditions.append("m.number_alpl = %s"); params.append(number_alpl)
    if result:
        conditions.append("m.result = %s"); params.append(result)
    if date_from:
        conditions.append("m.timestamp >= %s"); params.append(_day_start(date_from))
    if date_to:
        conditions.append("m.timestamp <= %s"); params.append(_day_end(date_to))
    if session_id is not None:
        conditions.append("m.session_id = %s"); params.append(session_id)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) AS total FROM measurements m {where}", params)
            total = cur.fetchone()["total"]
            cur.execute(
                f"{MEASUREMENTS_SELECT} {where} ORDER BY m.timestamp DESC LIMIT %s OFFSET %s",
                (*params, limit, offset),
            )
            items = cur.fetchall()
        return {"items": items, "total": total}
    finally:
        db.close()

@router.post("/api/measurements")
async def create_measurement(req: MeasurementCreate):
    # ผลวัดต้องผูกกับ session ที่ Agent กำลัง running อยู่จริงเท่านั้น
    if req.session_id is None:
        raise HTTPException(
            400,
            "ต้องมี session_id — ระบบไม่รับการเพิ่มผลวัดเองด้วยมืออีกต่อไป "
            "(ผลวัดต้องมาจากการวัดจริงผ่าน TM-X เท่านั้น)",
        )
    qstate = None
    db = get_db()
    try:
        # กันการ insert ซ้ำถ้า Agent retry POST นี้ด้วย client_uuid เดิม (เช่น
        # ตอบกลับจาก request ครั้งก่อนหลุดหายระหว่างทาง ทั้งที่จริง backend
        # insert สำเร็จไปแล้ว) — เช็คก่อนทำอะไรอื่นเลย ถ้าเคยเห็น UUID นี้แล้ว
        # คืนผลเดิมไปตรงๆ ไม่ insert แถวใหม่ ไม่นับ measured_count ซ้ำ
        if req.client_uuid:
            with db.cursor() as cur:
                cur.execute(
                    "SELECT measurement_id, session_id, result FROM measurements "
                    "WHERE client_uuid = %s",
                    (req.client_uuid,),
                )
                dup = cur.fetchone()
            if dup:
                with db.cursor() as cur:
                    cur.execute(
                        "SELECT measured_count, target_count FROM sessions WHERE session_id = %s",
                        (dup["session_id"],),
                    )
                    s = cur.fetchone() or {}
                log.info(
                    "Duplicate measurement POST (client_uuid=%s) — คืนผลเดิม measurement_id=%d",
                    req.client_uuid, dup["measurement_id"],
                )
                return {
                    "measurement_id": dup["measurement_id"],
                    "result":  dup["result"],
                    "status":  "duplicate_ignored",
                    "measured": s.get("measured_count"),
                    "target":   s.get("target_count"),
                }

        with db.cursor() as cur:
            session_id = req.session_id
            # Session ต้องอยู่ในสถานะ running
            cur.execute(
                "SELECT state, target_count, measured_count FROM sessions WHERE session_id = %s",
                (session_id,),
            )
            session = cur.fetchone()
            if not session or session["state"] != "running":
                raise HTTPException(400, "Session is not running")

            qstate = session_queues.get(session_id)
            if qstate is None:
                # คิวหาย (backend restart แล้ว _reload_session_queues() กู้กลับไม่ได้)
                # — ปฏิเสธดีกว่าเดา เพราะการเดาจะได้ ALPL ตัวแรกของคิวเสมอ ซึ่งผิด
                # ตั้งแต่ชิ้นที่ 2 และผิดแบบเงียบๆ ไม่มีใครรู้ ส่วนการปฏิเสธจะทำให้
                # measured_count ไม่ขยับ → Pi รอจนครบ MEASURE_TIMEOUT → เด้งถาม
                # ผู้ใช้บนหน้าเว็บ → มีคนเห็นแน่นอน
                raise HTTPException(
                    409,
                    f"คิว ALPL ของ session {session_id} หายไป (backend อาจถูก restart) "
                    "— กด Stop ที่หน้าเว็บแล้วเริ่ม session ใหม่",
                )

            # ── Queue-based (IPM / New) ─────────────────────────────────────
            queue = qstate["queue"]
            pos = qstate["position"]
            if pos >= len(queue):
                raise HTTPException(400, "Measurement queue หมดแล้วสำหรับ session นี้")
            number_alpl = queue[pos]
            # entry_mode/note ถูก map ไว้แล้วตั้งแต่ start_session ตามโหมด
            # ที่ผู้ใช้เลือกหน้าเว็บ: Rework → ('New', 'Rework'),
            # New → ('New', None), IPM → ('IPM', None)
            # ⚠ measure_type จึงมีได้แค่ 'IPM' กับ 'New' เท่านั้น — 'Manual' ถูก
            #   ถอดออกแล้วพร้อมกับปุ่ม Add Measurement ส่วน 'Rework' ไม่เคยลง DB
            #   อยู่แล้ว (เก็บเป็น note แทน)
            measure_type = qstate["entry_mode"]  # 'IPM' หรือ 'New'
            operator_name = qstate.get("operator")
            note = qstate.get("note")

            # ── Part เกิด/ถูกอัปเดต "พร้อมกับ" measurement ของชิ้นนี้ ─────────
            # ไม่มีการเขียน Part ล่วงหน้าตอน Start อีกแล้วทุกโหมด — ผลคือกด Start
            # แล้วกด Stop ทันที หรือวัดชิ้นแรกไม่ติด จะไม่มี Part ผีค้างใน DB เลย
            #
            #   New   ยังไม่มีแถว → insert ด้วย config ของกลุ่มที่ชิ้นนี้อยู่
            #   IPM   ยังไม่มีแถว → insert เหมือนกัน (ผู้ใช้ยืนยันจากหน้าเว็บแล้ว
            #                       ว่าจะลงทะเบียนให้ — ดู D5) มีแล้วก็ไม่แตะ
            #   Rework มีแถวอยู่แล้วเสมอ → update ด้วยค่าที่ผู้ใช้แก้ในฟอร์ม
            #
            # ⚠ ใช้ config ของ "กลุ่มที่ชิ้นนี้อยู่" ไม่ใช่กลุ่มแรก — ฟอร์มกด +Add
            #   ได้หลายกลุ่ม แต่ละกลุ่มมี part_number/vendor/PO คนละชุด
            group_cfg = _group_config_for(qstate, pos)
            if group_cfg is not None:
                cur.execute("SELECT 1 FROM parts_specifications WHERE number_alpl = %s", (number_alpl,))
                exists = cur.fetchone() is not None
                try:
                    if not exists:
                        _insert_part_row(cur, number_alpl, group_cfg)
                    elif qstate.get("measure_mode") == "Rework":
                        _update_part_row(cur, number_alpl, group_cfg)
                except pymysql.MySQLError as exc:
                    raise HTTPException(409, f"บันทึก Part ALPL {number_alpl} ไม่สำเร็จ: {exc}")

            # หาเกณฑ์ตัดสิน — แหล่งต่างกันตามโหมด (IPM → package_size,
            # New/Rework → part_number) ดูเหตุผลที่ _load_criteria
            part = _load_criteria(cur, number_alpl, measure_type)

            # เช็ค OK/NG — tolerance ตัวเดียวใช้ร่วมกันทั้งแกน X และ Y
            # offset จะถูกนับเป็นเกณฑ์หรือไม่ ขึ้นกับโหมด (ดู _judge/_offset_limit)
            verdict = _judge(req.value_x, req.value_y, req.offset, part, measure_type)
            result = verdict["result"]

            # resolve ชื่อ operator (จาก dropdown) เป็น operator_id ก่อน insert —
            # measurements.operator_id เป็น FK ไป operator table แล้ว (เดิมเป็น
            # คอลัมน์ VARCHAR ชื่อ "Oparetor" ที่เก็บชื่อ operator ตรงๆ)
            operator_id = _lookup_id(cur, "operator", "operator_id", "operator_name", operator_name)

            # Insert row ของ measurement (รวม measure_type/operator_id/note ถ้าเป็น
            # queue-based หรือ manual add — สำหรับ manual session (ผ่าน Agent) แบบเดิม
            # ทั้ง 3 ค่านี้จะเป็น NULL)
            try:
                cur.execute(
                    "INSERT INTO measurements "
                    "(session_id, number_alpl, value_x, value_y, `offset`, result, "
                    " measure_type, operator_id, note, client_uuid) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (session_id, number_alpl, req.value_x, req.value_y, req.offset, result,
                     measure_type, operator_id, note, req.client_uuid),
                )
            except pymysql.IntegrityError:
                # race เล็กๆ ที่ทฤษฎีมีได้: สอง request ที่มี client_uuid เดียวกัน
                # มาถึงพร้อมกันเป๊ะๆ ผ่านเช็ค dedup ด้านบนพร้อมกันทั้งคู่ (เช็คแล้ว
                # ยังไม่เจอ เพราะอีกฝั่งยัง insert ไม่เสร็จ) — unique index บน
                # client_uuid จะกันไม่ให้ insert ซ้ำจริงๆ ระดับ DB อยู่ดี แค่ต้อง
                # จับ error แล้วบอกให้รู้ว่าเป็นการซ้ำ ไม่ใช่ปล่อยเป็น 500 ดิบๆ
                raise HTTPException(409, "Measurement นี้ถูกบันทึกไปแล้ว (duplicate client_uuid)")
            measurement_id = cur.lastrowid

            # เพิ่มตัวนับของ session
            cur.execute(
                "UPDATE sessions SET measured_count = measured_count + 1 "
                "WHERE session_id = %s",
                (session_id,),
            )

            # อ่านค่าตัวนับล่าสุดอีกครั้ง เพื่อเช็คว่าครบ target แล้วหรือยัง
            cur.execute(
                "SELECT measured_count, target_count FROM sessions WHERE session_id = %s",
                (session_id,),
            )
            updated = cur.fetchone()
            measured = updated["measured_count"]
            target   = updated["target_count"]

        # เพิ่มตำแหน่งในคิว (memory) แล้ว sync สำเนาลง DB ทันที (คอลัมน์
        # sessions.queue_state) — กัน backend restart กลาง session นี้แล้ว
        # ตำแหน่งคิวหาย ทำให้ measurement หลังจากนั้นถูกบันทึกผิด ALPL ไปเรื่อยๆ
        # แบบเงียบๆ (ดู lifespan() ที่โหลดค่านี้กลับตอน boot)
        if qstate is not None:
            qstate["position"] += 1
            with db.cursor() as cur:
                cur.execute(
                    "UPDATE sessions SET queue_state = %s WHERE session_id = %s",
                    (json.dumps(qstate), session_id),
                )

        # Auto-complete session เมื่อถึง target_count แล้ว
        #
        # ⚠️ ห้ามใส่ `await` ระหว่าง UPDATE measured_count ข้างบน (ราวบรรทัด 2239)
        # กับ UPDATE state='stopped' ข้างล่าง — มีคนพึ่งพาช่วงนี้อยู่:
        #   send_command.py บน Pi poll GET /api/session/state เพื่อรอให้
        #   measured_count ขยับ พอครบ target มันจะหลุด loop เข้า finally แล้วอ่าน
        #   state อีกครั้ง ถ้าเจอ 'running' จะยิง POST /api/session/stop
        #   (ดูบล็อก "ปิด session ที่ค้าง running" ท้าย command_flow)
        # ตอนนี้ autocommit=True ทำให้ measured_count ถูก commit ทันที แต่ Pi ยัง
        # อ่านค่าคาบเกี่ยวไม่ได้ เพราะ handler นี้เป็น async def ที่เรียก pymysql
        # (sync ล้วน ไม่ยอมคืน control) → event loop สลับไปเสิร์ฟ
        # /api/session/state ระหว่างสอง UPDATE นี้ไม่ได้ Pi จึงเห็นทั้งคู่พร้อมกัน
        # เสมอ ไม่มีทางยิง stop ทับ session ที่กำลังจะปิดตัวเองอยู่พอดี
        #
        # การรับประกันนี้จะหายไปทันทีถ้า: ย้ายไป async DB driver, ยัด DB call ลง
        # threadpool, เปลี่ยน endpoint นี้เป็น `def` ธรรมดา (FastAPI จะโยนเข้า
        # threadpool ให้รันขนานได้), หรือรัน uvicorn หลาย worker
        # → ถ้าทำอย่างใดอย่างหนึ่ง ต้องรวมสอง UPDATE นี้เป็น transaction เดียว
        #   หรือให้ stop_session เช็ค state ก่อน UPDATE แทน
        status = "continue"
        if measured >= target:
            with db.cursor() as cur:
                cur.execute(
                    "UPDATE sessions SET state = 'stopped', ended_at = NOW() "
                    "WHERE session_id = %s",
                    (session_id,),
                )
            status = "complete"
            session_queues.pop(session_id, None)  # session จบแล้ว ลบคิวออกจาก memory
            measure_timeouts.pop(session_id, None)
            await push_event(
                "session_complete",
                {"session_id": session_id, "measured": measured, "target": target},
            )

        # broadcast ให้ทุก dashboard ที่เปิดอยู่ (เดิมมีเงื่อนไขข้ามตอน manual add
        # เพราะ onNewMeasurement ฝั่ง index.html ไม่ได้เช็คว่า session_id ตรงกับ
        # session ที่กำลังแสดงอยู่ไหม — ตอนนี้ไม่มีเส้นทาง manual แล้วจึงยิงเสมอ)
        await push_event(
            "measurement",
            {
                "measurement_id": measurement_id,
                "session_id":     session_id,
                "number_alpl":    number_alpl,
                "value_x":        req.value_x,
                "value_y":        req.value_y,
                "result":         result,
                # ผลแยกรายแกน + ช่วงที่รับได้ — ให้ Live Telemetry โชว์ได้ว่า
                # "พังที่แกนไหน" ไม่ใช่รู้แค่ result รวม (DB เก็บแค่ result
                # รวมอย่างเดียว ค่าพวกนี้จึงต้องส่งมาทาง event ตอนวัดเสร็จ
                # ส่วนตอน refresh หน้าเว็บ frontend คำนวณเองจาก nominal/tol
                # ที่ /api/measurements แนบมาให้ — ดู MEASUREMENTS_SELECT)
                "offset":         req.offset,
                # ok_x / ok_y / ok_offset / offset_counts / offset_tol มาจาก
                # _judge() ก้อนเดียวกับที่ใช้ตัดสิน result ข้างบน — หน้าเว็บจึง
                # ไม่มีทางแสดงผลแยกแกนที่ขัดกับ result ที่บันทึกลง DB
                #   offset_counts=false → IPM: โชว์ค่า offset เฉยๆ ห้ามติดป้าย OK/NG
                **{k: verdict[k] for k in ("ok_x", "ok_y", "ok_offset", "offset_counts", "offset_tol")},
                "measure_type":   measure_type,
                "nominal_x":      part["nominal_x"],
                "nominal_y":      part["nominal_y"],
                "upper_tol":      part["upper_tol"],
                "lower_tol":      part["lower_tol"],
                "measured":       measured,
                "target":         target,
            },
        )
        return {
            "measurement_id": measurement_id,
            "result":  result,
            "status":  status,
            "measured": measured,
            "target":  target,
        }
    finally:
        db.close()

@router.patch("/api/measurements/{measurement_id}")
def update_measurement(measurement_id: int, data: Dict[str, Any] = Body(...)):
    """แก้ไข measurement แบบ partial (เฉพาะ field ที่ส่งมาใน body) — ใช้โดยหน้า
    Database Editor (edit.html) ตอนกด Edit แล้ว Save

    ทำไมต้องมี endpoint นี้แยกจาก create_measurement: create_measurement เป็น flow
    ของ Agent (insert ค่าใหม่ที่ TM-X วัดได้ พร้อมตัดสิน OK/NG จาก tolerance) ส่วนการ
    "แก้" ค่าที่บันทึกไว้แล้วเป็นการ override ด้วยมือจากหน้า editor ซึ่งไม่มีมาก่อน

    ใช้ pattern เดียวกับ update_part(): whitelist เฉพาะ field ที่อนุญาตให้แก้ได้
    (number_alpl, operator) เพื่อกัน body ไปเขียนทับ column ที่ไม่ควรแก้ผ่าน
    endpoint นี้ (เช่น session_id, timestamp, image_path, value_x/value_y)

    `number_alpl` แก้ไขได้ (เพิ่มเข้ามาใหม่) — ใช้กรณี IPM พิมพ์/เลือก ALPL ผิดตัว
    (เลือกชิ้นที่มีอยู่จริงในระบบผิดตัว) วิธีแก้ที่ถูกคือ retarget measurement row
    นี้ไปที่ ALPL ที่ถูกต้อง ไม่ใช่ไปแก้ ALPL ที่ตัว Part (เพราะจะกลายเป็นเปลี่ยนชื่อ
    Part จริงที่มีประวัติของตัวเองอยู่แล้ว — ดู update_part สำหรับกรณีพิมพ์ ALPL
    ผิดตอน "New" ซึ่งเหมาะจะแก้ที่ตัว Part แทน)

    ไม่มี `result` ใน allowed อีกต่อไป (เดิมให้ผู้ใช้เลือก OK/NG เองตรงๆ) — เพราะ
    ตอนนี้ ALPL/value เปลี่ยนได้ ทำให้ tolerance ที่ใช้ตัดสิน OK/NG เปลี่ยนตามไปด้วย
    จึงคำนวณ result ใหม่เสมอหลัง update ทุกครั้ง (ไม่ว่าจะแก้ field ไหนก็ตาม) แทนที่
    จะรับค่าจาก frontend ตรงๆ กัน Result ค้างไม่ตรงกับ ALPL/ค่าที่วัดได้จริง
    """
    # แก้ได้เฉพาะ number_alpl กับ operator เท่านั้น (ตามที่ตกลงกันไว้) —
    # value_x/value_y เป็นผลวัดจริงจากเครื่อง ส่วน note/measure_type เป็นข้อมูล
    # ของ session ที่ระบบกำหนดตอนวัด ไม่ควรถูกแก้ย้อนหลังผ่าน endpoint นี้
    # operator ส่งมาเป็น "ชื่อ" จาก dropdown แล้ว resolve เป็น operator_id เอง
    # (เหมือน pattern ของ update_part) — measurements.operator_id เป็น NOT NULL
    # จึงไม่รับค่าว่าง ต้องเลือก operator ที่มีอยู่จริงเสมอ
    allowed = {"number_alpl"}
    db = get_db()
    try:
        with db.cursor() as cur:
            _block_if_session_running(cur, "แก้ไข")

            set_parts, values = [], []
            for k, v in data.items():
                if k in allowed:
                    set_parts.append(f"{k} = %s")
                    values.append(v)
            if "operator" in data:
                operator_id = _lookup_id(cur, "operator", "operator_id", "operator_name", data["operator"])
                if operator_id is None:
                    raise HTTPException(400, "ต้องเลือก Operator (เว้นว่างไม่ได้)")
                set_parts.append("operator_id = %s")
                values.append(operator_id)
            if not set_parts:
                raise HTTPException(400, "No valid fields provided")

            set_clause = ", ".join(set_parts)
            try:
                cur.execute(
                    f"UPDATE measurements SET {set_clause} WHERE measurement_id = %s",
                    (*values, measurement_id),
                )
            except pymysql.MySQLError as exc:
                raise HTTPException(
                    409,
                    f"บันทึกไม่สำเร็จ — ALPL ใหม่อาจยังไม่ได้ลงทะเบียนใน Parts: {exc}",
                )
            if cur.rowcount == 0:
                raise HTTPException(404, "Measurement not found")

            # คำนวณ OK/NG ใหม่จากค่า value_x/value_y/number_alpl "ปัจจุบัน" ของ row
            # นี้เสมอ (หลัง update) — ครอบคลุมทั้งกรณีแก้ ALPL, แก้ value, หรือแก้แค่ note
            #
            # ⚠ ต้องอ่าน measure_type ของแถวนั้นมาด้วย แล้วส่งเข้า _load_criteria/
            #   _judge ชุดเดียวกับตอนวัดจริง — ถ้าคำนวณใหม่ด้วยเกณฑ์คนละแหล่ง
            #   แค่กดแก้ note เฉยๆ ก็ทำให้ผล OK/NG ของแถวนั้นพลิกได้เงียบๆ
            cur.execute(
                "SELECT number_alpl, value_x, value_y, `offset`, measure_type "
                "FROM measurements WHERE measurement_id = %s",
                (measurement_id,),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, "Measurement not found")
            crit = _load_criteria(cur, row["number_alpl"], row["measure_type"])
            new_result = _judge(
                row["value_x"], row["value_y"], row.get("offset"), crit, row["measure_type"]
            )["result"]
            cur.execute(
                "UPDATE measurements SET result = %s WHERE measurement_id = %s",
                (new_result, measurement_id),
            )
        return {"ok": True, "result": new_result}
    finally:
        db.close()

@router.patch("/api/measurements/{measurement_id}/image")
async def update_image(measurement_id: int, req: ImageUpdate):
    """แนบ path ของรูปภาพเข้ากับ measurement หลังจาก Agent จัดเก็บรูปเรียบร้อยแล้ว
    (เดิมคือหลังอัปโหลดขึ้น MinIO — architecture ใหม่จะเป็น path ของไฟล์ใน
    โฟลเดอร์บนเครื่อง PC แทน รอดีไซน์การจัดเก็บ finalize ก่อน)

    ทำไมต้องแยก call นี้ออกจาก create_measurement: Agent จัดเก็บรูป inspection
    *หลังจาก* ค่า measurement ถูกบันทึกไปแล้ว endpoint นี้แค่ patch path ของ
    รูปเข้ากับ measurement ทีหลัง การ broadcast 'image_updated' ทำให้ dashboard
    เปลี่ยนปุ่มรูปภาพในแถวนั้นได้โดยไม่ต้อง refresh ตารางทั้งหมด
    """
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute(
                "UPDATE measurements SET image_path = %s, image_upload_failed = %s "
                "WHERE measurement_id = %s",
                (req.image_path, req.upload_failed, measurement_id),
            )
            if cur.rowcount == 0:
                raise HTTPException(404, "Measurement not found")
        await push_event(
            "image_updated",
            {
                "measurement_id": measurement_id,
                "image_path": req.image_path,
                "upload_failed": req.upload_failed,
            },
        )
        return {"ok": True}
    finally:
        db.close()

@router.post("/api/measurements/{measurement_id}/image-upload")
async def upload_measurement_image(measurement_id: int, file: UploadFile = File(...)):
    """รับไฟล์รูปจริง (multipart) จาก Agent แล้วบันทึกลงดิสก์ของเครื่อง PC ที่
    รัน backend นี้เอง — แทนที่ MinIO เดิมทั้งหมด (ดูหมายเหตุ ALPL_IMAGE_DIR
    ด้านบน) ต่างจาก update_image (PATCH /image) ตรงที่ endpoint นั้นรับแค่
    "path" ที่ Agent อ้างว่าเก็บไว้แล้ว (ใช้ได้ตอน Agent+Backend อยู่เครื่อง
    เดียวกัน) แต่ตอนนี้ Agent อยู่คนละเครื่อง (Pi) กับ backend (PC) จึงต้องรับ
    "เนื้อไฟล์จริง" มาด้วยเลย แล้ว backend เป็นคนตัดสินใจ path ปลายทางเอง

    path ปลายทาง (เปลี่ยนจากเดิมที่แยกตาม package_size มาเป็นแยกตามวันที่ ตามที่
    ตกลงกันไว้): ALPL_IMAGE_DIR/<DD-MM-YYYY พ.ศ.>/<number_alpl>_<DD-MM-YYYY พ.ศ.>.jpg
    เช่น "22-07-2569/203_22-07-2569.jpg" — ไฟล์ต้นทางจาก TM-X (ปกติเป็น .bmp)
    ถูกแปลงเป็น .jpg เสมอด้วย Pillow ก่อนเซฟ (ไม่เก็บไฟล์ต้นฉบับ .bmp ไว้เลย)
    เก็บเป็น "path สัมพัทธ์" (relative ต่อ ALPL_IMAGE_DIR) ลงคอลัมน์
    measurements.image_path — ไม่เก็บ absolute path เต็มๆ ลง DB เพื่อไม่ให้
    รั่วโครงสร้างไฟล์ระบบจริงออกไป และให้ /api/image-url ต่อ URL ได้ตรงๆ จาก
    ค่านี้ (ดู get_image_url ด้านล่าง กับ static mount /media/alpl ท้ายไฟล์)

    หมายเหตุ (อัปเดต): ชื่อไฟล์เปลี่ยนจาก "number_alpl + วันที่" เป็น
    "number_alpl + measurement_id + ตัวสุ่ม" (เช่น "203_5821_a3f9c8d4e5b6c7d8.jpg")
    — measurement_id ทำให้ชื่อไฟล์ไม่ซ้ำกันเองอยู่แล้วโดยธรรมชาติ (เลขรันของแต่ละ
    การวัด) ส่วนตัวสุ่ม (hex 16 ตัวอักษร จาก secrets.token_hex) กันคนในวง office
    network เดาชื่อไฟล์ ALPL ตัวอื่นถูกโดยไล่เลข measurement_id เอา (ตัว IP
    allowlist ของ office network เป็นชั้นป้องกันหลักที่กันคนนอกอยู่แล้ว ตัวสุ่มนี้
    เป็นชั้นเสริมเท่านั้น) โฟลเดอร์ปลายทางยังคงแยกตามวันที่วัดเหมือนเดิม (ดู
    dest_dir ด้านล่าง) แค่ชื่อไฟล์ข้างในไม่มีวันที่ปนแล้ว
    ผลข้างเคียง: ชื่อไฟล์ไม่ซ้ำกันเองอัตโนมัติอีกต่อไปเหมือนก่อนหน้านี้ (เดิมใช้
    number_alpl+วันที่ ล้วนๆ ทำให้เขียนทับไฟล์เดิมเองโดยไม่ต้องทำอะไรเพิ่ม) จึง
    ต้องลบไฟล์เก่าด้วยมือด้านล่าง (`old_image_path`) หลังเซฟไฟล์ใหม่สำเร็จ
    ไม่งั้นรูปเก่าจะค้างสะสมในโฟลเดอร์ทุกครั้งที่ ALPL เดียวกันถูกวัดซ้ำในวันเดียวกัน
    — ยังคงพฤติกรรมเดิมไว้ว่า "เก็บแค่รูปล่าสุดของ ALPL นั้นในแต่ละวัน"
    """
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute(
                "SELECT number_alpl, image_path FROM measurements WHERE measurement_id = %s",
                (measurement_id,),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, "Measurement not found")

            old_image_path = row["image_path"]  # ไฟล์เก่า (ถ้ามี) ของ ALPL นี้ — ต้องลบทิ้งเองหลังเซฟไฟล์ใหม่สำเร็จ

            date_str = _thai_date_str()
            dest_dir = os.path.join(ALPL_IMAGE_DIR, date_str)
            os.makedirs(dest_dir, exist_ok=True)

            # ตัวสุ่มต่อท้ายชื่อไฟล์ — ใช้ secrets (CSPRNG) ไม่ใช่ random module
            # เพราะเป็นงานที่เกี่ยวกับความปลอดภัย (เดาไม่ได้จริงในทางปฏิบัติ)
            # 8 ไบต์ (16 ตัวอักษร hex) พอสำหรับ defense-in-depth ชั้นเสริม ไม่ต้อง
            # ยาวถึงระดับกัน brute-force จากอินเทอร์เน็ตแบบ token รีเซ็ตรหัสผ่าน
            token = secrets.token_hex(8)
            filename = f"{row['number_alpl']}_{measurement_id}_{token}.jpg"
            dest_path_abs = os.path.join(dest_dir, filename)
            image_path_rel = f"{date_str}/{filename}"  # เก็บลง DB แบบ forward-slash เสมอ (ใช้ต่อ URL ตรงๆ ได้)

            try:
                image_bytes = await file.read()
                img = Image.open(BytesIO(image_bytes))
                if img.mode != "RGB":
                    img = img.convert("RGB")  # JPEG ไม่รองรับ alpha/palette (RGBA/P/LA ฯลฯ)
                img.save(dest_path_abs, "JPEG", quality=90)
            except Exception as exc:
                raise HTTPException(500, f"บันทึก/แปลงไฟล์รูปเป็น .jpg ไม่สำเร็จ: {exc}")
            finally:
                await file.close()

            cur.execute(
                "UPDATE measurements SET image_path = %s, image_upload_failed = 0 "
                "WHERE measurement_id = %s",
                (image_path_rel, measurement_id),
            )

            # ลบไฟล์เก่าทิ้ง "หลัง" เซฟไฟล์ใหม่และอัปเดต DB สำเร็จแล้วเท่านั้น —
            # ชื่อไฟล์มีตัวสุ่มแล้วจึงไม่ทับกันเองอัตโนมัติแบบเดิมอีกต่อไป ถ้าไม่ลบ
            # เอง ไฟล์เก่าจะค้างสะสมในโฟลเดอร์ทุกครั้งที่วัด ALPL เดิมซ้ำวันเดียวกัน
            if old_image_path and old_image_path != image_path_rel:
                # ใช้ _delete_image_file เพื่อให้ได้การกัน 2 ชั้นเหมือนตอน DELETE
                # (URL ตกค้างจากยุค MinIO + path ที่หลุดออกนอกโฟลเดอร์รูป) —
                # เดิม os.remove ตรงๆ ถ้าเจอแถวเก่าที่เก็บ URL เต็มไว้จะได้ path
                # มั่วๆ ที่ไม่ควรไปแตะตั้งแต่แรก
                _delete_image_file(old_image_path)
        await push_event(
            "image_updated",
            {
                "measurement_id": measurement_id,
                "image_path": image_path_rel,
                "upload_failed": False,
            },
        )
        return {"ok": True, "image_path": image_path_rel}
    finally:
        db.close()

@router.delete("/api/measurements/{measurement_id}")
def delete_measurement(measurement_id: int):
    """ลบ measurement 1 row (เช่น ลบค่าที่อ่านผิดพลาด/เป็นการทดสอบ) + ลบไฟล์รูปด้วย

    เดิมลบแค่แถวใน DB ทำให้ไฟล์รูปกลายเป็น "ไฟล์กำพร้า" ค้างสะสมใน
    ALPL_IMAGE_DIR ไปเรื่อยๆ โดยไม่มีอะไรอ้างถึงอีกเลย — และไล่เก็บทีหลังไม่ได้
    ด้วย เพราะข้อมูลที่จะใช้เทียบว่าไฟล์ไหนกำพร้า (แถวใน measurements) ถูกลบไป
    พร้อมกันแล้ว

    ลำดับสำคัญ: **อ่าน image_path ก่อน → ลบแถว → ค่อยลบไฟล์**
    ถ้าลบแถวไม่สำเร็จ (ไม่เจอ row / ติด session guard) ไฟล์ต้องยังอยู่ครบ
    ส่วนถ้าลบแถวสำเร็จแล้วลบไฟล์พลาด ก็ยอมให้ไฟล์ค้าง ดีกว่าทำให้ request พัง
    ทั้งที่ข้อมูลถูกลบไปเรียบร้อยแล้ว (autocommit=True แถวถูก commit ทันที)
    """
    db = get_db()
    try:
        with db.cursor() as cur:
            _block_if_session_running(cur, "ลบ")

            row = _fetch_one(
                cur, "SELECT * FROM measurements WHERE measurement_id = %s", (measurement_id,)
            )
            if not row:
                raise HTTPException(404, "Measurement not found")
            image_path = row["image_path"]

            # ── สำรองก่อนลบ ── ตัวนี้ "ย้าย" ไฟล์รูปเข้าถังขยะให้ด้วย ไม่ได้ลบ
            archived = _archive_before_delete(
                kind="measurement", table="measurements",
                pk={"measurement_id": measurement_id}, row=row,
                image_path=image_path,
            )

            cur.execute(
                "DELETE FROM measurements WHERE measurement_id = %s", (measurement_id,)
            )
            if cur.rowcount == 0:
                raise HTTPException(404, "Measurement not found")

        # ลบไฟล์รูปเฉพาะตอนที่ "สำรองไม่สำเร็จ" เท่านั้น — ถ้าสำรองได้ ไฟล์ถูก
        # ย้ายเข้าถังขยะไปแล้ว (_delete_image_file จะหาไม่เจอและคืน False เอง
        # อยู่แล้ว แต่เขียนเงื่อนไขให้ชัดดีกว่าพึ่งผลข้างเคียง)
        if archived is None and _delete_image_file(image_path):
            log.info("ลบไฟล์รูปของ measurement %s แล้ว (%s)", measurement_id, image_path)
        return {"ok": True}
    finally:
        db.close()

# ══════════════════════════════════════════════════════════════════════════════
# Image URL endpoint (stub — รอดีไซน์การจัดเก็บรูปแบบ local folder)
# ══════════════════════════════════════════════════════════════════════════════
# เดิมตรงนี้มี 2 endpoint ที่ผูกกับ MinIO ทั้งคู่:
#   POST /api/upload-url          — ออก presigned PUT URL ให้ Agent อัปโหลดรูป
#   GET  /api/image-url/{id}      — ออก presigned GET URL ให้ dashboard ดูรูป
# architecture ใหม่เลิกใช้ MinIO แล้ว รูปจะเก็บเป็นไฟล์ในโฟลเดอร์บนเครื่อง PC
# แทน แต่ดีไซน์การจัดเก็บ (โครงสร้างโฟลเดอร์/ชื่อไฟล์/ใครเป็นคนย้ายไฟล์) ยังไม่
# fix — จึงตัด /api/upload-url ทิ้งไปเลย (Agent ตอนนี้ไม่อัปโหลดรูปแล้ว) ส่วน
# /api/image-url: ดีไซน์เสร็จแล้ว — image_path ใน DB เป็น path สัมพัทธ์ต่อ
# ALPL_IMAGE_DIR เสมอ (เช่น "22-07-2569/203_22-07-2569.jpg" — แยกโฟลเดอร์ตาม
# วันที่วัด ดู upload_measurement_image ด้านบน) จึงต่อ URL ตรงๆ ได้จาก static
# mount "/media/alpl" (ท้ายไฟล์) ไม่ต้อง
# ออก presigned URL แบบ MinIO เดิมอีกต่อไป (ไฟล์อยู่บนดิสก์เครื่องนี้ตรงๆ)
@router.get("/api/image-url/{measurement_id}")
def get_image_url(measurement_id: int):
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute(
                "SELECT image_path, image_upload_failed FROM measurements WHERE measurement_id = %s",
                (measurement_id,),
            )
            row = cur.fetchone()
        if not row:
            raise HTTPException(404, "Measurement not found")
        if not row["image_path"]:
            detail = (
                "Agent อัปโหลดรูปไม่สำเร็จ (ลองครบ 3 ครั้งแล้ว)"
                if row["image_upload_failed"]
                else "ยังไม่มีรูปสำหรับ measurement นี้"
            )
            raise HTTPException(404, detail)
        return {"url": f"/media/alpl/{row['image_path']}"}
    finally:
        db.close()
