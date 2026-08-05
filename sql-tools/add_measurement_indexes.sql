-- ============================================================================
-- เพิ่ม INDEX ให้ตาราง measurements — แก้อาการช้าเมื่อข้อมูลเยอะ
-- ============================================================================
-- ⚠ ห้ามย้ายไฟล์นี้เข้า mysql-init/ — โฟลเดอร์นั้น mount เป็น
--   docker-entrypoint-initdb.d ซึ่งรันไฟล์ .sql ทุกไฟล์ตอน container เกิดใหม่
--   ถ้าไฟล์ไหน error ไฟล์ถัดไปจะไม่ถูกรันเลย
--   (index ชุดนี้ถูกใส่ใน init.sql ให้แล้ว — ไฟล์นี้มีไว้สำหรับ DB ที่มีข้อมูลอยู่แล้ว)
--
-- ปัญหาที่แก้: ตาราง measurements เดิมมี index แค่ PRIMARY KEY, UNIQUE(client_uuid)
--   และ index ที่ InnoDB สร้างให้อัตโนมัติจาก FOREIGN KEY (session_id, number_alpl,
--   operator_id) — แต่ "ไม่มี index บน timestamp เลย" ทั้งที่ทุก query ในระบบ
--   เรียงด้วย ORDER BY m.timestamp และตัวกรองวันที่ก็ใช้คอลัมน์นี้
--   MySQL จึงต้องอ่านทั้งตารางแล้วเรียงใหม่ (full scan + filesort) ทุกครั้งที่
--   เปิดหน้า Home / เปลี่ยนหน้าตาราง / กรองข้อมูล / export
--
-- วิธีรัน (PowerShell) — แนะนำวิธีนี้ เพราะ docker cp คัดลอกไฟล์แบบไบต์ต่อไบต์
--   จึงไม่มีปัญหาตัวอักษรไทยในคอมเมนต์เพี้ยน:
--     docker cp .\sql-tools\add_measurement_indexes.sql tm-x_project-mysql-1:/tmp/s.sql
--     docker exec tm-x_project-mysql-1 sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" tmx_db < /tmp/s.sql'
--
--   วิธี pipe ก็ใช้ได้ (ทุก statement เป็น ASCII แล้ว ไทยอยู่แค่ในคอมเมนต์):
--     Get-Content .\sql-tools\add_measurement_indexes.sql | docker exec -i tm-x_project-mysql-1 sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" tmx_db'
--
-- ใช้เวลาไม่นานบนข้อมูลไม่กี่แสนแถว และ "ไม่ต้องแก้โค้ดเลย" — MySQL เลือกใช้เอง
-- รันซ้ำได้ไม่พัง (เช็ค information_schema ก่อนทุกตัว)
-- ============================================================================

USE tmx_db;

-- ── ตัวช่วย: สร้าง index เฉพาะถ้ายังไม่มี ─────────────────────────────────
-- MySQL 8 ไม่มี CREATE INDEX IF NOT EXISTS จึงต้องเช็คเอง
DROP PROCEDURE IF EXISTS _add_index_if_missing;
DELIMITER //
CREATE PROCEDURE _add_index_if_missing(
  IN p_table VARCHAR(64), IN p_index VARCHAR(64), IN p_cols VARCHAR(255)
)
BEGIN
  IF (SELECT COUNT(*) FROM information_schema.STATISTICS
       WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = p_table
         AND INDEX_NAME = p_index) = 0 THEN
    SET @s = CONCAT('CREATE INDEX ', p_index, ' ON ', p_table, ' (', p_cols, ')');
    PREPARE st FROM @s; EXECUTE st; DEALLOCATE PREPARE st;
    SELECT CONCAT('created: ', p_index) AS result;
  ELSE
    SELECT CONCAT('already exists, skipped: ', p_index) AS result;
  END IF;
END //
DELIMITER ;

-- ── 1) timestamp ─────────────────────────────────────────────────────────
-- ใช้กับ: ORDER BY m.timestamp DESC (ทุกหน้าตาราง + export ทุกชนิด)
--         และตัวกรองช่วงวันที่ (m.timestamp >= / <=)
-- นี่คือตัวที่ให้ผลมากที่สุด เพราะแก้ทั้ง filesort และการหาช่วงวันที่
CALL _add_index_if_missing('measurements', 'idx_meas_timestamp', 'timestamp');

-- ── 2) (number_alpl, timestamp, measurement_id) ──────────────────────────
-- ใช้กับ: ตัวเลือก "เฉพาะการวัดล่าสุดของแต่ละ ALPL" ซึ่งเปิดเป็นค่าเริ่มต้น
--   ROW_NUMBER() OVER (PARTITION BY m.number_alpl
--                      ORDER BY m.timestamp DESC, m.measurement_id DESC)
-- ลำดับคอลัมน์ต้องตรงกับ PARTITION BY แล้วต่อด้วย ORDER BY เป๊ะๆ MySQL จึงจะ
-- เดินตาม index ได้เลยโดยไม่ต้องกาง (materialize) ทั้งชุดไว้ในหน่วยความจำก่อน
--
-- ประกาศเป็น ASC ทั้งชุด (ไม่ใช่ DESC) เพราะ MySQL เดิน index ย้อนกลับได้อยู่แล้ว
-- เมื่อ ORDER BY เป็น DESC ทุกคอลัมน์ — เขียน ASC จึงใช้ได้ทั้งกรณี ASC และ DESC
-- (export รายงานเรียง ASC, ตารางในหน้าเว็บเรียง DESC — index เดียวรับได้ทั้งคู่)
CALL _add_index_if_missing('measurements', 'idx_meas_alpl_ts', 'number_alpl, timestamp, measurement_id');

-- ── 3) (session_id, result) ──────────────────────────────────────────────
-- ใช้กับ: การ์ด OK/NG ในหน้า Home ที่ยิง COUNT ทุกครั้งที่มีการวัดเข้ามา
--   GET /api/measurements?session_id=X&result=OK&limit=1
-- session_id มี index จาก FK อยู่แล้ว แต่การเติม result เข้าไปทำให้ COUNT อ่านได้
-- จาก index ตรงๆ (covering index) ไม่ต้องแตะแถวจริงในตารางเลย
CALL _add_index_if_missing('measurements', 'idx_meas_session_result', 'session_id, result');

DROP PROCEDURE _add_index_if_missing;

-- ── ตรวจผล ───────────────────────────────────────────────────────────────
SELECT INDEX_NAME                                      AS index_name,
       GROUP_CONCAT(COLUMN_NAME ORDER BY SEQ_IN_INDEX)  AS columns_in_index,
       IF(NON_UNIQUE = 0, 'unique', '-')                AS kind
  FROM information_schema.STATISTICS
 WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'measurements'
 GROUP BY INDEX_NAME
 ORDER BY INDEX_NAME;

SELECT COUNT(*) AS total_rows FROM measurements;

-- ── อยากพิสูจน์ว่ามันถูกใช้จริง ให้รัน EXPLAIN เทียบดู ────────────────────
-- ก่อนมี index จะเห็น type=ALL (full scan) + Extra: Using filesort
-- หลังมี index ควรเห็น key=idx_meas_timestamp และไม่มี filesort
EXPLAIN SELECT measurement_id FROM measurements ORDER BY timestamp DESC LIMIT 100;
