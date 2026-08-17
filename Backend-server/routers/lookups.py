"""routers/lookups.py — ตารางอ้างอิง 7 ตัว ที่ dropdown ใช้ (operator/owner/vendor/handler/template/package_size/part_number)

ย้ายมาจาก main.py แบบยกก้อน ไม่ได้แก้ตรรกะใดๆ
⚠ ห้ามประกาศ session_queues / measure_timeouts / subscribers ซ้ำในไฟล์นี้
  ต้องดึงจาก shared.py เท่านั้น ไม่งั้นจะกลายเป็นคนละ object โดยไม่มี error
"""
from fastapi import APIRouter

from shared import *  # noqa: F401,F403

router = APIRouter()


# ══════════════════════════════════════════════════════════════════════════════
# Lookup endpoints (dropdown data สำหรับ index.html / edit.html)
# ══════════════════════════════════════════════════════════════════════════════
# Dropdown ทุกตัวนี้เป็นแบบ "ปิด" (closed) — frontend เลือกได้เฉพาะค่าที่มีอยู่
# จริงใน DB เท่านั้น ไม่มีช่องพิมพ์เพิ่มค่าใหม่ในฟอร์ม ถ้าต้องเพิ่ม
# owner/vendor/handler/operator ใหม่ ต้อง insert ตรงเข้า DB เอง
# (ตามที่คุยกันไว้ — ไม่ทำ "add new" inline ในฟอร์ม)
@router.get("/api/operators")
async def list_operators():
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute("SELECT operator_id, operator_name FROM operator ORDER BY operator_name")
            return cur.fetchall()
    finally:
        db.close()

@router.get("/api/owners")
async def list_owners():
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute("SELECT owner_id, owner_name FROM owner ORDER BY owner_name")
            return cur.fetchall()
    finally:
        db.close()

@router.get("/api/vendors")
async def list_vendors():
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute("SELECT vendor_id, vendor_name FROM vendor ORDER BY vendor_name")
            return cur.fetchall()
    finally:
        db.close()

@router.get("/api/handlers")
async def list_handlers():
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute("SELECT handler_id, handler_name FROM handler ORDER BY handler_name")
            return cur.fetchall()
    finally:
        db.close()

@router.get("/api/package-sizes")
async def list_package_sizes():
    """คืนรายการ package_size ทั้งหมด พร้อม nominal/tolerance + template_name
    — ใช้เติม datalist ของช่อง Package Size ใน index.html/edit.html และเป็น
    แหล่งข้อมูลของตาราง Lookup Tables → Package Size

    nominal/tolerance ถูกเก็บไว้ 2 ที่โดยตั้งใจ (ไม่ใช่ข้อมูลซ้ำที่ลืมลบ):
      • package_size — ค่ากลางของ "ขนาด" นั้น ใช้ตอนยังไม่รู้ part_number
      • part_number  — ค่าเฉพาะของ part นั้น (part_number เดียวกันอาจมี
        tolerance ต่างกันได้แม้ package_size เดียวกัน) ดู GET /api/part-numbers
    ทั้ง 5 คอลัมน์เป็น NOT NULL ทั้งคู่ (ดู init.sql)
    """
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute(
                "SELECT ps.package_size_id, ps.package_size, "
                "       ps.nominal_x, ps.nominal_y, ps.upper_tol, ps.lower_tol, ps.offset_tol, "
                "       t.template_name "
                "FROM package_size ps "
                "LEFT JOIN template t ON ps.template_id = t.template_id "
                "ORDER BY ps.package_size"
            )
            return cur.fetchall()
    finally:
        db.close()

