-- seed_lookup_data.sql
-- Insert ข้อมูลตั้งต้นให้ตาราง lookup (operator/owner/handler/vendor/template/
-- package_size/part_number) ใช้ INSERT IGNORE เพื่อให้รันซ้ำได้โดยไม่ error
-- (ชื่อซ้ำจะถูกข้าม เพราะทุกตารางมี UNIQUE อยู่แล้วบนคอลัมน์ชื่อ — ดู init.sql)

USE tmx_db;

-- ── Operator ─────────────────────────────────────────────────────────────
INSERT IGNORE INTO operator (operator_name) VALUES
  ('Boss'),
  ('Nut');

-- ── Owner ────────────────────────────────────────────────────────────────
INSERT IGNORE INTO owner (owner_name) VALUES
  ('Messi'),
  ('Ronaldo');

-- ── Handler ──────────────────────────────────────────────────────────────
INSERT IGNORE INTO handler (handler_name) VALUES
  ('HT9046'),
  ('HT9046MX');

-- ── Vendor ───────────────────────────────────────────────────────────────
INSERT IGNORE INTO vendor (vendor_name) VALUES
  ('A'),
  ('B'),
  ('C');

-- ── Template ───────────────────────────────────────────────────────────────
INSERT IGNORE INTO template (template_name) VALUES
  ('201');

-- ── Package Size ─────────────────────────────────────────────────────────
-- nominal_x / nominal_y / upper_tol / lower_tol / offset_tol เป็น NOT NULL
-- ทั้งหมด (ดู init.sql) จึงต้องใส่ค่ามาตั้งแต่ INSERT แถวนี้ — เว้นว่างไม่ได้
--
-- ที่มาของตัวเลข:
--   • ขนาดที่มี part_number อ้างถึงอยู่แล้ว → ลอกค่าจากบล็อก part_number
--     ท้ายไฟล์นี้ตรงๆ (ถ้า part_number หลายตัวใช้ package เดียวกันแล้วค่าไม่ตรง
--     กัน เช่น 3x3 กับ 3.5x3.75 → ใช้ค่าที่พบบ่อยที่สุด)
--   • ขนาดที่ยังไม่มี part_number ตัวไหนอ้างถึง → เดาจากรูปแบบเดียวกัน
--     (nominal = ขนาดตามชื่อ + 0.03, tolerance 0.02 / 0.01)
--
-- ⚠ offset_tol ยังไม่มีค่าจริงจากหน้างาน — ใส่ 0.03 ไว้ทุกแถวเป็นค่าชั่วคราว
--   ต้องแก้ให้ตรงของจริงก่อนใช้ตัดสิน OK/NG (ฝั่ง Pi อ่านค่านี้ไปเทียบ offset
--   ที่ได้จาก GM)
INSERT IGNORE INTO package_size (package_size, nominal_x, nominal_y, upper_tol, lower_tol, offset_tol, template_id) VALUES
  ('10x6.5',     10.03,  6.53, 0.02, 0.01, 0.03, (SELECT template_id FROM template WHERE template_name='201')),
  ('3.05x7.25',   3.08,  7.28, 0.02, 0.01, 0.03, (SELECT template_id FROM template WHERE template_name='201')),
  ('3.255x3.255', 3.285, 3.285,0.02, 0.01, 0.03, (SELECT template_id FROM template WHERE template_name='201')),
  ('3.25x7.40',   3.28,  7.43, 0.02, 0.01, 0.03, (SELECT template_id FROM template WHERE template_name='201')),
  ('3.5x3.75',    3.53,  3.78, 0.02, 0.01, 0.03, (SELECT template_id FROM template WHERE template_name='201')),
  ('3.5x3',       3.53,  3.03, 0.02, 0.01, 0.03, (SELECT template_id FROM template WHERE template_name='201')),
  ('3.5x4.6',     3.53,  4.63, 0.02, 0.01, 0.03, (SELECT template_id FROM template WHERE template_name='201')),
  ('3x2.5',       3.03,  2.53, 0.02, 0.01, 0.03, (SELECT template_id FROM template WHERE template_name='201')),
  ('3x3',         3.03,  3.02, 0.02, 0.01, 0.03, (SELECT template_id FROM template WHERE template_name='201')),
  ('3x4',         3.03,  4.03, 0.02, 0.01, 0.03, (SELECT template_id FROM template WHERE template_name='201')),
  ('4.25x4.25',   4.28,  4.28, 0.02, 0.01, 0.03, (SELECT template_id FROM template WHERE template_name='201')),
  ('4.5x5.75',    4.53,  5.78, 0.02, 0.01, 0.03, (SELECT template_id FROM template WHERE template_name='201')),
  ('4x4',         4.03,  4.03, 0.02, 0.01, 0.03, (SELECT template_id FROM template WHERE template_name='201')),
  ('4x5',         4.03,  5.03, 0.02, 0.01, 0.03, (SELECT template_id FROM template WHERE template_name='201')),
  ('5.16x5.16',   5.19,  5.19, 0.02, 0.01, 0.03, (SELECT template_id FROM template WHERE template_name='201')),
  ('5x5',         5.03,  5.03, 0.02, 0.01, 0.03, (SELECT template_id FROM template WHERE template_name='201')),
  ('6.55x4.3',    6.58,  4.33, 0.02, 0.01, 0.03, (SELECT template_id FROM template WHERE template_name='201')),
  ('6x6',         6.03,  6.03, 0.02, 0.01, 0.03, (SELECT template_id FROM template WHERE template_name='201')),
  ('7x7',         7.03,  7.03, 0.02, 0.01, 0.03, (SELECT template_id FROM template WHERE template_name='201')),
  ('8x8',         8.03,  8.03, 0.02, 0.01, 0.03, (SELECT template_id FROM template WHERE template_name='201')),
  ('9x15',        9.03, 15.03, 0.02, 0.01, 0.03, (SELECT template_id FROM template WHERE template_name='201')),
  ('9x9',         9.03,  9.03, 0.02, 0.01, 0.03, (SELECT template_id FROM template WHERE template_name='201'));

