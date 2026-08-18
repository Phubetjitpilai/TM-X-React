import MultiSelect from "../MultiSelect";

/** ช่องที่ติ๊กเลือกได้หลายค่า — ลำดับตรงกับ export.html เป๊ะ
 *
 *  ⚠ Package Size ต้องอยู่ "ก่อน" Part Number เพราะต้องเลือกขนาดก่อน แล้วรายการ
 *    Part Number จะถูกกรองตามขนาดที่เลือก (cascade) สลับที่กันแล้วผู้ใช้จะเจอ
 *    ช่อง Part Number ว่างเปล่าโดยไม่รู้ว่าต้องทำอะไรก่อน
 */
export const MULTI_KEYS = [
  { key: "result", label: "Result" },
  { key: "package_size", label: "Package Size" },
  { key: "part_number", label: "Part Number" },
  { key: "handler", label: "Handler" },
  { key: "operator", label: "Operator" },
  { key: "measure_type", label: "Measure Type" },
  { key: "vendor", label: "Vendor" },
  { key: "owner", label: "Owner" },
] as const;

export type MultiKey = (typeof MULTI_KEYS)[number]["key"];

export interface FilterState {
  latestOnly: boolean;
  dateFrom: string;
  dateTo: string;
  recvFrom: string;
  recvTo: string;
  alpl: string;
  poNumber: string;
  description: string;
  multi: Record<MultiKey, string[]>;
}

export const EMPTY_MULTI = Object.fromEntries(
  MULTI_KEYS.map((m) => [m.key, [] as string[]]),
) as Record<MultiKey, string[]>;

export const EMPTY_FILTERS: FilterState = {
  // ค่าเริ่มต้นคือ "เอาเฉพาะการวัดล่าสุดของแต่ละ ALPL" = สถานะปัจจุบัน
  // ซึ่งเป็นสิ่งที่คนอยากได้บ่อยที่สุด ติ๊กออกถ้าอยากได้ประวัติทุกครั้ง
  latestOnly: true,
  dateFrom: "", dateTo: "", recvFrom: "", recvTo: "",
  alpl: "", poNumber: "", description: "",
  multi: EMPTY_MULTI,
};

/** ตรวจรูปแบบช่อง ALPL — รับได้ทั้ง 400 / 400,500 / 400-407 / 400-407,500-507
 *
 *  ต้องเป็น type=text ไม่ใช่ number เพราะต้องพิมพ์ "-" กับ "," ได้
 *  (ตรงกับ _parse_int_ranges ฝั่ง backend)
 */
export function validateAlpl(raw: string): string | null {
  const s = raw.trim();
  if (!s) return null;
  if (!/^[\d\s,-]+$/.test(s)) return "ใส่ได้แค่ตัวเลข เครื่องหมาย , และ -";
  for (const part of s.split(",")) {
    const p = part.trim();
    if (!p) continue;
    if (/^\d+$/.test(p)) continue;
    const m = p.match(/^(\d+)\s*-\s*(\d+)$/);
    if (!m) return `รูปแบบไม่ถูกต้อง: "${p}"`;
    if (Number(m[1]) > Number(m[2])) return `ช่วงกลับหัว: "${p}"`;
  }
  return null;
}

/** แปลง state เป็น query params ที่ backend เข้าใจ
 *
 *  ⚠ multi-select ต้อง `append` ไม่ใช่ `set` — backend รับค่าซ้ำ key เดิมหลายตัว
 *    เป็น "หรือ" (ค่าในช่องเดียวกัน) ส่วนต่างช่องกันเป็น "และ"
 *  ⚠ วันที่ต้องครอบให้เต็มวัน — เลือก "ถึง 26/07" ต้องรวมข้อมูลของวันที่ 26
 *    ทั้งวัน ไม่ใช่หยุดที่ 00:00 ของวันนั้น (ไม่งั้นข้อมูลวันสุดท้ายหายทั้งวัน)
 */
export function toParams(f: FilterState, templateId: number | null): URLSearchParams {
  const p = new URLSearchParams();
  if (templateId != null) p.set("export_template_id", String(templateId));
  if (f.alpl.trim()) p.set("number_alpl", f.alpl.trim());
  if (f.poNumber.trim()) p.set("po_number", f.poNumber.trim());
  if (f.description.trim()) p.set("description", f.description.trim());
  if (f.dateFrom) p.set("date_from", `${f.dateFrom} 00:00:00`);
  if (f.dateTo) p.set("date_to", `${f.dateTo} 23:59:59`);
  if (f.recvFrom) p.set("recv_from", `${f.recvFrom} 00:00:00`);
  if (f.recvTo) p.set("recv_to", `${f.recvTo} 23:59:59`);
  MULTI_KEYS.forEach((m) => f.multi[m.key].forEach((v) => p.append(m.key, v)));
  p.set("latest_only", f.latestOnly ? "true" : "false");
  return p;
}

