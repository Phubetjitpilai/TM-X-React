import { useEffect, useState, type ReactNode } from "react";
import { apiDelete, apiGet, apiPatch, apiPost } from "../api/client";
import { useToast } from "./Toast";
import MultiSelectCell from "./MultiSelectCell";

/** ชนิดของช่องกรอกในตาราง lookup
 *  select-* = FK ไปตารางอื่น ต้องเลือกจากรายการที่มีจริงเท่านั้น ห้ามพิมพ์เอง
 */
type FieldType =
  | "text" | "number"
  | "select-template" | "select-package-size" | "select-handler"
  /** เลือกได้หลายค่า — เก็บใน state เป็นสตริงคั่นคอมมา แล้วแปลงเป็น array
   *  ตอนส่งไป backend (ดู `lookupToApiBody`) เพื่อไม่ต้องรื้อ state ทั้งไฟล์
   *  ที่เป็น Record<string, string> อยู่แล้ว */
  | "multi-handler";

interface LookupField {
  key: string;
  label: string;
  type?: FieldType;
  width?: string;
  /** ปล่อยว่างตอนกด Add ได้ไหม — default คือบังคับกรอกทุกช่อง */
  optional?: boolean;
}

interface LookupConfig {
  label: string;
  listUrl: string;
  basePath: string;
  idField: string;
  /** ความกว้างขั้นต่ำของทั้งตาราง — ตั้งเฉพาะตัวที่มีคอลัมน์เยอะ เพื่อให้เลื่อน
   *  ซ้าย-ขวาแทนการบีบคอลัมน์จนช่องตัวเลขแคบจนอ่านไม่ออก */
  minWidth?: string;
  fields: LookupField[];
}

// ยกจาก LOOKUP_CONFIG ใน edit.html ตรงๆ — field/label/width/type ตรงกันทุกตัว
const LOOKUP_CONFIG: Record<string, LookupConfig> = {
  operator: { label: "Operator", listUrl: "/api/operators", basePath: "/api/operators", idField: "operator_id",
    fields: [{ key: "operator_name", label: "Name", width: "260px" }] },
  owner: { label: "Owner", listUrl: "/api/owners", basePath: "/api/owners", idField: "owner_id",
    fields: [{ key: "owner_name", label: "Name", width: "260px" }] },
  vendor: { label: "Vendor", listUrl: "/api/vendors", basePath: "/api/vendors", idField: "vendor_id",
    fields: [{ key: "vendor_name", label: "Name", width: "260px" }] },
  handler: { label: "Handler", listUrl: "/api/handlers", basePath: "/api/handlers", idField: "handler_id",
    fields: [{ key: "handler_name", label: "Name", width: "260px" }] },
  template: { label: "Template", listUrl: "/api/templates", basePath: "/api/templates", idField: "template_id",
    fields: [{ key: "template_name", label: "Name", width: "260px" }] },
  package_size: { label: "Package Size", listUrl: "/api/package-sizes", basePath: "/api/package-sizes",
    idField: "package_size_id", minWidth: "1320px",
    fields: [
      { key: "package_size", label: "Package Size", width: "170px" },
      { key: "nominal_x", label: "Nominal X", type: "number", width: "140px" },
      { key: "nominal_y", label: "Nominal Y", type: "number", width: "140px" },
      { key: "upper_tol", label: "Upper Tol", type: "number", width: "140px" },
      { key: "lower_tol", label: "Lower Tol", type: "number", width: "140px" },
      { key: "offset_tol", label: "Offset Tol", type: "number", width: "140px" },
      { key: "template_name", label: "Template", type: "select-template", width: "150px" },
      /* ⚠ optional โดยตั้งใจ — ตอนเพิ่มขนาดใหม่มักยังไม่รู้ว่าลงเครื่องไหนได้บ้าง
         ถ้าบังคับ จะเพิ่ม Package Size ไม่ได้เลยจนกว่าจะไปถามหน้างานก่อน */
      { key: "handlers", label: "Handlers", type: "multi-handler", width: "210px", optional: true },
    ] },
  /* ⚠ ตารางนี้ **ไม่มีช่อง nominal/tolerance แล้ว** — part_number ไม่ได้ถือเกณฑ์
     ตัดสินอีกต่อไป ทุกโหมดใช้ของ Package Size (ดู `_load_criteria` ฝั่ง backend)
     ถ้าจะแก้เกณฑ์ ให้ไปแก้ที่ตาราง Package Size ด้านบนแทน
     minWidth ลดจาก 1420px เพราะเหลือ 3 คอลัมน์ ไม่ต้องเลื่อนแนวนอนอีก */
  part_number: { label: "Part Number", listUrl: "/api/part-numbers/all", basePath: "/api/part-numbers",
    idField: "part_number_id", minWidth: "700px",
    fields: [
      { key: "part_number_name", label: "Part Number", width: "230px" },
      { key: "package_size", label: "Package Size", type: "select-package-size", width: "170px" },
      { key: "handler", label: "Handler", type: "select-handler", width: "170px" },
    ] },
};

