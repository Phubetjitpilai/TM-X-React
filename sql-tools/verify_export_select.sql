-- SELECT ตัวจริงหลังแก้ — ต้องรันผ่านและได้ 3 แถว
SELECT m.measurement_id, m.session_id, m.number_alpl, m.value_x, m.value_y,
           -- ⚠ ตาราง measurements **ไม่มีคอลัมน์ `offset` เดี่ยวแล้ว** — ถูกแยกเป็น
           --   offset_opx / offset_opy / offset_pos_op ตั้งแต่ตอนแก้ _judge ให้ตรวจ
           --   ทีละแกน แต่ SELECT ก้อนนี้ถูกลืมไว้ ทำให้ทุก export (CSV/PDF/Excel)
           --   ตายด้วย `Unknown column 'm.offset'` → หน้าเว็บขึ้น "ไม่มีข้อมูล"
           --   ส่วน COUNT(*) ยังผ่านเพราะไม่ได้แตะคอลัมน์นี้ จึงดูเหมือนตัวกรองปกติ
           m.offset_opx, m.offset_opy, m.offset_pos_op,
           -- ค่าที่ใช้ตัดสิน OK/NG คือแกนที่แย่ที่สุด (ทั้งสองแกนเทียบ limit เดียวกัน
           -- ดู _judge) — คอลัมน์ "Offset" ในเทมเพลตเก่าจึงหมายถึงตัวนี้
           GREATEST(ABS(m.offset_opx), ABS(m.offset_opy)) AS `offset`,
           m.result, m.note, m.measure_type, m.timestamp,
           op.operator_name,
           pn.part_number_name,
           CASE WHEN m.measure_type = 'IPM' THEN ps.nominal_x  ELSE pn.nominal_x  END AS nominal_x,
           CASE WHEN m.measure_type = 'IPM' THEN ps.nominal_y  ELSE pn.nominal_y  END AS nominal_y,
           CASE WHEN m.measure_type = 'IPM' THEN ps.upper_tol  ELSE pn.upper_tol  END AS upper_tol,
           CASE WHEN m.measure_type = 'IPM' THEN ps.lower_tol  ELSE pn.lower_tol  END AS lower_tol,
           CASE WHEN m.measure_type = 'IPM' THEN NULL          ELSE pn.offset_tol END AS offset_tol,
           h.handler_name, ps.package_size, t.template_name,
           v.vendor_name, o.owner_name,
           p.po_number, p.description, p.recieve_date

    FROM measurements m
    LEFT JOIN operator op             ON m.operator_id = op.operator_id
    LEFT JOIN parts_specifications p  ON m.number_alpl = p.number_alpl
    LEFT JOIN part_number pn          ON p.part_number_id = pn.part_number_id
    LEFT JOIN handler h               ON pn.handler_id = h.handler_id
    LEFT JOIN package_size ps         ON ps.package_size_id = COALESCE(p.package_size_id, pn.package_size_id)
    LEFT JOIN template t              ON ps.template_id = t.template_id
    LEFT JOIN vendor v                ON p.vendor_id = v.vendor_id
    LEFT JOIN owner o                 ON p.owner_id = o.owner_id
ORDER BY m.timestamp DESC
LIMIT 3;
