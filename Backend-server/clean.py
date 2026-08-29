def remove_dummy_values(data_string, target="-9999.999"):
    # Split ข้อความตามเครื่องหมาย comma แล้วกรองเอาค่าที่ไม่ใช่ target ออก
    items = [item.strip() for item in data_string.split(",")]
    filtered_items = [item for item in items if item != target]

    # นำข้อมูลที่กรองแล้วมารวมกลับเป็น String ด้วย comma
    return ",".join(filtered_items)


# การทดลองใช้งาน
text_input = "+0007.108,+0007.087,+0005.758,,-9999.999,+0005.658,+0005.545,,-9999.999,+0005.670,+0000.079,+0000.079,-9999.999"
result = remove_dummy_values(text_input)

print(result)
# Output: +0007.108,+0007.087,+0005.758,+0005.658,+0005.545,+0005.670,+0000.079,+0000.079