/** มีการกรองอะไรอยู่ไหม — ใช้ถามยืนยันตอนกด Export ทั้งก้อนโดยไม่กรองเลย */
export function hasAnyFilter(f: FilterState): boolean {
  if (f.alpl.trim() || f.poNumber.trim() || f.description.trim()) return true;
  if (f.dateFrom || f.dateTo || f.recvFrom || f.recvTo) return true;
  return MULTI_KEYS.some((m) => f.multi[m.key].length > 0);
}

interface Props {
  value: FilterState;
  onChange: (next: FilterState) => void;
  options: Record<MultiKey, string[]>;
  /** catalog part number พร้อม package size — ใช้ cascade กรอง Part Number */
  partNumberCatalog: { part_number_name: string; package_size: string }[];
  onClear: () => void;
  /** error เรื่อง ALPL ที่ backend เป็นคนตรวจเจอ (รูปแบบช่วงบางแบบซับซ้อนกว่าที่
   *  ฝั่งนี้รู้) — ต้องชี้ที่ช่อง ALPL เหมือนกัน ไม่ใช่ลอยอยู่บรรทัดอื่นให้ผู้ใช้
   *  ไล่หาเองว่าพิมพ์อะไรผิด */
  serverAlplError?: string | null;
}

export default function ExportFilters({
  value, onChange, options, partNumberCatalog, onClear, serverAlplError,
}: Props) {
  const set = <K extends keyof FilterState>(k: K, v: FilterState[K]) => onChange({ ...value, [k]: v });
  const setMulti = (k: MultiKey, v: string[]) => onChange({ ...value, multi: { ...value.multi, [k]: v } });

  // ของเราตรวจก่อน (ตอบทันทีขณะพิมพ์) ถ้าผ่านค่อยโชว์ของ backend
  const alplError = validateAlpl(value.alpl) ?? serverAlplError ?? null;

  // Part Number ถูกกรองตาม Package Size ที่เลือก — ยังไม่เลือกขนาด = ยังไม่ให้เลือก
  const pkgSelected = value.multi.package_size;
  const partOptions =
    pkgSelected.length === 0
      ? []
      : Array.from(
          new Set(
            partNumberCatalog
              .filter((r) => pkgSelected.includes(r.package_size))
              .map((r) => r.part_number_name),
          ),
        ).sort();

  return (
    <>
      {/* ตัวเลือกสำคัญที่สุดของหน้านี้ ยกไว้บนสุดแยกจาก filter อื่น */}
      <label className="latest-toggle">
        <input
          type="checkbox"
          checked={value.latestOnly}
          onChange={(e) => set("latestOnly", e.target.checked)}
        />
        <span>
          <strong>เฉพาะการวัดล่าสุดของแต่ละ ALPL</strong>
          <small>ติ๊กออกเพื่อเอาประวัติการวัดทุกครั้ง</small>
        </span>
      </label>

      <div className="filters">
        <div className="fg">
          <label>วันที่วัด — ตั้งแต่</label>
          <input type="date" value={value.dateFrom} onChange={(e) => set("dateFrom", e.target.value)} />
        </div>
        <div className="fg">
          <label>วันที่วัด — ถึง</label>
          <input type="date" value={value.dateTo} onChange={(e) => set("dateTo", e.target.value)} />
        </div>
        <div className="fg">
          <label>วันที่รับ — ตั้งแต่</label>
          <input type="date" value={value.recvFrom} onChange={(e) => set("recvFrom", e.target.value)} />
        </div>
        <div className="fg">
          <label>วันที่รับ — ถึง</label>
          <input type="date" value={value.recvTo} onChange={(e) => set("recvTo", e.target.value)} />
        </div>

        <div className="fg">
          <label>
            ALPL <span className="hint">ระบุช่วงได้</span>
          </label>
          <input
            type="text"
            className={alplError ? "bad" : undefined}
            placeholder="เช่น 400-407,500"
            value={value.alpl}
            onChange={(e) => set("alpl", e.target.value)}
          />
          <div className="err">{alplError ?? ""}</div>
        </div>

        {MULTI_KEYS.map((m) => (
          <MultiSelect
            key={m.key}
            label={m.label}
            options={m.key === "part_number" ? partOptions : (options[m.key] ?? [])}
            selected={value.multi[m.key]}
            onChange={(next) => setMulti(m.key, next)}
            hint={m.key === "part_number" ? "เลือก Package Size ก่อน" : undefined}
            emptyText={
              m.key === "part_number" && pkgSelected.length === 0
                ? "เลือก Package Size ก่อน"
                : "ไม่มีตัวเลือก"
            }
          />
        ))}

        <div className="fg">
          <label>PO Number</label>
          <input
            type="number"
            placeholder="ทั้งหมด"
            value={value.poNumber}
            onChange={(e) => set("poNumber", e.target.value)}
          />
        </div>
        <div className="fg">
          <label>Description</label>
          <input
            type="text"
            placeholder="พิมพ์บางส่วนได้"
            value={value.description}
            onChange={(e) => set("description", e.target.value)}
          />
        </div>
      </div>

      <div className="filters-actions">
        <button type="button" className="btn-ghost" onClick={onClear}>✕ ล้างตัวกรอง</button>
      </div>
    </>
  );
}
