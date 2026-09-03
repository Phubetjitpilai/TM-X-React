import { useEffect, useRef, useState } from "react";
import { apiPost } from "../../api/client";

export type EntryMode = "IPM" | "New" | "Rework";

/** ค่าดิบจากช่องกรอกของ 1 กลุ่ม — key ตรงกับชื่อ field ใน GROUP_FIELDS */
export type GroupValues = Record<string, string>;

const FIELD_DEFS: Record<
  string,
  { label: string; type: "text" | "datalist" | "part_number" | "handler" | "select" | "date"; placeholder?: string }
> = {
  // ⚠ ยังรับหลายตัวคั่นด้วยจุลภาคได้เหมือนเดิม — แค่ตัดคำอธิบายออกจาก
  //   placeholder เพราะช่องแคบเกินกว่าจะแสดงจนจบ (ถูกตัดกลางคำ)
  //   ตัวอย่าง "201, 202, 203" สื่อเรื่องจุลภาคอยู่แล้วในตัว
  number_alpl:  { label: "ALPL", type: "text", placeholder: "เช่น 201, 202, 203" },
  package_size: { label: "Package Size", type: "datalist" },
  part_number:  { label: "Part Number", type: "part_number" },
  description:  { label: "Description", type: "text" },
  po_number:    { label: "PO Number", type: "text", placeholder: "ตัวเลขเท่านั้น" },
  vendor:       { label: "Vendor", type: "select" },
  owner:        { label: "Owner", type: "select" },
  receive_date: { label: "Receive Date", type: "date" },
  /** เครื่องทดสอบที่ ALPL ตัวนี้ติดตั้งอยู่ — cascade จาก Package Size เหมือน
   *  Part Number แต่คนละแหล่ง (package_size_handler ไม่ใช่ part_number) */
  handler:      { label: "Handler", type: "handler" },
};

/**
 * ⚠ ลำดับใน GROUP_FIELDS คือลำดับที่ช่องจะเรียงบนจอ (grid ไหลซ้าย→ขวา บน→ล่าง)
 *   จับคู่กับ `cols` แล้วได้ผังตามนี้ **ห้ามสลับลำดับโดยไม่ดูผังก่อน**
 *
 *     IPM (3 คอลัมน์)      [ ALPL | Package Size | Handler ]
 *
 *     New/Rework (3 คอลัมน์)
 *       แถว 1  [ ALPL      | Package Size | Part Number ]
 *       แถว 2  [ PO Number | Vendor       | Owner       ]
 *       แถว 3  [ Description (กว้าง 2 ช่อง)| Receive Date ]
 *
 * IPM ต้องมี Package Size ด้วย (ไม่ใช่ optional) — เกณฑ์ตัดสินและ template ของ
 * โหมด IPM มาจาก package_size ตรง ๆ ไม่ได้อ้อมผ่าน part_number
 *
 * ⚠ **Handler มีช่องให้กรอกเฉพาะ IPM** เพราะโหมดนั้นไม่มี part_number ให้ derive
 *   ส่วน New/Rework `setField` เติมค่าให้เองตอนเลือก Part Number แล้วส่งไป
 *   backend ด้วย — **แค่ไม่วาดช่องให้เห็น** เพราะเป็นช่องที่แก้ไม่ได้อยู่ดี
 *   มีไว้ก็กินที่แล้วทำให้ผู้ใช้สงสัยว่าทำไมกดไม่ได้
 *
 *   ⚠ ห้ามลบตรรกะใน `setField` ทิ้งตาม — ถ้าไม่ส่ง handler ไป ALPL ที่ลงทะเบียน
 *     ผ่าน New/Rework จะไม่มีเครื่องบันทึกไว้เลย (handler_id เป็น NULL)
 */
export const GROUP_FIELDS: Record<EntryMode, string[]> = {
  IPM: ["number_alpl", "package_size", "handler"],
  New: ["number_alpl", "package_size", "part_number",
        "po_number", "vendor", "owner",
        "description", "receive_date"],
  Rework: ["number_alpl", "package_size", "part_number",
           "po_number", "vendor", "owner",
           "description", "receive_date"],
};