@router.get("/api/part-numbers")
async def list_part_numbers(package_size: str = Query(..., min_length=1)):
    """คืนรายการ part_number (จากตาราง catalog part_number ตรงๆ ไม่ใช่ derive
    จาก parts_specifications ที่เคยลงทะเบียนแล้ว) ที่ผูกกับ package_size ที่
    ระบุ — ใช้เป็น dropdown ของช่อง Part Number ที่ cascade จาก Package Size
    ในฟอร์ม Part Entry (New/Rework/IPM) เป็น dropdown "ปิด" เหมือน
    operator/vendor/handler/owner/package_size — เลือกได้เฉพาะ part_number ที่
    มีอยู่จริงในตาราง part_number เท่านั้น ไม่มีช่องพิมพ์เพิ่มค่าใหม่ (handler
    ของ part นั้นๆ ผูกมากับ part_number อยู่แล้ว ไม่ต้องให้ผู้ใช้เลือก Handler
    เองอีกที)
    """
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute(
                "SELECT pn.part_number_name FROM part_number pn "
                "JOIN package_size ps ON pn.package_size_id = ps.package_size_id "
                "WHERE ps.package_size = %s "
                "ORDER BY pn.part_number_name",
                (package_size,),
            )
            return [row["part_number_name"] for row in cur.fetchall()]
    finally:
        db.close()

@router.get("/api/templates")
async def list_templates():
    """คืนรายการ template ทั้งหมด — ใช้โดย Database Editor (edit.html) ตอน
    จัดการตาราง template (Add/Rename/Delete) และตอนสร้าง/แก้ package_size
    (เลือก template ที่จะผูกให้)
    """
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute("SELECT template_id, template_name FROM template ORDER BY template_name")
            return cur.fetchall()
    finally:
        db.close()

@router.get("/api/part-numbers/all")
async def list_all_part_numbers():
    """คืนรายการ part_number ทั้งหมดพร้อมรายละเอียดครบ (package_size/handler/
    nominal/tolerance) — ใช้โดย Database Editor (edit.html) ต่างจาก
    GET /api/part-numbers (คืนแค่ชื่อ กรองด้วย package_size — ใช้เป็น cascading
    dropdown ของฟอร์ม Part Entry)
    """
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute(
                "SELECT pn.part_number_id, pn.part_number_name, ps.package_size, "
                "h.handler_name AS handler, pn.nominal_x, pn.nominal_y, "
                "pn.upper_tol, pn.lower_tol, pn.offset_tol "
                "FROM part_number pn "
                "JOIN package_size ps ON pn.package_size_id = ps.package_size_id "
                "JOIN handler h       ON pn.handler_id = h.handler_id "
                "ORDER BY pn.part_number_name"
            )
            return cur.fetchall()
    finally:
        db.close()

# ══════════════════════════════════════════════════════════════════════════════
# Lookup table management (Database Editor — Add/Rename/Delete)
# ══════════════════════════════════════════════════════════════════════════════
# operator/owner/vendor/handler/template เป็นตารางรูปแบบเดียวกันหมด (id + ชื่อ
# ตัวเดียว) เลยใช้ helper function ชุดเดียวกัน 3 ตัวนี้ร่วมกันได้ทั้งหมด แทนที่
# จะเขียน insert/rename/delete แยกกันซ้ำๆ ทีละตาราง — ยังคง endpoint แยกกัน
# ตามตารางเหมือนเดิม (ไม่ทำ dynamic routing) เพื่อให้ URL คาดเดาได้ตรงไปตรงมา
def _create_lookup(table: str, name_col: str, name: str) -> int:
    db = get_db()
    try:
        with db.cursor() as cur:
            try:
                cur.execute(f"INSERT INTO {table} ({name_col}) VALUES (%s)", (name,))
            except pymysql.MySQLError as exc:
                raise HTTPException(409, f"เพิ่มไม่สำเร็จ (ชื่อนี้อาจมีอยู่แล้ว): {exc}")
            return cur.lastrowid
    finally:
        db.close()

