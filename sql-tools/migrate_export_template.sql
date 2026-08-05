-- ============================================================================
-- Migration: เพิ่มคอลัมน์ kind / layout_json ให้ตาราง export_template
-- ============================================================================
-- ใช้เมื่อไหร่: ฐานข้อมูลถูกสร้างไว้ก่อนที่จะมีหน้า Export PDF/Excel จึงยังไม่มี
--   2 คอลัมน์นี้ ทำให้ backend ยิง SQL แล้วเจอ
--   ERROR 1054 "Unknown column 'kind' in 'field list'"
--   อาการที่เห็นหน้าเว็บ: บันทึกเทมเพลตรายงานไม่ได้ และรายการ Template ของหน้า
--   CSV ขึ้นว่างเปล่า (เพราะ SELECT ... WHERE kind=%s ก็พังไปด้วย)
--
-- วิธีรัน (PowerShell บนเครื่องที่รัน MySQL ผ่าน Docker):
--   Get-Content .\sql-tools\migrate_export_template.sql | docker exec -i <ชื่อ container> mysql -uroot -p<รหัส> tmx_db
-- หรือถ้า MySQL รันบนเครื่องโดยตรง:
--   mysql -uroot -p tmx_db < sql-tools/migrate_export_template.sql
--
-- ⚠ ห้ามย้ายไฟล์นี้กลับเข้า mysql-init/ — โฟลเดอร์นั้นถูก mount เป็น
--   docker-entrypoint-initdb.d ซึ่ง MySQL จะรันไฟล์ .sql ทุกไฟล์ในนั้นเรียงตาม
--   ตัวอักษรตอน container เกิดใหม่ ถ้าสคริปต์ตัวไหน error ตัวถัดไปจะไม่ถูกรันเลย
--
-- รันซ้ำได้ไม่พัง — เช็ค information_schema ก่อนทุกครั้งว่ามีคอลัมน์อยู่แล้วไหม
-- (MySQL 8 ไม่รองรับ ALTER TABLE ... ADD COLUMN IF NOT EXISTS จึงต้องเช็คเอง)
--
-- หมายเหตุเรื่อง encoding: ทุก statement ในไฟล์นี้เป็น ASCII ล้วน (ภาษาไทยอยู่แค่
--   ในคอมเมนต์) จึง pipe ผ่าน PowerShell ได้ปลอดภัย — ถ้าอยากให้คอมเมนต์ไทยไม่
--   เพี้ยนด้วย ใช้ docker cp แทน:
--     docker cp .\sql-tools\migrate_export_template.sql tm-x_project-mysql-1:/tmp/s.sql
--     docker exec tm-x_project-mysql-1 sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" tmx_db < /tmp/s.sql'
-- ============================================================================

USE tmx_db;

-- ── 1) เพิ่มคอลัมน์ kind ──────────────────────────────────────────────────
SET @sql = (
  SELECT IF(COUNT(*) = 0,
    "ALTER TABLE export_template ADD COLUMN kind VARCHAR(10) NOT NULL DEFAULT 'csv' AFTER name",
    "SELECT 'kind: already exists, skipped' AS note")
  FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'export_template' AND COLUMN_NAME = 'kind'
);
PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;

-- ── 2) เพิ่มคอลัมน์ layout_json ───────────────────────────────────────────
SET @sql = (
  SELECT IF(COUNT(*) = 0,
    "ALTER TABLE export_template ADD COLUMN layout_json JSON NULL AFTER columns_json",
    "SELECT 'layout_json: already exists, skipped' AS note")
  FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'export_template' AND COLUMN_NAME = 'layout_json'
);
PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;

-- ── 3) columns_json ต้องยอมให้ว่างได้ ─────────────────────────────────────
-- เทมเพลตชนิด 'report' ใช้ layout_json แทน ไม่มี columns_json
-- (ของเดิมประกาศเป็น NOT NULL ตอนที่ยังมีแต่ CSV)
ALTER TABLE export_template MODIFY COLUMN columns_json JSON NULL;

-- ── 4) แถวเก่าที่ยังไม่มีค่า kind ให้ถือเป็น csv ──────────────────────────
UPDATE export_template SET kind = 'csv' WHERE kind IS NULL OR kind = '';

-- ── 5) เอาเทมเพลตตั้งต้นของ CSV กลับมา ────────────────────────────────────
-- INSERT IGNORE + UPDATE คู่กัน เพื่อให้ได้ผลเหมือนกันทั้งกรณีที่แถวหายไปแล้ว
-- และกรณีที่แถวยังอยู่แต่ค่าใน columns_json ล้าสมัย
INSERT IGNORE INTO export_template (name, kind, columns_json, is_default) VALUES
  ('Default - All Column', 'csv',
   '["number_alpl","value_x","value_y","result","note","operator","measure_type","timestamp","part_number","handler","package_size","template_name","nominal_x","nominal_y","upper_tol","lower_tol","vendor","owner","po_number","description","recieve_date"]',
   1);

UPDATE export_template
   SET kind = 'csv',
       is_default = 1,
       columns_json = '["number_alpl","value_x","value_y","result","note","operator","measure_type","timestamp","part_number","handler","package_size","template_name","nominal_x","nominal_y","upper_tol","lower_tol","vendor","owner","po_number","description","recieve_date"]'
 WHERE name = 'Default - All Column';

-- ── ตรวจผล ────────────────────────────────────────────────────────────────
SELECT export_template_id, name, kind, is_default,
       JSON_LENGTH(columns_json) AS n_columns,
       (layout_json IS NOT NULL)  AS has_layout
  FROM export_template
 ORDER BY kind, is_default DESC, name;