// cols = จำนวนคอลัมน์ของ grid · span = ช่องไหนกินกว้างกว่า 1 คอลัมน์
// ส่งเข้า CSS ผ่านตัวแปร --cols เพื่อให้ media query ยุบเหลือ 1 คอลัมน์บนจอแคบได้
// (hardcode grid-template-columns ตรง ๆ จะ override ไม่ได้)
const GROUP_LAYOUT: Record<EntryMode, { cols: number; span: Record<string, number> }> = {
  IPM: { cols: 3, span: {} },
  New: { cols: 3, span: { description: 2 } },
  Rework: { cols: 3, span: { description: 2 } },
};

/** ช่องที่ถูก "ล็อก" หลังระบบเติมค่าจากข้อมูลที่ลงทะเบียนไว้
 *
 *  IPM    ล็อกเกือบหมด — ALPL ที่ลงทะเบียนแล้วมี config ครบอยู่แล้ว ไม่ควรแก้ที่นี่
 *  Rework ล็อกแค่ Package Size + Part Number — 2 ตัวนี้กำหนดเกณฑ์ OK/NG กับ
 *         template ของ TM-X ห้ามพิมพ์ผิด ส่วน Vendor/Owner/PO/Description ยังต้อง
 *         แก้ได้ เพราะนั่นคือสิ่งที่ฟอร์ม Rework มีไว้ทำ
 *  New    ไม่ล็อกอะไร — ALPL ต้องยังไม่มีในระบบอยู่แล้ว ไม่มีอะไรให้เติม
 */
const LOCKED_FIELDS: Record<EntryMode, string[]> = {
  // IPM ล็อก handler ด้วย **เฉพาะตอนที่ ALPL นั้นลงทะเบียนไว้แล้ว** (prefill เติมให้)
  // ถ้าเป็น ALPL ใหม่ ช่องจะว่างและเลือกได้ตามปกติ — ดู prefillGroup
  IPM: ["package_size", "part_number", "vendor", "owner", "po_number", "description", "handler"],
  // ⚠ ไม่มี handler ใน New/Rework เพราะ **ไม่มีช่องนั้นให้ล็อกแล้ว** (ดู GROUP_FIELDS)
  //   `setField` ยังเติมค่าให้เบื้องหลังอยู่ แต่ผู้ใช้ไม่เห็นและแตะไม่ได้ตั้งแต่ต้น
  //   ถ้าใส่ไว้จะเป็นรายการที่ไม่มีผลอะไรเลย แล้วคนอ่านต่อจะเข้าใจผิดว่ามีช่องอยู่
  Rework: ["package_size", "part_number"],
  New: [],
};

/** field ที่เว้นว่างได้ — นอกจากนี้บังคับกรอกหมด
 *
 *  ใช้ 2 ที่: ป้าย required ในฟอร์ม (`EntryGroups` บรรทัด ~371) และด่าน validate
 *  ตอนกด Start (`PartEntryModal` บรรทัด ~161) — แก้ที่นี่ที่เดียวได้ทั้งคู่
 *
 *  ⚠ ตอนนี้ **ว่างทั้ง 3 โหมด = บังคับกรอกทุกช่อง** · `receive_date` เคยเว้นว่าง
 *    ได้ในโหมด New แต่ถอดออกแล้ว เพราะ `_insert_part_row` ส่ง `NULL` ลง DB ตรง ๆ
 *    เมื่อไม่ได้กรอก (ไม่ได้ตกไปใช้ `DEFAULT CURRENT_TIMESTAMP`) แถวนั้นจึงโชว์
 *    Receive Date ว่างเปล่าในหน้า Edit ตลอดไป · ฝั่ง Rework บังคับอยู่แล้ว
 */
export const OPTIONAL_FIELDS: Record<EntryMode, string[]> = {
  IPM: [], New: [], Rework: [],
};

export function emptyGroup(mode: EntryMode): GroupValues {
  return Object.fromEntries(GROUP_FIELDS[mode].map((f) => [f, ""]));
}

