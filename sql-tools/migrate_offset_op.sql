-- ย้าย measurements จากคอลัมน์ `offset` ตัวเดียว → offset_opx / offset_opy / offset_pos_op
--
-- ทำไม: schema เดิมเก็บความเยื้องเป็นตัวเลขตัวเดียว (`offset`) ต่อมาแยกเป็น 2 แกน
-- พร้อมเก็บ "มุมที่แคบที่สุด" ที่ backend คำนวณจากค่า 4 มุมที่ Agent ส่งมา
-- (`_get_min_position_label`) — `init.sql` อัปเดตตามแล้ว แต่ DB ที่สร้างไว้ก่อนหน้า
-- ไม่ได้ตามไปด้วย
--
-- ⚠⚠ ทำไมแก้ init.sql อย่างเดียวไม่พอ
--   `mysql-init/` ถูก mount เป็น docker-entrypoint-initdb.d ซึ่ง MySQL รันให้
--   **เฉพาะตอน data directory ยังว่างเปล่า** (container เกิดใหม่ครั้งแรก) เท่านั้น
--   volume ที่มีข้อมูลอยู่แล้วจะข้ามไฟล์ในนั้นทั้งหมด
--
--   อาการถ้าไม่รันไฟล์นี้: `POST /api/measurements` ตอบ **500 Internal Server Error**
--   ทุกชิ้น เพราะ INSERT อ้าง `offset_opx` ที่ไม่มีอยู่จริง → MySQL error 1054
--   ซึ่งเป็น `OperationalError` **ไม่ใช่ `IntegrityError`** จึงหลุด except ที่ดักไว้
--   ออกไปเป็น 500 ดิบ · เห็นแค่ "Internal Server Error" ไล่ต้นตอไม่ได้เลย
--
-- ⚠ ไฟล์นี้ต้อง "รันเองด้วยมือ" เท่านั้น ห้ามย้ายไปไว้ใน mysql-init/ เด็ดขาด
--   (ดู CLAUDE.md — ไฟล์ที่ error จะทำให้ init.sql/insert.sql ถัดไปไม่ถูกรัน)
--
-- ⚠ ข้อมูลเก่า: ค่า `offset` เดิมถูกคัดลอกไปไว้ที่ `offset_opx` แบบ best-effort
--   ส่วน `offset_opy` เป็น 0 และ `offset_pos_op` เป็น '-' เพื่อบอกว่า
--   **"แถวนี้มาจาก schema เก่า ไม่เคยมีข้อมูลมุม"** ไม่ใช่ค่าที่วัดได้จริง
--   ห้ามเอาไปคิดสถิติปนกับแถวใหม่
--
-- วิธีรัน (dev ผ่าน Docker):
--   Get-Content -Raw -Encoding utf8 sql-tools\migrate_offset_op.sql |
--     docker exec -i tm-x_project-mysql-1 mysql -u root -prootpassword --default-character-set=utf8mb4 tmx_db
--
-- วิธีรัน (หน้างาน — MySQL ลงเครื่องตรง):
--   mysql -u root -p tmx_db < sql-tools\migrate_offset_op.sql

-- ห่อด้วย procedure เพราะ MySQL 8.0 ไม่มี ADD/DROP COLUMN IF EXISTS
-- (MariaDB มี แต่โปรเจกต์นี้ใช้ MySQL) — สคริปต์ migration มักถูกรันซ้ำโดยไม่
-- ตั้งใจตอนไล่ปัญหาหน้างาน จึงต้องรันซ้ำแล้วไม่พัง
DROP PROCEDURE IF EXISTS _tmx_migrate_offset_op;
DELIMITER //
CREATE PROCEDURE _tmx_migrate_offset_op()
BEGIN
  DECLARE has_old INT DEFAULT 0;

  SELECT COUNT(*) INTO has_old FROM information_schema.COLUMNS
   WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'measurements'
     AND COLUMN_NAME = 'offset';

  -- ── 1) เพิ่มคอลัมน์ใหม่ ────────────────────────────────────────────────
  -- ADD COLUMN ... NOT NULL กับตารางที่มีข้อมูลอยู่แล้ว MySQL เติม implicit
  -- default ให้เอง (0 / '') แล้วเราค่อย UPDATE ทับในขั้นที่ 2
  IF NOT EXISTS (SELECT 1 FROM information_schema.COLUMNS
                 WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'measurements'
                   AND COLUMN_NAME = 'offset_opx') THEN
    ALTER TABLE measurements ADD COLUMN offset_opx FLOAT NOT NULL AFTER value_y;
  END IF;

  IF NOT EXISTS (SELECT 1 FROM information_schema.COLUMNS
                 WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'measurements'
                   AND COLUMN_NAME = 'offset_opy') THEN
    ALTER TABLE measurements ADD COLUMN offset_opy FLOAT NOT NULL AFTER offset_opx;
  END IF;

  IF NOT EXISTS (SELECT 1 FROM information_schema.COLUMNS
                 WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'measurements'
                   AND COLUMN_NAME = 'offset_pos_op') THEN
    ALTER TABLE measurements ADD COLUMN offset_pos_op VARCHAR(20) NOT NULL AFTER offset_opy;
  END IF;

  -- ── 2) ย้ายข้อมูลเก่า แล้วค่อยลบคอลัมน์เดิม ─────────────────────────────
  -- ต้องทำ "ก่อน" DROP เสมอ ไม่งั้นค่าเดิมหายโดยไม่มีทางกู้
  IF has_old = 1 THEN
    UPDATE measurements
       SET offset_opx    = `offset`,
           offset_opy    = 0,
           offset_pos_op = '-';       -- '-' = ไม่เคยมีข้อมูลมุม (แถวจาก schema เก่า)
    ALTER TABLE measurements DROP COLUMN `offset`;
  END IF;
END//
DELIMITER ;

CALL _tmx_migrate_offset_op();
DROP PROCEDURE _tmx_migrate_offset_op;

-- ── ตรวจผล ──────────────────────────────────────────────────────────────
-- ต้องเห็น offset_opx / offset_opy / offset_pos_op และ **ไม่เห็น** offset
SELECT COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE
FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'measurements'
ORDER BY ORDINAL_POSITION;
