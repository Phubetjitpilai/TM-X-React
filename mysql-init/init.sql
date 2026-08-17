-- mysql-init/init.sql
-- Auto-executed by MySQL Docker container on first startup.
-- How to run: docker compose up -d

CREATE DATABASE IF NOT EXISTS tmx_db;
USE tmx_db;

-- Drop in FK-safe order (children first, lookup tables last)
DROP TABLE IF EXISTS export_template;
DROP TABLE IF EXISTS measurements;
DROP TABLE IF EXISTS sessions;
DROP TABLE IF EXISTS parts_specifications;
DROP TABLE IF EXISTS part_number;
DROP TABLE IF EXISTS package_size;
DROP TABLE IF EXISTS template;
DROP TABLE IF EXISTS operator;
DROP TABLE IF EXISTS owner;
DROP TABLE IF EXISTS vendor;
DROP TABLE IF EXISTS handler;

-- ===== Lookup tables (created first — parts/measurements reference these) =====

CREATE TABLE operator (
  operator_id   INT AUTO_INCREMENT PRIMARY KEY,
  operator_name VARCHAR(100) NOT NULL UNIQUE
);

CREATE TABLE owner (
  owner_id   INT AUTO_INCREMENT PRIMARY KEY,
  owner_name VARCHAR(100) NOT NULL UNIQUE
);

CREATE TABLE vendor (
  vendor_id   INT AUTO_INCREMENT PRIMARY KEY,
  vendor_name VARCHAR(100) NOT NULL UNIQUE
);

CREATE TABLE handler (
  handler_id   INT AUTO_INCREMENT PRIMARY KEY,
  handler_name VARCHAR(100) NOT NULL UNIQUE
);

