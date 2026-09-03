"""routers/measurements.py — ผลการวัดรายชิ้น + รูปภาพ

ย้ายมาจาก main.py แบบยกก้อน ไม่ได้แก้ตรรกะใดๆ
⚠ ห้ามประกาศ session_queues / measure_timeouts / subscribers ซ้ำในไฟล์นี้
  ต้องดึงจาก shared.py เท่านั้น ไม่งั้นจะกลายเป็นคนละ object โดยไม่มี error
"""
from fastapi import APIRouter

from shared import *  # noqa: F401,F403

router = APIRouter()


# ⚠ `_offset_ok` ย้ายไปอยู่ `shared.py` แล้ว (ก.ย. 2569) — มาถึงไฟล์นี้ผ่าน
#   `from shared import *` ข้างบน **ห้ามประกาศซ้ำที่นี่** เพราะจะไปบัง
#   (shadow) ตัวจริง แล้ว `_offset_state()` ใน shared.py จะใช้คนละสูตรกับ
#   `_judge()` ที่นี่โดยไม่มี error ให้เห็นเลย
#
#   เหตุผลที่ต้องย้าย: `_offset_state()` ใน shared.py ต้องใช้ตัวนี้ด้วย แต่
#   shared.py import measurements.py ไม่ได้ (ทิศทางเดียว) เดิมจึงต้องลอกสูตร
#   ไปเขียนซ้ำ แล้วสองที่ก็เพี้ยนกันจนได้


def _judge(
    value_x: float,
    value_y: float,
    offset_opx: Optional[float],
    offset_opy: Optional[float],
    crit,
    measure_type: str,
) -> dict:
    """ตัดสิน OK/NG ครั้งเดียวจบ — ตรวจ tolerance แกน X, Y และ Offset ทั้ง 4 แกนกับ limit เดียวกัน"""
    ok_x = _within_tolerance(value_x, crit["nominal_x"], crit["upper_tol"], crit["lower_tol"])
    ok_y = _within_tolerance(value_y, crit["nominal_y"], crit["upper_tol"], crit["lower_tol"])

    limit = _offset_limit(measure_type, crit)
    offset_counts = limit is not None

    if offset_counts:
        # ตรวจเช็ค Offset ทั้ง 4 แกนเทียบกับ limit เดียวกัน
        ok_opx = _offset_ok(offset_opx, limit)
        ok_opy = _offset_ok(offset_opy, limit)

        # ถ้าผ่านหมดทั้ง 4 ตัวจะได้ True แต่ถ้ามีตัวใดตัวหนึ่งเป็น False จะได้ False ทันที
        ok_offset = ok_opx and ok_opy
    else:
        # หากโหมดนี้ไม่ต้องตรวจ Offset ให้คืนค่าเป็น None
        ok_offset = None

    # ผลรวม: X ต้องผ่าน, Y ต้องผ่าน และ ok_offset ห้ามเป็น False
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
    """ลบไฟล์รูปที่ image_path (path สัมพัทธ์ต่อ ALPL_IMAGE_DIR) ชี้อยู่"""
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
        return False


def _group_config_for(qstate: Dict[str, Any], pos: int) -> Optional[Dict[str, Any]]:
    """config ของกลุ่มที่ชิ้นตำแหน่ง `pos` ในคิวสังกัดอยู่"""
    groups = qstate.get("groups")
    if groups:
        gof = qstate.get("group_of") or []
        gi = gof[pos] if pos < len(gof) else 0
        return groups[gi] if 0 <= gi < len(groups) else groups[0]
    return qstate.get("new_part_config")


