-- ย้าย UNIQUE ของ export_template จาก (name) → (name, kind)
--
-- ทำไม: ชื่อเทมเพลตเดิมห้ามซ้ำ "ทั้งตาราง" ซึ่งเป็นของตกค้างจากตอนที่ระบบมีแต่
-- CSV อย่างเดียว พอแยกเป็น csv/pdf/excel แล้ว หน้าเว็บแสดงเป็น 3 ลิสต์ที่ไม่
-- เกี่ยวกัน แต่ตั้งชื่อ "Default" ซ้ำข้ามชนิดไม่ได้ — ผู้ใช้ไม่มีทางรู้ว่าชนกับอะไร
-- (MySQL ตอบ 1062 Duplicate entry ซึ่งเด้งขึ้นหน้าจอดิบ ๆ)
--
-- ⚠ ไฟล์นี้ต้อง "รันเองด้วยมือ" เท่านั้น ห้ามย้ายไปไว้ใน mysql-init/ เด็ดขาด
--   (โฟลเดอร์นั้นถูก mount เป็น docker-entrypoint-initdb.d — MySQL รันทุกไฟล์
--    .sql ในนั้นเรียงตามตัวอักษรตอน container เกิดใหม่ · ดู CLAUDE.md)
--   DB ที่สร้างใหม่ได้ผังนี้จาก init.sql อยู่แล้ว ไม่ต้องรันไฟล์นี้ซ้ำ
--
-- วิธีรัน (dev ผ่าน Docker):
--   Get-Content -Raw -Encoding utf8 sql-tools\fix_export_template_unique.sql |
--     docker exec -i tm-x_project-mysql-1 mysql -u root -prootpassword --default-character-set=utf8mb4 tmx_db
--
-- ข้อมูลเดิมไม่กระทบ — ชื่อที่มีอยู่ตอนนี้ไม่ซ้ำกันอยู่แล้ว การ "ผ่อนกฎ" ให้
-- หลวมลงจึงไม่มีทางทำให้แถวเดิมผิดกติกา

-- ── 1) ถอด UNIQUE เดิมที่อยู่บน name ตัวเดียว ────────────────────────────
-- MySQL ตั้งชื่อ index ที่มาจาก `name ... UNIQUE` ว่า `name` โดยอัตโนมัติ
-- ห่อด้วย procedure เพราะ MySQL ไม่มี DROP INDEX IF EXISTS — รันซ้ำแล้วต้องไม่พัง
DROP PROCEDURE IF EXISTS _tmx_fix_tpl_unique;
DELIMITER //
CREATE PROCEDURE _tmx_fix_tpl_unique()
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.STATISTICS
             WHERE TABLE_SCHEMA = DATABASE()
               AND TABLE_NAME   = 'export_template'
               AND INDEX_NAME   = 'name') THEN
    ALTER TABLE export_template DROP INDEX `name`;
  END IF;

  IF NOT EXISTS (SELECT 1 FROM information_schema.STATISTICS
                 WHERE TABLE_SCHEMA = DATABASE()
                   AND TABLE_NAME   = 'export_template'
                   AND INDEX_NAME   = 'uq_tpl_name_kind') THEN
    ALTER TABLE export_template ADD UNIQUE KEY uq_tpl_name_kind (name, kind);
  END IF;
END//
DELIMITER ;

CALL _tmx_fix_tpl_unique();
DROP PROCEDURE _tmx_fix_tpl_unique;

-- ── 2) ตรวจผล ───────────────────────────────────────────────────────────
SELECT INDEX_NAME, GROUP_CONCAT(COLUMN_NAME ORDER BY SEQ_IN_INDEX) AS cols, NON_UNIQUE
FROM information_schema.STATISTICS
WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'export_template'
GROUP BY INDEX_NAME, NON_UNIQUE;
