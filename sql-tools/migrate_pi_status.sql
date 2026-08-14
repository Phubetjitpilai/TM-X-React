-- migrate_pi_status.sql — เพิ่มตาราง pi_status ให้ DB ที่สร้างไว้ก่อนหน้านี้
--
-- ⚠ ต้องรันเองด้วยมือ ห้ามเอาไปวางใน mysql-init/ เด็ดขาด
--   โฟลเดอร์นั้น mount เป็น docker-entrypoint-initdb.d ซึ่ง MySQL รันไฟล์ .sql
--   ทุกไฟล์เรียงตามตัวอักษรตอน container เกิดใหม่ — ไฟล์ชื่อขึ้นต้นด้วย m จะ
--   เรียงมาก่อน init.sql แล้วพังทั้งชุด (เคยเกิดจริงกับไฟล์ diagnose)
--
-- ทำไมต้องมีไฟล์นี้ทั้งที่เพิ่มใน init.sql ไปแล้ว:
--   init.sql ถูกรันอัตโนมัติ "เฉพาะตอน volume ว่างเปล่าครั้งแรก" เท่านั้น
--   DB ที่มีข้อมูลอยู่แล้ว (โดยเฉพาะเครื่อง PC หน้างานที่ import มือ) จะไม่ได้
--   ตารางนี้เลย แล้วป้าย Pi Online จะพังด้วย ERROR 1146 table doesn't exist
--
-- วิธีรัน
--   dev  : docker exec -i tmx-mysql mysql -uroot -p<pass> tmx_db < sql-tools/migrate_pi_status.sql
--   หน้างาน: mysql -u root -p tmx_db < sql-tools\migrate_pi_status.sql
--
-- รันซ้ำได้ปลอดภัย (IF NOT EXISTS)

CREATE TABLE IF NOT EXISTS pi_status (
  -- 'pi' = send_command.py บน Raspberry Pi · 'receive' = Recieve_tm-x.py บน PC
  source     VARCHAR(32) NOT NULL PRIMARY KEY,
  last_seen  DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  session_id INT         NULL,
  host       VARCHAR(64) NULL
);

-- ── ตรวจผล ────────────────────────────────────────────────────────────────
-- ควรได้ 4 คอลัมน์ และ 0 แถว (แถวจะเกิดเองตอน heartbeat ตัวแรกยิงเข้ามา)
SELECT COUNT(*) AS n_rows FROM pi_status;
DESCRIBE pi_status;

-- ── คิวรีที่ Backend จะใช้จริง (เอาไว้ทดสอบด้วยมือ) ───────────────────────
-- เขียน: 1 statement จบ ไม่ต้อง SELECT ก่อน
--   INSERT INTO pi_status (source, last_seen, session_id, host)
--   VALUES ('pi', NOW(), 42, '192.168.10.20')
--   ON DUPLICATE KEY UPDATE last_seen = NOW(), session_id = VALUES(session_id);
--
-- อ่าน: คำนวณ online สดทุกครั้ง ไม่เก็บเป็นคอลัมน์
--   SELECT source, last_seen, session_id,
--          (last_seen >= NOW() - INTERVAL 15 SECOND) AS online
--   FROM pi_status;