def _update_part_row(cur, number_alpl: int, config: Dict[str, Any]) -> None:
    """Update 1 row ที่มีอยู่แล้วใน table `parts_specifications`"""
    part_number_id = _lookup_id(cur, "part_number", "part_number_id", "part_number_name", config.get("part_number"))
    vendor_id      = _lookup_id(cur, "vendor",      "vendor_id",      "vendor_name",      config.get("vendor"))
    owner_id       = _lookup_id(cur, "owner",       "owner_id",       "owner_name",       config.get("owner"))
    package_size_id = _lookup_id(cur, "package_size", "package_size_id", "package_size", config.get("package_size"))
    # ⚠ ต้องเขียน handler_id ด้วย ให้ตรงกับ `_insert_part_row` — ถ้าตกหล่นที่นี่
    #   การแก้ผ่านโหมด Rework จะไม่อัปเดตเครื่อง ทั้งที่ฟอร์มแสดงว่าเปลี่ยนแล้ว
    handler_id = _lookup_id(cur, "handler", "handler_id", "handler_name", config.get("handler"))
    cur.execute(
        "UPDATE parts_specifications SET part_number_id = %s, package_size_id = %s, "
        "handler_id = %s, description = %s, vendor_id = %s, po_number = %s, owner_id = %s, "
        "recieve_date = %s "
        "WHERE number_alpl = %s",
        (
            part_number_id, package_size_id, handler_id, config.get("description"),
            vendor_id, config.get("po_number"), owner_id,
            config.get("recieve_date") or None, number_alpl,
        ),
    )


# ระยะที่ถือว่า "สองมุมเท่ากัน" — ต่างกันน้อยกว่านี้ = เสมอ
#
# ⚠⚠ **ห้ามเทียบ `tr == tl` ตรง ๆ เด็ดขาด** แม้ TM-X จะส่งมาเป็นทศนิยม 3 ตำแหน่ง
#   ก็ตาม เพราะค่าเดินทางผ่าน `float` ของ Python และคอลัมน์ `FLOAT` ของ MySQL
#   ซึ่งเก็บเป็น binary — `0.012` อ่านกลับได้ `0.012000000104308128`
#   สองมุมที่ "เท่ากัน" ในสายตาคนจึงแทบไม่มีทางเท่ากันด้วย `==`
#   ผลคือเงื่อนไขขอบ (TOP/BOTTOM/LEFT/RIGHT) จะไม่มีวันทำงานเลยสักครั้ง
#
# ⚠ ค่านี้ใหญ่กว่า `_TOL_EPS` (1e-6) โดยตั้งใจ — ตัวนั้นแก้ปัญหาความคลาดเคลื่อน
#   ของ float ล้วน ๆ ส่วนตัวนี้ต้องเผื่อ "ความไม่เท่ากันทางกายภาพที่เล็กจนไม่มี
#   ความหมาย" ด้วย (0.012 กับ 0.0121 คือชิ้นงานเบียดขอบบนพอ ๆ กัน ไม่ใช่เบียดมุม)
#   ปรับได้จาก .env ถ้าหน้างานพบว่าหยาบ/ละเอียดเกิน
_POS_TIE_EPS = float(os.getenv("OFFSET_POS_TIE_EPS", 5e-4))

# รหัสตำแหน่งที่เก็บลง DB — **เป็นรหัสสำหรับเครื่องอ่าน ไม่ใช่ข้อความให้คนอ่าน**
# หน้าเว็บแปลเป็นภาษาไทยเอง ("TOP_RIGHT" → "บนขวา") จึงเปลี่ยนคำที่แสดงได้
# โดยไม่ต้องแตะ DB และไม่ต้อง migrate ข้อมูลเก่า
_POS_TR, _POS_TL, _POS_BR, _POS_BL = "TOP RIGHT", "TOP LEFT", "BOTTOM RIGHT", "BOTTOM LEFT"
_POS_TOP, _POS_BOTTOM, _POS_LEFT, _POS_RIGHT = "TOP", "BOTTOM", "LEFT", "RIGHT"
_POS_CENTER = "CENTER"