def _rename_lookup(table: str, id_col: str, name_col: str, id_value: int, name: str) -> None:
    db = get_db()
    try:
        with db.cursor() as cur:
            try:
                cur.execute(f"UPDATE {table} SET {name_col} = %s WHERE {id_col} = %s", (name, id_value))
            except pymysql.MySQLError as exc:
                raise HTTPException(409, f"แก้ไขชื่อไม่สำเร็จ (ชื่อใหม่นี้อาจมีอยู่แล้ว): {exc}")
            if cur.rowcount == 0:
                raise HTTPException(404, "ไม่พบข้อมูล")
    finally:
        db.close()

def _delete_lookup(table: str, id_col: str, id_value: int, references: List[tuple],
                   kind: Optional[str] = None) -> None:
    """ลบ row ของตาราง lookup — ปฏิเสธถ้ายังมีตารางอื่นอ้างอิง id นี้อยู่จริง
    (`references` คือ list ของ (referencing_table, referencing_col)) เพื่อไม่ให้
    Part/Measurement ที่มีอยู่แล้วกลายเป็นข้อมูลกำพร้า (orphan FK) — แนะนำให้
    "เปลี่ยนชื่อ" (rename) แทนถ้ายังมีข้อมูลผูกอยู่ ไม่ใช่ลบทิ้งแล้วสร้างใหม่
    """
    db = get_db()
    try:
        with db.cursor() as cur:
            for ref_table, ref_col in references:
                cur.execute(f"SELECT 1 FROM {ref_table} WHERE {ref_col} = %s LIMIT 1", (id_value,))
                if cur.fetchone():
                    display_name = _TABLE_DISPLAY_NAME.get(ref_table, ref_table)
                    raise HTTPException(
                        409,
                        f"ลบไม่ได้ — ยังมีข้อมูลใน {display_name} ที่อ้างอิงถึงอยู่ "
                        f"กรุณาเปลี่ยนชื่อแทนถ้าต้องการแก้ไข",
                    )
            # ── สำรองก่อนลบ ── ต้องอ่านตอนแถวยังอยู่ และหลังผ่านด่านเช็ค FK แล้ว
            # (ถ้าเช็คไม่ผ่านจะ raise 409 ไปก่อน ไม่มีอะไรถูกลบ ไม่ต้องสำรอง)
            row = _fetch_one(cur, f"SELECT * FROM {table} WHERE {id_col} = %s", (id_value,))
            if row is None:
                raise HTTPException(404, "ไม่พบข้อมูล")
            _archive_before_delete(
                kind=kind or table, table=table, pk={id_col: id_value}, row=row
            )

            cur.execute(f"DELETE FROM {table} WHERE {id_col} = %s", (id_value,))
            if cur.rowcount == 0:
                raise HTTPException(404, "ไม่พบข้อมูล")
    finally:
        db.close()

@router.post("/api/operators", status_code=201)
async def create_operator(body: LookupCreate):
    return {"operator_id": _create_lookup("operator", "operator_name", body.name)}

@router.patch("/api/operators/{operator_id}")
async def rename_operator(operator_id: int, body: LookupUpdate):
    _rename_lookup("operator", "operator_id", "operator_name", operator_id, body.name)
    return {"ok": True}

@router.delete("/api/operators/{operator_id}")
async def delete_operator(operator_id: int):
    # operator ถูกอ้างอิงจาก measurements.operator_id เท่านั้น
    _delete_lookup("operator", "operator_id", operator_id, [("measurements", "operator_id")])
    return {"ok": True}

@router.post("/api/owners", status_code=201)
async def create_owner(body: LookupCreate):
    return {"owner_id": _create_lookup("owner", "owner_name", body.name)}

@router.patch("/api/owners/{owner_id}")
async def rename_owner(owner_id: int, body: LookupUpdate):
    _rename_lookup("owner", "owner_id", "owner_name", owner_id, body.name)
    return {"ok": True}

@router.delete("/api/owners/{owner_id}")
async def delete_owner(owner_id: int):
    # owner ถูกอ้างอิงจาก parts_specifications.owner_id เท่านั้น
    _delete_lookup("owner", "owner_id", owner_id, [("parts_specifications", "owner_id")])
    return {"ok": True}

