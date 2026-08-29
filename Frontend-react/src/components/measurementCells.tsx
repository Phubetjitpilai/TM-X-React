import type { ReactNode } from "react";

/* ── เซลล์ค่าที่วัดได้ ใช้ร่วมกันระหว่างตาราง Measurements ของหน้า Home
      (DashboardPage) กับหน้า Edit (EditPage) ──────────────────────────────

   ⚠ ต้องอยู่ที่เดียวจริง ๆ ห้ามก๊อปไปวางซ้ำในสองหน้า — เกณฑ์ตัดสินสี
     เขียว/แดง คือ "สิ่งที่คนหน้างานเชื่อ" ถ้าสองหน้าคิดไม่ตรงกันเมื่อไหร่
     จะกลายเป็นแถวเดียวกันแต่คนละสีในสองหน้าจอ แล้วไม่มีใครรู้ว่าอันไหนถูก

   ⚠ สูตรตรงนี้ต้องตรงกับ `_within_tolerance` / `_offset_ok` ฝั่ง backend
     ฝั่งนั้นบวก `_TOL_EPS` (1e-6) เผื่อความคลาดเคลื่อนของ float ไว้ด้วย
     ตรงนี้ยังไม่ได้บวก — ค่าที่อยู่ "ตรงขอบเป๊ะ" จึงมีโอกาสขึ้นสีแดงบนจอ
     ทั้งที่คอลัมน์ Result (ซึ่งมาจาก DB) บอกว่า OK
     ยังไม่แก้เพราะ Result เป็นตัวตัดสินจริงอยู่แล้ว สีเป็นแค่ตัวช่วยอ่าน   */

const EPS = 0;   // ← เปลี่ยนเป็น 1e-6 ถ้าอยากให้ตรงกับ backend เป๊ะ

/** ค่าที่วัดได้ 1 แกน — เขียว = อยู่ในเกณฑ์ · แดง = หลุด · ไม่มีเกณฑ์ = สีปกติ */
export function axisValue(
  v?: number | null,
  nominal?: number | null,
  upper?: number | null,
  lower?: number | null,
): ReactNode {
  if (v == null) return "—";
  const txt = Number(v).toFixed(3);
  if (nominal == null || upper == null || lower == null) return txt;
  const lo = nominal - lower;
  const hi = nominal + upper;
  const ok = v >= lo - EPS && v <= hi + EPS;
  return (
    <span className={ok ? "val-ok" : "val-ng"} title={`รับได้ ${lo.toFixed(3)} – ${hi.toFixed(3)}`}>
      {txt}
    </span>
  );
}

/** ระยะเยื้อง 1 แกน — เทียบกับเพดาน offset_tol (ไม่ใช่ช่วง nominal ± tol) */
export function offsetValue(v?: number | null, tol?: number | null): ReactNode {
  if (v == null) return "—";
  const txt = Number(v).toFixed(3);
  // tol เป็น null = โหมด IPM ที่ไม่เอา offset มาตัดสิน → ไม่ระบายสี
  if (tol == null) return txt;
  const ok = Math.abs(v) <= tol + EPS;
  return (
    <span className={ok ? "val-ok" : "val-ng"} title={`ไม่เกิน ${Number(tol).toFixed(3)}`}>
      {txt}
    </span>
  );
}

/** วางค่า 2 แกนไว้ในช่องเดียว คั่นด้วย " / " โดยแต่ละตัวระบายสีของตัวเอง
 *  — X ผ่านแต่ Y ไม่ผ่าน ต้องเห็นทันทีว่าแกนไหนเป็นตัวปัญหา */
export function xyPair(x: ReactNode, y: ReactNode): ReactNode {
  return (
    <span className="xy-pair">
      {x}
      <span className="xy-sep">/</span>
      {y}
    </span>
  );
}
