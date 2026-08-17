-- drop_pi_status.sql — ลบตาราง pi_status ที่เลิกใช้แล้ว (17 ส.ค. 2569)
--
-- ⚠ ต้องรันเองด้วยมือ ห้ามเอาไปวางใน mysql-init/ เด็ดขาด
--   โฟลเดอร์นั้น mount เป็น docker-entrypoint-initdb.d — MySQL รันไฟล์ .sql
--   ทุกไฟล์เรียงตามตัวอักษรตอน container เกิดใหม่ ไฟล์ชื่อขึ้นต้นด้วย d จะเรียง
--   มาก่อน init.sql แล้วพังทั้งชุด (เคยเกิดจริงกับไฟล์ diagnose)
--
-- ── ทำไมถึงเลิกใช้ ────────────────────────────────────────────────────────
--
--   ตาราง pi_status เก็บ "Backend เห็น Pi ครั้งล่าสุดเมื่อไหร่" ไว้แถวเดียว
--   แต่ฝั่งอ่าน (read_pi_status) ย้ายไปใช้ตัวแปรใน memory (_pi_last_seen) ตั้งแต่
--   ตอนแก้ปัญหา connection churn แล้ว — ตารางจึงเหลือหน้าที่เดียวคือ "กู้ค่ากลับ
--   เข้า memory ตอน Backend restart" เพื่อไม่ให้ชิป PI กระพริบเป็น 🟡 ราว 2 วินาที
--
--   ต้นทุนที่จ่ายเพื่อสิ่งนั้น:
--       UPDATE 1 แถว ทุก HEARTBEAT_INTERVAL (2 วิ) = 43,200 ครั้ง/วัน
--       ลง binary log ทั้งหมด (MySQL 8 เปิด log_bin เป็น default)
--       ≈ 200-300 MB/เดือน ของข้อมูลที่หมดอายุใน 5 วินาที
--
--   และประโยชน์เกิดเฉพาะตอน dev ที่ใช้ `uvicorn --reload` ซึ่งรีสตาร์ททุกครั้งที่
--   เซฟไฟล์ — หน้างานจริง Backend รันยาว แทบไม่รีสตาร์ทเลย
--
--   จึงถอดออก · ชิปขึ้น 🟡 Connecting ราว 2 วิหลัง restart ซึ่งถูกต้องตาม
--   ความหมายอยู่แล้ว (= ยังไม่รู้จริง ๆ ในวินาทีนั้น) แล้วหายเองตอน heartbeat
--   ตัวถัดไปมาถึง
--
-- ── วิธีรัน ───────────────────────────────────────────────────────────────
--   dev     : docker exec -i tmx-mysql mysql -uroot -p<pass> tmx_db < sql-tools/drop_pi_status.sql
--   หน้างาน : mysql -u root -p tmx_db < sql-tools\drop_pi_status.sql
--
--   รันซ้ำได้ปลอดภัย (IF EXISTS) · ไม่รันก็ได้ ตารางจะค้างอยู่เฉย ๆ ไม่มีใคร
--   เขียนหรืออ่านมันอีกแล้ว แค่กินพื้นที่นิดเดียว

DROP TABLE IF EXISTS pi_status;

-- ── ตรวจผล ────────────────────────────────────────────────────────────────
-- ควรได้ 0 แถว (ไม่มีตารางชื่อนี้แล้ว)
SELECT COUNT(*) AS still_exists
FROM information_schema.tables
WHERE table_schema = DATABASE() AND table_name = 'pi_status';

-- ── เก็บกวาด binlog เก่าที่บวมจาก UPDATE ชุดนี้ (ทำหรือไม่ทำก็ได้) ────────
-- ⚠ ลบแล้วกู้ไม่ได้ และถ้ามี replica อยู่ห้ามทำ — ระบบนี้ไม่มี replica
-- ดูก่อนว่ามีไฟล์อะไรบ้าง:
--     SHOW BINARY LOGS;
-- ลบของที่เก่ากว่า 7 วัน:
--     PURGE BINARY LOGS BEFORE DATE_SUB(NOW(), INTERVAL 7 DAY);
