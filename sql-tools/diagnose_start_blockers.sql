-- ============================================================================
-- Diagnose: ทำไมกด Start แล้วขึ้น "ยังไม่ได้ตั้ง Part Number"
-- ============================================================================
-- ตอน Start โหมด IPM backend ต้องหา template_name ให้ได้ โดยไล่ join 4 ทอด:
--
--   parts_specifications.part_number_id
--        -> part_number.package_size_id
--             -> package_size.template_id
--                  -> template.template_name
--
-- ขาดข้อไหนก็หาไม่เจอทั้งสาย — ไม่ใช่แค่ Part Number อย่างเดียว
-- สคริปต์นี้ไล่เช็คทีละข้อว่าข้อมูลขาดตรงไหนบ้าง (อ่านอย่างเดียว ไม่แก้ข้อมูล)
--
-- ⚠ ห้ามย้ายไฟล์นี้เข้า mysql-init/ — สคริปต์นี้ SELECT จากตารางที่ต้องมีอยู่
--   ก่อน ถ้าไปอยู่ในโฟลเดอร์ auto-run มันจะถูกรันก่อน init.sql (เรียงตามตัวอักษร)
--   แล้ว error 1146 ทำให้ init.sql/insert.sql ไม่ถูกรันเลย = ฐานข้อมูลว่างเปล่า
--
-- วิธีรัน:
--   Get-Content .\sql-tools\diagnose_start_blockers.sql | docker exec -i <container> mysql -uroot -p<รหัส> tmx_db
--
-- หมายเหตุเรื่อง encoding: ทุก statement ในไฟล์นี้เป็น ASCII ล้วน (ภาษาไทยอยู่แค่
--   ในคอมเมนต์) จึง pipe ผ่าน PowerShell ได้ปลอดภัย — ถ้าอยากให้คอมเมนต์ไทยไม่
--   เพี้ยนด้วย ใช้ docker cp แทน:
--     docker cp .\sql-tools\diagnose_start_blockers.sql tm-x_project-mysql-1:/tmp/s.sql
--     docker exec tm-x_project-mysql-1 sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" tmx_db < /tmp/s.sql'
-- ============================================================================

USE tmx_db;

-- ── 1) ALPL ที่ยังเริ่มวัดไม่ได้ พร้อมบอกว่าติดตรงไหน ────────────────────
SELECT
  p.number_alpl                                  AS ALPL,
  COALESCE(pn.part_number_name, '(none)')        AS part_number,
  COALESCE(ps.package_size,     '(none)')        AS package_size,
  COALESCE(t.template_name,     '(none)')        AS template,
  CASE
    -- ข้อความเป็นอังกฤษเพราะ PowerShell pipe ทำตัวอักษรไทยเพี้ยน (ดูหัวไฟล์)
    WHEN p.part_number_id   IS NULL THEN '1. part has no Part Number set'
    WHEN pn.part_number_id  IS NULL THEN '2. linked Part Number was deleted'
    WHEN pn.package_size_id IS NULL THEN '3. Part Number has no Package Size'
    WHEN ps.package_size_id IS NULL THEN '4. linked Package Size was deleted'
    WHEN ps.template_id     IS NULL THEN '5. Package Size has no Template  <-- most common'
    WHEN t.template_id      IS NULL THEN '6. linked Template was deleted'
  END                                            AS blocked_by
FROM parts_specifications p
LEFT JOIN part_number  pn ON p.part_number_id   = pn.part_number_id
LEFT JOIN package_size ps ON pn.package_size_id = ps.package_size_id
LEFT JOIN template     t  ON ps.template_id     = t.template_id
WHERE t.template_id IS NULL
ORDER BY p.number_alpl;

-- ── 2) Package Size ที่ยังไม่ได้ตั้ง Template ─────────────────────────────
-- (สร้างผ่านหน้า Edit › Lookup Tables โดยไม่ได้เลือก Template จะมาโผล่ตรงนี้)
SELECT package_size_id, package_size, '<- no Template selected' AS problem
  FROM package_size
 WHERE template_id IS NULL
 ORDER BY package_size;

-- ── 3) Part Number ที่ยังไม่ได้ผูก Package Size ───────────────────────────
SELECT part_number_id, part_number_name, '<- no Package Size selected' AS problem
  FROM part_number
 WHERE package_size_id IS NULL
 ORDER BY part_number_name;

-- ── 4) สรุปว่ามี ALPL กี่ตัวที่พร้อมวัด / ยังไม่พร้อม ─────────────────────
SELECT
  COUNT(*)                        AS total_alpl,
  SUM(t.template_id IS NOT NULL)  AS ready_to_measure,
  SUM(t.template_id IS NULL)      AS cannot_start
FROM parts_specifications p
LEFT JOIN part_number  pn ON p.part_number_id   = pn.part_number_id
LEFT JOIN package_size ps ON pn.package_size_id = ps.package_size_id
LEFT JOIN template     t  ON ps.template_id     = t.template_id;