def _get_position_label(
    horizon_left: float, horizon_right: float,
    vertical_top: float, vertical_bottom: float,
) -> str:
    """หา "ชิ้นงานเบียดไปทางไหน" จากระยะ opening 4 ด้าน — คืนรหัส 1 ใน 9 ค่า

    คิดเป็น **2 คู่แกน** (ไม่ใช่ 4 มุมแบบตรรกะเดิม) — เทียบผลต่างของแต่ละคู่
    แล้วดูแค่ *เครื่องหมาย* ของผลต่าง ไม่ได้ดูว่าค่าไหนน้อยที่สุด

        dx = horizon_left  - horizon_right     → แกนซ้าย/ขวา
        dy = vertical_top  - vertical_bottom   → แกนบน/ล่าง

    ตารางผลลัพธ์ (ตามผัง Flowchart ที่ตกลงกันไว้):

                    dy > 0        dy = 0        dy < 0
        dx > 0    TOP LEFT        LEFT       BOTTOM LEFT
        dx = 0       TOP         CENTER        BOTTOM
        dx < 0   TOP RIGHT        RIGHT     BOTTOM RIGHT

    ⚠ **"= 0" ไม่ได้แปลว่าเท่ากันเป๊ะ** — ใช้ `_POS_TIE_EPS` เป็นเขตตาย
      (deadband) เพราะค่าที่วัดจากของจริงไม่มีทางเท่ากันพอดี ถ้าเทียบ `== 0`
      ตรง ๆ จะไม่มีวันได้ CENTER/TOP/LEFT เลย เหลือแต่ 4 มุม
      ปรับความกว้างได้จาก `OFFSET_POS_TIE_EPS` ใน .env

    ⚠ ตรรกะนี้ **ไม่มีทางล้มเหลว** — ทุก input ตกลงช่องใดช่องหนึ่งใน 9 ช่องเสมอ
      จึงไม่มีเคส warning แบบ "เสมอทแยง" ของตรรกะเดิมอีกต่อไป (เคสชิ้นงานเอียง
      ตอนนี้จะถูกกลืนเป็นตำแหน่งใดตำแหน่งหนึ่งเงียบ ๆ แทนที่จะขึ้น log)
    """
    dx = horizon_left - horizon_right      # + = เบียดไปทางซ้าย
    dy = vertical_top - vertical_bottom    # + = เบียดขึ้นบน

    # -1 / 0 / +1 โดยมีเขตตายกว้าง _POS_TIE_EPS รอบศูนย์
    sx = 0 if abs(dx) <= _POS_TIE_EPS else (1 if dx > 0 else -1)
    sy = 0 if abs(dy) <= _POS_TIE_EPS else (1 if dy > 0 else -1)

    return {
        ( 1,  1): _POS_TL, ( 1, 0): _POS_LEFT,   ( 1, -1): _POS_BL,
        ( 0,  1): _POS_TOP, (0, 0): _POS_CENTER, ( 0, -1): _POS_BOTTOM,
        (-1,  1): _POS_TR, (-1, 0): _POS_RIGHT,  (-1, -1): _POS_BR,
    }[(sx, sy)]


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
        # ⚠ แปะผลตัดสินรายแกนไปด้วย — หน้าเว็บ **ต้องไม่คำนวณเอง**
        #   คอลัมน์ `result` เป็นผลรวมของทั้งแถว (X ผ่านแต่ Y ไม่ผ่าน → NG)
        #   ระบายสีช่อง X ด้วย `result` จึงผิด · เดิม frontend เลยไปคำนวณ
        #   `nominal ± tol` ใหม่เองโดยไม่ปัดทศนิยม แล้วชิ้นที่ตกขอบพอดีขึ้น
        #   สีแดงทั้งที่ `result` บอก OK — ดู `_ok_flags` ใน shared.py
        for it in items:
            it.update(_ok_flags(it))
        return {"items": items, "total": total}
    finally:
        db.close()


# มุมมองของ Measurement ที่ใช้บันทึกลงประวัติ — เก็บเฉพาะฟิลด์ที่ "คนแก้ได้"
# บวก result ที่ระบบคำนวณใหม่ให้ · join เอาชื่อ operator มาแทน operator_id ดิบ
#
# ⚠ ไม่เอา value_x/value_y/timestamp มาด้วย — เป็นผลวัดจริงจากเครื่องที่แก้
#   ย้อนหลังไม่ได้อยู่แล้ว ใส่มาก็รกเปล่า ๆ (ตอนลบยังเก็บครบทุกฟิลด์เหมือนเดิม)
_MEAS_HISTORY_SQL = """
    SELECT m.number_alpl, op.operator_name AS operator, m.result, m.note
    FROM measurements m
    LEFT JOIN operator op ON m.operator_id = op.operator_id
    WHERE m.measurement_id = %s
"""

