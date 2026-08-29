def _parse_measurement_line(line: str):
    items = [item.strip() for item in line.split(",")]

    # แก้ไข: เทียบเป็น String หรือ แปลงเป็น float เพื่อเปรียบเทียบ
    filtered_items = [item for item in items if item != "-9999.999"]

    if len(filtered_items) < 8:
        return None

    try:
        value_x = float(filtered_items[0])
        value_y = float(filtered_items[1])
        tr_op = float(filtered_items[2])
        tl_op = float(filtered_items[3])
        bl_op = float(filtered_items[4])
        br_op = float(filtered_items[5])
        offset_opx = float(filtered_items[6])
        offset_opy = float(filtered_items[7])
    except ValueError:
        return None

    return (
        value_x,
        value_y,
        tr_op,
        tl_op,
        bl_op,
        br_op,
        offset_opx,
        offset_opy,
    )


FIELDS = [
    "value_x",
    "value_y",
    "tr_op",
    "tl_op",
    "bl_op",
    "br_op",
    "offset_opx",
    "offset_opy",
]

# แก้ไขจุดทศนิยมผิดในตัวอย่างกรณีทดสอบ
CASES = [
    (
        "ค่าปกติ (จากล็อกจริง)",
        "+0007.108,+0007.087,+0005.758,+0005.658,+0005.545,+0005.670,+0000.079,+0000.079,-9999.999,-9999.999",
    ),
]

for title, raw in CASES:
    print("─" * 72)
    print(f"{title}")
    print(f"   input : {raw!r}")
    result = _parse_measurement_line(raw)
    if result is None:
        print("   ผลลัพธ์: None  ← โค้ดจริงจะข้ามบรรทัดนี้")
        continue
    print("   ผลลัพธ์:")
    for name, val in zip(FIELDS, result):
        print(f"     {name:<11} = {val}")