-- ── Export template (ค่าเริ่มต้นของหน้า Export) ───────────────────────────
-- is_default = 1 → หน้าเว็บจะล็อกไม่ให้แก้/ลบ (Duplicate ได้อย่างเดียว)
-- ลำดับใน array คือลำดับคอลัมน์ที่จะออกในไฟล์ CSV
INSERT IGNORE INTO export_template (name, kind, columns_json, is_default) VALUES
  ('Default - All Column', 'csv',
   '["number_alpl","value_x","value_y","result","note","operator","measure_type","timestamp","part_number","handler","package_size","template_name","nominal_x","nominal_y","upper_tol","lower_tol","vendor","owner","po_number","description","recieve_date"]',
   1);

-- ── Part Number ──────────────────────────────────────────────────────────
-- package_size_id / handler_id หาให้อัตโนมัติผ่าน subquery จับคู่ชื่อ
-- offset_tol เป็น NOT NULL เหมือนกัน (ดู init.sql) — ยังไม่มีค่าจริงจากหน้างาน
-- ใส่ 0.03 ไว้ทุกแถวเป็นค่าชั่วคราวเช่นเดียวกับ package_size
INSERT IGNORE INTO part_number (part_number_name, package_size_id, handler_id, nominal_x, nominal_y, upper_tol, lower_tol, offset_tol) VALUES
  ('TL1400HT-0501-P-A', (SELECT package_size_id FROM package_size WHERE package_size='3.25x7.40'), (SELECT handler_id FROM handler WHERE handler_name='HT9046'),   3.28, 7.43, 0.02, 0.01, 0.03),
  ('TL775HT-0501-P-A',  (SELECT package_size_id FROM package_size WHERE package_size='3.5x3.75'),  (SELECT handler_id FROM handler WHERE handler_name='HT9046'),   3.53, 3.78, 0.02, 0.01, 0.03),
  ('TL805HT-0500-F-A',  (SELECT package_size_id FROM package_size WHERE package_size='3.5x3.75'),  (SELECT handler_id FROM handler WHERE handler_name='HT9046'),   3.53, 3.78, 0.03, 0.00, 0.03),
  ('TL1010HT-0501-P-A', (SELECT package_size_id FROM package_size WHERE package_size='3x3'),       (SELECT handler_id FROM handler WHERE handler_name='HT9046'),   3.02, 3.02, 0.02, 0.01, 0.03),
  ('TL722HT-0501-P-A',  (SELECT package_size_id FROM package_size WHERE package_size='3x3'),       (SELECT handler_id FROM handler WHERE handler_name='HT9046'),   3.03, 3.02, 0.02, 0.01, 0.03),
  ('TL733HT-0501-P-A',  (SELECT package_size_id FROM package_size WHERE package_size='3x3'),       (SELECT handler_id FROM handler WHERE handler_name='HT9046'),   3.03, 3.02, 0.02, 0.01, 0.03),
  ('TL1009HT-0501-P-A', (SELECT package_size_id FROM package_size WHERE package_size='3x3'),       (SELECT handler_id FROM handler WHERE handler_name='HT9046MX'), 3.02, 3.02, 0.02, 0.01, 0.03),
  ('TL774HT-0501-P-A',  (SELECT package_size_id FROM package_size WHERE package_size='3x3'),       (SELECT handler_id FROM handler WHERE handler_name='HT9046MX'), 3.03, 3.02, 0.02, 0.01, 0.03),
  ('TL391HT-0501-P-A1', (SELECT package_size_id FROM package_size WHERE package_size='3x3'),       (SELECT handler_id FROM handler WHERE handler_name='HT9046MX'), 3.03, 3.02, 0.02, 0.01, 0.03),
  ('TL1384HT-0501-P-A', (SELECT package_size_id FROM package_size WHERE package_size='3x4'),       (SELECT handler_id FROM handler WHERE handler_name='HT9046'),   3.03, 4.03, 0.02, 0.01, 0.03),
  ('TL776HT-0501-P-A',  (SELECT package_size_id FROM package_size WHERE package_size='4x4'),       (SELECT handler_id FROM handler WHERE handler_name='HT9046'),   4.03, 4.03, 0.02, 0.01, 0.03),
  ('TL777HT-0501-P-A',  (SELECT package_size_id FROM package_size WHERE package_size='4x4'),       (SELECT handler_id FROM handler WHERE handler_name='HT9046'),   4.03, 4.03, 0.02, 0.01, 0.03),
  ('TL370HT-0501-P-A1', (SELECT package_size_id FROM package_size WHERE package_size='4x4'),       (SELECT handler_id FROM handler WHERE handler_name='HT9046MX'), 4.03, 4.03, 0.02, 0.01, 0.03),
  ('TL778HT-0501-P-A',  (SELECT package_size_id FROM package_size WHERE package_size='5x5'),       (SELECT handler_id FROM handler WHERE handler_name='HT9046'),   5.03, 5.03, 0.02, 0.01, 0.03),
  ('TL779HT-0501-P-A',  (SELECT package_size_id FROM package_size WHERE package_size='5x5'),       (SELECT handler_id FROM handler WHERE handler_name='HT9046'),   5.03, 5.03, 0.02, 0.01, 0.03),
  ('TL1449HT-0501-P-A', (SELECT package_size_id FROM package_size WHERE package_size='5x5'),       (SELECT handler_id FROM handler WHERE handler_name='HT9046MX'), 5.03, 5.03, 0.02, 0.01, 0.03),
  ('TL371HT-0501-P-A1', (SELECT package_size_id FROM package_size WHERE package_size='5x5'),       (SELECT handler_id FROM handler WHERE handler_name='HT9046MX'), 5.03, 5.03, 0.02, 0.01, 0.03),
  ('TL781HT-0501-P-A',  (SELECT package_size_id FROM package_size WHERE package_size='7x7'),       (SELECT handler_id FROM handler WHERE handler_name='HT9046'),   7.03, 7.03, 0.02, 0.01, 0.03),
  ('TL1551HT-0501-P-A', (SELECT package_size_id FROM package_size WHERE package_size='7x7'),       (SELECT handler_id FROM handler WHERE handler_name='HT9046MX'), 7.03, 7.03, 0.02, 0.01, 0.03),
  ('TL392HT-0501-P-A1', (SELECT package_size_id FROM package_size WHERE package_size='7x7'),       (SELECT handler_id FROM handler WHERE handler_name='HT9046MX'), 7.03, 7.03, 0.02, 0.01, 0.03),
  ('TL392HT-0501-P-B',  (SELECT package_size_id FROM package_size WHERE package_size='7x7'),       (SELECT handler_id FROM handler WHERE handler_name='HT9046MX'), 7.03, 7.03, 0.02, 0.01, 0.03),
  ('TL782HT-0501-P-B',  (SELECT package_size_id FROM package_size WHERE package_size='8x8'),       (SELECT handler_id FROM handler WHERE handler_name='HT9046'),   8.03, 8.03, 0.02, 0.01, 0.03),
  ('TL783HT-0501-P-A1', (SELECT package_size_id FROM package_size WHERE package_size='8x8'),       (SELECT handler_id FROM handler WHERE handler_name='HT9046'),   8.03, 8.03, 0.02, 0.01, 0.03),
  ('TL393HT-0501-P-B1', (SELECT package_size_id FROM package_size WHERE package_size='8x8'),       (SELECT handler_id FROM handler WHERE handler_name='HT9046MX'), 8.03, 8.03, 0.02, 0.01, 0.03),
  ('TL1383HT-0501-P-A', (SELECT package_size_id FROM package_size WHERE package_size='9x9'),       (SELECT handler_id FROM handler WHERE handler_name='HT9046'),   9.03, 9.03, 0.02, 0.01, 0.03),
  ('TL784HT-0501-P-A1', (SELECT package_size_id FROM package_size WHERE package_size='9x9'),       (SELECT handler_id FROM handler WHERE handler_name='HT9046'),   9.03, 9.03, 0.02, 0.01, 0.03),
  ('TL754HT-0501-P-A',  (SELECT package_size_id FROM package_size WHERE package_size='9x9'),       (SELECT handler_id FROM handler WHERE handler_name='HT9046MX'),9.03, 9.03, 0.02, 0.01, 0.03);
