"""เทสต์ edit_image.process_and_save_image() กับภาพจริง 1 ใบ

รัน:  cd Backend-server && python Test_ctop_image.py

⚠⚠ `process_and_save_image` **เขียนทับไฟล์ต้นฉบับ** (`cv2.imwrite(image_path, canvas)`
   ที่ท้ายฟังก์ชัน) สคริปต์นี้จึงก๊อปไฟล์ไปไว้ที่ `<ชื่อเดิม>_test.jpg` ก่อนเสมอ
   แล้วค่อยสั่งประมวลผลกับสำเนา — ภาพดิบจะได้ไม่หายไปตอนลองปรับ CROP_SIZE ซ้ำ ๆ
   (ถ้ารันกับไฟล์ต้นฉบับตรง ๆ ครั้งเดียว ภาพดิบหายถาวร เอาคืนไม่ได้)
"""
import os
import shutil

import edit_image

# ⚠ ต้องมี `r` นำหน้า — ไม่งั้น `\56` ถูกตีความเป็น **escape เลขฐานแปด**
#   `"...Backend-server\56_149.jpg"` → `"...Backend-server._149.jpg"` (`\56` = '.')
#   แล้วจะได้ FileNotFoundError ที่ชี้ไปพาธที่ไม่มีอยู่จริงโดยไม่รู้สาเหตุ
SRC = r"D:\All Work\TM-X React\Backend-server\56_149_b2b2f850f6df16d7.jpg"

# ค่าการวัด 8 ตัว เรียงตามที่ `process_and_save_image` แกะออก (บรรทัด ~396):
#   value_x, value_y,
#   horizon_left, horizon_right,
#   vertical_bottom, vertical_top,     ← ⚠ bottom มาก่อน top ตามลำดับใน pair
#   offset_opx, offset_opy
#
# ใส่ 0.0 ทั้งหมดเพื่อดูว่า **การ crop กับการวาดเส้น** ถูกไหม — ตารางด้านขวา
# จะโชว์ 0.000 ทั้ง 8 แถว ซึ่งไม่เกี่ยวกับสิ่งที่กำลังเทสต์
pair = (0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

if __name__ == "__main__":
    if not os.path.exists(SRC):
        raise SystemExit(f"ไม่พบไฟล์: {SRC}")

    base, ext = os.path.splitext(SRC)
    dst = f"{base}_test{ext}"
    shutil.copyfile(SRC, dst)          # ทำงานกับสำเนา ต้นฉบับไม่ถูกแตะ
    print(f"ต้นฉบับ  : {SRC}")
    print(f"ผลลัพธ์  : {dst}")

    edit_image.process_and_save_image(dst, pair)
    print("✅ เสร็จแล้ว — เปิดไฟล์ผลลัพธ์ดูได้เลย")
