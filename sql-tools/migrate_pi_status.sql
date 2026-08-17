-- migrate_pi_status.sql — เพิ่มตาราง pi_status ให้ DB ที่สร้างไว้ก่อนหน้านี้
--
-- ⚠ ต้องรันเองด้วยมือ ห้ามเอาไปวางใน mysql-init/ เด็ดขาด
--   โฟลเดอร์นั้น mount เป็น docker-entrypoint-initdb.d ซึ่ง MySQL รันไฟล์ .sql
--   ทุกไฟล์เรียงตามตัวอักษรตอน container เกิดใหม่ — ไฟล์ชื่อขึ้นต้นด้วย m จะ
--   เรียงมาก่อน init.sql แล้วพังทั้งชุด (เคยเกิดจริงกับไฟล์ diagnose)
--
-- ทำไมต้องมีไฟล์นี้ทั้งที่เพิ่มใน init.sql ไปแล้ว:
--   init.sql ถูกรันอัตโนมัติ "เฉพาะตอน volume ว่างเปล่าครั้งแรก" เท่านั้น
--   DB ที่มีข้อมูลอยู่แล้ว (ทั้งเครื่อง dev ที่ container เกิดไปนานแล้ว และ
--   เครื่อง PC หน้างานที่ import มือ) จะไม่ได้ตารางนี้เลย
--
--   ผลถ้าไม่รัน: `/api/session/state` จะ query ตารางที่ไม่มี → ERROR 1146
--   ซึ่ง endpoint นั้นถูก poll ทุก 5 วิและทั้ง Dashboard พึ่งมัน — Live Telemetry
--   ปุ่ม Start แถบคิว ตายหมด ไม่ใช่แค่ชิป PI หาย
--   (ฝั่ง Backend จึงครอบ try/except ไว้อีกชั้น ให้ชิปเป็น "ไม่ทราบ" แทนที่จะ
--    ลากทั้งหน้าไปด้วย — แต่ก็ควรรัน migration ให้เรียบร้อยอยู่ดี)
--
-- วิธีรัน
--   dev     : docker exec -i tmx-mysql mysql -uroot -p<pass> tmx_db < sql-tools/migrate_pi_status.sql
--   หน้างาน : mysql -u root -p tmx_db < sql-tools\migrate_pi_status.sql
--
-- รันซ้ำได้ปลอดภัยทั้ง 2 คำสั่ง (IF NOT EXISTS / WHERE NOT EXISTS)

-- ① สร้างตาราง — แถวเดียว คอลัมน์เดียว
--    ห้ามเพิ่มคอลัมน์ is_online เด็ดขาด สถานะต้องคำนวณสดจาก last_seen เสมอ
--    (การ "ออฟไลน์" คือการไม่มีเหตุการณ์ ตอนสคริปต์ตายไม่มีใครเหลือมาเขียน 0 ให้)
CREATE TABLE IF NOT EXISTS pi_status (
  last_seen DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- ② สร้างแถวตั้งต้นถ้ายังไม่มี
--    ปกติ Backend ทำให้เองตอนบูตอยู่แล้ว ใส่ไว้ตรงนี้ด้วยเผื่อกรณีที่อยาก
--    ตรวจด้วยมือก่อนสตาร์ต Backend
INSERT INTO pi_status (last_seen)
SELECT NOW() FROM DUAL
WHERE NOT EXISTS (SELECT 1 FROM pi_status);

-- ── ตรวจผล ────────────────────────────────────────────────────────────────
-- ควรได้ 1 คอลัมน์ และ 1 แถวเสมอ (ไม่ว่าจะรันกี่ครั้ง)
SELECT COUNT(*) AS n_rows FROM pi_status;
DESCRIBE pi_status;

-- ── คิวรีที่ Backend ใช้จริง (เอาไว้ทดสอบด้วยมือ) ─────────────────────────
-- เขียน (ทุก heartbeat):
--   UPDATE pi_status SET last_seen = NOW();
--
-- อ่าน (ทุกครั้งที่หน้าเว็บ poll /api/session/state):
--   SELECT last_seen >= NOW() - INTERVAL 15 SECOND AS pi_status FROM pi_status;
--   (15 ต้องเป็นค่าเดียวกับ HEARTBEAT_TIMEOUT ใน .env ที่ Pi ใช้ตัดสินใจหยุดตัวเอง)
SELECT last_seen,
       NOW() AS now_,
       TIMESTAMPDIFF(SECOND, last_seen, NOW()) AS age_sec,
       (last_seen >= NOW() - INTERVAL 15 SECOND) AS pi_status
FROM pi_status;
