import { useEffect, useReducer, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { apiGet, apiPatch, apiPost, ApiError } from "../api/client";
import { useToast } from "../components/Toast";
import { useDialog } from "../components/Dialog";
import ColorButton from "../components/report/ColorButton";
// ⚠ สไตล์ของหน้านี้อยู่ในไฟล์ของตัวเอง ไม่ใช่ index.css — import ตรงนี้เพื่อให้
//    Vite ผูกมันเป็น dependency ของโมดูลหน้านี้โดยตรง (HMR/บันเดิลจะไม่มีทาง
//    หลุดกันได้) และกันไม่ให้กฎยาว ๆ ของหน้านี้ไปปนกับ stylesheet กลาง
import "./ReportTemplate.css";

/**
 * ตัวแก้ผังรายงานแบบสเปรดชีต — พอร์ตจาก Frontend/report-template.html
 *
 * ใช้กับเทมเพลตชนิด pdf/excel เท่านั้น (csv ใช้ modal เลือกคอลัมน์ที่หน้า Export)
 * เพราะรายงาน PDF/Excel ไม่ได้เรียงคอลัมน์เป็นแถวเดียว แต่จัดเป็นผังตารางที่มี
 * หัวเรื่อง/หัวตาราง/แถวข้อมูลที่ถูกทำซ้ำ
 *
 * ⚠ ทั้งไฟล์นี้ทำงานกับ `gridRef.current` แบบแก้ในที่ (mutate) แล้วสั่งวาดใหม่ด้วย
 *   bump() — ไม่ได้ทำ immutable update แบบ React ปกติ เพราะ:
 *     1. ผังเป็นตาราง 2 มิติที่ทุก action แตะหลายเซลล์พร้อมกัน (ผสาน/ย้ายบล็อก/
 *        แทรกแถว) การ clone ทั้งผังทุกครั้งทำให้โค้ดยาวขึ้นเท่าตัวโดยไม่ได้อะไร
 *     2. ตรรกะทั้งหมดยกมาจากต้นฉบับตัวต่อตัว การเปลี่ยนเป็น immutable ระหว่างพอร์ต
 *        คือเปลี่ยน 2 อย่างพร้อมกัน ถ้าพังจะแยกไม่ออกว่าพังเพราะอะไร
 *   เก็บ selection/editing ไว้ใน ref ด้วยเหตุผลเดียวกัน — `renderGrid()` ของ
 *   ต้นฉบับ = `bump()` ที่นี่ แบบ 1:1
 */

// ── ชนิดข้อมูล ────────────────────────────────────────────────────────────
export interface CellStyle {
  font?: string; size?: number; bold?: boolean; italic?: boolean; underline?: boolean;
  fill?: string; color?: string; align?: string; valign?: string; indent?: number;
}

export interface Cell {
  /** ข้อความที่พิมพ์เอง */
  v: string;
  /** key ของช่องข้อมูล — เซลล์นี้จะกลายเป็นค่าจริงทีละแถวตอน export */
  f: string;
  /** เซลล์นี้เป็น "หัวตาราง" ของช่องข้อมูลตัวไหน — ผูกไว้เพื่อให้ลบทีเดียวแล้ว
   *  หายพร้อมกันทั้งคู่ และรู้ว่าฟิลด์ไหนถูกใช้ไปแล้ว (กันลากซ้ำ)
   *  เก็บแยกจาก v เพราะผู้ใช้แก้ข้อความหัวตารางเป็นอย่างอื่นได้ แต่ความผูกพัน
   *  กับฟิลด์ต้องไม่หายไปด้วย */
  hdr: string;
  /** เซลล์ "สเปกของกลุ่ม" ของบล็อก — พิมพ์ครั้งเดียวต่อกลุ่ม ต่างจาก f ที่ซ้ำทุกแถว */
  spec: string;
  s: CellStyle;
  span: { r: number; c: number } | null;
  /** ถูกกลืนเพราะเซลล์ข้างบน/ซ้ายผสานทับ */
  hidden: boolean;
  /** หน้าตาแยกตามค่า เช่น Result มี {OK:{...}, NG:{...}} */
  variants: Record<string, CellStyle> | null;
  /** ตอนนี้กำลังแก้หน้าตาของค่าไหนอยู่ */
  vsel: string;
  /** รูปแบบการแสดงผลที่ติ๊กไว้ (ช่องวันเวลา: date/time/datetime) */
  fmt: string;
}

interface CatalogCol {
  key: string;
  label: string;
  group: string;
  header?: string;
  values?: string[] | null;
  formats?: { key: string; label: string }[] | null;
  block?: { cols: number; header?: string; data: { key: string; label: string; values?: string[] | null; formats?: any }[] } | null;
}

interface TemplateRow {
  export_template_id: number;
  name: string;
  is_default: boolean;
  layout?: { nRows: number; nCols: number; dataRow?: number; grid: Cell[][] } | null;
}

const ROWS0 = 5, COLS0 = 10;
/** รายงานถูกแบ่งกลุ่มด้วยสเปก Tolerance เสมอ (ไม่มีตัวเลือกให้ผู้ใช้เปลี่ยน) —
 *  รายงานที่ห้อง PM Kit ใช้จริงพิมพ์ทีละสเปก ชิ้นงานคนละสเปกอยู่คนละก้อน */
const GROUP_BY = "tolerance_spec";

const FONTS = ["Calibri", "Arial", "Tahoma", "Segoe UI", "Times New Roman"];
/** ขนาดอักษรที่มีให้เลือก — ปุ่ม A▲/A▼ ไล่ไปตามรายการนี้เหมือน Excel
 *  (ไม่ใช่ +1/-1 ทีละหน่วย ไม่งั้นค่าจะหลุดออกนอกรายการใน dropdown) */
const SIZES = [8, 9, 10, 11, 12, 14, 16, 18, 20, 22, 24, 26, 28, 36, 48, 72];

const blank = (): Cell => ({
  v: "", f: "", hdr: "", spec: "", s: {}, span: null, hidden: false,
  variants: null, vsel: "", fmt: "",
});

const colName = (i: number) => {
  // เกิน Z ต้องเป็น AA, AB, … — ต้นฉบับใช้ String.fromCharCode(65+i) ตรงๆ ซึ่ง
  // พอผู้ใช้แทรกคอลัมน์เกิน 26 ช่องจะได้ "[" "\" "]" โผล่มาเป็นชื่อคอลัมน์
  let s = "", n = i;
  do { s = String.fromCharCode(65 + (n % 26)) + s; n = Math.floor(n / 26) - 1; } while (n >= 0);
  return s;
};

export default function ReportTemplatePage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const toast = useToast();
  const dialog = useDialog();

  const format = (params.get("format") ?? params.get("kind") ?? "pdf").toLowerCase();
  const output = format === "excel" ? "Excel" : "PDF";
  const openId = params.get("id") != null ? Number(params.get("id")) : null;
  const backToWizard = () => navigate(`/export?format=${format}`);

  // ── สถานะที่ต้องแก้ในที่ (ดูหมายเหตุหัวไฟล์) ────────────────────────────
  const [, bump] = useReducer((x: number) => x + 1, 0);
  const gridRef = useRef<Cell[][]>([]);
  const sizeRef = useRef({ nRows: ROWS0, nCols: COLS0 });
  const dataRowRef = useRef(2);
  /** การเลือกเป็น "ช่วง" เสมอ — คลิกธรรมดา anchor = focus (ช่วง 1 ช่อง)
   *  Shift+คลิก ขยับ focus โดย anchor อยู่กับที่ → ได้สี่เหลี่ยมคลุม */
  const selRef = useRef({ anchor: { r: 0, c: 0 }, focus: { r: 0, c: 0 } });
  const editRef = useRef<{ r: number; c: number; prevF: string; prevHdr: string; seed: string | null } | null>(null);
  const dragFieldRef = useRef<string | null>(null);
  const dragFromRef = useRef<{ r: number; c: number; dr: number; dc: number } | null>(null);
  const painterRef = useRef<CellStyle | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const [catalog, setCatalog] = useState<CatalogCol[]>([]);
  const [name, setName] = useState("");
  const [editingId, setEditingId] = useState<number | null>(null);
  /** เปิดตัวที่ระบบล็อกไว้อยู่ → บันทึกเป็นตัวใหม่แทนการทับ */
  const [lockedDefault, setLockedDefault] = useState(false);
  const [ready, setReady] = useState(false);
  const [saving, setSaving] = useState(false);
  /** เมนูของหัวคอลัมน์/เลขแถว — ต้นฉบับใช้ prompt() ให้พิมพ์เลข ซึ่งไม่มีใคร
   *  เดาได้ว่ามีฟีเจอร์นี้ และ prompt() บล็อก event loop ทั้งเส้น */
  const [headMenu, setHeadMenu] = useState<{ kind: "col" | "row"; i: number; x: number; y: number } | null>(null);

  const g = () => gridRef.current;
  const nRows = () => sizeRef.current.nRows;
  const nCols = () => sizeRef.current.nCols;

  // ── helper ที่อ้างอิง catalog ────────────────────────────────────────────
  const labelOf = (k: string) =>
    catalog.find((c) => c.key === k)?.label
    ?? catalog.flatMap((c) => c.block?.data ?? []).find((d) => d.key === k)?.label
    ?? k;
  const blockOf = (k: string) => catalog.find((c) => c.key === k)?.block ?? null;
  /** ข้อความที่ใช้เป็นหัวตารางจริงในรายงาน — ต่างจาก labelOf ที่เป็นชื่อชิปในแผงซ้าย
   *  (ชิปต้องบอกว่าลากแล้วได้อะไรบ้าง เช่น "Tolerance + Value X/Y" แต่หัวตาราง
   *  บนกระดาษต้องสั้นว่า "Tolerance") */
  const headerOf = (k: string) => blockOf(k)?.header ?? catalog.find((c) => c.key === k)?.header ?? labelOf(k);
  const dataLabel = (k: string) => `ข้อมูล ${labelOf(k)}`;
  /** key ทั้งหมดของบล็อกนี้ — ใช้ตอนลบให้หายยกชุด ไม่เหลือเศษ */
  const blockKeys = (k: string) => { const b = blockOf(k); return b ? [k, ...b.data.map((d) => d.key)] : [k]; };
  /** ถ้า key เป็นลูกของบล็อกไหน คืน key ของบล็อกนั้น (value_x → tolerance_spec) */
  const ownerOf = (k: string) => catalog.find((c) => c.block?.data?.some((d) => d.key === k))?.key ?? k;
  const valuesOf = (k: string) =>
    catalog.find((c) => c.key === k)?.values
    ?? catalog.flatMap((c) => c.block?.data ?? []).find((d) => d.key === k)?.values
    ?? null;
  const formatsOf = (k: string): { key: string; label: string }[] | null =>
    catalog.find((c) => c.key === k)?.formats
    ?? catalog.flatMap((c) => c.block?.data ?? []).find((d) => d.key === k)?.formats
    ?? null;

  /** ตั้งรูปแบบเริ่มต้นให้เซลล์ถ้าช่องนี้มีให้เลือก (ตัวแรกในลิสต์ = ค่าเริ่มต้น) */
  function initFmt(cell: Cell) {
    const fs = cell.f ? formatsOf(cell.f) : null;
    if (fs && !fs.some((x) => x.key === cell.fmt)) cell.fmt = fs[0].key;
    return fs;
  }

  /** คืนรายการค่าถ้าเซลล์นี้รองรับ (พร้อมสร้างชุดรูปแบบตั้งต้นให้ครบ) — null ถ้าไม่ */
  function variantsOf(cell: Cell): string[] | null {
    const vals = cell.f ? valuesOf(cell.f) : null;
    if (!vals) return null;
    if (!cell.variants) cell.variants = {};
    // ชุดแรกลอกรูปแบบเดิมของเซลล์มาเป็นจุดตั้งต้น จะได้ไม่เสียการจัดวางที่ทำไว้
    vals.forEach((v) => { if (!cell.variants![v]) cell.variants![v] = { ...cell.s }; });
    if (!vals.includes(cell.vsel)) cell.vsel = vals[0];
    return vals;
  }

  /** รูปแบบที่ "กำลังแก้อยู่" ของเซลล์ — ปุ่มในแถบเครื่องมือทุกปุ่มเขียนลงตัวนี้
   *  ไม่ใช่ cell.s ตรงๆ ไม่งั้นตั้งสีให้ OK แล้ว NG จะเปลี่ยนตามไปด้วย */
  function styleOf(cell: Cell): CellStyle {
    const vals = variantsOf(cell);
    return vals ? cell.variants![cell.vsel] : cell.s;
  }

  /** หัวตารางของช่องที่เลือกรูปแบบได้ ต้องเปลี่ยนตามที่ติ๊ก (Date → "Date")
   *  ⚠ แต่ต้องไม่ทับข้อความที่ผู้ใช้พิมพ์เองไว้ — เปลี่ยนให้เฉพาะตอนที่หัวยังเป็น
   *    ข้อความอัตโนมัติอยู่ ถ้าผู้ใช้แก้เป็น "วันที่ตรวจ" แล้ว สลับกี่รอบก็ไม่โดนทับ */
  function syncFmtHeader(key: string) {
    const fs = formatsOf(key);
    if (!fs) return;
    const dc = findCell((x) => x.f === key);
    const hc = findCell((x) => x.hdr === key);
    if (!dc || !hc) return;
    const head = g()[hc.r][hc.c];
    const auto = new Set([...fs.map((f) => f.label), headerOf(key), labelOf(key)]);
    if (!auto.has((head.v || "").trim())) return;
    const cur2 = fs.find((f) => f.key === g()[dc.r][dc.c].fmt);
    if (cur2) head.v = cur2.label;
  }

  // ── การเลือกช่วง ────────────────────────────────────────────────────────
  function range() {
    const { anchor, focus } = selRef.current;
    return {
      r1: Math.min(anchor.r, focus.r), r2: Math.max(anchor.r, focus.r),
      c1: Math.min(anchor.c, focus.c), c2: Math.max(anchor.c, focus.c),
    };
  }
  const inRange = (r: number, c: number) => {
    const q = range();
    return r >= q.r1 && r <= q.r2 && c >= q.c1 && c <= q.c2;
  };
  function selectedCells(): Cell[] {
    const q = range(), out: Cell[] = [];
    for (let r = q.r1; r <= q.r2; r++) for (let c = q.c1; c <= q.c2; c++) out.push(g()[r][c]);
    return out;
  }
  const hasContent = (cell: Cell) => !!(cell.f || cell.spec || (cell.v && cell.v.trim()));
  const cur = () => g()[selRef.current.focus.r][selRef.current.focus.c];

  function findCell(pred: (c: Cell) => boolean) {
    for (let r = 0; r < nRows(); r++) for (let c = 0; c < nCols(); c++) if (pred(g()[r][c])) return { r, c };
    return null;
  }

  /** ฟิลด์ที่ถูกวางไปแล้ว — ใช้ทำให้ชิปในแผงซ้ายกดลากซ้ำไม่ได้ */
  function usedFields(): Set<string> {
    const set = new Set<string>();
    g().flat().forEach((c) => { [c.f, c.hdr, c.spec].forEach((k) => { if (k) set.add(ownerOf(k)); }); });
    return set;
  }

  /** ยกเลิกการผสานของเซลล์หนึ่ง แล้วคืนเซลล์ที่ถูกกลืนให้กลับมามองเห็น */
  function unspan(r: number, c: number) {
    const cell = g()[r][c];
    if (!cell.span) return;
    for (let dr = 0; dr < cell.span.r; dr++)
      for (let dc = 0; dc < cell.span.c; dc++) {
        const x = g()[r + dr]?.[c + dc];
        if (x && x !== cell) x.hidden = false;
      }
    cell.span = null;
  }

  /** เอาฟิลด์ออกทั้งคู่ (หัวตาราง + ข้อมูล) — ลบตัวไหนตัวหนึ่งก็หายไปทั้งคู่
   *  หัวตารางถูกผสาน 2 แถวไว้ตอนวาง จึงต้องคืนเซลล์ที่ถูกกลืนกลับมาด้วย
   *  ไม่งั้นจะเหลือช่องผีที่คลิกไม่ได้ค้างอยู่ในผัง */
  function removeField(key: string) {
    const keys = new Set(blockKeys(ownerOf(key)));
    for (let r = 0; r < nRows(); r++)
      for (let c = 0; c < nCols(); c++) {
        const cell = g()[r][c];
        if (!(keys.has(cell.f) || keys.has(cell.hdr) || keys.has(cell.spec))) continue;
        unspan(r, c);
        cell.f = ""; cell.hdr = ""; cell.spec = ""; cell.v = "";
        cell.variants = null; cell.vsel = ""; cell.fmt = "";
      }
  }

  function ensureRows(need: number) {
    while (nRows() < need) {
      g().push(Array.from({ length: nCols() }, blank));
      sizeRef.current.nRows++;
    }
  }

  /** วางบล็อกของฟิลด์ลงที่ (top,left) — สูง 3 แถวเสมอ แถวที่ 3 คือแถวข้อมูล
   *
   *   คอลัมน์ธรรมดา (กว้าง 1)          บล็อก Tolerance (กว้าง 2)
   *     ┌──────────┐                   ┌───────────────────────┐
   *     │   ALPL   │ ผสาน 2 แถว        │       Tolerance       │ ผสาน 2 คอลัมน์
   *     ├──────────┤                   ├───────────────────────┤
   *     │ข้อมูล ALPL│ ← แถวข้อมูล        │  9.030 +0.020 -0.010  │ ผสาน 2 คอลัมน์
   *     └──────────┘                   ├───────────┬───────────┤
   *                                    │ข้อมูล Value X│ข้อมูล Value Y│ ← แถวข้อมูล
   *                                    └───────────┴───────────┘
   *  คืน false ถ้าปลายทางล้นตาราง หรือชนเซลล์ที่ผสานไว้อยู่แล้ว */
  function placeFieldBlock(key: string, top: number, left: number, headText: string): boolean {
    const b = blockOf(key);
    const w = b ? b.cols : 1;
    if (left < 0 || left + w > nCols()) { toast.show("คอลัมน์ทางขวาไม่พอสำหรับบล็อกนี้"); return false; }
    ensureRows(top + 3);

    const cells: Cell[] = [];
    for (let dr = 0; dr < 3; dr++) for (let dc = 0; dc < w; dc++) cells.push(g()[top + dr][left + dc]);
    if (cells.some((x) => x.hidden || x.span)) {
      toast.show("ตำแหน่งปลายทางชนกับเซลล์ที่ผสานไว้ — เลือกที่อื่น");
      return false;
    }
    const swallow = (x: Cell) => { x.hidden = true; x.v = ""; x.f = ""; x.hdr = ""; x.spec = ""; };
    const center = (x: Cell) => { x.s.align = x.s.align || "center"; x.s.valign = x.s.valign || "middle"; };

    const h = g()[top][left];
    h.v = headText; h.f = ""; h.hdr = key; h.spec = ""; center(h);

    if (!b) {
      h.span = { r: 2, c: 1 };
      swallow(g()[top + 1][left]);
      const d = g()[top + 2][left];
      d.v = ""; d.f = key; d.hdr = ""; d.spec = "";
    } else {
      h.span = { r: 1, c: w };
      for (let dc = 1; dc < w; dc++) swallow(g()[top][left + dc]);

      const sp = g()[top + 1][left];
      sp.v = `ข้อมูล ${headerOf(key)}`; sp.f = ""; sp.hdr = ""; sp.spec = key;
      sp.span = { r: 1, c: w }; center(sp);
      for (let dc = 1; dc < w; dc++) swallow(g()[top + 1][left + dc]);

      b.data.forEach((d, i) => {
        const cell = g()[top + 2][left + i];
        cell.v = ""; cell.f = d.key; cell.hdr = ""; cell.spec = ""; center(cell);
      });
    }
    dataRowRef.current = top + 2;
    return true;
  }

  /** ย้ายทั้งบล็อกไปตำแหน่งใหม่ — (dr,dc) คือระยะห่างของเซลล์ที่ผู้ใช้จับจากมุม
   *  บนซ้ายของบล็อก จับตรงไหนลากไปวางตรงนั้น ที่เหลือจัดตัวเองตาม */
  function moveFieldBlock(key: string, dropR: number, dropC: number, dr: number, dc: number): boolean {
    const owner = ownerOf(key);
    const oldH = findCell((x) => x.hdr === owner);
    const headText = oldH ? g()[oldH.r][oldH.c].v : headerOf(owner);
    const old = oldH ? { r: oldH.r, c: oldH.c } : null;
    const top = dropR - dr, left = dropC - dc;

    // ชุดรูปแบบแยกตามค่า (OK/NG) ผูกกับ "ฟิลด์" ไม่ใช่ตำแหน่ง — ย้ายบล็อกแล้ว
    // ต้องติดไปด้วย ไม่งั้นจัดสี OK/NG ไว้สวยๆ แล้วลากย้ายทีเดียวหายหมด
    const keep: Record<string, { variants: Cell["variants"]; vsel: string; fmt: string }> = {};
    g().flat().forEach((x) => {
      if (x.f && (x.variants || x.fmt)) keep[x.f] = { variants: x.variants, vsel: x.vsel, fmt: x.fmt };
    });
    const reapply = () => g().flat().forEach((x) => {
      const k = x.f && keep[x.f];
      if (k) { x.variants = k.variants; x.vsel = k.vsel; x.fmt = k.fmt; }
    });
    const restore = () => { if (old) { placeFieldBlock(owner, old.r, old.c, headText); reapply(); } };
    if (top < 0) { toast.show("ต้องมีที่ว่างข้างบนสำหรับหัวตาราง"); return false; }

    // ล้างของเก่าก่อนเช็คปลายทาง เพื่อให้ลากทับตัวเองได้ (เช่นเลื่อนลง 1 แถว)
    // ไม่งั้น span ของตัวมันเองจะไปบล็อกตำแหน่งใหม่ซะเอง
    removeField(owner);
    if (!placeFieldBlock(owner, top, left, headText)) { restore(); return false; }
    reapply();
    selRef.current = { anchor: { r: top, c: left }, focus: { r: top, c: left } };
    return true;
  }

  function newGrid() {
    gridRef.current = Array.from({ length: ROWS0 }, () => Array.from({ length: COLS0 }, blank));
    sizeRef.current = { nRows: ROWS0, nCols: COLS0 };
    dataRowRef.current = 2;
    selRef.current = { anchor: { r: 0, c: 0 }, focus: { r: 0, c: 0 } };
  }

  // ── โหลดข้อมูลตั้งต้น ────────────────────────────────────────────────────
  useEffect(() => {
    (async () => {
      // kind=pdf|excel → ได้ช่องรวม "Tolerance" ช่องเดียวแทน Nominal X/Y + Upper/Lower Tol
      const cols = await apiGet<CatalogCol[]>("/api/export/columns", { kind: format }).catch(() => []);
      const tpls = await apiGet<TemplateRow[]>("/api/export/templates", { kind: format }).catch(() => []);
      setCatalog(cols);

      const t = openId != null ? tpls.find((x) => x.export_template_id === openId) : null;
      // เปิดมาด้วย id ที่หาไม่เจอ (ถูกลบไปแล้ว / ลิงก์เก่า) — ต้องบอก ไม่ใช่ตกไป
      // สร้างผังเปล่าเงียบๆ แล้วผู้ใช้บันทึกทับเป็นตัวใหม่โดยไม่รู้ตัว
      if (openId != null && !t) toast.show("ไม่พบเทมเพลตนี้ (อาจถูกลบไปแล้ว) — เริ่มผังใหม่ให้แทน");
      const locked = !!t?.is_default;
      // เทมเพลตค่าเริ่มต้นแก้ไม่ได้ (backend ปฏิเสธด้วย 403) — บอกตั้งแต่ตอนเปิด
      // ดีกว่าปล่อยให้จัดผังจนเสร็จแล้วค่อยเด้ง error ตอนกดบันทึก งานที่ทำหายหมด
      if (locked) toast.show("เทมเพลตค่าเริ่มต้นแก้ไม่ได้ — บันทึกจะกลายเป็นตัวใหม่ให้อัตโนมัติ");
      setLockedDefault(locked);
      setEditingId(t && !locked ? t.export_template_id : null);
      setName(t ? (locked ? `${t.name} (สำเนา)` : t.name) : "");

      if (t?.layout?.grid) {
        // โหลดผังเดิมกลับมา — เติมเซลล์ที่ขาดให้ครบกันกรณี layout เก่ามีคอลัมน์น้อยกว่า
        const nr = t.layout.nRows, nc = t.layout.nCols;
        sizeRef.current = { nRows: nr, nCols: nc };
        dataRowRef.current = t.layout.dataRow ?? 2;
        gridRef.current = Array.from({ length: nr }, (_, r) =>
          Array.from({ length: nc }, (_, c) => ({ ...blank(), ...(t.layout!.grid[r]?.[c] || {}) })));
      } else {
        newGrid();
      }
      selRef.current = { anchor: { r: 0, c: 0 }, focus: { r: 0, c: 0 } };
      setReady(true);
      bump();
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [format, openId]);

  // ── การเลือก / แก้ไขในเซลล์ ─────────────────────────────────────────────
  function selectCell(r: number, c: number, extend = false) {
    selRef.current.focus = { r, c };
    if (!extend) selRef.current.anchor = { r, c };
    bump();
  }

  function startEdit(r: number, c: number, initial: string | null = null) {
    selRef.current = { anchor: { r, c }, focus: { r, c } };
    const cell = g()[r][c];
    // เก็บ f/hdr เดิมไว้แทนที่จะล้างทิ้งทันที — ถ้าล้างตั้งแต่เริ่มพิมพ์ ตอน commit
    // จะไม่รู้แล้วว่าเซลล์นี้เคยผูกกับฟิลด์ไหน ทำให้เซลล์คู่ของมันค้างเป็นเศษ
    editRef.current = { r, c, prevF: cell.f || cell.spec, prevHdr: cell.hdr, seed: initial };
    bump();
  }

  function commitEdit(val: string) {
    const e = editRef.current;
    if (!e) return;
    const { r, c, prevF, prevHdr } = e;
    const cell = g()[r][c];
    editRef.current = null;

    if (prevF) {
      // เคยเป็นช่องข้อมูล/สเปก — พิมพ์ทับ = เอาฟิลด์นั้นออกทั้งบล็อก
      cell.f = ""; cell.spec = "";
      removeField(prevF);
      cell.v = val;
    } else if (prevHdr) {
      // เคยเป็นหัวตาราง — เปลี่ยนข้อความได้โดยไม่ตัดความผูกพันกับฟิลด์
      // แต่ถ้าลบจนว่าง ถือว่าเอาออก (ข้อมูลคู่ของมันหายตามไปด้วย)
      if (!val.trim()) removeField(prevHdr);
      else { cell.v = val; cell.hdr = prevHdr; }
    } else {
      cell.v = val;
    }
    bump();
  }

  /** ลาก 1 ครั้งได้ทั้งบล็อก: หัวตารางตรงที่วาง + "ข้อมูล …" ในช่องใต้มัน */
  function dropField(r: number, c: number, key: string): boolean {
    if (usedFields().has(key)) { toast.show(`"${labelOf(key)}" ถูกวางไปแล้ว`); return false; }
    return placeFieldBlock(key, r, c, headerOf(key));
  }

  // ── แถบเครื่องมือ ────────────────────────────────────────────────────────
  const applyStyle = (fn: (s: CellStyle) => void) => { selectedCells().forEach((c) => fn(styleOf(c))); bump(); };
  const toggleStyle = (key: "bold" | "italic" | "underline") => {
    const next = !styleOf(cur())[key];
    selectedCells().forEach((c) => { styleOf(c)[key] = next; });
    bump();
  };
  const stepSize = (v: number, dir: number) => {
    const i = SIZES.findIndex((s) => (dir > 0 ? s > v : s >= v));
    if (dir > 0) return i === -1 ? SIZES[SIZES.length - 1] : SIZES[i];
    return i <= 0 ? SIZES[0] : SIZES[i - 1];
  };

  /** ทารูปแบบที่คัดไว้ลงทุกช่องในช่วงที่เลือก — คืน false ถ้ายังไม่ได้คัดอะไร */
  function paintRange(): boolean {
    if (!painterRef.current) return false;
    selectedCells().forEach((c) => {
      const target = styleOf(c);
      // ล้างของเดิมทิ้งก่อนแล้วทาทับ ไม่ใช่ merge เข้าไป — ไม่งั้นสีเก่าที่ปลายทาง
      // มีแต่ต้นฉบับไม่มี จะค้างอยู่ ผลลัพธ์ไม่เหมือนต้นฉบับ
      Object.keys(target).forEach((k) => delete (target as any)[k]);
      Object.assign(target, painterRef.current);
    });
    bump();
    return true;
  }

  function togglePainter() {
    // เก็บสำเนา กันไม่ให้แก้รูปแบบต้นฉบับทีหลังแล้วสิ่งที่ทาไปเปลี่ยนตาม
    painterRef.current = painterRef.current ? null : { ...styleOf(cur()) };
    if (painterRef.current) toast.show("คัดลอกรูปแบบแล้ว — คลิกช่องที่ต้องการทา (Esc เพื่อเลิก)");
    bump();
  }

  function unmergeCells() {
    const q = range();
    let count = 0;
    for (let r = q.r1; r <= q.r2; r++)
      for (let c = q.c1; c <= q.c2; c++) if (g()[r][c].span) { unspan(r, c); count++; }
    if (!count) { toast.show("ช่องที่เลือกไม่มีการผสานอยู่"); return; }
    bump();
    toast.show(`ยกเลิกการผสานแล้ว ${count} จุด`);
  }

  async function mergeCells() {
    const c0 = cur();
    if (c0.span) { unmergeCells(); return; }   // กดซ้ำที่ก้อนเดิม = ยกเลิก

    const q = range();
    if (q.r1 === q.r2 && q.c1 === q.c2) {
      toast.show("เลือกช่วงก่อน — คลิกช่องแรก แล้ว Shift+คลิกช่องสุดท้าย");
      return;
    }
    // ห้ามผสานทับบล็อกที่ผสานไว้แล้ว ไม่งั้นเซลล์ที่ซ่อนอยู่จะกู้กลับไม่ได้
    for (let r = q.r1; r <= q.r2; r++)
      for (let cc = q.c1; cc <= q.c2; cc++) {
        const cell = g()[r][cc];
        if (cell.hidden || (cell.span && !(r === q.r1 && cc === q.c1))) {
          toast.show("ในช่วงที่เลือกมีเซลล์ที่ผสานไว้แล้ว — ยกเลิกการผสานเดิมก่อน");
          return;
        }
      }

    // เนื้อหาของทุกช่องถูกยุบมาไว้ที่ช่องบนซ้าย (เหมือน Excel) แต่เตือนก่อนถ้ามี
    // ข้อมูลในช่องอื่น จะได้ไม่หายเงียบๆ
    const others: Cell[] = [];
    for (let r = q.r1; r <= q.r2; r++)
      for (let cc = q.c1; cc <= q.c2; cc++)
        if (!(r === q.r1 && cc === q.c1) && hasContent(g()[r][cc])) others.push(g()[r][cc]);
    if (others.length && !await dialog.confirm(
      <>
        ในช่วงที่เลือกมีข้อมูลอยู่ <strong>{others.length} ช่อง</strong>
        <br />
        ผสานแล้วจะเหลือเฉพาะช่องซ้ายบน ข้อมูลช่องอื่นจะหายไป
      </>,
      { title: "ผสานช่อง", okLabel: "ผสาน", danger: true },
    )) return;

    for (let r = q.r1; r <= q.r2; r++)
      for (let cc = q.c1; cc <= q.c2; cc++) {
        if (r === q.r1 && cc === q.c1) continue;
        g()[r][cc].hidden = true;
        g()[r][cc].f = ""; g()[r][cc].v = "";
      }
    const top = g()[q.r1][q.c1];
    top.span = { r: q.r2 - q.r1 + 1, c: q.c2 - q.c1 + 1 };
    top.s.align = "center";
    top.s.valign = "middle";
    selRef.current = { anchor: { r: q.r1, c: q.c1 }, focus: { r: q.r1, c: q.c1 } };
    bump();
  }

  // ── แทรก/ลบ แถวและคอลัมน์ ───────────────────────────────────────────────
  function insertCol(at: number) {
    g().forEach((row) => row.splice(at, 0, blank()));
    sizeRef.current.nCols++;
    bump();
  }
  function deleteCol(at: number) {
    if (nCols() <= 1) { toast.show("ต้องเหลืออย่างน้อย 1 คอลัมน์"); return; }
    g().forEach((row) => row.splice(at, 1));
    sizeRef.current.nCols--;
    if (selRef.current.focus.c >= nCols()) {
      const c = nCols() - 1;
      selRef.current = { anchor: { r: selRef.current.focus.r, c }, focus: { r: selRef.current.focus.r, c } };
    }
    bump();
  }
  function insertRow(at: number) {
    g().splice(at, 0, Array.from({ length: nCols() }, blank));
    sizeRef.current.nRows++;
    if (at <= dataRowRef.current) dataRowRef.current++;   // แถวข้อมูลเลื่อนตาม
    bump();
  }
  function deleteRow(at: number) {
    if (nRows() <= 1) { toast.show("ต้องเหลืออย่างน้อย 1 แถว"); return; }
    g().splice(at, 1);
    sizeRef.current.nRows--;
    if (at < dataRowRef.current) dataRowRef.current--;
    else if (at === dataRowRef.current) dataRowRef.current = Math.min(dataRowRef.current, nRows() - 1);
    if (selRef.current.focus.r >= nRows()) {
      const r = nRows() - 1;
      selRef.current = { anchor: { r, c: selRef.current.focus.c }, focus: { r, c: selRef.current.focus.c } };
    }
    bump();
  }

  // ── คีย์ลัดบนตาราง (เหมือน Excel) ───────────────────────────────────────
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      // ไม่แย่งคีย์ตอนโฟกัสอยู่ในช่องกรอกอื่น (ชื่อเทมเพลต, fx, ช่องแก้เซลล์)
      const tag = (document.activeElement as HTMLElement | null)?.tagName;
      if (editRef.current || tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA") return;

      if (e.key === "Escape" && painterRef.current) {
        e.preventDefault(); painterRef.current = null; bump();
        toast.show("เลิกใช้ Format Painter"); return;
      }
      if (e.key === "Delete" || e.key === "Backspace") {
        // ลบเฉพาะ "เนื้อหา" ของทุกเซลล์ในช่วง — สี/ตัวหนา/การผสาน ยังอยู่
        // (พฤติกรรมเดียวกับกด Delete ใน Excel)
        e.preventDefault();
        const keys = new Set<string>();
        selectedCells().forEach((c) => { [c.f, c.hdr, c.spec].forEach((k) => { if (k) keys.add(k); }); });
        keys.forEach(removeField);
        selectedCells().forEach((c) => { c.v = ""; });
        bump();
        return;
      }
      const move: Record<string, [number, number]> = {
        ArrowUp: [-1, 0], ArrowDown: [1, 0], ArrowLeft: [0, -1], ArrowRight: [0, 1],
      };
      if (move[e.key]) {
        e.preventDefault();
        const [dr, dc] = move[e.key];
        const r = Math.max(0, Math.min(nRows() - 1, selRef.current.focus.r + dr));
        const c = Math.max(0, Math.min(nCols() - 1, selRef.current.focus.c + dc));
        selectCell(r, c, e.shiftKey);
        return;
      }
      if (e.key === "F2" || e.key === "Enter") {
        e.preventDefault();
        startEdit(selRef.current.focus.r, selRef.current.focus.c);
        return;
      }
      // พิมพ์ตัวอักษรทับได้เลยเหมือน Excel (ไม่ต้องดับเบิลคลิกก่อน)
      if (e.key.length === 1 && !e.ctrlKey && !e.altKey && !e.metaKey) {
        e.preventDefault();
        startEdit(selRef.current.focus.r, selRef.current.focus.c, e.key);
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [catalog]);

  // โฟกัสช่องกรอกทันทีที่เข้าโหมดพิมพ์
  useEffect(() => {
    if (editRef.current && inputRef.current) { inputRef.current.focus(); inputRef.current.select(); }
  });

  // ปิดเมนูหัวคอลัมน์/แถวเมื่อคลิกที่อื่น
  useEffect(() => {
    if (!headMenu) return;
    const close = () => setHeadMenu(null);
    document.addEventListener("click", close);
    return () => document.removeEventListener("click", close);
  }, [headMenu]);

  // ── บันทึก ──────────────────────────────────────────────────────────────
  async function saveTemplate() {
    if (!name.trim()) { toast.show("ตั้งชื่อเทมเพลตก่อน"); return; }
    if (!g().flat().some((c) => c.f)) { toast.show("ยังไม่ได้ลากช่องข้อมูลลงในเซลล์เลย"); return; }
    const body = {
      name: name.trim(),
      kind: format,   // 'pdf' หรือ 'excel' — แยกลิสต์กันคนละรูปแบบ
      layout: { nRows: nRows(), nCols: nCols(), dataRow: dataRowRef.current, groupBy: GROUP_BY, grid: g() },
    };
    setSaving(true);
    try {
      // ตัวที่ถูกล็อกไว้ → สร้างเป็นตัวใหม่เสมอ ไม่ยิง PATCH ไปให้โดนปฏิเสธ
      if (editingId != null && !lockedDefault) await apiPatch(`/api/export/templates/${editingId}`, body);
      else await apiPost("/api/export/templates", body);
      toast.show("บันทึกแล้ว");
      backToWizard();
    } catch (err) {
      toast.show(err instanceof ApiError ? err.message : "บันทึกไม่สำเร็จ");
    } finally {
      setSaving(false);
    }
  }

  // ── วาด ─────────────────────────────────────────────────────────────────
  if (!ready) return <div className="main-edit"><div className="filter-result-note">กำลังโหลด…</div></div>;

  const sel = range();
  const focus = selRef.current.focus;
  const focusStyle = styleOf(cur());
  const many = sel.r1 !== sel.r2 || sel.c1 !== sel.c2;
  const nameBox = many
    ? `${colName(sel.c1)}${sel.r1 + 1}:${colName(sel.c2)}${sel.r2 + 1}`
    : `${colName(focus.c)}${focus.r + 1}`;
  const used = usedFields();

  // แผงซ้าย — จัดกลุ่มตามแหล่งข้อมูล (Map รักษาลำดับที่ backend ส่งมา)
  const palGroups = new Map<string, CatalogCol[]>();
  catalog.forEach((c) => {
    if (!palGroups.has(c.group)) palGroups.set(c.group, []);
    palGroups.get(c.group)!.push(c);
  });

  const cellCss = (s: CellStyle): React.CSSProperties => ({
    fontFamily: s.font || undefined,
    fontSize: s.size ? `${s.size}px` : undefined,
    fontWeight: s.bold ? 700 : undefined,
    fontStyle: s.italic ? "italic" : undefined,
    textDecoration: s.underline ? "underline" : undefined,
    background: s.fill || undefined,
    color: s.color || undefined,
    textAlign: (s.align as any) || undefined,
    verticalAlign: (s.valign as any) || undefined,
    paddingLeft: s.indent ? `${0.4 + s.indent * 0.7}rem` : undefined,
    // หมายเหตุ: เส้นขอบหนารอบเซลล์ที่มีเนื้อหา "ไม่แสดงในหน้าแก้ไข" — ไปโผล่ตอน
    // Preview กับในไฟล์จริงเท่านั้น เพื่อให้หน้าแก้ไขดูโล่งเหมือน Excel เปล่าๆ
  });

  return (
    <div className="rt-root">
      <section className="rt-app">
        <div className="rt-hd">
          <span>Export · {output}</span>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="ชื่อเทมเพลต"
            style={{ width: 200 }}
          />
          <span style={{ marginLeft: "auto", display: "flex", gap: ".4rem" }}>
            <button type="button" className="btn-ghost" onClick={backToWizard}>ยกเลิก</button>
            <button type="button" className="btn-primary" disabled={saving} onClick={saveTemplate}>
              บันทึกเทมเพลต
            </button>
          </span>
        </div>

        {/* ── Ribbon แบบ Excel ────────────────────────────────────────────
            ไม่มีปุ่ม Border เพราะเซลล์ที่มีเนื้อหาได้เส้นขอบหนาอัตโนมัติตอน
            export อยู่แล้ว ไม่ต้องให้ผู้ใช้มาตีเส้นเอง */}
        <div className="rt-ribbon">
          <div className="rgroup">
            <div className="rrow">
              <select
                style={{ width: 112 }} title="แบบอักษร"
                value={focusStyle.font ?? "Tahoma"}
                onChange={(e) => applyStyle((s) => { s.font = e.target.value; })}
              >
                {FONTS.map((f) => <option key={f}>{f}</option>)}
              </select>
              <select
                style={{ width: 54 }} title="ขนาดอักษร"
                value={focusStyle.size ?? 11}
                onChange={(e) => applyStyle((s) => { s.size = Number(e.target.value); })}
              >
                {SIZES.map((n) => <option key={n}>{n}</option>)}
              </select>
              <button type="button" className="tb" title="เพิ่มขนาดอักษร"
                onClick={() => applyStyle((s) => { s.size = stepSize(s.size || 11, 1); })}>
                A<span style={{ fontSize: ".62rem" }}>▲</span>
              </button>
              <button type="button" className="tb" title="ลดขนาดอักษร"
                onClick={() => applyStyle((s) => { s.size = stepSize(s.size || 11, -1); })}>
                A<span style={{ fontSize: ".62rem" }}>▼</span>
              </button>
            </div>
            <div className="rrow">
              <button type="button" className={`tb${focusStyle.bold ? " on" : ""}`} title="ตัวหนา"
                onClick={() => toggleStyle("bold")}><b>B</b></button>
              <button type="button" className={`tb${focusStyle.italic ? " on" : ""}`} title="ตัวเอียง"
                onClick={() => toggleStyle("italic")}><i>I</i></button>
              <button type="button" className={`tb${focusStyle.underline ? " on" : ""}`} title="ขีดเส้นใต้"
                onClick={() => toggleStyle("underline")}><u>U</u></button>
              <span className="sep" />
              <button
                type="button"
                className={`tb${painterRef.current ? " armed" : ""}`}
                title="Format Painter — คัดลอกรูปแบบไปทาช่องอื่น"
                onClick={togglePainter}
              >
                <svg className="ic" viewBox="0 0 16 16" style={{ fill: "currentColor", stroke: "none" }}>
                  <path d="M2 1.6h9.2v3.2H2zM3.4 4.8h6.4v1.9H3.4zM6.1 6.7h1.9v2.4a1 1 0 0 1-.5.9v3.9a1 1 0 0 1-1 1 1 1 0 0 1-1-1v-3.9a1 1 0 0 1-.4-.9V6.7z" />
                </svg>
              </button>
              <ColorButton
                kind="fill" title="สีพื้น (ใช้สีล่าสุด)" glyph="🪣" initial="#ffff00"
                onPick={(hex) => applyStyle((s) => { if (hex) s.fill = hex; else delete s.fill; })}
              />
              <ColorButton
                kind="color" title="สีตัวอักษร (ใช้สีล่าสุด)" glyph={<b>A</b>} initial="#c00000"
                onPick={(hex) => applyStyle((s) => { if (hex) s.color = hex; else delete s.color; })}
              />
            </div>
            <div className="rname">Font</div>
          </div>

          <div className="rgroup">
            <div className="rrow">
              {(["top", "middle", "bottom"] as const).map((v, i) => (
                <button
                  key={v} type="button"
                  className={`tb${focusStyle.valign === v ? " on" : ""}`}
                  title={["ชิดบน", "กึ่งกลางแนวตั้ง", "ชิดล่าง"][i]}
                  onClick={() => applyStyle((s) => { s.valign = v; })}
                >{["⎺", "⎼", "⎽"][i]}</button>
              ))}
            </div>
            <div className="rrow">
              {(["left", "center", "right"] as const).map((a, i) => (
                <button
                  key={a} type="button"
                  className={`tb${focusStyle.align === a ? " on" : ""}`}
                  title={["ชิดซ้าย", "กึ่งกลาง", "ชิดขวา"][i]}
                  onClick={() => applyStyle((s) => { s.align = a; })}
                >
                  <svg className="ic" viewBox="0 0 16 16">
                    <path d={[
                      "M1 3h14M1 6.3h9M1 9.6h14M1 12.9h9",
                      "M1 3h14M3.5 6.3h9M1 9.6h14M3.5 12.9h9",
                      "M1 3h14M6 6.3h9M1 9.6h14M6 12.9h9",
                    ][i]} />
                  </svg>
                </button>
              ))}
              <span className="sep" />
              <button type="button" className="tb" title="ลดระยะย่อหน้า"
                onClick={() => applyStyle((s) => { s.indent = Math.max(0, (s.indent || 0) - 1); })}>⇤</button>
              <button type="button" className="tb" title="เพิ่มระยะย่อหน้า"
                onClick={() => applyStyle((s) => { s.indent = Math.min(6, (s.indent || 0) + 1); })}>⇥</button>
              <span className="sep" />
              <button
                type="button"
                className={`tb${cur().span ? " on" : ""}`}
                title="ผสานเซลล์ที่เลือกไว้และจัดกึ่งกลาง (กดซ้ำที่ก้อนที่ผสานแล้ว = ยกเลิกการผสาน)"
                onClick={mergeCells}
              ><small>⊞ Merge &amp; Center</small></button>
            </div>
            <div className="rname">Alignment</div>
          </div>

          <div className="rgroup">
            <div className="rrow">
              <button type="button" className="tb" title="แทรกคอลัมน์ทางซ้ายของช่องที่เลือก"
                onClick={() => insertCol(focus.c)}><small>⇤ แทรกซ้าย</small></button>
              <button type="button" className="tb" title="แทรกคอลัมน์ทางขวาของช่องที่เลือก"
                onClick={() => insertCol(focus.c + 1)}><small>แทรกขวา ⇥</small></button>
              <button type="button" className="tb del" title="ลบคอลัมน์ที่เลือก"
                onClick={() => deleteCol(focus.c)}><small>✕ ลบคอลัมน์</small></button>
            </div>
            <div className="rrow">
              <button type="button" className="tb" title="แทรกแถวด้านบนของช่องที่เลือก"
                onClick={() => insertRow(focus.r)}><small>⤒ แทรกบน</small></button>
              <button type="button" className="tb" title="แทรกแถวด้านล่างของช่องที่เลือก"
                onClick={() => insertRow(focus.r + 1)}><small>⤓ แทรกล่าง</small></button>
              <button type="button" className="tb del" title="ลบแถวที่เลือก"
                onClick={() => deleteRow(focus.r)}><small>✕ ลบแถว</small></button>
            </div>
            <div className="rname">Rows &amp; Columns</div>
          </div>
        </div>

        {/* ── แถบสูตร ─────────────────────────────────────────────────── */}
        <div className="rt-fbar">
          <span className="nbox">{nameBox}</span>
          <span className="fx">
            <input
              placeholder="พิมพ์ข้อความ หรือลากช่องข้อมูลจากซ้ายมาวางในเซลล์"
              value={cur().f ? dataLabel(cur().f) : (cur().v || "")}
              onChange={(e) => { const c = cur(); c.v = e.target.value; c.f = ""; bump(); }}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  if (focus.r < nRows() - 1) selectCell(focus.r + 1, focus.c);
                }
              }}
            />
          </span>
        </div>

        <div className="rt-body">
          {/* ── แผงช่องข้อมูลที่ลากได้ ────────────────────────────────
              ลากข้อความจากตารางมาทิ้งที่นี่ = เอาฟิลด์นั้นออก "ทั้งคู่" */}
          <div
            className="pal"
            onDragOver={(e) => { if (dragFromRef.current) e.preventDefault(); }}
            onDrop={(e) => {
              const from = dragFromRef.current;
              if (!from) return;
              e.preventDefault();
              const src = g()[from.r][from.c];
              const key = src.f || src.hdr;
              if (key) { removeField(key); toast.show(`เอา "${labelOf(key)}" ออกแล้ว`); }
              else src.v = "";
              dragFromRef.current = null;
              bump();
            }}
          >
            <div className="palt">ลากไปวางในเซลล์ →</div>
            {[...palGroups.entries()].map(([grp, cols]) => (
              <div key={grp}>
                <div className="palt">{grp}</div>
                {cols.map((c) => {
                  const u = used.has(c.key);
                  return (
                    <div
                      key={c.key}
                      className={`pc${grp === "ข้อมูลการวัด" ? "" : " gray"}${u ? " used" : ""}`}
                      draggable={!u}
                      title={u ? "วางไปแล้ว — ลากออกจากตารางก่อนถ้าอยากย้าย" : "ลากไปวางในเซลล์"}
                      onDragStart={(e) => {
                        dragFieldRef.current = c.key;
                        dragFromRef.current = null;   // กันค่าค้างจากการลากครั้งก่อน
                        e.dataTransfer.effectAllowed = "copy";
                        // ต้อง setData ไม่งั้น Firefox ไม่ยอมเริ่มลาก
                        e.dataTransfer.setData("text/plain", c.key);
                      }}
                      onDragEnd={() => { dragFieldRef.current = null; }}
                    >
                      <span className="gp">⠿</span>{c.label}{u ? " ✓" : ""}
                    </div>
                  );
                })}
              </div>
            ))}
          </div>

          <div className={`sheet${painterRef.current ? " painting" : ""}`}>
            <table>
              <tbody>
                <tr className="ch">
                  <td className="rn" />
                  {Array.from({ length: nCols() }, (_, c) => (
                    <td
                      key={c}
                      className={c >= sel.c1 && c <= sel.c2 ? "hi" : undefined}
                      onClick={(e) => {
                        e.stopPropagation();
                        selRef.current = { anchor: { r: focus.r, c }, focus: { r: focus.r, c } };
                        setHeadMenu({ kind: "col", i: c, x: e.clientX, y: e.clientY });
                        bump();
                      }}
                    >{colName(c)}</td>
                  ))}
                </tr>

                {Array.from({ length: nRows() }, (_, r) => (
                  <tr key={r}>
                    <td
                      className={`rn${r >= sel.r1 && r <= sel.r2 ? " hi" : ""}`}
                      onClick={(e) => {
                        e.stopPropagation();
                        selRef.current = { anchor: { r, c: focus.c }, focus: { r, c: focus.c } };
                        setHeadMenu({ kind: "row", i: r, x: e.clientX, y: e.clientY });
                        bump();
                      }}
                    >{r + 1}</td>

                    {Array.from({ length: nCols() }, (_, c) => {
                      const cell = g()[r][c];
                      if (cell.hidden) return null;   // ถูกกลืนจากการผสาน
                      const isFocus = r === focus.r && c === focus.c;
                      const editingHere = editRef.current?.r === r && editRef.current?.c === c;
                      const cls = ["cell",
                        isFocus ? "sel" : "",
                        inRange(r, c) && !isFocus ? "inrange" : "",
                        r === dataRowRef.current ? "datarow" : ""].filter(Boolean).join(" ");

                      let content: React.ReactNode;
                      if (editingHere) {
                        const e0 = editRef.current!;
                        // seed = ตัวอักษรที่ผู้ใช้เพิ่งพิมพ์ทับ (ไม่ต้องดับเบิลคลิกก่อน)
                        const iv = e0.seed != null ? e0.seed : (cell.f ? "" : (cell.v || ""));
                        content = (
                          <input
                            ref={inputRef}
                            className="cellinput"
                            defaultValue={iv}
                            onKeyDown={(ev) => {
                              const el = ev.currentTarget;
                              if (ev.key === "Enter") {
                                ev.preventDefault(); commitEdit(el.value);
                                if (focus.r < nRows() - 1) selectCell(focus.r + 1, focus.c);
                              } else if (ev.key === "Escape") {
                                ev.preventDefault(); editRef.current = null; bump();
                              } else if (ev.key === "Tab") {
                                ev.preventDefault(); commitEdit(el.value);
                                if (focus.c < nCols() - 1) selectCell(focus.r, focus.c + 1);
                              }
                            }}
                            onBlur={(ev) => { if (editRef.current) commitEdit(ev.currentTarget.value); }}
                          />
                        );
                      } else if (cell.f) {
                        const vals = variantsOf(cell);
                        const fmts = initFmt(cell);
                        const text = fmts ? "ข้อมูล" : dataLabel(cell.f) + (vals ? ` (${cell.vsel})` : "");
                        const tok = (
                          <span
                            className="tok" draggable
                            onDragStart={(ev) => startTokDrag(ev, r, c)}
                            onDragEnd={() => { dragFromRef.current = null; }}
                          >{text}</span>
                        );
                        // เซลล์ข้อมูลมี dropdown ได้ 2 แบบ (ไม่มีช่องไหนใช้ทั้งคู่พร้อมกัน):
                        //   vsel → เลือกว่ากำลังจัดรูปแบบ "ของค่าไหน" (OK/NG)
                        //   fsel → เลือก "รูปแบบข้อความ" ที่จะพิมพ์ออกมาจริง (วันที่/เวลา)
                        if (vals) {
                          content = (
                            <span className="vwrap">{tok}
                              <select
                                className="vsel" title="เลือกค่าที่จะจัดรูปแบบ" value={cell.vsel}
                                onMouseDown={(ev) => ev.stopPropagation()}
                                onClick={(ev) => ev.stopPropagation()}
                                onChange={(ev) => { cell.vsel = ev.target.value; selectCell(r, c); }}
                              >
                                {vals.map((v) => <option key={v}>{v}</option>)}
                              </select>
                            </span>
                          );
                        } else if (fmts) {
                          content = (
                            <span className="vwrap">{tok}
                              <select
                                className="vsel wide" title="รูปแบบที่จะพิมพ์ออกมา" value={cell.fmt}
                                onMouseDown={(ev) => ev.stopPropagation()}
                                onClick={(ev) => ev.stopPropagation()}
                                onChange={(ev) => { cell.fmt = ev.target.value; syncFmtHeader(cell.f); selectCell(r, c); }}
                              >
                                {fmts.map((f) => <option key={f.key} value={f.key}>{f.label}</option>)}
                              </select>
                            </span>
                          );
                        } else content = tok;
                      } else if (cell.spec || cell.hdr) {
                        // สเปกของกลุ่ม / หัวตาราง — ลากย้ายหรือลากออกได้เหมือนกัน
                        content = (
                          <span
                            className="tok" draggable
                            onDragStart={(ev) => startTokDrag(ev, r, c)}
                            onDragEnd={() => { dragFromRef.current = null; }}
                          >{cell.v || ""}</span>
                        );
                      } else content = cell.v || "";

                      return (
                        <td
                          key={c}
                          className={cls}
                          style={cellCss(styleOf(cell))}
                          colSpan={cell.span?.c ?? undefined}
                          rowSpan={cell.span?.r ?? undefined}
                          onClick={(e) => {
                            if (editRef.current) return;
                            selectCell(r, c, e.shiftKey);
                            // เปิด Format Painter อยู่ → คลิกที่ไหนคือทารูปแบบลงที่นั่น
                            if (painterRef.current) paintRange();
                          }}
                          onDoubleClick={() => startEdit(r, c)}
                          onDragOver={(e) => { e.preventDefault(); e.currentTarget.classList.add("drop"); }}
                          onDragLeave={(e) => e.currentTarget.classList.remove("drop")}
                          onDrop={(e) => {
                            e.preventDefault();
                            e.currentTarget.classList.remove("drop");
                            const from = dragFromRef.current;
                            if (from) {
                              const src = g()[from.r][from.c];
                              if (from.r !== r || from.c !== c) {
                                const key = src.hdr || src.spec || src.f;
                                if (key) {
                                  // ย้ายทั้งบล็อกพร้อมกัน — หัวตาราง/สเปก/ข้อมูลต้องเรียงตัวกันเสมอ
                                  // ไม่งั้นรายงานจะพิมพ์ข้อมูลผิดคอลัมน์
                                  if (!moveFieldBlock(key, r, c, from.dr, from.dc)) {
                                    dragFromRef.current = null; bump(); return;
                                  }
                                } else {
                                  const dst = g()[r][c];
                                  dst.v = src.v; dst.f = ""; dst.hdr = "";
                                  src.v = "";
                                }
                              }
                              dragFromRef.current = null;
                            } else if (dragFieldRef.current) {
                              if (!dropField(r, c, dragFieldRef.current)) {
                                dragFieldRef.current = null; bump(); return;
                              }
                              dragFieldRef.current = null;
                            } else return;
                            selectCell(r, c);
                          }}
                        >
                          {c === 0 && r === dataRowRef.current && <span className="rowbadge" />}
                          {content}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div className="legend">
          <span className="pill">↻ แถบม่วงซ้ายมือ = แถวข้อมูล</span>{" "}
          ทำซ้ำหนึ่งแถวต่อหนึ่งการวัด · แถวอื่นเป็นหัวตารางที่พิมพ์ซ้ำทุกกลุ่ม ·
          รายงานถูกแบ่งกลุ่มด้วยสเปก <strong>Tolerance</strong> เสมอ<br />
          <strong>ลาก 1 ครั้งได้ทั้งบล็อก</strong> — ชื่อคอลัมน์ผสาน 2 แถวตรงที่วาง แล้ว "ข้อมูล …" ลงแถวถัดไปอัตโนมัติ ·{" "}
          <strong>Tolerance</strong> กว้าง 2 คอลัมน์ (หัว / สเปก / ข้อมูล Value X + Value Y) ·
          รูปแบบที่ตั้งให้เซลล์ "ข้อมูล …" จะถูกใช้กับทุกแถวตอน export<br />
          คลิกหัวคอลัมน์/หมายเลขแถวเพื่อแทรกหรือลบ · Shift+คลิกเพื่อคลุมหลายช่องก่อนกด Merge ·
          ลากข้อความออกไปทิ้งที่แผงซ้ายเพื่อเอาออก
        </div>
      </section>

      {/* เมนูของหัวคอลัมน์/เลขแถว */}
      {headMenu && (
        <div
          className="rt-headmenu"
          style={{ left: headMenu.x, top: headMenu.y }}
          onClick={(e) => e.stopPropagation()}
        >
          <div className="hm-title">
            {headMenu.kind === "col" ? `คอลัมน์ ${colName(headMenu.i)}` : `แถวที่ ${headMenu.i + 1}`}
          </div>
          {headMenu.kind === "col" ? (
            <>
              <button type="button" onClick={() => { insertCol(headMenu.i); setHeadMenu(null); }}>⇤ แทรกทางซ้าย</button>
              <button type="button" onClick={() => { insertCol(headMenu.i + 1); setHeadMenu(null); }}>แทรกทางขวา ⇥</button>
              <button type="button" className="del" onClick={() => { deleteCol(headMenu.i); setHeadMenu(null); }}>✕ ลบคอลัมน์นี้</button>
            </>
          ) : (
            <>
              <button type="button" onClick={() => { insertRow(headMenu.i); setHeadMenu(null); }}>⤒ แทรกด้านบน</button>
              <button type="button" onClick={() => { insertRow(headMenu.i + 1); setHeadMenu(null); }}>⤓ แทรกด้านล่าง</button>
              <button type="button" className="del" onClick={() => { deleteRow(headMenu.i); setHeadMenu(null); }}>✕ ลบแถวนี้</button>
              <button type="button" onClick={() => { dataRowRef.current = headMenu.i; setHeadMenu(null); bump(); }}>
                ↻ ตั้งเป็นแถวข้อมูล
              </button>
            </>
          )}
        </div>
      )}
    </div>
  );

  /** เริ่มลากข้อความในเซลล์ — จับตรงไหนก็ได้ในบล็อก แล้วบล็อกทั้งก้อนย้ายตาม
   *  โดยรักษาระยะที่จับไว้ (dr,dc = ระยะจากมุมบนซ้ายของบล็อก) */
  function startTokDrag(ev: React.DragEvent, r: number, c: number) {
    const cell = g()[r][c];
    const owner = ownerOf(cell.hdr || cell.spec || cell.f);
    const o = findCell((x) => x.hdr === owner);
    dragFromRef.current = { r, c, dr: o ? r - o.r : 0, dc: o ? c - o.c : 0 };
    dragFieldRef.current = null;   // กันค่าค้างจากการลากครั้งก่อน
    ev.dataTransfer.effectAllowed = "move";
    ev.dataTransfer.setData("text/plain", `${r}-${c}`);
    ev.stopPropagation();
  }
}
