-- 1) มีข้อมูลให้ export ไหม
SELECT COUNT(*) AS measurements_total FROM measurements;

-- 2) เทมเพลตที่หน้าเว็บเลือกมีจริงไหม
SELECT export_template_id, name, kind, is_default FROM export_template;

-- 3) คอลัมน์ที่ Export ต้องใช้มีครบไหม (ต้องเห็น offset / operator_id)
DESCRIBE measurements;

-- 4) query ตัวจริงที่ backend รัน (latest_only = ติ๊กอยู่)
SELECT COUNT(*) AS n 
    FROM measurements m
    LEFT JOIN operator op             ON m.operator_id = op.operator_id
    LEFT JOIN parts_specifications p  ON m.number_alpl = p.number_alpl
    LEFT JOIN part_number pn          ON p.part_number_id = pn.part_number_id
    LEFT JOIN handler h               ON pn.handler_id = h.handler_id
    LEFT JOIN package_size ps         ON ps.package_size_id = COALESCE(p.package_size_id, pn.package_size_id)
    LEFT JOIN template t              ON ps.template_id = t.template_id
    LEFT JOIN vendor v                ON p.vendor_id = v.vendor_id
    LEFT JOIN owner o                 ON p.owner_id = o.owner_id
 WHERE m.measurement_id IN (
    SELECT measurement_id FROM (
        SELECT m.measurement_id,
               ROW_NUMBER() OVER (
                   PARTITION BY m.number_alpl
                   ORDER BY m.timestamp DESC, m.measurement_id DESC
               ) AS rn
    FROM measurements m
    LEFT JOIN operator op             ON m.operator_id = op.operator_id
    LEFT JOIN parts_specifications p  ON m.number_alpl = p.number_alpl
    LEFT JOIN part_number pn          ON p.part_number_id = pn.part_number_id
    LEFT JOIN handler h               ON pn.handler_id = h.handler_id
    LEFT JOIN package_size ps         ON ps.package_size_id = COALESCE(p.package_size_id, pn.package_size_id)
    LEFT JOIN template t              ON ps.template_id = t.template_id
    LEFT JOIN vendor v                ON p.vendor_id = v.vendor_id
    LEFT JOIN owner o                 ON p.owner_id = o.owner_id
    ) AS latest WHERE latest.rn = 1
);
