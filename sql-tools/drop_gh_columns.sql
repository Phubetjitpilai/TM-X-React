-- ถอดคอลัมน์ฝั่ง GH ออกจากตาราง measurements
--   offset_ghx · offset_ghy · offset_pos_gh
--
-- ทำไม: เลิกใช้เครื่องมือฝั่ง GH แล้ว โปรแกรมวัดของ TM-X คืน -9999.999 มาทุกครั้ง
-- จึงถอดออกจาก `MeasurementCreate` (shared.py) และจาก INSERT ใน measurements.py
-- ไปแล้ว — แต่คอลัมน์ในตารางยังเป็น NOT NULL อยู่
--
-- ⚠⚠ ทำไมแก้ init.sql อย่างเดียวไม่พอ
--   `mysql-init/` ถูก mount เป็น docker-entrypoint-initdb.d ซึ่ง MySQL รันให้
--   **เฉพาะตอน data directory ยังว่างเปล่า** (container เกิดใหม่ครั้งแรก) เท่านั้น
--   ถ้า volume มีข้อมูลอยู่แล้ว ไฟล์ในนั้นถูกข้ามทั้งหมด · ส่วนเครื่อง PC หน้างาน
--   ยิ่งชัด เพราะ MySQL เป็น Windows Service ที่ import init.sql ไปครั้งเดียว
--   ตอนติดตั้ง การแก้ไฟล์วันนี้จึงไม่มีผลกับ DB ที่รันอยู่เลย
--
--   ผลถ้าไม่รันไฟล์นี้: INSERT ที่ไม่ส่ง 3 คอลัมน์นี้จะโดน
--     ERROR 1364 (HY000): Field 'offset_ghx' doesn't have a default value
--   = **บันทึกผลการวัดไม่ได้เลยทุกชิ้น**
--
-- ⚠ ไฟล์นี้ต้อง "รันเองด้วยมือ" เท่านั้น ห้ามย้ายไปไว้ใน mysql-init/ เด็ดขาด
--   (ดู CLAUDE.md — ไฟล์ที่ error จะทำให้ init.sql/insert.sql ถัดไปไม่ถูกรัน)
--   DB ที่สร้างใหม่ได้ผังที่ถูกต้องจาก init.sql อยู่แล้ว ไม่ต้องรันไฟล์นี้
--
-- ⚠ ข้อมูลเก่าหาย: ค่าที่เคยบันทึกไว้ใน 3 คอลัมน์นี้จะถูกลบไปพร้อมกัน
--   ถ้ายังอยากเก็บไว้อ้างอิง ให้สำรองก่อน:
--     CREATE TABLE _backup_gh AS
--       SELECT measurement_id, offset_ghx, offset_ghy, offset_pos_gh FROM measurements;
--
-- วิธีรัน (dev ผ่าน Docker):
--   Get-Content -Raw -Encoding utf8 sql-tools\drop_gh_columns.sql |
--     docker exec -i tm-x_project-mysql-1 mysql -u root -prootpassword --default-character-set=utf8mb4 tmx_db
--
-- วิธีรัน (หน้างาน — MySQL ลงเครื่องตรง):
--   mysql -u root -p tmx_db < sql-tools\drop_gh_columns.sql

-- ── ถอดทีละคอลัมน์ ──────────────────────────────────────────────────────
-- ห่อด้วย procedure เพราะ MySQL 8.0 **ไม่มี** DROP COLUMN IF EXISTS
-- (MariaDB มี แต่โปรเจกต์นี้ใช้ MySQL) — รันซ้ำแล้วต้องไม่พัง เพราะสคริปต์
-- migration มักถูกรันซ้ำโดยไม่ได้ตั้งใจตอนไล่ปัญหาหน้างาน
DROP PROCEDURE IF EXISTS _tmx_drop_gh;
DELIMITER //
CREATE PROCEDURE _tmx_drop_gh()
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE()
               AND TABLE_NAME   = 'measurements'
               AND COLUMN_NAME  = 'offset_ghx') THEN
    ALTER TABLE measurements DROP COLUMN offset_ghx;
  END IF;

  IF EXISTS (SELECT 1 FROM information_schema.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE()
               AND TABLE_NAME   = 'measurements'
               AND COLUMN_NAME  = 'offset_ghy') THEN
    ALTER TABLE measurements DROP COLUMN offset_ghy;
  END IF;

  IF EXISTS (SELECT 1 FROM information_schema.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE()
               AND TABLE_NAME   = 'measurements'
               AND COLUMN_NAME  = 'offset_pos_gh') THEN
    ALTER TABLE measurements DROP COLUMN offset_pos_gh;
  END IF;
END//
DELIMITER ;

CALL _tmx_drop_gh();
DROP PROCEDURE _tmx_drop_gh;

-- ── ตรวจผล ──────────────────────────────────────────────────────────────
-- ต้องไม่เหลือแถวไหนที่ COLUMN_NAME ขึ้นต้นด้วย offset_gh / offset_pos_gh
SELECT COLUMN_NAME, IS_NULLABLE, COLUMN_TYPE
FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA = DATABASE()
  AND TABLE_NAME   = 'measurements'
  AND COLUMN_NAME LIKE '%gh%';
