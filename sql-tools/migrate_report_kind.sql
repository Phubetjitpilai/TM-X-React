-- ============================================================================
-- Migration: แยกเทมเพลตรายงาน kind='report' ออกเป็น 'pdf' / 'excel'
-- ============================================================================
-- ⚠ ห้ามย้ายไฟล์นี้เข้า mysql-init/ — โฟลเดอร์นั้นถูก mount เป็น
--   docker-entrypoint-initdb.d ซึ่งรันไฟล์ .sql ทุกไฟล์ตอน container เกิดใหม่
--   ถ้าไฟล์ไหน error ไฟล์ถัดไปจะไม่ถูกรันเลย
--
-- ใช้เมื่อไหร่: ตอนแรก PDF กับ Excel ใช้ kind='report' ร่วมกัน เทมเพลตจึงโผล่
--   ทั้งสองหน้าและปนกัน ตอนนี้แยกเป็น 'pdf' กับ 'excel' แล้ว แต่ของเก่าที่
--   บันทึกไว้ยังเป็น 'report' อยู่ — โค้ดยังแสดงให้เห็นในทั้งสองหน้าเพื่อไม่ให้
--   หาย แต่พอเปิดแก้จากหน้าไหน มันจะกลายเป็น kind ของหน้านั้นแล้วหายจากอีกหน้า
--   ทันทีโดยไม่มีอะไรบอก สคริปต์นี้ตัดความกำกวมทิ้งด้วยการปักให้เป็น 'pdf'
--
-- วิธีรัน:
--   Get-Content .\sql-tools\migrate_report_kind.sql | docker exec -i <container> mysql -uroot -p<รหัส> tmx_db
--
-- รันซ้ำได้ไม่พัง (รอบสองจะไม่เจอแถว kind='report' เหลือแล้ว)
--
-- หมายเหตุเรื่อง encoding: ทุก statement ในไฟล์นี้เป็น ASCII ล้วน (ภาษาไทยอยู่แค่
--   ในคอมเมนต์) จึง pipe ผ่าน PowerShell ได้ปลอดภัย — ถ้าอยากให้คอมเมนต์ไทยไม่
--   เพี้ยนด้วย ใช้ docker cp แทน:
--     docker cp .\sql-tools\migrate_report_kind.sql tm-x_project-mysql-1:/tmp/s.sql
--     docker exec tm-x_project-mysql-1 sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" tmx_db < /tmp/s.sql'
-- ============================================================================

USE tmx_db;

-- ── ก่อนแก้: มีอะไรอยู่บ้าง ───────────────────────────────────────────────
SELECT kind, COUNT(*) AS n FROM export_template GROUP BY kind ORDER BY kind;

-- ── ปักเทมเพลตเก่าให้เป็นของฝั่ง PDF ─────────────────────────────────────
-- ถ้าตัวไหนอยากให้ไปอยู่ฝั่ง Excel แทน ให้เปิดหน้า Export - Excel แล้วกด
-- Duplicate จากฝั่ง PDF เอา (หรือแก้ kind ของแถวนั้นเป็น 'excel' ด้วยมือ)
UPDATE export_template
   SET kind = 'pdf'
 WHERE kind = 'report';

-- ── หลังแก้ ──────────────────────────────────────────────────────────────
SELECT export_template_id, name, kind, is_default,
       (layout_json IS NOT NULL) AS has_layout
  FROM export_template
 ORDER BY kind, is_default DESC, name;
