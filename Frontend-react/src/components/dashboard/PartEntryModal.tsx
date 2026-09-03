import { useState } from "react";
import { apiPost } from "../../api/client";
import EntryGroups, {
  GROUP_FIELDS, OPTIONAL_FIELDS, emptyGroup,
  type EntryMode, type GroupValues,
} from "./EntryGroups";

/** คิวที่พร้อมกด Start — โครงเดียวกันทั้ง 3 โหมด ต่างกันแค่ field ในกลุ่ม */
/** กลุ่มที่พร้อมส่ง backend — number_alpl ถูกแปลงเป็นลิสต์ตัวเลขแล้ว
 *  (ต่างจาก GroupValues ที่เป็นค่าดิบจากช่องกรอก) */
export type PayloadGroup = { number_alpl: number[]; [k: string]: string | number[] };

export interface EntryQueue {
  mode: EntryMode;
  operator: string;
  groups: PayloadGroup[];
  /** ALPL ทั้งหมดคลี่เรียงตามลำดับที่จะวัด — ใช้โชว์จำนวนและวาดแถบคิว */
  list: number[];
  session_id?: number | null;
}

/**
 * แยก "400, 401" หรือ "400-403" เป็นลิสต์ตัวเลข
 * รับรูปแบบเดียวกับที่ backend เข้าใจ (ดู _parse_int_ranges)
 */
export function parseAlplList(raw: string): { list: number[]; error: string | null } {
  const s = raw.trim();
  if (!s) return { list: [], error: "กรอก ALPL อย่างน้อย 1 ค่า" };
  const out: number[] = [];
  for (const part of s.split(",")) {
    const p = part.trim();
    if (!p) continue;
    if (/^\d+$/.test(p)) { out.push(Number(p)); continue; }
    const m = p.match(/^(\d+)\s*-\s*(\d+)$/);
    if (!m) return { list: [], error: `รูปแบบไม่ถูกต้อง: "${p}"` };
    const [a, b] = [Number(m[1]), Number(m[2])];
    if (a > b) return { list: [], error: `ช่วงกลับหัว: "${p}"` };
    for (let n = a; n <= b; n++) out.push(n);
  }
  if (!out.length) return { list: [], error: "กรอก ALPL อย่างน้อย 1 ค่า" };
  return { list: out, error: null };
}

interface Props {
  operators: string[];
  vendors: string[];
  owners: string[];
  packageSizes: string[];
  partNumbersFor: (packageSize: string) => string[];
  /** เครื่องที่ package size นั้นลงได้ (ตาราง package_size_handler) */
  handlersFor: (packageSize: string) => string[];
  /** เครื่องของ part number นั้น — ใช้เติมช่อง Handler อัตโนมัติใน New/Rework */
  handlerOfPartNumber: (partNumber: string) => string;
  onSave: (queue: EntryQueue) => void;
  onClose: () => void;
  /** ให้หน้าแม่ถามยืนยันก่อนลงทะเบียน ALPL ใหม่ (โหมด IPM)
   *  ส่ง package_size ของกลุ่มที่ ALPL นั้นอยู่ไปด้วย — ผู้ใช้ต้องเห็นว่ากำลังจะ
   *  ลงทะเบียนด้วยเกณฑ์ไหน ไม่ใช่เห็นแค่เลข ALPL แล้วกดตกลงไปโดยไม่รู้ */
  confirmRegister: (items: { alpl: number; package_size: string }[]) => Promise<boolean>;
  /** แจ้งเตือนทั่วไป (toast) — ใช้ตอน autofill เขียนทับค่าที่ผู้ใช้พิมพ์เอง */
  onNotify: (message: string) => void;
  /** ถามยืนยันก่อนสลับโหมดตอนฟอร์มมีข้อมูลค้าง — คืน false = ยกเลิก อยู่โหมดเดิม
   *
   *  ให้หน้าแม่เป็นคนถาม (ไม่ใช่ window.confirm ในนี้) เพราะ dialog ของโปรเจกต์
   *  อยู่ที่ DashboardPage ผ่าน useDialog — แบบเดียวกับ confirmRegister */
  confirmSwitch: (target: EntryMode, current: EntryMode) => Promise<boolean>;
  /** คิวเดิมที่จะเอามาเติมในฟอร์ม — `undefined` = เปิดฟอร์มเปล่า
   *
   *  ปุ่ม "✎ Edit" กับ "+ New Entry" ใช้ฟังก์ชันเปิด modal ตัวเดียวกัน แต่ปุ่มแรก
   *  จะโผล่เฉพาะตอนมีคิวอยู่ · ปุ่มหลังโผล่เฉพาะตอนไม่มี — ส่ง `entryQueue`
   *  เข้ามาตรง ๆ จึงถูกทั้งสองกรณีโดยไม่ต้องมีธงบอกโหมด
   */
  initial?: EntryQueue;
}

