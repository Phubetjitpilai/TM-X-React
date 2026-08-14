-- migrate_last_event.sql — เพิ่ม 3 คอลัมน์ last_event ให้ DB เก่า
--
-- ⚠ รันเองด้วยมือเท่านั้น ห้ามย้ายไป mysql-init/ (โฟลเดอร์นั้นถูก mount เป็น
--   docker-entrypoint-initdb.d — MySQL รันทุกไฟล์ .sql ในนั้นตอน container เกิดใหม่)
--
-- DB ที่สร้างใหม่จาก init.sql มีคอลัมน์พวกนี้อยู่แล้ว ไม่ต้องรันไฟล์นี้
--
--   mysql -u root -p tmx_db < sql-tools/migrate_last_event.sql
--
-- ── ทำอะไร ──────────────────────────────────────────────────────────────────
-- เพิ่มช่องรายงาน "สาเหตุที่ค่าไม่ถูกบันทึกลง DB" ให้ Backend หยิบไปตอบ Pi
--   Recieve_tm-x.py  →  POST /api/session/event   (MEASURE_FAILED ฯลฯ)
--   send_command.py  →  POST /api/session/stop    (PI_ERROR + reason)
-- แล้ว Backend รวมกับที่ Pi รายงาน timeout → SSE → modal บนหน้าเว็บ
-- (ดู IMPROVEMENT_PLAN.md ข้อ 7)

ALTER TABLE sessions
  ADD COLUMN last_event        VARCHAR(32) NULL AFTER queue_state,
  ADD COLUMN last_event_detail TEXT        NULL AFTER last_event,
  ADD COLUMN last_event_at     DATETIME    NULL AFTER last_event_detail;

-- ── ล้างค่า 'paused' ที่ค้างจากก่อนถอด Pause ออก (7 ส.ค. 2569) ───────────────
-- ถ้ามี session ค้างเป็น paused อยู่ จะไม่มีอะไรมาปิดให้อีกแล้ว เพราะ endpoint
-- /api/session/resume ถูกลบไปแล้ว และ heartbeat_checker แตะเฉพาะ state='running'
UPDATE sessions
   SET state    = 'stopped',
       ended_at = COALESCE(ended_at, NOW())
 WHERE state = 'paused';
