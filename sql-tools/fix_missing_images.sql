-- ============================================================================
-- ล้าง image_path ของแถวที่ "ไฟล์รูปหายไปจากดิสก์แล้ว"
-- ============================================================================
-- ⚠ ห้ามย้ายไฟล์นี้เข้า mysql-init/ — โฟลเดอร์นั้น mount เป็น
--   docker-entrypoint-initdb.d ซึ่งรันไฟล์ .sql ทุกไฟล์ตอน container เกิดใหม่
--   ถ้าไฟล์ไหน error ไฟล์ถัดไปจะไม่ถูกรันเลย
--
-- ปัญหาที่แก้: measurements.image_path เก็บ "path สัมพัทธ์" เท่านั้น
--   (เช่น "30-07-2569/402_30-07-2569.jpg") ส่วนโฟลเดอร์แม่มาจาก ALPL_IMAGE_DIR
--   ใน .env — DB ไม่มีทางรู้ว่าไฟล์จริงยังอยู่ไหม พอไฟล์ถูกลบ/เขียนทับ/ย้าย
--   แถวนั้นจะยังมีค่า image_path ค้างอยู่ แล้วหน้าเว็บจะขึ้น "รูปแตก"
--   (แสดง alt text) แทนที่จะขึ้นข้อความ "No image" อย่างสุภาพ
--
--   เพราะโค้ดหน้าเว็บเช็คแค่ `if (m.image_path)` ไม่ได้เช็คว่าไฟล์มีจริงไหม
--   ตั้งเป็น NULL จึงทำให้มันกลับไปแสดง placeholder ได้ถูกต้อง
--
-- วิธีรัน (PowerShell) — แนะนำ docker cp เพราะคัดลอกแบบไบต์ต่อไบต์
--   คอมเมนต์ภาษาไทยจึงไม่เพี้ยน:
--     docker cp .\sql-tools\fix_missing_images.sql tm-x_project-mysql-1:/tmp/s.sql
--     docker exec tm-x_project-mysql-1 sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" tmx_db < /tmp/s.sql'
--
--   วิธี pipe ก็ใช้ได้ (ทุก statement เป็น ASCII แล้ว ไทยอยู่แค่ในคอมเมนต์):
--     Get-Content .\sql-tools\fix_missing_images.sql | docker exec -i tm-x_project-mysql-1 sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" tmx_db'
--
-- รันซ้ำได้ไม่พัง (แถวที่เป็น NULL อยู่แล้วจะไม่ถูกแตะอีก)
-- ============================================================================

USE tmx_db;

-- ── ขั้นที่ 1: ดูก่อนว่ามีแถวไหนอ้างถึงไฟล์รูปบ้าง ────────────────────────
-- เอาผลตรงนี้ไปเทียบกับไฟล์จริงบนดิสก์ก่อนตัดสินใจลบ:
--
--   Get-ChildItem "D:\All Work\TM-X_Project\image_ALPL" -Recurse -Filter *.jpg |
--     ForEach-Object { $_.Directory.Name + "/" + $_.Name }
--
-- แถวไหนอยู่ในผล SQL แต่ไม่อยู่ในลิสต์ไฟล์ = รูปหายแล้ว ให้เอา id ไปใส่ขั้นที่ 2
SELECT measurement_id,
       number_alpl,
       image_path,
       DATE(timestamp) AS measured_on
  FROM measurements
 WHERE image_path IS NOT NULL
 ORDER BY measurement_id;

-- ── ขั้นที่ 2: ล้างเฉพาะแถวที่รูปหายจริง ─────────────────────────────────
-- ⚠ แก้เลข id ในวงเล็บให้ตรงกับที่ตรวจได้จากขั้นที่ 1 ก่อนรัน
--   ค่าเริ่มต้นใส่ id = 10 ไว้ (แถวที่ยืนยันแล้วว่าไฟล์หาย)
--   ถ้าเจอหลายแถวใส่คั่นด้วยคอมมาได้เลย เช่น (1, 2, 3, 10)
--
-- ทำไมไม่ลบทั้งแถว: ค่า value_x/value_y/result ยังเป็นข้อมูลการวัดที่ใช้ได้อยู่
--   หายไปแค่รูปเท่านั้น ลบทั้งแถวจะทำให้สถิติ OK/NG เพี้ยนโดยไม่จำเป็น
SET @ids = '10';

UPDATE measurements
   SET image_path = NULL,
       image_upload_failed = 0
 WHERE image_path IS NOT NULL
   AND FIND_IN_SET(measurement_id, @ids) > 0;

SELECT ROW_COUNT() AS rows_cleared;

-- ── ขั้นที่ 3: ตรวจผล ────────────────────────────────────────────────────
SELECT COUNT(*) AS still_have_image_path
  FROM measurements
 WHERE image_path IS NOT NULL;

SELECT measurement_id, number_alpl, image_path
  FROM measurements
 WHERE image_path IS NOT NULL
 ORDER BY measurement_id;