const MODES: EntryMode[] = ["IPM", "New", "Rework"];

/** แปลงคิวที่เก็บไว้ กลับเป็นค่าที่ฟอร์มใช้ได้
 *
 *  ⚠ สองชนิดนี้เก็บ ALPL คนละแบบ — `PayloadGroup.number_alpl` เป็น `number[]`
 *    (คลี่ช่วงแล้ว) ส่วนฟอร์มเป็น string ดิบที่ผู้ใช้พิมพ์
 *
 *  ⚠ **การแปลงกลับสูญข้อมูลรูปแบบ** — ถ้าผู้ใช้พิมพ์ "400-403" ตอนแรก มันถูก
 *    คลี่เป็น [400,401,402,403] ไปแล้วตั้งแต่ตอน Save เปิด Edit จึงเห็นเป็น
 *    "400, 401, 402, 403" ค่าถูกต้องทุกตัวแต่หน้าตาไม่เหมือนที่พิมพ์
 *    ถ้าจะให้เหมือนเป๊ะต้องเก็บ string ดิบไว้ใน EntryQueue อีกฟิลด์
 */
function toFormGroups(q: EntryQueue): GroupValues[] {
  return q.groups.map((g) => {
    const out: GroupValues = {};
    for (const [k, v] of Object.entries(g)) {
      out[k] = Array.isArray(v) ? v.join(", ") : String(v ?? "");
    }
    return out;
  });
}