/**
 * แปลงค่าที่อ่านจากช่องกรอกให้ตรงกับ shape ที่ endpoint ของแต่ละตารางต้องการ
 * (ดู LookupCreate / PackageSizeCreate / PartNumberCreate ใน main.py)
 *
 * ⚠ ตารางแบบ "ชื่อเดียว" (operator/owner/vendor/handler/template) ต้องส่งเป็น
 *   `{name: ...}` **ไม่ใช่** `{operator_name: ...}` — ส่งชื่อคอลัมน์จริงไปจะถูก
 *   ปฏิเสธเป็น 422 ทั้งที่หน้าจอดูเหมือนกรอกครบ
 *
 * ⚠ อย่า hardcode รายชื่อคอลัมน์ตัวเลขตรงนี้ — อ่านจาก config เป็นแหล่งเดียว
 *   ไม่งั้นเพิ่ม field ใหม่ทีหลังแล้วลืมมาเติม ค่าจะถูกส่งเป็น string เงียบๆ
 */
function lookupToApiBody(kind: string, values: Record<string, string>): Record<string, unknown> {
  const cfg = LOOKUP_CONFIG[kind];
  if (kind === "package_size" || kind === "part_number") {
    const body: Record<string, unknown> = { ...values };
    cfg.fields.filter((f) => f.type === "number").forEach((f) => { body[f.key] = Number(body[f.key]); });
    /* ⚠ multi-* เก็บใน state เป็นสตริงคั่นคอมมา แต่ backend รับเป็น array
       — `"".split(",")` คืน `[""]` ไม่ใช่ `[]` จึงต้องกรองตัวว่างทิ้ง ไม่งั้น
       backend จะไปหา handler ชื่อ "" แล้วตอบ 400 ทั้งที่ผู้ใช้แค่ไม่ได้เลือก */
    cfg.fields.filter((f) => f.type === "multi-handler").forEach((f) => {
      body[f.key] = String(values[f.key] ?? "").split(",").map((s) => s.trim()).filter(Boolean);
    });
    return body;
  }
  return { name: values[cfg.fields[0].key] };
}

/** 10 แถวต่อหน้า — เท่ากับ Parts/Measurements/History/Trash ในหน้าเดียวกัน
 *
 *  ⚠ แบ่งฝั่ง client เพราะ endpoint ของ lookup ทุกตัวคืนมาทั้งก้อน ไม่มี
 *    limit/offset (เป็นตารางอ้างอิงที่ปกติมีไม่กี่สิบแถว) — ยกเว้น part_number
 *    ที่โตได้เรื่อย ๆ ตาม catalog จริง ตรงนั้นแหละที่ต้องมีแบ่งหน้าจริง ๆ
 */
const PAGE = 10;

interface Props {
  /** เรียกหลังลบสำเร็จ — ให้หน้าแม่ไปโหลดถังขยะใหม่ */
  onDeleted?: () => void;
  /** เรียกหลังแก้/เพิ่ม — dropdown ที่อื่นอาจต้องอัปเดตตาม */
  onChanged?: () => void;
  /** เด้ง popup แจ้งเตือนที่ต้องกด "ตกลง" เอง — ใช้กับกรณีลบไม่ได้เพราะยังมี
   *  ตารางอื่นอ้างอิงอยู่ (409) ซึ่งต้องอ่านให้จบก่อน ไม่ใช่ toast ที่หายเองใน 3 วิ */
  onAlert?: (message: string) => void;
  /** ขอให้หน้าแม่ถามยืนยันก่อนลบ (ใช้ modal ตัวเดียวกับ Parts/Measurements) */
  onConfirm?: (message: ReactNode, action: () => void) => void;
}

