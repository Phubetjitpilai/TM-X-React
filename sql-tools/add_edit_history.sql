-- เพิ่มตาราง edit_history ให้ฐานข้อมูลที่สร้างไว้ก่อนมีฟีเจอร์นี้
--
-- ⚠ ไฟล์นี้ต้อง "รันเองด้วยมือ" เท่านั้น ห้ามย้ายไปไว้ใน mysql-init/ เด็ดขาด
--   (โฟลเดอร์นั้นถูก mount เป็น docker-entrypoint-initdb.d แล้ว MySQL จะรันไฟล์
--    .sql ทุกไฟล์ในนั้นเรียงตามตัวอักษรตอน container เกิดใหม่ — ดู CLAUDE.md)
--   DB ที่สร้างใหม่ได้ตารางนี้จาก init.sql อยู่แล้ว ไม่ต้องรันไฟล์นี้ซ้ำ
--
-- วิธีรัน (หน้างาน):
--   mysql -u root -p tmx_db < sql-tools\add_edit_history.sql
-- วิธีรัน (dev ผ่าน Docker):
--   docker compose exec -T mysql mysql -u root -p<password> tmx_db < sql-tools/add_edit_history.sql
--
-- รันซ้ำได้ไม่พัง — IF NOT EXISTS ข้ามให้เองถ้ามีตารางอยู่แล้ว

CREATE TABLE IF NOT EXISTS edit_history (
  history_id  INT AUTO_INCREMENT PRIMARY KEY,
  edited_at   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  table_name  VARCHAR(48)  NOT NULL,
  action      ENUM('add','edit','delete','restore','purge') NOT NULL,
  ref         VARCHAR(120) NOT NULL,
  changes_json JSON        NULL,
  trash_id    VARCHAR(200) NULL,
  INDEX idx_hist_time (edited_at),
  INDEX idx_hist_table_time (table_name, edited_at),
  INDEX idx_hist_action_time (action, edited_at)
);

-- อัปเกรดตารางที่สร้างไปก่อนมี restore/purge — รันซ้ำได้ไม่พัง (ตั้งค่าเดิมซ้ำเฉย ๆ)
-- ⚠ ต้องมีบรรทัดนี้แยกจาก CREATE TABLE ข้างบน เพราะ IF NOT EXISTS จะข้ามทั้งก้อน
--   ถ้าตารางมีอยู่แล้ว ENUM ที่เพิ่มใหม่จึงไม่ถูกนำไปใช้
ALTER TABLE edit_history
  MODIFY COLUMN action ENUM('add','edit','delete','restore','purge') NOT NULL;

SELECT 'edit_history พร้อมใช้งานแล้ว' AS status;