interface Props {
  mode: EntryMode;
  groups: GroupValues[];
  onChange: (next: GroupValues[]) => void;
  disabled?: boolean;
  errors?: Record<number, Record<string, string>>;
  /** แจ้งเมื่อระบบเขียนทับค่าที่ผู้ใช้พิมพ์เอง — หน้าแม่เอาไปขึ้น toast */
  onOverwrite?: (message: string) => void;
  options: {
    vendor: string[];
    owner: string[];
    packageSize: string[];
    /** part number ที่เลือกได้ ขึ้นกับ package size ของกลุ่มนั้น */
    partNumbersFor: (packageSize: string) => string[];
    /** เครื่องที่ package size นั้นลงได้ — มาจากตาราง package_size_handler
     *  ใช้เป็นตัวเลือกของช่อง Handler ในโหมด IPM */
    handlersFor: (packageSize: string) => string[];
    /** เครื่องของ part number นั้น — ใช้เติมช่อง Handler ให้อัตโนมัติในโหมด
     *  New/Rework คืน "" ถ้าไม่รู้จัก part number นั้น */
    handlerOfPartNumber: (partNumber: string) => string;
  };
}

export default function EntryGroups({ mode, groups, onChange, disabled, errors, options, onOverwrite }: Props) {
  // กลุ่มไหนถูกย่ออยู่ — เก็บเป็น index เพราะกลุ่มไม่มี id ของตัวเอง
  const [collapsed, setCollapsed] = useState<Set<number>>(new Set());

  /* กลุ่มไหนมี error ต้องกางออกเสมอ
   *
   * ⚠ เคยเป็นบั๊กจริง: ผู้ใช้กรอกกลุ่มที่ 2 ครบแล้วยุบกลุ่มที่ 1 ไว้ พอกด Save
   *   แล้วกลุ่มที่ 1 ยังมีช่องว่าง handleSave จะ return ทันที **โดยที่ error
   *   ไปแสดงอยู่ในกลุ่มที่มองไม่เห็น** — อาการที่เห็นคือ "กด Save แล้วไม่มีอะไรเกิดขึ้น"
   *   หาสาเหตุไม่เจอเลยเพราะไม่มีอะไรผิดตรงที่ตาเห็น
   */
  useEffect(() => {
    const bad = Object.keys(errors ?? {}).map(Number);
    if (!bad.length) return;
    setCollapsed((prev) => {
      if (!bad.some((gi) => prev.has(gi))) return prev;   // กางอยู่แล้ว ไม่ต้อง setState ซ้ำ
      const next = new Set(prev);
      bad.forEach((gi) => next.delete(gi));
      return next;
    });
  }, [errors]);
  const layout = GROUP_LAYOUT[mode];
  const fields = GROUP_FIELDS[mode];

  /** ช่องไหนของกลุ่มไหนที่ "ระบบเป็นคนเติม" — ใช้แยกจากของที่ผู้ใช้พิมพ์เอง
   *  เก็บเป็น ref ไม่ใช่ state เพราะเป็นข้อมูลประกอบ ไม่ได้ทำให้ต้องวาดใหม่เอง
   *  (การวาดใหม่มาจาก groups ที่เปลี่ยนอยู่แล้ว) */
  const autoRef = useRef<Record<number, Set<string>>>({});
  const timers = useRef<Record<number, number>>({});

  /** groups ล่าสุดเสมอ — **ห้ามใช้ตัวแปร `groups` ใน prefillGroup เด็ดขาด**
   *
   *  prefillGroup ถูกเรียกจาก setTimeout + await จึงปิดทับ (closure) ค่า `groups`
   *  ของ render ตอนที่ตั้ง timer ไว้ กว่าจะได้ผลกลับมาผู้ใช้พิมพ์ต่อไปแล้ว
   *  ถ้าเอาก้อนเก่าทั้งก้อนมา onChange สิ่งที่พิมพ์ระหว่างรอจะถูกเขียนทับหายไป
   *
   *  อาการที่เจอจริง: พิมพ์ "400" แล้วช่องเด้งกลับเป็น "40" เพราะ timer ของ
   *  "40" ยิงทีหลังแล้วเขียน state เก่ากลับลงไป
   */
  const groupsRef = useRef(groups);
  groupsRef.current = groups;

  /** ดึง config ของ ALPL ที่ลงทะเบียนไว้มาเติมให้อัตโนมัติ
   *
   *  ⚠ ถามทั้งกลุ่มทีเดียว ไม่ใช่ถามตัวแรกแล้วเหมาว่าตัวอื่นเหมือนกัน — ถ้าในกลุ่ม
   *    มีของคนละ Package Size อยู่ ช่องจะถูกเติมด้วยค่าของตัวแรกเงียบ ๆ แล้วผู้ใช้
   *    เห็นช่องมีค่าครบก็กด Start ต่อ กลายเป็นวัดทั้งกลุ่มด้วยเกณฑ์ของตัวแรกตัวเดียว
   *    (backend ดักได้ตอน Start แต่เสียเวลาไปแล้ว และค่าที่ถูกเติมให้ดูเหมือน
   *     "ระบบยืนยันแล้วว่าถูก" ซึ่งอันตรายกว่า)
   */
  async function prefillGroup(gi: number, alplRaw: string) {
    if (disabled || mode === "New") return;   // New: ALPL ต้องยังไม่มีอยู่แล้ว
    const nums = alplRaw
      .split(",").flatMap((p) => {
        const t = p.trim();
        if (/^\d+$/.test(t)) return [Number(t)];
        const m = t.match(/^(\d+)\s*-\s*(\d+)$/);
        if (!m) return [];
        const [a, b] = [Number(m[1]), Number(m[2])];
        return a <= b ? Array.from({ length: b - a + 1 }, (_, k) => a + k) : [];
      });
    const auto = autoRef.current[gi] ?? new Set<string>();

    // ALPL ว่าง/รูปแบบผิด → ล้างเฉพาะของที่ระบบเคยเติม แล้วปลดล็อก
    // (ถ้าปล่อยค้าง ช่องที่ล็อกจะถือค่าของ ALPL ชุดเก่าไว้ทั้งที่เลขเปลี่ยนไปแล้ว)
    if (!nums.length) {
      if (auto.size) {
        onChange(groupsRef.current.map((g, i) =>
          i === gi ? { ...g, ...Object.fromEntries([...auto].map((f) => [f, ""])) } : g));
        autoRef.current[gi] = new Set();
      }
      return;
    }

    let detail: Record<string, Record<string, unknown>>;
    let exists: number[];
    try {
      const res = await apiPost<{ exists: number[]; detail: Record<string, Record<string, unknown>> }>(
        "/api/parts/check", { alpl: nums },
      );
      exists = res.exists ?? [];
      detail = res.detail ?? {};
    } catch { return; }

    const known = exists.map((a) => detail[String(a)]).filter(Boolean);
    if (!known.length) {
      if (auto.size) {
        onChange(groupsRef.current.map((g, i) =>
          i === gi ? { ...g, ...Object.fromEntries([...auto].map((f) => [f, ""])) } : g));
        autoRef.current[gi] = new Set();
      }
      return;
    }

    /** ค่าของ field นี้ตรงกันทุกตัวที่ลงทะเบียนแล้วไหม — ไม่ตรงคืน null
     *  ALPL ที่ยังไม่ลงทะเบียนไม่นับ (จะถูกสร้างด้วย config ของกลุ่มนี้อยู่แล้ว) */
    const agreed = (f: string): string | null => {
      const vals = new Set(known.map((d) => (d[f] == null ? null : String(d[f]))));
      return vals.size === 1 ? [...vals][0] : null;
    };

    const fields = GROUP_FIELDS[mode];
    const lockable = LOCKED_FIELDS[mode];
    const g = groupsRef.current[gi] ?? {};
    const patch: Record<string, string> = {};
    const overwritten: string[] = [];
    const nextAuto = new Set(auto);

    for (const f of ["package_size", "part_number", "vendor", "owner", "po_number", "description", "handler"]) {
      if (!fields.includes(f)) continue;        // โหมดนี้ไม่มีช่องนั้น
      const v = agreed(f);
      const wasAuto = auto.has(f);

      if (v == null || v === "") {
        // ⚠ ล้างเฉพาะของที่ "ระบบเคยเติมเอง" — ของที่ผู้ใช้พิมพ์เองห้ามแตะ
        //   โหมด IPM อนุญาตให้กรอก ALPL ที่ยังไม่มีในระบบ แล้วผู้ใช้ต้องพิมพ์
        //   Package Size เอง ถ้าล้างด้วยจะพิมพ์เท่าไรก็หายทุกครั้ง
        if (wasAuto) { patch[f] = ""; nextAuto.delete(f); }
        continue;
      }

      // ── มีค่าที่ลงทะเบียนไว้ → เขียนทับเสมอ แล้วล็อกช่อง ──────────────────
      // เดิมมีกฎ "ของที่ผู้ใช้พิมพ์เองห้ามแตะ" ซึ่งทำให้ผลต่างกันตามลำดับที่กรอก
      //   กรอก ALPL ก่อน        → ช่องว่าง → เติม + ล็อก
      //   กรอก Package Size ก่อน → ไม่ว่าง → ข้าม แล้วไปโผล่เป็น error ตอน Start
      // ตอนนี้ยึด "ข้อมูลที่ลงทะเบียนไว้เป็นความจริงเสมอ" กรอกลำดับไหนผลก็เท่ากัน
      if (!wasAuto && (g[f] ?? "") && String(g[f]) !== v) overwritten.push(`${f} ${g[f]} → ${v}`);
      patch[f] = v;
      if (lockable.includes(f)) nextAuto.add(f);
    }

    autoRef.current[gi] = nextAuto;
    if (Object.keys(patch).length) {
      // ⚠ ต้อง groupsRef ไม่ใช่ groups — เก็บสิ่งที่ผู้ใช้พิมพ์ระหว่างรอผลไว้
      onChange(groupsRef.current.map((gg, i) => (i === gi ? { ...gg, ...patch } : gg)));
    }
    // บอกเสมอเมื่อทับของที่ผู้ใช้พิมพ์เอง — การเปลี่ยนค่าเงียบ ๆ คือสิ่งที่อันตราย
    // ที่สุด ผู้ใช้พิมพ์ 5x5 ไว้แล้วอยู่ ๆ กลายเป็น 4x4 โดยไม่มีอะไรบอก จะไม่มีทาง
    // รู้เลยว่าค่าที่กด Start ไปคืออะไร · ไม่แจ้งตอนเติมช่องว่าง (ไม่มีอะไรถูกทับ)
    if (overwritten.length) {
      onOverwrite?.(`เปลี่ยนตามข้อมูลที่ลงทะเบียนไว้ของ ALPL — ${overwritten.join(" · ")}`);
    }
  }

  // ยิงหลังหยุดพิมพ์ 400ms — ไม่งั้น "400" จะกลายเป็น 3 request (4 → 40 → 400)
  // และค่าจะกระพริบเพราะ ALPL 4/40 อาจมีจริงแต่คนละขนาด
  function schedulePrefill(gi: number) {
    window.clearTimeout(timers.current[gi]);
    // อ่านค่าจาก ref ตอน timer ยิง ไม่ใช่ตอนตั้ง — ไม่งั้นถาม DB ด้วยเลขที่
    // ล้าสมัยไปแล้ว (ตั้งตอนพิมพ์ "40" แต่ตอนยิงผู้ใช้พิมพ์ "400" ไปแล้ว)
    timers.current[gi] = window.setTimeout(
      () => prefillGroup(gi, groupsRef.current[gi]?.number_alpl ?? ""), 400,
    );
  }
  useEffect(() => () => Object.values(timers.current).forEach((t) => window.clearTimeout(t)), []);

  /** เปลี่ยนค่าช่องหนึ่ง — พร้อม cascade ที่ต้องเกิดตามทันที
   *
   *  New/Rework: เลือก Part Number แล้ว **Handler ต้องตามมาเอง** เพราะ
   *  `part_number` ผูก `handler_id` ของตัวเองไว้ตั้งแต่ในตาราง catalog แล้ว
   *  (ดู init.sql) การให้ผู้ใช้เลือกเองจะเปิดช่องให้ 2 แหล่งขัดกัน
   *
   *  ⚠ ต้องล้าง Handler ด้วยเมื่อ Part Number ถูกล้าง ไม่งั้นช่องจะค้างค่าของ
   *    part ตัวเก่าไว้ทั้งที่ผู้ใช้เปลี่ยนไปแล้ว — เป็นค่าที่ผิดแบบเงียบสนิท
   */
  const setField = (gi: number, key: string, v: string) => {
    const patch: Record<string, string> = { [key]: v };
    if (key === "part_number" && mode !== "IPM") {
      // ⚠ `handler` ไม่ได้อยู่ใน GROUP_FIELDS ของ New/Rework — จงใจไม่วาดช่อง
      //   แต่ค่ายังต้องติดไปกับกลุ่มเพื่อส่งให้ backend (handleSave ส่ง `{...g}`
      //   ทั้งก้อน ไม่ได้กรองตาม GROUP_FIELDS) **ห้ามลบบล็อกนี้ตามช่องที่หายไป**
      //   ไม่งั้น ALPL ที่ลงทะเบียนผ่าน New/Rework จะได้ handler_id = NULL
      patch.handler = v ? options.handlerOfPartNumber(v) : "";
      // ไม่ต้องแตะ autoRef แล้ว — ไม่มีช่องให้ล็อก (ดู LOCKED_FIELDS)
    }
    onChange(groups.map((g, i) => (i === gi ? { ...g, ...patch } : g)));
  };

  const addGroup = () => onChange([...groups, emptyGroup(mode)]);

  const delGroup = (gi: number) => {
    onChange(groups.filter((_, i) => i !== gi));
    // index ของกลุ่มที่อยู่หลังตัวที่ลบจะเลื่อนขึ้น 1 — ต้องเลื่อนสถานะย่อตาม
    // ไม่งั้นกลุ่มที่ไม่เกี่ยวจะถูกย่อแทนแบบไม่มีสาเหตุ
    setCollapsed((prev) => {
      const next = new Set<number>();
      prev.forEach((i) => { if (i < gi) next.add(i); else if (i > gi) next.add(i - 1); });
      return next;
    });
    /* ⚠ `autoRef` ก็ผูกกับ index เหมือนกัน ต้องเลื่อนตามด้วย — ตกหล่นแล้วกลุ่ม
       ที่ไม่เกี่ยวจะถูกล็อกช่องแทน (อาการเดียวกับ collapsed ข้างบนเป๊ะ)
       ลบกลุ่ม 1 จาก 3 กลุ่ม → กลุ่ม 2,3 เลื่อนเป็น 1,2 แต่ autoRef ยังชี้ที่เดิม */
    const shifted: Record<number, Set<string>> = {};
    Object.entries(autoRef.current).forEach(([k, v]) => {
      const i = Number(k);
      if (i < gi) shifted[i] = v;
      else if (i > gi) shifted[i - 1] = v;
    });
    autoRef.current = shifted;
    /* timer ของ debounce ก็เช่นกัน — ยกเลิกตัวที่ค้างของกลุ่มที่ลบทิ้ง ไม่งั้น
       มันจะยิง prefill ด้วย index ที่ตอนนี้เป็นของกลุ่มอื่นไปแล้ว */
    window.clearTimeout(timers.current[gi]);
    delete timers.current[gi];
  };

  const toggle = (gi: number) =>
    setCollapsed((prev) => {
      const next = new Set(prev);
      next.has(gi) ? next.delete(gi) : next.add(gi);
      return next;
    });

  /** สรุปกลุ่มแบบย่อ ไว้โชว์บนหัวตอนพับ — เห็นได้ว่ากลุ่มไหนคืออะไรโดยไม่ต้องกาง */
  const summaryOf = (g: GroupValues) => {
    const alpl = (g.number_alpl ?? "").trim();
    if (!alpl) return "ยังไม่ได้กรอก ALPL";
    const extra = [g.package_size, g.part_number].filter(Boolean).join(" · ");
    return extra ? `${alpl} — ${extra}` : alpl;
  };

  return (
    <>
      {groups.map((g, gi) => {
        const isCollapsed = collapsed.has(gi);
        return (
          <div key={gi} className={`entry-group${isCollapsed ? " collapsed" : ""}`}>
            <div className="entry-group-head" onClick={() => toggle(gi)}>
              <span className="entry-group-title">กลุ่มที่ {gi + 1}</span>
              <span className="entry-group-sum">{summaryOf(g)}</span>
              {/* เตือนที่หัวกลุ่มด้วย เผื่อผู้ใช้ยุบกลับเองหลังเห็น error แล้ว */}
              {errors?.[gi] && <span className="entry-group-badge">ยังกรอกไม่ครบ</span>}
              {/* ลบได้เฉพาะตอนมีมากกว่า 1 กลุ่ม — ลบกลุ่มสุดท้ายทิ้งแล้วฟอร์มจะว่าง
                  โดยไม่มีทางกรอกอะไรได้เลย */}
              {groups.length > 1 && !disabled && (
                <button
                  type="button"
                  className="entry-group-del"
                  title="ลบกลุ่มนี้"
                  onClick={(e) => { e.stopPropagation(); delGroup(gi); }}
                >
                  ✕ ลบกลุ่ม
                </button>
              )}
              <span className="entry-group-arrow">{isCollapsed ? "▸" : "▾"}</span>
            </div>

            <div className="entry-group-body">
              <div
                className="entry-form-grid"
                style={{ ["--cols" as string]: layout.cols }}
              >
                {fields.map((f) => {
                  const def = FIELD_DEFS[f];
                  const required = !OPTIONAL_FIELDS[mode].includes(f);
                  const err = errors?.[gi]?.[f];
                  const span = layout.span[f];
                  const val = g[f] ?? "";
                  // ช่องที่ระบบเติมให้จากข้อมูลที่ลงทะเบียนไว้ — ล็อกไม่ให้แก้ที่นี่
                  const locked = !!autoRef.current[gi]?.has(f);
                  return (
                    <div
                      key={f}
                      className={`form-group${span ? " span-2" : ""}`}
                      style={span ? { gridColumn: `span ${span}` } : undefined}
                    >
                      <label>
                        {def.label}
                        {required && <span className="req">*</span>}
                      </label>

                      {def.type === "select" ? (
                        <select
                          className={`${err ? "invalid" : ""}${locked ? " auto-locked" : ""}`.trim() || undefined}
                          disabled={disabled || locked}
                          value={val}
                          onChange={(e) => setField(gi, f, e.target.value)}
                        >
                          {/* disabled hidden = โชว์ตอนยังไม่ได้เลือก แต่ไม่โผล่
                              ในรายการตอนกดเปิด · vendor/owner เป็น required
                              ทุกโหมด (ดู OPTIONAL_FIELDS) จึงไม่ต้องเผื่อให้ล้างกลับ */}
                          <option value="" disabled hidden>-- เลือก {def.label} --</option>
                          {(f === "vendor" ? options.vendor : options.owner).map((o) => (
                            <option key={o} value={o}>{o}</option>
                          ))}
                        </select>
                      ) : def.type === "handler" ? (
                        /* Handler — ตัวเลือกมาจาก package_size_handler ของขนาดที่เลือกไว้
                           ในกลุ่มนี้ (คนละแหล่งกับ Part Number ที่มาจากตาราง part_number)
                           โหมด New/Rework ช่องนี้จะถูกล็อกเสมอเพราะ setField เติมให้เอง
                           ตอนเลือก Part Number — ดู LOCKED_FIELDS */
                        <select
                          className={`${err ? "invalid" : ""}${locked ? " auto-locked" : ""}`.trim() || undefined}
                          disabled={disabled || locked || !g.package_size}
                          value={val}
                          onChange={(e) => setField(gi, f, e.target.value)}
                        >
                          {/* 3 สาเหตุที่เลือกไม่ได้ ต้องบอกให้ต่างกัน ไม่งั้นผู้ใช้
                              ไม่รู้ว่าต้องไปทำอะไรก่อน — โดยเฉพาะกรณีที่ 3 ที่ต้อง
                              ไปผูกเครื่องให้ขนาดนั้นที่หน้า Edit ก่อน */}
                          {!g.package_size ? (
                            <option value="">-- เลือก Package Size ก่อน --</option>
                          ) : options.handlersFor(g.package_size).length === 0 ? (
                            <option value="">-- ขนาดนี้ยังไม่ได้ผูกเครื่อง (ตั้งที่หน้า Edit) --</option>
                          ) : (
                            <>
                              <option value="" disabled hidden>-- เลือก Handler --</option>
                              {options.handlersFor(g.package_size).map((o) => (
                                <option key={o} value={o}>{o}</option>
                              ))}
                            </>
                          )}
                        </select>
                      ) : def.type === "part_number" ? (
                        // Part Number ขึ้นกับ Package Size ของ "กลุ่มนี้" — ยังไม่เลือก
                        // ขนาดก็ยังเลือกไม่ได้ บอกไว้ที่ placeholder ให้รู้ว่าต้องทำอะไรก่อน
                        <select
                          className={`${err ? "invalid" : ""}${locked ? " auto-locked" : ""}`.trim() || undefined}
                          disabled={disabled || locked || !g.package_size}
                          value={val}
                          onChange={(e) => setField(gi, f, e.target.value)}
                        >
                          {/* ⚠ ใส่ hidden เฉพาะตอนเลือก Package Size แล้ว — ตอนยังไม่เลือก
                              ตัวเลือกนี้เป็น **ตัวเดียวในลิสต์** ถ้าซ่อนด้วยจะได้ dropdown
                              ว่างเปล่าที่ไม่บอกอะไรเลย (select ถูก disabled อยู่แล้วตอนนั้น) */}
                          <option value="" disabled hidden={!!g.package_size}>
                            {g.package_size ? "-- เลือก Part Number --" : "-- เลือก Package Size ก่อน --"}
                          </option>
                          {options.partNumbersFor(g.package_size ?? "").map((o) => (
                            <option key={o} value={o}>{o}</option>
                          ))}
                        </select>
                      ) : def.type === "datalist" ? (
                        <>
                          <input
                            list="package-size-list"
                            className={`${err ? "invalid" : ""}${locked ? " auto-locked" : ""}`.trim() || undefined}
                            disabled={disabled || locked}
                            value={val}
                            onChange={(e) => setField(gi, f, e.target.value)}
                          />
                          <datalist id="package-size-list">
                            {options.packageSize.map((o) => <option key={o} value={o} />)}
                          </datalist>
                        </>
                      ) : (
                        <input
                          type={def.type === "date" ? "date" : "text"}
                          placeholder={def.placeholder}
                          className={`${err ? "invalid" : ""}${locked ? " auto-locked" : ""}`.trim() || undefined}
                          disabled={disabled || locked}
                          value={val}
                          onChange={(e) => {
                            setField(gi, f, e.target.value);
                            // พิมพ์ ALPL แล้วดึง config ของตัวที่ลงทะเบียนไว้มาเติมให้
                            if (f === "number_alpl") schedulePrefill(gi);
                          }}
                        />
                      )}

                      <div className="field-error">
                        {err ?? (locked
                          ? <span className="autofill-note">มาจากข้อมูลที่ลงทะเบียนไว้ — แก้ที่หน้า Edit › Parts</span>
                          : "")}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
        );
      })}

      {!disabled && (
        <div className="entry-group-add">
          <button type="button" className="btn-pe-action" onClick={addGroup}>
            + Add Group
          </button>
          <span className="entry-group-hint">
            1 กลุ่ม = ALPL ที่ใช้ข้อมูลชุดเดียวกัน (Package Size / Part Number / PO …)
          </span>
        </div>
      )}
    </>
  );
}