/**
 * จัดการตาราง lookup ทั้ง 7 ตาราง
 *
 * เปลี่ยนชื่อ/ค่าได้เสมอ แต่ **ลบไม่ได้ถ้ายังมีตารางอื่นอ้างอิงอยู่** — backend
 * เช็คให้แล้ว คืน 409 พร้อมข้อความบอกให้เปลี่ยนชื่อแทน (ดู _delete_lookup)
 * ฝั่งนี้แค่เอาข้อความนั้นมาโชว์ ไม่ตัดสินเองว่าลบได้ไหม
 */
export default function LookupTables({ onDeleted, onChanged, onAlert, onConfirm }: Props) {
  const toast = useToast();
  const [kind, setKind] = useState("operator");
  const [rows, setRows] = useState<Record<string, any>[]>([]);
  const [draft, setDraft] = useState<Record<string, string>>({});   // แถวใหม่ที่ยังไม่บันทึก
  const [edited, setEdited] = useState<Record<string, Record<string, string>>>({});
  const [busy, setBusy] = useState(false);
  const [page, setPage] = useState(1);
  /** คำค้นของตารางที่เปิดอยู่ — กรองฝั่ง client ล้วน
   *
   *  ⚠ ตารางกลุ่มนี้ `load()` ดึงมาทั้งตารางอยู่แล้ว (ไม่มี server-side paging
   *    เหมือนตาราง Parts/Measurements) การกรองในหน่วยความจำจึงเห็นครบทุกหน้า
   *    จริง ๆ ไม่ใช่แค่ 10 แถวที่กำลังแสดง — ถ้าวันหลังตารางไหนโตจนต้องแบ่งหน้า
   *    ฝั่ง server ต้องย้ายการกรองไปที่ backend ด้วย ไม่งั้นจะค้นเจอไม่ครบ */
  const [filter, setFilter] = useState("");

  // ตัวเลือกของช่องแบบ FK — โหลดครั้งเดียวใช้ทุกตาราง
  const [opts, setOpts] = useState({ handler: [] as string[], packageSize: [] as string[], template: [] as string[] });

  const cfg = LOOKUP_CONFIG[kind];

  async function loadSupportData() {
    const get = async (p: string) => { try { return await apiGet<any[]>(p); } catch { return []; } };
    const [handlers, pkgs, tpls] = await Promise.all([
      get("/api/handlers"), get("/api/package-sizes"), get("/api/templates"),
    ]);
    setOpts({
      handler: handlers.map((h) => h.handler_name).filter(Boolean),
      packageSize: pkgs.map((p) => p.package_size).filter(Boolean),
      template: tpls.map((t) => t.template_name).filter(Boolean),
    });
  }

  useEffect(() => { loadSupportData(); }, []);

  async function load() {
    try {
      const d = await apiGet<any>(cfg.listUrl);
      setRows(Array.isArray(d) ? d : (d.items ?? []));
    } catch {
      setRows([]);
      toast.show(`โหลด ${cfg.label} ไม่สำเร็จ`);
    }
    setEdited({});
    setDraft({});
  }

  // สลับตารางแล้วต้องกลับหน้า 1 — ไม่งั้นค้างอยู่หน้า 4 ของตารางที่มี 3 แถว
  // ⚠ ต้องล้าง filter ด้วย — คำค้นของตารางเก่าแทบไม่มีทางตรงกับตารางใหม่
  //   ถ้าไม่ล้าง ผู้ใช้จะเจอตารางว่างเปล่าแล้วนึกว่าข้อมูลหาย
  useEffect(() => { setPage(1); setFilter(""); load(); /* eslint-disable-line react-hooks/exhaustive-deps */ }, [kind]);

  /** ค่าจาก DB → สตริงที่ช่องกรอกใช้ได้
   *  ฟิลด์ multi-* มาจาก backend เป็น array — แปลงเป็นสตริงคั่นคอมมาให้เป็น
   *  รูปแบบเดียวกับที่ state เก็บ ไม่งั้น `isDirty` จะเทียบ array กับ string
   *  แล้วเห็นว่า "แก้แล้ว" ตลอดเวลาทั้งที่ผู้ใช้ไม่ได้แตะ */
  const cellText = (v: unknown) => (Array.isArray(v) ? v.join(",") : String(v ?? ""));

  const valueOf = (row: Record<string, any>, key: string) => {
    const id = String(row[cfg.idField]);
    const e = edited[id]?.[key];
    return e !== undefined ? e : cellText(row[key]);
  };

  const setValue = (row: Record<string, any>, key: string, v: string) => {
    const id = String(row[cfg.idField]);
    setEdited((prev) => ({ ...prev, [id]: { ...prev[id], [key]: v } }));
  };

  /** แถวนี้ถูกแก้ไว้แต่ยังไม่ได้กด Save ไหม — เทียบค่าปัจจุบันในช่องกับค่าจาก DB
   *  ทุกครั้ง ถ้าแก้แล้วแก้กลับเป็นค่าเดิมเป๊ะ ปุ่มจะกลับเป็นปกติเอง */
  function isDirty(row: Record<string, any>): boolean {
    const id = String(row[cfg.idField]);
    const patch = edited[id];
    if (!patch) return false;
    return cfg.fields.some((f) => {
      const v = patch[f.key];
      return v !== undefined && v !== cellText(row[f.key]);
    });
  }
  /* ⚠ นับจาก `rows` ทั้งหมด **ไม่ใช่** `visibleRows` โดยตั้งใจ — แถวที่แก้ค้างไว้
     อาจถูกคำค้นซ่อนไป ถ้านับเฉพาะที่มองเห็นจะขึ้น "ไม่มีแถวค้าง" ทั้งที่ยังมี
     แล้วผู้ใช้จะปิดหน้าไปโดยที่งานหาย */
  const dirtyCount = rows.filter(isDirty).length;

  /** แถวที่ผ่านคำค้น — เทียบกับทุกคอลัมน์ที่แสดงอยู่ในตารางนั้น
   *
   *  ⚠ เทียบกับ **ค่าจาก DB** (`row[f.key]`) ไม่ใช่ค่าในช่องกรอก (`valueOf`)
   *    โดยตั้งใจ — ถ้าเทียบค่าที่กำลังพิมพ์ แถวจะหายไปจากตารางกลางคันตอนที่
   *    ผู้ใช้แก้ชื่อจนไม่ตรงคำค้นอีกต่อไป แล้วช่องที่พิมพ์ค้างอยู่จะหลุด focus
   *
   *  ⚠ รวมคอลัมน์ ID ด้วย เพื่อให้พิมพ์เลข id ค้นได้ตรง ๆ */
  const q = filter.trim().toLowerCase();
  const visibleRows = q === "" ? rows : rows.filter((row) =>
    [String(row[cfg.idField] ?? ""), ...cfg.fields.map((f) => cellText(row[f.key]))]
      .some((s) => s.toLowerCase().includes(q)));

  /* ⚠ หนีบเลขหน้าให้อยู่ในช่วงที่มีจริงเสมอ — ลบแถวสุดท้ายของหน้าท้าย ๆ แล้ว
     จำนวนหดลง ถ้าไม่หนีบจะค้างอยู่หน้าที่ไม่มีข้อมูล เห็นตารางว่างทั้งที่ยังมีของ
     ⚠ ต้องคิดจาก `visibleRows` ด้วย ไม่งั้นพิมพ์ค้นแล้วเหลือ 2 แถวแต่ยังค้าง
       อยู่หน้า 3 จะเห็นตารางว่าง */
  const lastPage = Math.max(1, Math.ceil(visibleRows.length / PAGE));
  const curPage = Math.min(page, lastPage);
  const pageRows = visibleRows.slice((curPage - 1) * PAGE, curPage * PAGE);
  const from = visibleRows.length === 0 ? 0 : (curPage - 1) * PAGE + 1;
  const to = (curPage - 1) * PAGE + pageRows.length;

  function optionsFor(type?: FieldType): string[] | null {
    if (type === "select-template") return opts.template;
    if (type === "select-package-size") return opts.packageSize;
    if (type === "select-handler") return opts.handler;
    return null;
  }

  async function addRow() {
    const values = Object.fromEntries(cfg.fields.map((f) => [f.key, (draft[f.key] ?? "").trim()]));
    // ข้ามช่องที่ตั้ง optional ไว้ (เช่น Handlers) — ดูคอมเมนต์ที่ LOOKUP_CONFIG
    if (cfg.fields.some((f) => !f.optional && values[f.key] === "")) {
      toast.show("กรอก/เลือกข้อมูลให้ครบทุกช่องก่อน Add");
      return;
    }
    setBusy(true);
    try {
      await apiPost(cfg.basePath, lookupToApiBody(kind, values));
      toast.show(`เพิ่ม ${cfg.label} สำเร็จ`);
      await load();
      await loadSupportData();
      onChanged?.();
    } catch (e: any) {
      toast.show(e?.message ?? `เพิ่ม ${cfg.label} ไม่สำเร็จ`);
    }
    setBusy(false);
  }

  async function saveRow(row: Record<string, any>) {
    const id = String(row[cfg.idField]);
    if (!isDirty(row)) { toast.show("ยังไม่มีอะไรเปลี่ยน"); return; }
    const values = Object.fromEntries(cfg.fields.map((f) => [f.key, valueOf(row, f.key).trim()]));

    setBusy(true);
    try {
      await apiPatch(`${cfg.basePath}/${id}`, lookupToApiBody(kind, values));

      // ⚠⚠ ห้ามเรียก load() ตรงนี้เด็ดขาด
      //   load() ดึงทั้งตารางมาใหม่แล้วล้าง edited ทิ้ง ผลคือค่าที่ผู้ใช้พิมพ์ค้าง
      //   ไว้ในแถวอื่น (ยังไม่ได้กด Save) หายไปเงียบๆ พร้อมปุ่มเขียวของแถวพวกนั้น
      //   — ดูเหมือน "บันทึกครบทุกแถว" ทั้งที่ PATCH ไปแค่แถวเดียว
      //   แก้เป็น: อัปเดตเฉพาะแถวนี้ใน rows แล้วปลด dirty ของแถวนี้ตัวเดียว
      setRows((prev) => prev.map((r) => (String(r[cfg.idField]) === id ? { ...r, ...values } : r)));
      setEdited((prev) => {
        const next = { ...prev };
        delete next[id];
        return next;
      });

      const rowName = values[cfg.fields[0].key] || `ID ${id}`;
      const stillDirty = dirtyCount - 1;
      toast.show(stillDirty > 0
        ? `บันทึก "${rowName}" แล้ว — ยังมีอีก ${stillDirty} แถวที่แก้ไว้แต่ยังไม่ได้กด Save`
        : `บันทึก "${rowName}" แล้ว`);

      // อัปเดตเฉพาะรายชื่อใน dropdown (เผื่อชื่อ handler/package size เปลี่ยน)
      // โดยไม่แตะตาราง — ค่าที่ค้างในแถวอื่นจึงไม่หาย
      await loadSupportData();
      onChanged?.();
    } catch (e: any) {
      toast.show(e?.message ?? `บันทึก ${cfg.label} ไม่สำเร็จ`);
    }
    setBusy(false);
  }

  function deleteRow(row: Record<string, any>) {
    const id = String(row[cfg.idField]);
    const run = async () => {
      setBusy(true);
      try {
        await apiDelete(`${cfg.basePath}/${id}`);
        await load();
        await loadSupportData();
        onDeleted?.();
        onChanged?.();
        toast.show(`ลบ ${cfg.label} สำเร็จ`);
      } catch (e: any) {
        // 409 = ยังมี Part/Measurement/ตารางอื่นอ้างอิง id นี้อยู่จริง
        // (ดู _delete_lookup ใน main.py) — โชว์เป็น popup เด่นๆ ไม่ใช่ toast เล็กๆ
        // มุมจอ เพราะเป็นเหตุผลเชิงตรรกะที่ผู้ใช้ควรอ่านจริง
        const msg = e?.message ?? `ลบ ${cfg.label} ไม่สำเร็จ`;
        if (onAlert) onAlert(msg); else toast.show(msg);
      }
      setBusy(false);
    };
    if (onConfirm) onConfirm(<>ลบรายการนี้ออกจากตาราง <strong>{cfg.label}</strong> ใช่ไหม?</>, run);
    else void run();
  }

  /** ช่องกรอก 1 ช่อง — select ถ้าเป็น FK, input ถ้าไม่ใช่
   *  ⚠ ตัวเลือกว่างของ select ระบุชื่อ field ไว้ตรงๆ ("-- Package Size --" ไม่ใช่
   *    "--" เฉยๆ) เพราะแถว Add มี select ติดกันหลายตัว ถ้าเขียนเหมือนกันหมดจะ
   *    แยกไม่ออกว่าอันไหนคือ field อะไรถ้าไม่เงยไปดูหัวคอลัมน์
   *
   *  ⚠ `disabled hidden` ทำให้ตัวเลือกนี้ **โชว์ตอนยังไม่ได้เลือก แต่ไม่โผล่ในรายการ
   *    ตอนกดเปิด** — ยังบอกได้ว่าช่องนี้คือ field อะไร โดยไม่มีบรรทัดขยะให้เลื่อนผ่าน
   *    `disabled` กันเลือกกลับมาเป็นค่าว่างด้วย ซึ่งเป็นค่าที่ทุก field ที่นี่ไม่รับอยู่แล้ว */
  function fieldInput(f: LookupField, value: string, onChange: (v: string) => void) {
    if (f.type === "multi-handler") {
      return (
        <MultiSelectCell
          options={opts.handler}
          // state เก็บเป็นสตริงคั่นคอมมา — แตกเข้า/ประกอบออกตรงนี้ที่เดียว
          value={value ? value.split(",").filter(Boolean) : []}
          onChange={(next) => onChange(next.join(","))}
          minWidth={f.width}
        />
      );
    }
    const list = optionsFor(f.type);
    if (list) {
      return (
        <select value={value} onChange={(e) => onChange(e.target.value)}>
          <option value="" disabled hidden>-- {f.label} --</option>
          {list.map((o) => <option key={o} value={o}>{o}</option>)}
        </select>
      );
    }
    return (
      <input
        type={f.type === "number" ? "number" : "text"}
        step={f.type === "number" ? "0.001" : undefined}
        placeholder={f.label}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        // ช่องตัวเลข: ลด padding ขวา (spinner ของ input[type=number] กินที่อยู่แล้ว)
        // ให้ตัวเลข/placeholder แสดงเต็มไม่โดนตัดกลางคำ
        style={f.type === "number" ? { width: "100%", paddingRight: "0.25rem" } : { width: "100%" }}
      />
    );
  }

  return (
    <section className="card" id="lookup-section">
      <div className="card-header">
        <div className="card-title">Lookup Tables</div>
        <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
          {/* ⚠ ต้อง `setPage(1)` ทุกครั้งที่คำค้นเปลี่ยน — ไม่งั้นค้นแล้วเหลือ
              2 แถวแต่ยังอยู่หน้า 3 จะเห็นตารางว่างทั้งที่ค้นเจอ */}
          <input
            type="search"
            value={filter}
            placeholder={`ค้นใน ${cfg.label}`}
            aria-label={`ค้นหาใน ${cfg.label}`}
            style={{ minWidth: 200 }}
            onChange={(e) => { setFilter(e.target.value); setPage(1); }}
          />
          <select style={{ minWidth: 180 }} value={kind} onChange={(e) => setKind(e.target.value)}>
            {Object.entries(LOOKUP_CONFIG).map(([k, c]) => (
              <option key={k} value={k}>{c.label}</option>
            ))}
          </select>
        </div>
      </div>
      <div className="filter-result-note">
        เปลี่ยนชื่อ/ค่าได้เสมอ (แก้แล้วกด Save ของแถวนั้น) — ลบไม่ได้ถ้ายังมีตารางอื่นอ้างอิงอยู่
        (ระบบจะแจ้งเตือนให้เปลี่ยนชื่อแทน)
      </div>

      <div className="table-wrap">
        <table style={{ tableLayout: "fixed", minWidth: cfg.minWidth }}>
          <thead>
            <tr>
              <th style={{ width: 80 }}>ID</th>
              {cfg.fields.map((f) => <th key={f.key} style={{ width: f.width }}>{f.label}</th>)}
              <th style={{ width: 190 }}>Actions</th>
              {/* คอลัมน์ spacer ท้ายสุด — ไม่มีหัวข้อ ไม่กำหนด width
                  table-layout:fixed จะเอาพื้นที่ที่เหลือทั้งหมดยัดใส่คอลัมน์ที่ไม่
                  ระบุ width ถ้าไม่มีตัวนี้ พื้นที่เหลือจะไปยืดคอลัมน์ข้อมูลจริงจน
                  ช่องสั้นๆ อย่าง Name กว้างเต็มหน้าจอ และปุ่ม Actions หลุดออกนอก
                  เส้นแบ่งแถว */}
              <th />
            </tr>
          </thead>
          <tbody>
            {/* แถว "เพิ่มใหม่" อยู่ในตารางเดียวกันเสมอ (ไม่ใช่ div แยก) เพื่อให้
                แต่ละช่องตรงกับคอลัมน์ของ header ด้านบนพอดี ผู้ใช้จะเห็นทันที
                ว่าช่องไหนคือ field อะไร */}
            <tr style={{ background: "var(--surface2)" }}>
              <td style={{ color: "var(--muted)", fontStyle: "italic" }}>ใหม่</td>
              {cfg.fields.map((f) => (
                <td key={f.key}>
                  {fieldInput(f, draft[f.key] ?? "", (v) => setDraft({ ...draft, [f.key]: v }))}
                </td>
              ))}
              <td className="row-actions">
                <div className="actions-inner">
                  <button type="button" className="btn-add" disabled={busy} onClick={addRow}>+ Add</button>
                </div>
              </td>
              <td />
            </tr>

            {/* ⚠ แยก 2 ข้อความ — "ค้นไม่เจอ" กับ "ตารางว่าง" คนละเรื่องกัน
                ถ้าใช้ข้อความเดียวผู้ใช้จะนึกว่าข้อมูลหายไปทั้งตาราง */}
            {visibleRows.length === 0 ? (
              <tr className="empty-row">
                <td colSpan={cfg.fields.length + 3}>
                  {rows.length === 0
                    ? "ยังไม่มีข้อมูล"
                    : `ไม่พบรายการที่ตรงกับ "${filter.trim()}" (มีทั้งหมด ${rows.length} รายการ)`}
                </td>
              </tr>
            ) : (
              pageRows.map((row) => {
                const id = row[cfg.idField];
                return (
                  <tr key={id}>
                    <td><strong>{id}</strong></td>
                    {cfg.fields.map((f) => (
                      <td key={f.key}>
                        {fieldInput(f, valueOf(row, f.key), (v) => setValue(row, f.key, v))}
                      </td>
                    ))}
                    <td className="row-actions">
                      <div className="actions-inner">
                        <button
                          type="button"
                          className={`btn-icon${isDirty(row) ? " dirty" : ""}`}
                          disabled={busy}
                          onClick={() => saveRow(row)}
                        >
                          ✔ Save
                        </button>
                        <button type="button" className="btn-icon delete" disabled={busy} onClick={() => deleteRow(row)}>
                          🗑 Delete
                        </button>
                      </div>
                    </td>
                    <td />
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      <div className="pagination-bar">
        <button type="button" className="btn-icon" disabled={curPage <= 1} onClick={() => setPage(curPage - 1)}>
          ‹ Previous
        </button>
        <span style={{ fontSize: "0.85rem", fontWeight: 600 }}>
          {visibleRows.length === 0
            ? "ไม่มีรายการ"
            : `แสดง ${from}–${to} จาก ${visibleRows.length} รายการ`}
          {/* บอกด้วยว่ากำลังกรองอยู่ ไม่งั้นตัวเลข "จาก N" จะดูเหมือนข้อมูลหาย */}
          {q !== "" && (
            <span style={{ color: "var(--muted)", fontWeight: 400 }}>
              {" "}(กรองจากทั้งหมด {rows.length})
            </span>
          )}
          {/* ⚠ เตือนไว้ตรงนี้เพราะแถวที่แก้ค้างไว้อาจอยู่คนละหน้ากับที่กำลังดู
              มองไม่เห็นแล้วนึกว่าบันทึกไปแล้ว — ตารางนี้ไม่มีปุ่ม "Save ทั้งหมด"
              ต้องกด Save ของแต่ละแถวเอง */}
          {dirtyCount > 0 && (
            <span style={{ color: "var(--warn)", fontWeight: 600 }}>
              {" "}· มี {dirtyCount} แถวที่แก้ไว้ยังไม่ได้กด Save
            </span>
          )}
        </span>
        <button type="button" className="btn-icon" disabled={to >= visibleRows.length} onClick={() => setPage(curPage + 1)}>
          Next ›
        </button>
      </div>
    </section>
  );
}
