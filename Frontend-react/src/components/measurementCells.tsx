import type { ReactNode } from "react";

/* ── เซลล์ค่าที่วัดได้ ใช้ร่วมกันระหว่างตาราง Measurements ของหน้า Home
      (DashboardPage) กับหน้า Edit (EditPage) ──────────────────────────────

   ⚠ ต้องอยู่ที่เดียวจริง ๆ ห้ามก๊อปไปวางซ้ำในสองหน้า — เกณฑ์ตัดสินสี
     เขียว/แดง คือ "สิ่งที่คนหน้างานเชื่อ" ถ้าสองหน้าคิดไม่ตรงกันเมื่อไหร่
     จะกลายเป็นแถวเดียวกันแต่คนละสีในสองหน้าจอ แล้วไม่มีใครรู้ว่าอันไหนถูก

   ⚠⚠ **ห้ามคำนวณ OK/NG เองที่นี่อีก** — รับ `ok` ที่ backend ตัดสินมาแล้ว
     เท่านั้น (`ok_x` / `ok_y` / `ok_offset` จาก `/api/measurements` และจาก
     SSE event `measurement`)

     เดิมไฟล์นี้คำนวณ `nominal ± tol` ใหม่เองโดยไม่ปัดทศนิยม ส่วน backend ปัด
     ด้วย `_DP` ผลคือชิ้นที่ตกขอบพอดีขึ้น **สีแดงบนจอแต่คอลัมน์ Result บอก OK**
     (เกิดจริงกับ ALPL ที่วัดได้ 8.05 บนเกณฑ์ 8.03 +0.02 — ขอบที่คำนวณจาก
     FLOAT ได้ 8.049999732… ซึ่งต่ำกว่า 8.050000190… ที่อ่านกลับมา)

     ค่าที่ส่งมาให้ยังเป็น `nominal`/`tol` อยู่ แต่ **ใช้แค่โชว์ช่วงใน tooltip
     เท่านั้น ห้ามเอาไปเทียบ** — ถ้าต้องเปลี่ยนกฎการตัดสิน ให้แก้ที่
     `_within_tolerance` / `_offset_ok` ใน `shared.py` ที่เดียว แล้วที่นี่
     ตามเองอัตโนมัติ                                                       */

/* ── จำนวนทศนิยมที่แสดงบนจอ ────────────────────────────────────────────────
   **แยกเป็น 2 ระดับโดยตั้งใจ ห้ามยุบเหลือค่าเดียว**

   `DP_MM`  ขนาดชิ้นงาน / nominal / tolerance — TM-X ถูกตั้งให้ออก 2 ตำแหน่ง
            แล้ว หลักที่ 3 จึงเป็น 0 ที่เติมให้เปล่า ๆ ทุกแถว สื่อความละเอียด
            ที่เครื่องไม่ได้ให้

   `DP_OFF` ระยะเยื้อง (offset_opx/opy) กับ offset_tol — อยู่ระดับ 0.0xx
            ⚠ ตัดเหลือ 2 ตำแหน่งเมื่อไหร่ `0.018` กับ `0.024` จะกลายเป็น
              `0.02` เท่ากันทั้งคู่ แล้วผัง OffsetMap ที่สเกลด้วย offset_tol
              จะอ่านไม่ได้เลยว่าใกล้หลุดแค่ไหน — คนละเรื่องกับความละเอียด
              ของ TM-X เพราะค่าพวกนี้เป็นผลต่างที่คำนวณมา ไม่ใช่ค่าที่อ่านตรง

   ⚠ ตัวเลขพวกนี้กระทบ **การแสดงผลอย่างเดียว** ไม่แตะเกณฑ์ตัดสิน OK/NG
     (ตัวตัดสินคือคอลัมน์ `result` จาก backend) — ค่าที่ปัดขึ้นบนจอแล้ว
     ดูเหมือนหลุดเกณฑ์ จึงยังขึ้นเขียวได้ตามปกติ ไม่ใช่บั๊ก                */
export const DP_MM  = 2;
export const DP_OFF = 2;

/** ค่าที่วัดได้ 1 แกน — เขียว = อยู่ในเกณฑ์ · แดง = หลุด · `ok` เป็น null = ไม่ระบายสี
 *
 *  `ok` มาจาก backend (`ok_x` / `ok_y`) — ⚠ **ห้ามคำนวณเอง** ดูหัวไฟล์
 *  `nominal`/`upper`/`lower` ใช้แค่เขียน tooltip บอกช่วงที่รับได้เท่านั้น
 */
export function axisValue(
  v?: number | null,
  nominal?: number | null,
  upper?: number | null,
  lower?: number | null,
  ok?: boolean | null,
): ReactNode {
  if (v == null) return "—";
  const txt = Number(v).toFixed(DP_MM);
  // ⚠ `ok == null` = backend ตัดสินไม่ได้ (ALPL ยังไม่ผูก package_size)
  //   ต่างจาก false ที่แปลว่าตรวจแล้วไม่ผ่าน — ห้ามระบายสีในกรณีนี้
  //   วาดเขียวให้ทั้งที่ไม่เคยตรวจจะชวนอ่านผิดว่าผ่าน
  if (ok == null) return txt;
  const range = nominal != null && upper != null && lower != null
    ? `รับได้ ${(nominal - lower).toFixed(DP_MM)} – ${(nominal + upper).toFixed(DP_MM)}`
    : undefined;
  return (
    <span className={ok ? "val-ok" : "val-ng"} title={range}>
      {txt}
    </span>
  );
}

/** ระยะเยื้อง 1 แกน — ⚠ ห้ามคำนวณเอง รับ `ok` จาก backend
 *
 *  ⚠⚠ **ต้องส่ง `ok_opx` / `ok_opy` (แยกรายแกน) ห้ามส่ง `ok_offset`** ซึ่งเป็น
 *    ผลรวมของทั้ง 2 แกน · เคยพลาดมาแล้ว: opx หลุด (0.05 > 0.03) แล้วช่อง opy
 *    ที่ผ่านอยู่ (0.03 ตกขอบพอดี) โดนแดงไปด้วยทั้งที่ตัวมันไม่ผิดอะไร
 *    `ok_offset` มีไว้ใช้กับผัง OffsetMap / ป้าย OK-NG ของทั้งการ์ดเท่านั้น
 */
export function offsetValue(
  v?: number | null,
  tol?: number | null,
  ok?: boolean | null,
): ReactNode {
  if (v == null) return "—";
  const txt = Number(v).toFixed(DP_OFF);
  // ok เป็น null = โหมด IPM ที่ไม่เอา offset มาตัดสิน หรือยังไม่ตั้ง tol
  if (ok == null) return txt;
  return (
    <span
      className={ok ? "val-ok" : "val-ng"}
      title={tol != null ? `ไม่เกิน ${Number(tol).toFixed(DP_OFF)}` : undefined}
    >
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