@router.post("/api/vendors", status_code=201)
async def create_vendor(body: LookupCreate):
    return {"vendor_id": _create_lookup("vendor", "vendor_name", body.name)}

@router.patch("/api/vendors/{vendor_id}")
async def rename_vendor(vendor_id: int, body: LookupUpdate):
    _rename_lookup("vendor", "vendor_id", "vendor_name", vendor_id, body.name)
    return {"ok": True}

@router.delete("/api/vendors/{vendor_id}")
async def delete_vendor(vendor_id: int):
    # vendor ถูกอ้างอิงจาก parts_specifications.vendor_id เท่านั้น
    _delete_lookup("vendor", "vendor_id", vendor_id, [("parts_specifications", "vendor_id")])
    return {"ok": True}

@router.post("/api/handlers", status_code=201)
async def create_handler(body: LookupCreate):
    return {"handler_id": _create_lookup("handler", "handler_name", body.name)}

@router.patch("/api/handlers/{handler_id}")
async def rename_handler(handler_id: int, body: LookupUpdate):
    _rename_lookup("handler", "handler_id", "handler_name", handler_id, body.name)
    return {"ok": True}

@router.delete("/api/handlers/{handler_id}")
async def delete_handler(handler_id: int):
    # handler ถูกอ้างอิงจาก part_number.handler_id เท่านั้น (parts_specifications
    # ไม่มี handler_id ตรงๆ แล้ว — derive ผ่าน part_number)
    _delete_lookup("handler", "handler_id", handler_id, [("part_number", "handler_id")])
    return {"ok": True}

@router.post("/api/templates", status_code=201)
async def create_template(body: LookupCreate):
    return {"template_id": _create_lookup("template", "template_name", body.name)}

@router.patch("/api/templates/{template_id}")
async def rename_template(template_id: int, body: LookupUpdate):
    _rename_lookup("template", "template_id", "template_name", template_id, body.name)
    return {"ok": True}

@router.delete("/api/templates/{template_id}")
async def delete_template(template_id: int):
    # template ถูกอ้างอิงจาก package_size.template_id เท่านั้น
    _delete_lookup("template", "template_id", template_id, [("package_size", "template_id")])
    return {"ok": True}

@router.post("/api/package-sizes", status_code=201)
async def create_package_size(body: PackageSizeCreate):
    db = get_db()
    try:
        with db.cursor() as cur:
            template_id = _lookup_id(cur, "template", "template_id", "template_name", body.template_name)
            try:
                cur.execute(
                    "INSERT INTO package_size "
                    "(package_size, nominal_x, nominal_y, upper_tol, lower_tol, offset_tol, template_id) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    (
                        body.package_size,
                        *(getattr(body, f) for f in _PKG_NUM_FIELDS),
                        template_id,
                    ),
                )
            except pymysql.MySQLError as exc:
                raise HTTPException(409, f"เพิ่ม Package Size ไม่สำเร็จ (ชื่อนี้อาจมีอยู่แล้ว): {exc}")
            return {"package_size_id": cur.lastrowid}
    finally:
        db.close()

@router.patch("/api/package-sizes/{package_size_id}")
async def update_package_size(package_size_id: int, body: PackageSizeUpdate):
    db = get_db()
    try:
        with db.cursor() as cur:
            set_parts, values = [], []
            if body.package_size is not None:
                set_parts.append("package_size = %s")
                values.append(body.package_size)
            for f in _PKG_NUM_FIELDS:
                v = getattr(body, f)
                if v is not None:
                    set_parts.append(f"{f} = %s")
                    values.append(v)
            if body.template_name is not None:
                template_id = _lookup_id(cur, "template", "template_id", "template_name", body.template_name)
                set_parts.append("template_id = %s")
                values.append(template_id)
            if not set_parts:
                raise HTTPException(400, "No valid fields provided")
            try:
                cur.execute(
                    f"UPDATE package_size SET {', '.join(set_parts)} WHERE package_size_id = %s",
                    (*values, package_size_id),
                )
            except pymysql.MySQLError as exc:
                raise HTTPException(409, f"แก้ไข Package Size ไม่สำเร็จ (ชื่อใหม่นี้อาจมีอยู่แล้ว): {exc}")
            if cur.rowcount == 0:
                raise HTTPException(404, "Package Size not found")
        return {"ok": True}
    finally:
        db.close()