-- template ต้องถูกสร้างก่อน package_size เพราะ package_size.template_id
-- อ้าง FK มาที่ตารางนี้ (แก้ลำดับจากเดิมที่สร้าง package_size ก่อน ทำให้
-- CREATE TABLE package_size พังด้วย ERROR 1824 'Failed to open the
-- referenced table template')
CREATE TABLE template (
  template_id   INT AUTO_INCREMENT PRIMARY KEY,
  template_name VARCHAR(100) NOT NULL UNIQUE
);

-- package_size ผูกกับ template (โปรแกรมวัดของ TM-X) — VARCHAR(20) เพราะมีชื่อ
-- ยาวสุดคือ "3.255x3.255" (11 ตัวอักษร เกิน VARCHAR(10) เดิม)
CREATE TABLE package_size (
  package_size_id INT AUTO_INCREMENT PRIMARY KEY,
  package_size    VARCHAR(20) NOT NULL UNIQUE,
  nominal_x       FLOAT NOT NULL,
  nominal_y       FLOAT NOT NULL,
  upper_tol       FLOAT NOT NULL,
  lower_tol       FLOAT NOT NULL,
  offset_tol      FLOAT NOT NULL,
  template_id     INT,
  FOREIGN KEY (template_id) REFERENCES template(template_id)
);

-- part_number: catalog ของ part number จริงที่เคยกำหนดไว้ล่วงหน้า ผูกกับ
-- package_size + handler ของตัวเอง พร้อม nominal X/Y และ tolerance เดียวที่
-- ใช้ร่วมกันทั้งสองแกน (upper_tol/lower_tol) — เป็นตัวกำหนด handler จริงๆ
-- ของ part นั้น (ฟอร์ม New/Rework/IPM จึงไม่ต้องมีช่อง Handler ให้กรอกเอง
-- เพราะ link ผ่าน Part Number ได้เลย)
CREATE TABLE part_number (
  part_number_id   INT AUTO_INCREMENT PRIMARY KEY,
  part_number_name VARCHAR(50) NOT NULL UNIQUE,
  package_size_id  INT NOT NULL,
  handler_id       INT NOT NULL,
  nominal_x        FLOAT NOT NULL,
  nominal_y        FLOAT NOT NULL,
  upper_tol        FLOAT NOT NULL,
  lower_tol        FLOAT NOT NULL,
  offset_tol       FLOAT NOT NULL,
  FOREIGN KEY (package_size_id) REFERENCES package_size(package_size_id),
  FOREIGN KEY (handler_id)      REFERENCES handler(handler_id)
);

-- ===== Core tables =====

-- parts_specifications: 1 แถว = 1 ALPL (number_alpl) ที่เคยลงทะเบียนไว้แล้ว —
-- part_number_id เป็น FK ไปตาราง part_number (nullable — กรอกทีหลังได้ตอน
-- ยังไม่รู้ part_number จริง) handler/package_size/nominal/tolerance ทั้งหมด
-- derive มาจาก part_number_id นี้ ไม่ได้เก็บซ้ำที่ตารางนี้โดยตรง
CREATE TABLE parts_specifications (
  part_id          INT AUTO_INCREMENT PRIMARY KEY,
  number_alpl      INT UNIQUE,
  part_number_id   INT,
  package_size_id   INT,
  vendor_id        INT,
  owner_id         INT,
  po_number        BIGINT,
  description      TEXT,
  recieve_date     DATETIME DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (part_number_id)  REFERENCES part_number(part_number_id),
  FOREIGN KEY (package_size_id)  REFERENCES package_size(package_size_id),
  FOREIGN KEY (vendor_id)       REFERENCES vendor(vendor_id),
  FOREIGN KEY (owner_id)        REFERENCES owner(owner_id)
);

-- ON UPDATE CASCADE: ให้แก้ ALPL ใน parts_specifications ได้แม้จะมีประวัติ
-- session/measurement ผูกอยู่แล้ว (แก้ผ่าน edit.html ได้) — ค่า number_alpl ใน
-- sessions/measurements จะถูกอัปเดตตามอัตโนมัติ ไม่ใช่ถูก MySQL ปฏิเสธแบบ
-- RESTRICT (default) — หมายเหตุ: sessions/measurements อ้างอิง
-- parts_specifications ผ่าน number_alpl (ไม่ใช่ part_id) เพราะ main.py ทั้งไฟล์
-- query/insert สองตารางนี้ด้วยคอลัมน์ number_alpl ตรงๆ ทุกจุด — number_alpl
-- มี UNIQUE constraint จึงใช้เป็นเป้าหมายของ FOREIGN KEY ได้เหมือน PK
-- queue_state: สำเนา JSON ของคิว ALPL (session_queues ใน memory ของ backend)
-- เขียนทับทุกครั้งที่มีการเปลี่ยนแปลง ใช้กู้คืนคิวกลับเข้า memory ถ้า backend
-- restart กลาง session ที่ยัง running อยู่
-- state มีได้ 4 ค่าเท่านั้น: idle | running | stopped | timeout
-- (เคยมี 'paused' แต่ถอด Pause/Resume ออกทั้งระบบแล้ว 7 ส.ค. 2569 เพราะฝั่ง Pi
--  ไม่เคยรองรับ กดแล้วหน้าเว็บขึ้น paused แต่เครื่องจริงยังวัดต่อ)
--
-- last_event / last_event_detail / last_event_at:
--   ช่องรายงาน "สาเหตุที่ค่าไม่ถูกบันทึกลง DB" ให้ Backend หยิบไปตอบ Pi
--   เขียนโดย Recieve_tm-x.py (POST /api/session/event) หรือ Pi (ตอน stop พร้อม reason)
--   ⚠ มีช่องเดียว ค่าใหม่ทับค่าเก่า — จึงเก็บเฉพาะเรื่องที่ "มีคนรอคำตอบอยู่"
--     เรื่องที่ค่าลง DB ไปแล้ว (เช่นรูปอัปโหลดไม่สำเร็จ) ห้ามเขียนลงช่องนี้
--     ไม่งั้นจะไปทับสาเหตุที่ Pi กำลังรอ (ดู IMPROVEMENT_PLAN.md ข้อ 7)
CREATE TABLE sessions (
  session_id        INT          AUTO_INCREMENT PRIMARY KEY,
  state             VARCHAR(20)  NOT NULL DEFAULT 'idle',
  target_count      INT          NOT NULL DEFAULT 1,
  measured_count    INT          NOT NULL DEFAULT 0,
  queue_state       JSON         NULL,
  last_event        VARCHAR(32)  NULL,
  last_event_detail TEXT         NULL,
  last_event_at     DATETIME     NULL,
  last_seen         DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  started_at        DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  ended_at          DATETIME     NULL
);


-- pi_status: "Backend เห็น Pi ครั้งล่าสุดเมื่อไหร่" — มีแถวเดียว คอลัมน์เดียว
-- ใช้วาดชิป PI ในแถบ Session Control ของหน้า index
--
-- ทำไมต้องมีตารางนี้ ทั้งที่ sessions.last_seen ก็เก็บ heartbeat อยู่แล้ว:
--   sessions.last_seen อัปเดตเฉพาะตอนมี session ที่ state='running' เท่านั้น
--   (ดู `POST /api/heartbeat` — session_id เป็น NULL จะ return ทันทีไม่แตะ DB)
--   แปลว่าช่วงที่ Pi "ว่างแต่ยังมีชีวิต" ไม่มีที่ไหนบันทึกไว้เลย ซึ่งเป็นช่วงที่
--   ป้ายต้องทำงานมากที่สุด — คนเปิดเว็บมาดูก่อนกด Start ว่าเครื่องพร้อมไหม
--
-- ⚠ **ห้ามเพิ่มคอลัมน์ is_online เด็ดขาด** — สถานะออนไลน์ต้อง "คำนวณสด" จาก
--   last_seen เสมอ:
--       last_seen >= NOW() - INTERVAL <HEARTBEAT_TIMEOUT> SECOND
--   เพราะการ "ออฟไลน์" คือการ *ไม่มีเหตุการณ์เกิดขึ้น* ตอนสายหลุด/สคริปต์ตาย
--   ไม่มีใครเหลืออยู่มาเขียน is_online=0 ให้ ค่าจะค้างเป็น 1 ตลอดกาล = ป้ายโกหก
--   (หลักเดียวกับ sessions.last_seen ที่ heartbeat_checker คำนวณเอาเอง)
--
-- ⚠ ใช้เกณฑ์เวลาตัวเดียวกับ HEARTBEAT_TIMEOUT ใน .env ที่ Pi ใช้ตัดสินใจหยุด
--   ตัวเอง — ป้ายบนเว็บกับพฤติกรรมเครื่องจริงจะได้ตรงกันเสมอ
--
-- ── ดีไซน์: ตารางนี้มี "แถวเดียวตลอดชีวิต" ────────────────────────────────
--   Backend สร้างแถวให้เองตอนบูต (ดู lifespan):
--       INSERT INTO pi_status (last_seen)
--       SELECT NOW() FROM DUAL WHERE NOT EXISTS (SELECT 1 FROM pi_status);
--   heartbeat จึงเป็น UPDATE เปล่าๆ ไม่ต้องมี WHERE:
--       UPDATE pi_status SET last_seen = NOW();
--
--   ⚠ ที่ต้องให้ Backend สร้างแถวเองตอนบูต แทนการ seed ไว้ใน insert.sql:
--     UPDATE ที่ไม่มีแถวให้อัปเดตจะกระทบ 0 แถว **โดยไม่มี error ใดๆ** →
--     last_seen ไม่เคยขยับ → ป้ายขึ้นแดงตลอดกาลทั้งที่ Pi ปกติดี และไล่หา
--     สาเหตุยากมาก เพราะทุกอย่างดู "ทำงานอยู่" หมด (Pi ยิง · Backend ตอบ ok ·
--     ไม่มี error สักบรรทัด) · การ ensure ตอนบูตทำให้ DB ที่ยังไม่มีแถว
--     กู้ตัวเองได้เสมอ ไม่ว่าจะมาจาก init.sql หรือ import มือ
--
--   ⚠ ทั้งขาเขียนและขาอ่านต้องใช้ NOW() ของ MySQL — ห้ามเขียนด้วย
--     datetime.now() ของ Python เพราะตอน dev MySQL อยู่ใน Docker คนละนาฬิกา
--     กับ host เหลื่อมกันไม่กี่วินาที ป้ายจะแดงๆ เขียวๆ สลับโดยไม่มีสาเหตุ
--
-- ── ข้อจำกัดที่ยอมรับแล้ว ────────────────────────────────────────────────
--   • รองรับได้ตัวเดียว (Pi) — ถ้าจะเพิ่ม Recieve_tm-x.py ทีหลังต้อง ALTER TABLE
--     เติมคอลัมน์ source ตั้งเป็น PK แล้วแก้ query ทั้งขาเขียนและขาอ่าน
--     (Recieve ตายอันตรายกว่า Pi ตายด้วยซ้ำ — เครื่องวัดปกติทุกอย่างแต่ค่า
--      ไม่เข้า DB สักชิ้น แล้ว modal ไปบอกสาเหตุผิดว่า "TM-X วัดไม่ติด")
--   • แยกไม่ออกว่าใครยิงมา — เปิด mockup.py ค้างไว้ ป้ายจะเขียวแม้ Pi จริงดับ
CREATE TABLE pi_status (
  last_seen DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- client_uuid: UUID ที่ Agent สร้างต่อการวัด 1 ครั้ง ใช้กัน insert ซ้ำตอน retry
-- POST /api/measurements
CREATE TABLE measurements (
  measurement_id INT          AUTO_INCREMENT PRIMARY KEY,
  session_id     INT          NOT NULL,
  number_alpl    INT          NOT NULL,
  value_x        FLOAT        NOT NULL,
  value_y        FLOAT        NOT NULL,
  -- ⚠ ต้องมี backtick ครอบเสมอ — OFFSET เป็น reserved keyword ของ MySQL 8
  --   (ใช้กับ LIMIT ... OFFSET) เขียนเปล่าๆ จะได้ ERROR 1064 ตั้งแต่ CREATE TABLE
  --   ทุก query ที่อ้างคอลัมน์นี้ก็ต้องใส่ backtick เหมือนกัน
  `offset`       FLOAT        NOT NULL DEFAULT 0,
  result         VARCHAR(10)  NOT NULL,
  note           TEXT,
  operator_id    INT          NOT NULL,
  client_uuid    VARCHAR(36)  NULL UNIQUE,
  measure_type   VARCHAR(10)  NOT NULL,
  image_path     VARCHAR(255),
  image_upload_failed TINYINT(1) NOT NULL DEFAULT 0,
  timestamp      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (session_id)  REFERENCES sessions(session_id),
  FOREIGN KEY (number_alpl) REFERENCES parts_specifications(number_alpl) ON UPDATE CASCADE,
  FOREIGN KEY (operator_id) REFERENCES operator(operator_id),

  -- ── INDEX สำหรับตอนข้อมูลเยอะ ───────────────────────────────────────────
  -- InnoDB สร้าง index ให้อัตโนมัติแล้วสำหรับคอลัมน์ที่เป็น FOREIGN KEY
  -- (session_id / number_alpl / operator_id) แต่ 3 ตัวข้างล่างต้องประกาศเอง
  -- ถ้าไม่มี ทุก query จะ full scan + filesort ทั้งตาราง
  -- (DB ที่สร้างไว้ก่อนหน้าให้รัน sql-tools/add_measurement_indexes.sql เพิ่ม)

  -- ทุก query เรียงด้วย ORDER BY m.timestamp และตัวกรองวันที่ก็ใช้คอลัมน์นี้
  INDEX idx_meas_timestamp (timestamp),

  -- ตัวเลือก "เฉพาะการวัดล่าสุดของแต่ละ ALPL" (เปิดเป็นค่าเริ่มต้น) ใช้
  -- ROW_NUMBER() OVER (PARTITION BY number_alpl ORDER BY timestamp, measurement_id)
  -- ลำดับคอลัมน์ต้องตรงกับ PARTITION BY แล้วต่อด้วย ORDER BY เป๊ะๆ
  INDEX idx_meas_alpl_ts (number_alpl, timestamp, measurement_id),

  -- การ์ด OK/NG ในหน้า Home ยิง COUNT ทุกครั้งที่มีการวัดเข้ามา
  -- (?session_id=X&result=OK) — index นี้ทำให้ COUNT อ่านจาก index ได้ตรงๆ
  INDEX idx_meas_session_result (session_id, result)
);

-- ===== Export templates =====

-- เทมเพลตของหน้า Export — เก็บว่าจะ export คอลัมน์ไหนบ้างและเรียงลำดับยังไง
-- ⚠ อย่าสับสนกับตาราง `template` ด้านบน ซึ่งคนละเรื่องกันคนละความหมาย:
--     template         = โปรแกรมวัดของเครื่อง TM-X (เช่น "201")
--     export_template  = ชุดคอลัมน์สำหรับ export ไฟล์ (เช่น "รายงานประจำวัน")
-- columns_json: array ของ key คอลัมน์ "เรียงตามลำดับที่จะออกในไฟล์" เช่น
--   ["number_alpl","value_x","value_y","result","operator","timestamp"]
--   (รายชื่อ key ที่ใช้ได้ดูที่ EXPORT_COLUMNS ใน Backend-server/main.py)
-- is_default: 1 = เทมเพลตตั้งต้นของระบบ ห้ามแก้/ห้ามลบ (Duplicate ได้อย่างเดียว)
-- kind: แยกเทมเพลต 2 ชนิดที่ใช้คนละหน้ากัน
--   'csv'    → เลือกคอลัมน์ + ลำดับอย่างเดียว (หน้า export.html) ใช้ columns_json
--   'report' → ผังตารางแบบสเปรดชีตสำหรับ PDF/Excel (หน้า report-template.html)
--              ใช้ layout_json เก็บทุกอย่าง: ข้อความ/ช่องข้อมูลในแต่ละเซลล์,
--              รูปแบบตัวอักษร, การผสานเซลล์, แถวที่เป็นแถวข้อมูล, คอลัมน์ที่ใช้
--              แบ่งกลุ่ม — เก็บเป็นก้อน JSON ก้อนเดียวเพราะโครงเป็นตาราง 2 มิติ
--              ที่ผู้ใช้ปรับได้อิสระ ไม่เหมาะกับการแตกเป็นคอลัมน์ตายตัวใน SQL
CREATE TABLE export_template (
  export_template_id INT AUTO_INCREMENT PRIMARY KEY,
  name         VARCHAR(100) NOT NULL UNIQUE,
  kind         VARCHAR(10)  NOT NULL DEFAULT 'csv',
  columns_json JSON         NULL,
  layout_json  JSON         NULL,
  is_default   TINYINT(1)   NOT NULL DEFAULT 0,
  created_at   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
);
