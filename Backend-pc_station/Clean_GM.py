def clean_tools(tools):
                """คัดกรองเอาเฉพาะข้อมูลที่สถานะ (index 1) ไม่เป็น 0 และ 3"""
                if not tools:
                    return []
                return [item for item in tools if str(item[0]) != ("-9999.999")]

data = [
    (-9999.999,1,1,1,1)
]

cleaned_data = clean_tools(data)
print(cleaned_data)