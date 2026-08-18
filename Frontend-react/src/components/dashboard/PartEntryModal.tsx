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
  onSave: (queue: EntryQueue) => void;
  onClose: () => void;
  /** ให้หน้าแม่ถามยืนยันก่อนลงทะเบียน ALPL ใหม่ (โหมด IPM)
   *  ส่ง package_size ของกลุ่มที่ ALPL นั้นอยู่ไปด้วย — ผู้ใช้ต้องเห็นว่ากำลังจะ
   *  ลงทะเบียนด้วยเกณฑ์ไหน ไม่ใช่เห็นแค่เลข ALPL แล้วกดตกลงไปโดยไม่รู้ */
  confirmRegister: (items: { alpl: number; package_size: string }[]) => Promise<boolean>;
  /** แจ้งเตือนทั่วไป (toast) — ใช้ตอน autofill เขียนทับค่าที่ผู้ใช้พิมพ์เอง */
  onNotify: (message: string) => void;
}

const MODES: EntryMode[] = ["IPM", "New", "Rework"];

export default function PartEntryModal({
  operators, vendors, owners, packageSizes, partNumbersFor,
  onSave, onClose, confirmRegister, onNotify,
}: Props) {
  const [mode, setMode] = useState<EntryMode>("IPM");
  const [operator, setOperator] = useState("");
  const [groups, setGroups] = useState<GroupValues[]>([emptyGroup("IPM")]);
  const [errors, setErrors] = useState<Record<number, Record<string, string>>>({});
  const [operatorError, setOperatorError] = useState("");
  const [busy, setBusy] = useState(false);

  // เปลี่ยนโหมด = ล้างกลุ่มทิ้ง เพราะ field คนละชุดกัน — เก็บของเดิมไว้แล้วโชว์
  // ในโหมดใหม่จะได้ค่าที่ไม่มีความหมาย (เช่น Part Number ที่ IPM ไม่ได้ใช้)
  function switchMode(next: EntryMode) {
    if (next === mode) return;
    setMode(next);
    setGroups([emptyGroup(next)]);
    setErrors({});
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
              onClick={() => switchMode(m)}
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
            <option value="">-- เลือก Operator --</option>
            {operators.map((o) => <option key={o} value={o}>{o}</option>)}
          </select>
          <div className="field-error">{operatorError}</div>
        </div>

        <EntryGroups
          mode={mode}
          groups={groups}
          onChange={setGroups}
          errors={errors}
          onOverwrite={onNotify}
          options={{ vendor: vendors, owner: owners, packageSize: packageSizes, partNumbersFor }}
        />

        <div className="entry-actions">
          <button type="button" className="btn-submit-entry" disabled={busy} onClick={handleSave}>
            ✓ Save
          </button>
        </div>
      </div>
    </div>
  );
}