@router.delete("/api/package-sizes/{package_size_id}")
async def delete_package_size(package_size_id: int):
    # package_size ถูกอ้างอิงจาก part_number.package_size_id เท่านั้น
    _delete_lookup("package_size", "package_size_id", package_size_id, [("part_number", "package_size_id")])
    return {"ok": True}

@router.post("/api/part-numbers", status_code=201)
async def create_part_number(body: PartNumberCreate):
    db = get_db()
    try:
        with db.cursor() as cur:
            package_size_id = _lookup_id(cur, "package_size", "package_size_id", "package_size", body.package_size)
            handler_id      = _lookup_id(cur, "handler",      "handler_id",      "handler_name",  body.handler)
            if package_size_id is None or handler_id is None:
                raise HTTPException(400, "ต้องระบุ package_size และ handler ที่มีอยู่จริงในระบบ")
            try:
                cur.execute(
                    "INSERT INTO part_number "
                    "(part_number_name, package_size_id, handler_id, nominal_x, nominal_y, "
                    " upper_tol, lower_tol, offset_tol) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                    (
                        body.part_number_name, package_size_id, handler_id,
                        body.nominal_x, body.nominal_y, body.upper_tol, body.lower_tol,
                        body.offset_tol,
                    ),
                )
            except pymysql.MySQLError as exc:
                raise HTTPException(409, f"เพิ่ม Part Number ไม่สำเร็จ (ชื่อนี้อาจมีอยู่แล้ว): {exc}")
            return {"part_number_id": cur.lastrowid}
    finally:
        db.close()

@router.patch("/api/part-numbers/{part_number_id}")
async def update_part_number(part_number_id: int, body: PartNumberUpdate):
    db = get_db()
    try:
        with db.cursor() as cur:
            set_parts, values = [], []
            if body.part_number_name is not None:
                set_parts.append("part_number_name = %s")
                values.append(body.part_number_name)
            if body.package_size is not None:
                package_size_id = _lookup_id(cur, "package_size", "package_size_id", "package_size", body.package_size)
                set_parts.append("package_size_id = %s")
                values.append(package_size_id)
            if body.handler is not None:
                handler_id = _lookup_id(cur, "handler", "handler_id", "handler_name", body.handler)
                set_parts.append("handler_id = %s")
                values.append(handler_id)
            for field_name in ("nominal_x", "nominal_y", "upper_tol", "lower_tol", "offset_tol"):
                value = getattr(body, field_name)
                if value is not None:
                    set_parts.append(f"{field_name} = %s")
                    values.append(value)
            if not set_parts:
                raise HTTPException(400, "No valid fields provided")
            try:
                cur.execute(
                    f"UPDATE part_number SET {', '.join(set_parts)} WHERE part_number_id = %s",
                    (*values, part_number_id),
                )
            except pymysql.MySQLError as exc:
                raise HTTPException(409, f"แก้ไข Part Number ไม่สำเร็จ (ชื่อใหม่นี้อาจมีอยู่แล้ว): {exc}")
            if cur.rowcount == 0:
                raise HTTPException(404, "Part Number not found")
        return {"ok": True}
    finally:
        db.close()

@router.delete("/api/part-numbers/{part_number_id}")
async def delete_part_number(part_number_id: int):
    # part_number ถูกอ้างอิงจาก parts_specifications.part_number_id เท่านั้น
    _delete_lookup("part_number", "part_number_id", part_number_id, [("parts_specifications", "part_number_id")])
    return {"ok": True}