export default function PartEntryModal({
  operators, vendors, owners, packageSizes, partNumbersFor, handlersFor, handlerOfPartNumber,
  onSave, onClose, confirmRegister, confirmSwitch, onNotify, initial,
}: Props) {
  /* ตั้งค่าเริ่มต้นจาก `initial` ครั้งเดียวตอน mount — พอเพียงเพราะหน้าแม่วาด
     modal นี้แบบ `{peModalOpen && <PartEntryModal .../>}` ทุกครั้งที่เปิดใหม่
     component จึงเกิดใหม่ทั้งตัวและ initializer ทำงานซ้ำเสมอ

     ⚠ ห้ามใช้ useEffect ซิงก์ `initial` เข้ามาทีหลัง — ระหว่างที่ผู้ใช้กำลัง
       พิมพ์อยู่ ถ้าคิวฝั่งแม่เปลี่ยน (เช่น SSE สั่งล้างคิวตอน session จบ)
       ของที่พิมพ์ค้างไว้จะโดนเขียนทับกลางคัน */
  const [mode, setMode] = useState<EntryMode>(initial?.mode ?? "IPM");
  const [operator, setOperator] = useState(initial?.operator ?? "");
  const [groups, setGroups] = useState<GroupValues[]>(() =>
    initial ? toFormGroups(initial) : [emptyGroup("IPM")],
  );
  const [errors, setErrors] = useState<Record<number, Record<string, string>>>({});
  const [operatorError, setOperatorError] = useState("");
  const [busy, setBusy] = useState(false);

  /** ฟอร์มมีข้อมูลที่จะหายไหม — ใช้ตัดสินว่าต้องถามยืนยันก่อนสลับโหมดไหม
   *
   *  ⚠ **ไม่นับ Operator** เพราะมันไม่ถูกล้างตอนสลับโหมด (ดู switchMode)
   *    ถ้านับด้วย จะกลายเป็นถามทุกครั้งหลังเลือก Operator แล้วทั้งที่ยังไม่ได้
   *    กรอกอะไรที่จะหายจริง
   */
  const formHasData = () =>
    groups.some((g) => Object.values(g).some((v) => (v ?? "").trim() !== ""));

  /** เปลี่ยนโหมด = ล้างกลุ่มทิ้ง เพราะ field คนละชุดกัน — เก็บของเดิมไว้แล้วโชว์
   *  ในโหมดใหม่จะได้ค่าที่ไม่มีความหมาย (เช่น Part Number ที่ IPM ไม่ได้ใช้)
   *
   *  ⚠ **ไม่ล้าง Operator** — คนที่ยืนวัดยังเป็นคนเดิม สลับโหมดไม่ได้แปลว่า
   *    เปลี่ยนคน (ฝั่ง vanilla เดิมล้างด้วย ซึ่งทำให้ต้องเลือกซ้ำทุกครั้ง
   *    โดยไม่ได้ประโยชน์ — ตั้งใจไม่ทำตาม)
   *
   *  ⚠ ถามเฉพาะตอนฟอร์มมีข้อมูลจริง ถ้ายังว่างให้สลับได้เลย — ไม่งั้นน่ารำคาญมาก
   *    ตอนคนแค่กดดูว่าโหมดไหนมีช่องอะไรบ้าง (ยกกติกานี้มาจาก vanilla ตรงๆ)
   */
  async function switchMode(next: EntryMode) {
    if (next === mode) return;
    if (formHasData() && !(await confirmSwitch(next, mode))) return;   // ยกเลิก = อยู่โหมดเดิม
    setMode(next);
    setGroups([emptyGroup(next)]);
    setErrors({});
    setOperatorError("");
  }

  async function handleSave() {
    const errs: Record<number, Record<string, string>> = {};
    let opErr = "";
    if (!operator.trim()) opErr = "เลือก Operator";

    // ── ตรวจทีละกลุ่ม ────────────────────────────────────────────────────
    const perGroupLists: number[][] = [];
    groups.forEach((g, gi) => {
      const ge: Record<string, string> = {};
      const { list, error } = parseAlplList(g.number_alpl ?? "");
      if (error) ge.number_alpl = error;
      perGroupLists[gi] = list;

      GROUP_FIELDS[mode].forEach((f) => {
        if (f === "number_alpl") return;
        if (OPTIONAL_FIELDS[mode].includes(f)) return;
        if (!(g[f] ?? "").trim()) ge[f] = "กรอกช่องนี้ก่อน";
      });
      if (mode !== "IPM" && (g.po_number ?? "").trim() && isNaN(Number(g.po_number)))
        ge.po_number = "ต้องเป็นตัวเลข";

      if (Object.keys(ge).length) errs[gi] = ge;
    });

    // ⚠ ALPL ห้ามซ้ำ "ข้ามกลุ่ม" ด้วย ไม่ใช่แค่ในกลุ่มเดียวกัน — ถ้าปล่อยให้ซ้ำ
    //   ชิ้นเดียวกันจะถูกวัด 2 ครั้งด้วย config คนละชุด แล้วอันหลังเขียนทับ Part
    //   ของอันแรกโดยที่ผู้ใช้ไม่รู้ตัว (backend ก็เช็คซ้ำ แต่บอกตั้งแต่ตรงนี้ดีกว่า)
    const seen = new Map<number, number>();
    perGroupLists.forEach((list, gi) => {
      list.forEach((n) => {
        if (seen.has(n) && seen.get(n) !== gi) {
          errs[gi] = { ...errs[gi], number_alpl: `ALPL ${n} ซ้ำกับกลุ่มที่ ${seen.get(n)! + 1}` };
        } else seen.set(n, gi);
      });
    });

    setErrors(errs);
    setOperatorError(opErr);
    if (opErr || Object.keys(errs).length) return;

    const all = perGroupLists.flat();

    // ── เช็คกับ DB ว่า ALPL มี/ไม่มี ตามเงื่อนไขของโหมด ────────────────────
    // IPM    ยังไม่มี → ถามยืนยันแล้วลงทะเบียนให้ตอนวัดจริง
    // New    มีอยู่แล้ว → บล็อก (กันเขียนทับ config เดิมที่มีประวัติ)
    // Rework ยังไม่มี → บล็อก (Rework ต้องเคยวัดมาก่อนเท่านั้น)
    setBusy(true);
    try {
      const res = await apiPost<{ exists: number[]; missing: number[] }>(
        "/api/parts/check", { alpl: all },
      );
      if (mode === "New" && res.exists.length) {
        setErrors({ 0: { number_alpl: `ALPL ${res.exists.join(", ")} ลงทะเบียนไปแล้ว` } });
        setBusy(false);
        return;
      }
      if (mode === "Rework" && res.missing.length) {
        setErrors({ 0: { number_alpl: `ALPL ${res.missing.join(", ")} ยังไม่ได้ลงทะเบียน — ไปลงที่แท็บ New ก่อน` } });
        setBusy(false);
        return;
      }
      if (mode === "IPM" && res.missing.length) {
        // หา package_size จากกลุ่มที่ ALPL ตัวนั้นอยู่ (ไม่ใช่กลุ่มแรกเสมอไป)
        const pkgOf = (a: number) => {
          const gi = perGroupLists.findIndex((list) => list.includes(a));
          return gi >= 0 ? (groups[gi]?.package_size ?? "") : "";
        };
        const ok = await confirmRegister(res.missing.map((a) => ({ alpl: a, package_size: pkgOf(a) })));
        if (!ok) { setBusy(false); return; }
      }
    } catch {
      // ถามไม่สำเร็จ (DB มีปัญหา) — ปล่อยผ่านให้ start_session เป็นคนตัดสินแทน
      // ดีกว่าบล็อกผู้ใช้ด้วยข้อมูลที่เราเองก็ไม่มี
    }
    setBusy(false);

    onSave({
      mode,
      operator: operator.trim(),
      // ส่ง number_alpl เป็น "ลิสต์ตัวเลข" ให้ backend ตรง ๆ ไม่ใช่ string ดิบ
      groups: groups.map((g, gi) => ({ ...g, number_alpl: perGroupLists[gi] })),
      list: all,
    });
  }

  return (
    <div className="modal-overlay open">
      <div className="pe-modal-box">
        <div className="pe-modal-header">
          <div className="card-title">Part Entry</div>
          <button className="pe-modal-close" title="Close" onClick={onClose}>✕</button>
        </div>

        <div className="entry-toggle">
          {MODES.map((m) => (
            <button
              key={m}
              type="button"
              className={`entry-toggle-btn${mode === m ? " active" : ""}`}
              /* ⚠ switchMode เป็น async (รอคำตอบจาก dialog) — ต้อง catch เอง
                 ไม่งั้นถ้ามันโยน exception จะกลายเป็น unhandled rejection ที่
                 ไม่มีอะไรแสดงบนจอเลย ผู้ใช้เห็นแค่ปุ่มกดแล้วไม่เกิดอะไรขึ้น */
              onClick={() => { switchMode(m).catch((e) => console.error("switchMode:", e)); }}
            >
              {m}
            </button>
          ))}
        </div>

        <div className="entry-session-hint">
          ℹ️ ลำดับ ALPL ที่กรอก (ไล่จากกลุ่มบนลงล่าง) คือลำดับที่ค่าที่วัดได้จะถูก map เข้าไป —
          1 กลุ่มคือ ALPL ที่ใช้ข้อมูลชุดเดียวกัน
        </div>

        {/* Operator อยู่นอกกลุ่ม ใช้ร่วมกันทั้ง session (คนวัดคนเดียวกัน) */}
        <div className="form-group" style={{ marginBottom: "1rem" }}>
          <label>Operator<span className="req">*</span></label>
          <select
            className={operatorError ? "invalid" : undefined}
            value={operator}
            onChange={(e) => setOperator(e.target.value)}
          >
            {/* disabled hidden = โชว์ตอนยังไม่ได้เลือก แต่ไม่โผล่ในรายการตอนกดเปิด */}
            <option value="" disabled hidden>-- เลือก Operator --</option>
            {operators.map((o) => <option key={o} value={o}>{o}</option>)}
          </select>
          <div className="field-error">{operatorError}</div>
        </div>

        <EntryGroups
          /* ⚠ key ผูกกับ mode — บังคับให้ component เกิดใหม่ทั้งตัวเมื่อสลับโหมด
             เพราะ EntryGroups ถือ state ภายในที่ผู้เรียกล้างให้ไม่ได้:
               autoRef   ช่องไหนถูกระบบเติมค่าให้แล้วล็อกไว้
               collapsed กลุ่มไหนถูกย่อ
               timers    debounce ของ prefill
             ถ้าไม่ใส่ ช่องที่ล็อกไว้ตอน IPM จะยังล็อกอยู่ในโหมด New ทั้งที่ค่าว่าง
             → กรอกไม่ได้ → Save ไม่ผ่าน และไม่มีอะไรมาปลดล็อกให้ด้วย เพราะ
             prefillGroup ออกตั้งแต่บรรทัดแรกเมื่อ mode === "New" */
          key={mode}
          mode={mode}
          groups={groups}
          onChange={setGroups}
          errors={errors}
          onOverwrite={onNotify}
          options={{ vendor: vendors, owner: owners, packageSize: packageSizes,
                     partNumbersFor, handlersFor, handlerOfPartNumber }}
        />

        <div className="entry-actions">
          <button type="button" className="btn-submit-entry" disabled={busy} onClick={handleSave}>
            ✓ Save
          </button>
          {/* บอกให้รู้ว่า Save ไม่ผ่านเพราะอะไร — ของเดิม handleSave แค่ return เงียบ ๆ
              ถ้าช่องที่ขาดอยู่ในกลุ่มที่ยุบไว้ ผู้ใช้จะไม่เห็นอะไรเลยว่าเกิดอะไรขึ้น */}
          {Object.keys(errors).length > 0 && (
            <span className="entry-actions-error">
              ยังกรอกไม่ครบใน{" "}
              {Object.keys(errors).map(Number).sort((a, b) => a - b)
                .map((gi) => `กลุ่มที่ ${gi + 1}`).join(" · ")}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