@router.post("/api/measurements")
async def create_measurement(req: MeasurementCreate):
    if req.session_id is None:
        raise HTTPException(
            400,
            "ต้องมี session_id — ระบบไม่รับการเพิ่มผลวัดเองด้วยมืออีกต่อไป "
            "(ผลวัดต้องมาจากการวัดจริงผ่าน TM-X เท่านั้น)",
        )
    qstate = None
    db = get_db()
    try:
        # ⚠ เดิมตรงนี้มีบล็อกเช็ค `client_uuid` ซ้ำ แล้วคืนแถวเดิมแทนการ insert ใหม่
        #   ถอดออกแล้วพร้อมกับตัว client_uuid เอง เพราะไม่มีฝั่งไหนส่งค่าที่ "คงที่
        #   ต่อชิ้น" มาอีก — Data Receiver ไม่ส่งเลย ส่วน Pi ก็ยิงครั้งเดียวไม่มี retry
        #   การกันซ้ำจึงไม่เคยได้ทำงานจริง มีแต่ทำให้ทุก POST เสีย SELECT ฟรี 1 ครั้ง
        with db.cursor() as cur:
            session_id = req.session_id
            cur.execute(
                "SELECT state, target_count, measured_count FROM sessions WHERE session_id = %s",
                (session_id,),
            )
            session = cur.fetchone()
            if not session or session["state"] != "running":
                raise HTTPException(400, "Session is not running")

            qstate = session_queues.get(session_id)
            if qstate is None:
                raise HTTPException(
                    409,
                    f"คิว ALPL ของ session {session_id} หายไป (backend อาจถูก restart) "
                    "— กด Stop ที่หน้าเว็บแล้วเริ่ม session ใหม่",
                )

            queue = qstate["queue"]
            pos = qstate["position"]
            if pos >= len(queue):
                raise HTTPException(400, "Measurement queue หมดแล้วสำหรับ session นี้")
            number_alpl = queue[pos]
            measure_type = qstate["entry_mode"]
            operator_name = qstate.get("operator")
            note = qstate.get("note")

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

            part = _load_criteria(cur, number_alpl, measure_type)

            # ── คำนวณหาตำแหน่ง Offset ที่น้อยที่สุด (OP) ─────────────────
            offset_pos_op = _get_position_label(
                req.horizon_left, req.horizon_right, req.vertical_top, req.vertical_bottom,
            )

            # ── [FIX 1] ส่ง Parameter ให้ครบทั้ง 8 ตัว ──────────────────────────
            verdict = _judge(
                value_x=req.value_x,
                value_y=req.value_y,
                offset_opx=req.offset_opx,
                offset_opy=req.offset_opy,
                crit=part,
                measure_type=measure_type,
            )
            result = verdict["result"]

            operator_id = _lookup_id(cur, "operator", "operator_id", "operator_name", operator_name)

            try:
                cur.execute(
                    "INSERT INTO measurements "
                    "(session_id, number_alpl, value_x, value_y, "
                    " offset_opx, offset_opy, "
                    " offset_pos_op, result, "
                    " measure_type, operator_id, note) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (
                        session_id, number_alpl, req.value_x, req.value_y,
                        req.offset_opx, req.offset_opy,
                        offset_pos_op, result,
                        measure_type, operator_id, note
                    ),
                )
            except pymysql.IntegrityError as exc:
                log.warning("INSERT measurement ไม่สำเร็จ: %s", exc)
                raise HTTPException(409, "เกิดปัญหาในการบันทึกข้อมูลลงใน Database")
            measurement_id = cur.lastrowid

            cur.execute(
                "UPDATE sessions SET measured_count = measured_count + 1 "
                "WHERE session_id = %s",
                (session_id,),
            )

            cur.execute(
                "SELECT measured_count, target_count FROM sessions WHERE session_id = %s",
                (session_id,),
            )
            updated = cur.fetchone()
            measured = updated["measured_count"]
            target   = updated["target_count"]

        if qstate is not None:
            qstate["position"] += 1
            with db.cursor() as cur:
                cur.execute(
                    "UPDATE sessions SET queue_state = %s WHERE session_id = %s",
                    (json.dumps(qstate), session_id),
                )

        status = "continue"
        if measured >= target:
            with db.cursor() as cur:
                cur.execute(
                    "UPDATE sessions SET state = 'stopped', ended_at = NOW() "
                    "WHERE session_id = %s",
                    (session_id,),
                )
            status = "complete"
            session_queues.pop(session_id, None)
            measure_timeouts.pop(session_id, None)
            await push_event(
                "session_complete",
                {"session_id": session_id, "measured": measured, "target": target},
            )

        await push_event(
            "measurement",
            {
                "measurement_id": measurement_id,
                "session_id":     session_id,
                "number_alpl":    number_alpl,
                "value_x":        req.value_x,
                "value_y":        req.value_y,
                "result":         result,
                "offset_opx":     req.offset_opx,
                "offset_opy":     req.offset_opy,
                "offset_pos_op":  offset_pos_op,
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
            "result":        result,
            "offset_pos_op": offset_pos_op,
            "status":        status,
            "measured":      measured,
            "target":        target,
        }
    finally:
        db.close()


@router.patch("/api/measurements/{measurement_id}")
def update_measurement(measurement_id: int, data: Dict[str, Any] = Body(...)):
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
                # ค่าเดิมก่อนแก้ — join เอาชื่อ operator มาแทน operator_id ดิบ
                _hist_before = _fetch_one(cur, _MEAS_HISTORY_SQL, (measurement_id,))
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

            # ⚠ บันทึกประวัติ "ก่อน" ที่ result จะถูกคำนวณใหม่ด้านล่าง — ตรงนี้คือ
            #   สิ่งที่ "คนแก้" จริง ๆ (ALPL / Operator) ส่วน result ที่เปลี่ยนตาม
            #   เป็นผลจากระบบ ไม่ใช่การกระทำของผู้ใช้ ถ้าเอามารวมเป็นบรรทัดเดียวกัน
            #   จะอ่านไม่ออกว่าใครเปลี่ยนอะไร
            _hist_after = _fetch_one(cur, _MEAS_HISTORY_SQL, (measurement_id,))
            if _hist_before is not None and _hist_after is not None:
                log_edit("measurements", "edit", f"ID {measurement_id}",
                         before=_hist_before, after=_hist_after)

            # ── [FIX 2] อ่าน คอลัมน์ Offset แยกแกนแทนคอลัมน์ `offset` เดิม ────────
            cur.execute(
                "SELECT number_alpl, value_x, value_y, "
                "offset_opx, offset_opy, measure_type "
                "FROM measurements WHERE measurement_id = %s",
                (measurement_id,),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, "Measurement not found")
            
            crit = _load_criteria(cur, row["number_alpl"], row["measure_type"])
            
            # ── [FIX 3] คำนวณ result ใหม่โดยส่ง offset ทั้ง 4 แกนเข้า _judge ────────
            new_result = _judge(
                value_x=row["value_x"],
                value_y=row["value_y"],
                offset_opx=row.get("offset_opx"),
                offset_opy=row.get("offset_opy"),
                crit=crit,
                measure_type=row["measure_type"],
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

            old_image_path = row["image_path"]

            date_str = _thai_date_str()
            dest_dir = os.path.join(ALPL_IMAGE_DIR, date_str)
            os.makedirs(dest_dir, exist_ok=True)

            token = secrets.token_hex(8)
            filename = f"{row['number_alpl']}_{measurement_id}_{token}.jpg"
            dest_path_abs = os.path.join(dest_dir, filename)
            image_path_rel = f"{date_str}/{filename}"

            try:
                image_bytes = await file.read()
                img = Image.open(BytesIO(image_bytes))
                if img.mode != "RGB":
                    img = img.convert("RGB")
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

            if old_image_path and old_image_path != image_path_rel:
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
            log_edit("measurements", "delete", f"ID {measurement_id}",
                     before=row, trash_id=archived)

        if archived is None and _delete_image_file(image_path):
            log.info("ลบไฟล์รูปของ measurement %s แล้ว (%s)", measurement_id, image_path)
        return {"ok": True}
    finally:
        db.close()


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