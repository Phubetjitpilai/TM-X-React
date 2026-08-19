"""routers/measurements.py — ผลการวัดรายชิ้น + รูปภาพ

ย้ายมาจาก main.py แบบยกก้อน ไม่ได้แก้ตรรกะใดๆ
⚠ ห้ามประกาศ session_queues / measure_timeouts / subscribers ซ้ำในไฟล์นี้
  ต้องดึงจาก shared.py เท่านั้น ไม่งั้นจะกลายเป็นคนละ object โดยไม่มี error
"""
from fastapi import APIRouter

from shared import *  # noqa: F401,F403

router = APIRouter()


def _offset_ok(offset: Optional[float], offset_tol: Optional[float]) -> bool:
    """offset ผ่านเกณฑ์ไหม — เทียบกับ offset_tol ของ part_number"""
    if offset is None or offset_tol is None:
        return True
    return abs(offset) <= offset_tol + _TOL_EPS


def _judge(
    value_x: float,
    value_y: float,
    offset_ghx: Optional[float],
    offset_ghy: Optional[float],
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
        ok_ghx = _offset_ok(offset_ghx, limit)
        ok_ghy = _offset_ok(offset_ghy, limit)
        ok_opx = _offset_ok(offset_opx, limit)
        ok_opy = _offset_ok(offset_opy, limit)

        # ถ้าผ่านหมดทั้ง 4 ตัวจะได้ True แต่ถ้ามีตัวใดตัวหนึ่งเป็น False จะได้ False ทันที
        ok_offset = ok_ghx and ok_ghy and ok_opx and ok_opy
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


def _get_min_position_label(tr: float, tl: float, br: float, bl: float) -> str:
    """เปรียบเทียบค่า 4 มุมและคืนชื่อตำแหน่งที่มีค่าน้อยที่สุด"""
    positions = {
        "Top Right": tr,
        "Top Left": tl,
        "Bottom Right": br,
        "Bottom Left": bl,
    }
    return min(positions, key=positions.get)


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
        return {"items": items, "total": total}
    finally:
        db.close()


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

            # ── คำนวณหาตำแหน่ง Offset ที่น้อยที่สุด (GH / OP) ─────────────────
            offset_pos_gh = _get_min_position_label(req.tr_gh, req.tl_gh, req.br_gh, req.bl_gh)
            offset_pos_op = _get_min_position_label(req.tr_op, req.tl_op, req.br_op, req.bl_op)

            # ── [FIX 1] ส่ง Parameter ให้ครบทั้ง 8 ตัว ──────────────────────────
            verdict = _judge(
                value_x=req.value_x,
                value_y=req.value_y,
                offset_ghx=req.offset_ghx,
                offset_ghy=req.offset_ghy,
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
                    " offset_ghx, offset_ghy, offset_opx, offset_opy, "
                    " offset_pos_gh, offset_pos_op, result, "
                    " measure_type, operator_id, note, client_uuid) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (
                        session_id, number_alpl, req.value_x, req.value_y,
                        req.offset_ghx, req.offset_ghy, req.offset_opx, req.offset_opy,
                        offset_pos_gh, offset_pos_op, result,
                        measure_type, operator_id, note, req.client_uuid
                    ),
                )
            except pymysql.IntegrityError:
                raise HTTPException(409, "Measurement นี้ถูกบันทึกไปแล้ว (duplicate client_uuid)")
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
                "offset_ghx":     req.offset_ghx,
                "offset_ghy":     req.offset_ghy,
                "offset_opx":     req.offset_opx,
                "offset_opy":     req.offset_opy,
                "offset_pos_gh":  offset_pos_gh,
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
            "offset_pos_gh": offset_pos_gh,
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

            # ── [FIX 2] อ่าน คอลัมน์ Offset แยกแกนแทนคอลัมน์ `offset` เดิม ────────
            cur.execute(
                "SELECT number_alpl, value_x, value_y, "
                "offset_ghx, offset_ghy, offset_opx, offset_opy, measure_type "
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
                offset_ghx=row.get("offset_ghx"),
                offset_ghy=row.get("offset_ghy"),
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