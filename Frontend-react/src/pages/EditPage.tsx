import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { apiGet, apiPost, apiPatch, apiDelete, ApiError } from "../api/client";
import { useToast } from "../components/Toast";
import TrashCard from "../components/TrashCard";
import LookupTables from "../components/LookupTables";
import HistoryCard from "../components/HistoryCard";
import { axisValue, offsetValue, xyPair, DP_MM, DP_OFF } from "../components/measurementCells";
import { useSessionState } from "../hooks/useSessionState";

// EditPage — พอร์ตจาก Frontend/edit.html (Database Editor) แบบยึดโครงสร้าง/
// field/คอลัมน์/ข้อความ ตามต้นฉบับเป็นหลัก
//
// ความต่างจากต้นฉบับที่ตั้งใจ (ตามที่ผู้ใช้ขอ): ต้นฉบับ edit.html มีฟิลด์
// "Category" (dropdown จาก GET /api/categories) ในฟอร์ม/ตาราง Parts แต่
// backend (main.py) ปัจจุบันไม่มี endpoint /api/categories และ PARTS_SELECT
// ก็ไม่ได้ SELECT คอลัมน์ category เลย — dropdown นี้เลยว่างเปล่าเสมอและใช้
// งานจริงไม่ได้ จึงตัด Category ออกทั้งฟอร์มและคอลัมน์ตาราง แล้วใช้
// "Receive Date" (recieve_date — มีอยู่จริงใน parts/PARTS_SELECT/PartCreate)
// แทนที่ตำแหน่งเดิม

const PAGE_SIZE = 10;

interface Part {
  part_id?: number;
  number_alpl: number;
  part_number: string | null;
  description: string | null;
  po_number: number | null;
  recieve_date: string | null;
  handler: string | null;
  vendor: string | null;
  owner: string | null;
  package_size: string | null;
  nominal_x: number | null;
  nominal_y: number | null;
  upper_tol: number | null;
  lower_tol: number | null;
  template_name: string | null;
}

interface Measurement {
  measurement_id: number;
  session_id: number | null;
  number_alpl: number;
  value_x: number | null;
  value_y: number | null;
  result: string | null;
  note: string | null;
  timestamp: string | null;
  operator_name?: string | null;
  /** ระยะเยื้องแยกแกน — โหมด IPM ไม่เอามาตัดสิน OK/NG (ดู _judge ฝั่ง backend)
   *
   *  ⚠ ตาราง measurements **ไม่มีคอลัมน์ `offset` เดี่ยว** แล้ว ถูกแยกเป็น
   *    offset_opx / offset_opy ตั้งแต่ตอนแก้ _judge ให้ตรวจทีละแกน —
   *    ของเดิมหน้านี้อ่าน `m.offset` ซึ่ง backend ไม่เคยส่งมา ช่อง Offset
   *    จึงว่างเปล่าทุกแถวโดยไม่มี error อะไรเตือน */
  offset_opx?: number | null;
  offset_opy?: number | null;
  offset_tol?: number | null;
  measure_type?: string | null;
  nominal_x?: number | null;
  nominal_y?: number | null;
  upper_tol?: number | null;
  lower_tol?: number | null;
  /** ผลตัดสินรายแกนจาก backend (`_ok_flags` ใน shared.py) — ⚠ **ต้องใช้ตัวนี้
   *  ระบายสี ห้ามคำนวณ `nominal ± tol` เองที่หน้าเว็บ** เพราะ backend ปัด
   *  ทศนิยมด้วย `_DP` ก่อนเทียบ ถ้าคำนวณเองแบบไม่ปัด ชิ้นที่ตกขอบพอดีจะขึ้น
   *  สีแดงทั้งที่คอลัมน์ Result บอก OK · `null` = ตัดสินไม่ได้ ไม่ใช่ไม่ผ่าน */
  ok_x?: boolean | null;
  ok_y?: boolean | null;
  /** แยกรายแกน — ใช้ระบายสีช่องตัวเลข Offset X / Y */
  ok_opx?: boolean | null;
  ok_opy?: boolean | null;
  /** ⚠ ผลรวมของทั้ง 2 แกน — ห้ามเอาไประบายสีช่องรายแกน (ใช้ ok_opx/ok_opy แทน) */
  ok_offset?: boolean | null;
}

/** catalog ของ Part Number — ผูก package_size/handler/nominal/tolerance ของตัวเองไว้แล้ว
 *  (ดู schema `part_number` ใน init.sql) ใช้แสดงกล่องค่า read-only ในฟอร์ม Part */
/** ⚠ ไม่มี nominal/tolerance แล้ว — part_number ไม่ได้ถือเกณฑ์ตัดสินอีกต่อไป
 *  ทุกโหมดใช้ของ package_size (ดู `_load_criteria` ฝั่ง backend) ค่าพวกนั้นจึง
 *  ต้องอ่านจาก `PackageSizeRow` ของขนาดที่ part ตัวนี้ผูกอยู่แทน */
interface PartNumberRow {
  part_number_name: string;
  package_size: string | null;
  handler: string | null;
}

interface PackageSizeRow {
  package_size: string;
  template_name: string | null;
  nominal_x: number | null;
  nominal_y: number | null;
  upper_tol: number | null;
  lower_tol: number | null;
}

interface EditContext {
  table: "parts" | "measurements" | null;
  mode: "add" | "edit" | null;
  key: number | null;
  original: Part | Measurement | null;
}

interface ConfirmState {
  message: ReactNode;
  onConfirm: () => void | Promise<void>;
}

/* ⚠ `valueCell` / `offsetCell` ที่เคยอยู่ตรงนี้ ย้ายไป
   components/measurementCells.tsx แล้ว (เป็น axisValue / offsetValue) เพราะ
   ตาราง Measurements ของหน้า Home ใช้เกณฑ์สีชุดเดียวกัน — ถ้าปล่อยให้ต่างคน
   ต่างมีจะกลายเป็นแถวเดียวกันแต่คนละสีในสองหน้าจอ */

function pageInfoText(page: number, total: number, count: number): string {
  if (total === 0) return "ไม่มีรายการ";
  const start = (page - 1) * PAGE_SIZE + 1;
  const end = (page - 1) * PAGE_SIZE + count;
  return `แสดง ${start}–${end} จาก ${total} รายการ`;
}

function errMsg(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}

/** 1 ช่องในกล่องค่า read-only (label เล็กจางอยู่บน ค่าอยู่ล่าง) — ใช้ทั้งกล่อง
 *  "ค่าที่ผูกมากับ Part Number" ของฟอร์ม Part และ "ข้อมูลของรายการนี้" ของฟอร์ม
 *  Measurement เพราะต้นฉบับใช้หน้าตาเดียวกันทั้งคู่ */
function DerivedCell({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="derived-cell-label">{label}</div>
      <div>{value}</div>
    </div>
  );
}

/** ตัวเลือกของ select ที่มาจาก lookup — ใช้ร่วมกันทุกช่องในหน้านี้
 *
 *  ⚠ `disabled hidden` บนตัวเลือกว่าง = โชว์ตอนยังไม่ได้เลือก แต่ไม่โผล่ในรายการ
 *    ตอนกดเปิด (ไม่มีบรรทัด "-- เลือก --" ให้เลื่อนผ่าน) และเลือกกลับเป็นค่าว่าง
 *    ไม่ได้ — ตั้งใจ เพราะทุกช่องที่ใช้ helper นี้เป็น field ที่ต้องมีค่า
 */
function renderOptions(items: string[]) {
  return (
    <>
      <option value="" disabled hidden>-- เลือก --</option>
      {items.map((name) => (
        <option key={name} value={name}>
          {name}
        </option>
      ))}
    </>
  );
}

export default function EditPage() {
  const toast = useToast();

  // ── ต่อสายกับถังขยะ ──────────────────────────────────────────────────
  // หน้านี้ถือ state เองด้วย useState (พอร์ตตรงจาก edit.html) ไม่ได้ใช้ TanStack
  // Query จึงต้องบอก TrashCard ตรงๆ ว่า "เพิ่งลบอะไรไป ไปโหลดใหม่ที"
  //
  // ⚠ ทุกจุดที่ยิง DELETE ต้องเรียก bumpTrash() ด้วย — ตอนนี้มี 3 จุด (Part /
  //   Measurement / Lookup) ถ้าวันหลังเพิ่มปุ่มลบที่ 4 แล้วลืมเติม ถังขยะจะไม่
  //   อัปเดตเฉพาะปุ่มนั้น อาการจะสับสนมากเพราะที่อื่นทำงานปกติดี
  //   (ต้นฉบับใช้ afterDelete() เป็นตัวกลางกันลืมด้วยเหตุผลเดียวกัน)
  const [trashReload, setTrashReload] = useState(0);
  /** ⚠ ประวัติต้องรีเฟรชทุกครั้งที่มีการเขียน DB ไม่ใช่เฉพาะตอนลบเหมือนถังขยะ —
   *  bumpTrash() เดิมถูกเรียกเฉพาะจุดที่ลบ ถ้าใช้ตัวเดียวกัน การ "เพิ่ม/แก้ไข"
   *  จะไม่โผล่ในประวัติจนกว่าจะรีเฟรชหน้า */
  const [historyReload, setHistoryReload] = useState(0);
  const bumpHistory = () => setHistoryReload((v) => v + 1);
  const bumpTrash = () => { setTrashReload((v) => v + 1); bumpHistory(); };
  const formRef = useRef<HTMLFormElement>(null);

  // ── Parts state (server-side pagination + search) ──────────────────
  const [partsData, setPartsData] = useState<Part[]>([]);
  const [partsTotal, setPartsTotal] = useState(0);
  const [partsPage, setPartsPage] = useState(1);
  const [partsSearchInput, setPartsSearchInput] = useState("");
  const partsSearchRef = useRef("");
  const partsSearchTimer = useRef<number | null>(null);

  // ── Measurements state (server-side pagination + filter) ───────────
  const [measurementsData, setMeasurementsData] = useState<Measurement[]>([]);
  const [measTotal, setMeasTotal] = useState(0);
  const [measPage, setMeasPage] = useState(1);
  const [measSearchInput, setMeasSearchInput] = useState("");
  const [measDate, setMeasDate] = useState("");
  const measSearchRef = useRef("");
  const measSearchTimer = useRef<number | null>(null);

  // ── Session running lock ────────────────────────────────────────────
  /** กำลังมีการวัดอยู่ไหม — ใช้ล็อกปุ่มแก้/ลบทั้งหน้า
   *
   *  ⚠ เดิมหน้านี้ตั้ง setInterval ยิง /api/session/state เองทุก 4 วิ ตอนนี้ไป
   *    เกาะ useSessionState() แทน เพราะ:
   *      · TanStack Query รวมคำขอให้ตาม queryKey — Layout ก็เรียก hook เดียวกัน
   *        อยู่แล้ว เปิดหน้านี้จึงไม่ได้เพิ่มคำขอใหม่เลย (ของเดิมเพิ่ม 1 ชุด)
   *      · ตรรกะแยก 503 / อ่าน pi_status จาก body ของ error / retry:false
   *        อยู่ในนั้นครบแล้ว ไม่ต้องลอกมาไว้ที่นี่อีกชุด
   *
   *  ⚠ ผลข้างเคียงที่ยอมรับ: ตอน session กำลัง running จะ poll ถี่ขึ้นเป็น 1 วิ
   *    (ของเดิม 4 วิคงที่) เพราะ useSessionState เร่งความถี่เองตอนวัดอยู่
   *
   *  `undefined` (ยังโหลดไม่เสร็จ / ถามไม่ได้) → ถือว่า **ไม่ได้วัดอยู่** เพื่อไม่ให้
   *  หน้าจอล็อกค้างตอน backend ล่ม — ฝั่ง backend มี _block_if_session_running()
   *  กันอีกชั้นอยู่แล้ว ตัวนี้เป็นแค่การบอกผู้ใช้ล่วงหน้า
   */
  const { data: sessionState } = useSessionState();
  const sessionRunning = sessionState?.state === "running";

  // ── Dropdown lookups ─────────────────────────────────────────────────
  /* Handler กลับมาเป็น field ที่กรอกตรงๆ อีกครั้ง — `parts_specifications` เก็บ
     `handler_id` ของตัวเองแล้ว ไม่ได้ derive จาก part_number อย่างเดียว
     (คอมเมนต์เดิมตรงนี้บอกว่าไม่มี Handler แล้ว ซึ่งตกรุ่นไปตั้งแต่เพิ่มคอลัมน์) */
  const [handlerOptions, setHandlerOptions] = useState<string[]>([]);
  const [vendorOptions, setVendorOptions] = useState<string[]>([]);
  const [ownerOptions, setOwnerOptions] = useState<string[]>([]);
  const [operatorOptions, setOperatorOptions] = useState<string[]>([]);
  const [packageSizeOptions, setPackageSizeOptions] = useState<string[]>([]);
  // catalog เต็มของ part_number / package_size — เก็บไว้ทั้งแถวเพื่อคำนวณกล่อง
  // ค่า read-only ในฟอร์ม Part ได้ทันทีที่เปลี่ยน dropdown โดยไม่ต้องยิง API ซ้ำ
  const [partNumberCatalog, setPartNumberCatalog] = useState<PartNumberRow[]>([]);
  const [packageSizeCatalog, setPackageSizeCatalog] = useState<PackageSizeRow[]>([]);

  // ── Modal / form state ───────────────────────────────────────────────
  const [editContext, setEditContext] = useState<EditContext>({ table: null, mode: null, key: null, original: null });
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [alplNoteConsumed, setAlplNoteConsumed] = useState(false);
  const [confirmState, setConfirmState] = useState<ConfirmState | null>(null);
  /** popup แจ้งเตือนเฉยๆ (ปุ่ม "ตกลง" อย่างเดียว) — แยกจาก confirmState ที่มีปุ่ม
   *  ลบซึ่งทำ action จริง ใช้กับกรณี "ลบไม่ได้เพราะยังมีตารางอื่นอ้างอิงอยู่" (409)
   *  ที่ต้องให้ผู้ใช้เห็นชัดๆ ไม่ใช่ toast ที่หายไปเองใน 3 วิ */
  const [alertText, setAlertText] = useState<string | null>(null);

  // ── ฟอร์ม Part: ช่องที่ต้อง cascade กันจึงคุมด้วย state (ที่เหลืออ่านจาก FormData)
  //    Package Size → กำหนดว่าเลือก Part Number ตัวไหนได้ → Part Number กำหนด
  //    Handler/Nominal/Tolerance/Template ที่โชว์ในกล่อง read-only อีกทอด
  const [pkgValue, setPkgValue] = useState("");
  const [pnValue, setPnValue] = useState("");
  const [pnOptions, setPnOptions] = useState<string[]>([]);
  const pnImmediate = useRef(false);

  // ── Row highlight (highlight-row, 2.2s fade — เหมือนต้นฉบับ) ─────────
  const [highlight, setHighlight] = useState<{ table: "parts" | "measurements"; key: number } | null>(null);
  function flashHighlight(table: "parts" | "measurements", key: number) {
    setHighlight({ table, key });
    window.setTimeout(() => setHighlight((h) => (h && h.key === key && h.table === table ? null : h)), 2300);
  }

  async function loadParts(page: number, search: string) {
    const params: Record<string, string | number> = { limit: PAGE_SIZE, offset: (page - 1) * PAGE_SIZE };
    if (search) params.search = search;
    try {
      const d = await apiGet<{ items: Part[]; total: number }>("/api/parts", params);
      setPartsData(d.items ?? []);
      setPartsTotal(d.total ?? 0);
      return d.items ?? [];
    } catch (e) {
      console.error("loadParts:", e);
      toast.show("ไม่สามารถดึงข้อมูล Parts จาก Database ได้");
      return [];
    }
  }

  async function loadMeasurements(page: number, search: string, date: string) {
    const params: Record<string, string | number> = { limit: PAGE_SIZE, offset: (page - 1) * PAGE_SIZE };
    if (search && /^\d+$/.test(search)) params.number_alpl = search;
    if (date) {
      params.date_from = `${date} 00:00:00`;
      params.date_to = `${date} 23:59:59`;
    }
    try {
      const d = await apiGet<{ items: Measurement[]; total: number }>("/api/measurements", params);
      setMeasurementsData(d.items ?? []);
      setMeasTotal(d.total ?? 0);
      return d.items ?? [];
    } catch (e) {
      console.error("loadMeasurements:", e);
      toast.show("ไม่สามารถดึงข้อมูล Measurements จาก Database ได้");
      return [];
    }
  }

  async function loadDropdownData() {
    /* ⚠ ลำดับชื่อทางซ้ายต้องตรงกับลำดับ promise ทางขวาเป๊ะ — แทรกตัวใหม่ตรงกลาง
       แล้วลืมเติมชื่อ จะทำให้ทุกตัวหลังจากนั้นรับข้อมูลผิดชนิดโดยไม่มี error
       (TypeScript จับให้ได้เพราะ type ต่างกัน แต่ถ้าบังเอิญเหมือนกันจะเงียบสนิท) */
    const [vendors, handlers, owners, packageSizes, partNumbers, operators] = await Promise.all([
      apiGet<{ vendor_name: string }[]>("/api/vendors").catch(() => []),
      apiGet<{ handler_name: string }[]>("/api/handlers").catch(() => []),
      apiGet<{ owner_name: string }[]>("/api/owners").catch(() => []),
      apiGet<PackageSizeRow[]>("/api/package-sizes").catch(() => []),
      apiGet<PartNumberRow[]>("/api/part-numbers/all").catch(() => []),
      apiGet<{ operator_name: string }[]>("/api/operators").catch(() => []),
    ]);
    setHandlerOptions(handlers.map((h) => h.handler_name));
    setVendorOptions(vendors.map((v) => v.vendor_name));
    setOwnerOptions(owners.map((o) => o.owner_name));
    setOperatorOptions(operators.map((o) => o.operator_name));
    setPackageSizeCatalog(packageSizes);
    setPartNumberCatalog(partNumbers);
    setPackageSizeOptions(packageSizes.map((p) => p.package_size));
  }

  useEffect(() => {
    (async () => {
      await Promise.all([loadParts(1, ""), loadMeasurements(1, "", ""), loadDropdownData()]);
    })();
    // ไม่มี setInterval แล้ว — สถานะ session มาจาก useSessionState() ข้างบน
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function reloadPartsAfterMutation(highlightAlpl?: number) {
    let page = partsPage;
    let items = await loadParts(page, partsSearchRef.current);
    if (items.length === 0 && page > 1) {
      page -= 1;
      setPartsPage(page);
      items = await loadParts(page, partsSearchRef.current);
    }
    if (highlightAlpl != null) flashHighlight("parts", highlightAlpl);
  }
  async function reloadMeasAfterMutation(highlightId?: number) {
    let page = measPage;
    let items = await loadMeasurements(page, measSearchRef.current, measDate);
    if (items.length === 0 && page > 1) {
      page -= 1;
      setMeasPage(page);
      items = await loadMeasurements(page, measSearchRef.current, measDate);
    }
    if (highlightId != null) flashHighlight("measurements", highlightId);
  }

  // ── Parts filter handlers ────────────────────────────────────────────
  function onPartsSearchChange(value: string) {
    setPartsSearchInput(value);
    if (partsSearchTimer.current) window.clearTimeout(partsSearchTimer.current);
    partsSearchTimer.current = window.setTimeout(async () => {
      partsSearchRef.current = value.trim();
      setPartsPage(1);
      await loadParts(1, partsSearchRef.current);
    }, 300);
  }
  async function onPartsClearFilter() {
    if (partsSearchTimer.current) window.clearTimeout(partsSearchTimer.current);
    setPartsSearchInput("");
    partsSearchRef.current = "";
    setPartsPage(1);
    await loadParts(1, "");
  }
  async function onPartsPrev() {
    if (partsPage <= 1) return;
    const p = partsPage - 1;
    setPartsPage(p);
    await loadParts(p, partsSearchRef.current);
  }
  async function onPartsNext() {
    if ((partsPage - 1) * PAGE_SIZE + partsData.length >= partsTotal) return;
    const p = partsPage + 1;
    setPartsPage(p);
    await loadParts(p, partsSearchRef.current);
  }

  // ── Measurements filter handlers ─────────────────────────────────────
  function onMeasSearchChange(value: string) {
    setMeasSearchInput(value);
    if (measSearchTimer.current) window.clearTimeout(measSearchTimer.current);
    measSearchTimer.current = window.setTimeout(async () => {
      measSearchRef.current = value.trim();
      setMeasPage(1);
      await loadMeasurements(1, measSearchRef.current, measDate);
    }, 300);
  }
  async function onMeasDateChange(value: string) {
    setMeasDate(value);
    setMeasPage(1);
    await loadMeasurements(1, measSearchRef.current, value);
  }
  async function onMeasClearFilter() {
    if (measSearchTimer.current) window.clearTimeout(measSearchTimer.current);
    setMeasSearchInput("");
    setMeasDate("");
    measSearchRef.current = "";
    setMeasPage(1);
    await loadMeasurements(1, "", "");
  }
  async function onMeasPrev() {
    if (measPage <= 1) return;
    const p = measPage - 1;
    setMeasPage(p);
    await loadMeasurements(p, measSearchRef.current, measDate);
  }
  async function onMeasNext() {
    if ((measPage - 1) * PAGE_SIZE + measurementsData.length >= measTotal) return;
    const p = measPage + 1;
    setMeasPage(p);
    await loadMeasurements(p, measSearchRef.current, measDate);
  }

  // ── Modal open/close ─────────────────────────────────────────────────
  function openPartModal(mode: "add" | "edit", numberAlpl: number | null = null) {
    const part = mode === "edit" ? partsData.find((p) => p.number_alpl === numberAlpl) ?? null : null;
    setEditContext({ table: "parts", mode, key: numberAlpl, original: part });
    setFieldErrors({});
    setAlplNoteConsumed(false);
    // ตั้งค่าตั้งต้นของคู่ที่ cascade กัน — effect ด้านล่างจะไปโหลด option ของ
    // Part Number ให้เองตาม pkgValue แล้วคงค่า pnValue เดิมไว้ถ้ายังเลือกได้อยู่
    setPkgValue(String(part?.package_size ?? ""));
    setPnValue(String(part?.part_number ?? ""));
    setPnOptions([]);
    // รอบแรกตอนเปิด modal ต้องโหลดทันที ไม่ต้อง debounce — ไม่งั้นช่อง Part Number
    // จะขึ้น disabled ค้างอยู่ 250ms ทั้งที่ Package Size มีค่าอยู่แล้ว (โหมด Edit)
    pnImmediate.current = true;
  }

  /* Package Size → Part Number (cascade)
   *
   * Part Number เป็น catalog ที่ผูก package_size ของตัวเองไว้แล้ว จึงเลือกได้
   * เฉพาะตัวที่อยู่ใน Package Size ที่กรอกไว้เท่านั้น — debounce 250ms เพราะช่อง
   * Package Size เป็น input ที่พิมพ์ได้ (datalist) ไม่ใช่ dropdown ปิด ถ้ายิงทุก
   * keystroke จะได้ request ท่วมและผลกลับมาสลับลำดับกันเอง
   *
   * ⚠ ต้อง cleanup timer ทุกครั้ง — ไม่งั้นพิมพ์เร็วๆ แล้ว request ของค่าเก่า
   *   ตอบทีหลัง จะทับ option ของค่าล่าสุด
   */
  useEffect(() => {
    if (editContext.table !== "parts") return;
    const pkg = pkgValue.trim();
    if (!pkg) {
      setPnOptions([]);
      return;
    }
    const delay = pnImmediate.current ? 0 : 250;
    pnImmediate.current = false;
    const t = window.setTimeout(async () => {
      try {
        const names = await apiGet<string[]>("/api/part-numbers", { package_size: pkg });
        setPnOptions(names);
        // Package Size ใหม่อาจไม่มี Part Number ตัวเดิมอยู่ → ล้างทิ้ง ไม่ปล่อยให้
        // ค้างค่าที่เลือกไม่ได้แล้ว (กล่องค่า read-only จะได้ไม่โชว์ของผิดชุด)
        setPnValue((v) => (names.includes(v) ? v : ""));
      } catch {
        setPnOptions([]);
      }
    }, delay);
    return () => window.clearTimeout(t);
  }, [pkgValue, editContext.table]);
  function openMeasModal(mode: "add" | "edit", measurementId: number | null = null) {
    const m = mode === "edit" ? measurementsData.find((x) => x.measurement_id === measurementId) ?? null : null;
    setEditContext({ table: "measurements", mode, key: measurementId, original: m });
    setFieldErrors({});
    setAlplNoteConsumed(false);
  }
  function closeEditModal() {
    setEditContext({ table: null, mode: null, key: null, original: null });
    setFieldErrors({});
  }

  // ── Save Part ─────────────────────────────────────────────────────────
  async function savePart(e: FormEvent) {
    e.preventDefault();
    if (!formRef.current) return;
    const fd = new FormData(formRef.current);
    const get = (k: string) => ((fd.get(k) as string) ?? "").trim();
    const errors: Record<string, string> = {};
    const isAdd = editContext.mode === "add";

    const numberAlplRaw = get("number_alpl");
    const nAlpl = Number(numberAlplRaw);
    if (numberAlplRaw === "" || !Number.isInteger(nAlpl) || nAlpl <= 0) {
      errors.number_alpl = "ต้องเป็นเลขจำนวนเต็มบวก";
    } else if (partsData.some((p) => p.number_alpl === nAlpl && p.number_alpl !== editContext.key)) {
      errors.number_alpl = `ALPL ${nAlpl} มีอยู่ในตารางแล้ว`;
    }

    // field อื่นนอกจาก ALPL บังคับกรอกเฉพาะตอน Add — ตอน Edit ปล่อยว่างได้หมด
    if (isAdd) {
      // package_size เป็นตัวกำหนด catalog ของ Part Number ที่เลือกได้ จึงบังคับก่อนเสมอ
      if (!pkgValue.trim()) errors.package_size = "กรอก Package Size ก่อนถึงจะเลือก Part Number ได้";
      // Part Number เป็นตัวกำหนด Handler/Nominal/Tolerance/Template ให้อัตโนมัติทั้งหมด
      if (!pnValue) errors.part_number = "เลือก Part Number";
      if (!get("vendor")) errors.vendor = "เลือก Vendor";
      if (!get("description")) errors.description = "กรอก Description";
      if (!get("po_number")) errors.po_number = "กรอก PO Number";
      if (!get("owner")) errors.owner = "เลือก Owner";
    }

    if (Object.keys(errors).length > 0) {
      setFieldErrors(errors);
      if (errors.number_alpl) setAlplNoteConsumed(true);
      return;
    }

    /* ⚠ คอมเมนต์เดิมตรงนี้บอกว่า "ไม่มี handler ใน record เพราะ backend derive
       จาก part_number ให้เอง" — **ตกรุ่นแล้ว** ตอนนี้ parts_specifications เก็บ
       handler_id ของตัวเอง เพราะ "ALPL ตัวนี้อยู่บนเครื่องไหน" เป็นข้อเท็จจริง
       ของ ALPL ไม่ใช่ของ catalog (part เดียวกันอาจมี ALPL อยู่คนละเครื่อง)
       ฝั่ง backend อ่านด้วย COALESCE(ของ ALPL, ของ part_number) เสมอ */
    const record: Record<string, unknown> = {
      number_alpl: nAlpl,
      part_number: pnValue,
      handler: get("handler") || null,
      vendor: get("vendor") || null,
      description: get("description") || null,
      po_number: get("po_number") === "" ? null : Number(get("po_number")),
      package_size: pkgValue.trim() || null,
      owner: get("owner") || null,
      recieve_date: get("recieve_date") || null,
    };

    if (!isAdd && editContext.original) {
      const orig = editContext.original as unknown as Record<string, unknown>;
      const changed = Object.keys(record).some((k) => String(orig[k] ?? null) !== String(record[k] ?? null));
      if (!changed) {
        closeEditModal();
        return;
      }
    }

    try {
      if (isAdd) await apiPost("/api/parts", record);
      else await apiPatch(`/api/parts/${editContext.key}`, record);
      toast.show(isAdd ? `เพิ่ม ALPL ${nAlpl} สำเร็จ` : `บันทึก ALPL ${nAlpl} สำเร็จ`);
      bumpHistory();
      await reloadPartsAfterMutation(nAlpl);
      closeEditModal();
    } catch (err) {
      toast.show(errMsg(err, "บันทึกข้อมูล Part ไม่สำเร็จ"));
    }
  }

  function confirmDeletePart(numberAlpl: number) {
    // ลบ Part ได้ต่อเมื่อ ALPL นี้ไม่มี Session/Measurement เหลืออยู่เลยเท่านั้น —
    // FK เป็น RESTRICT (ไม่มีโหมด cascade ตามที่ตกลงกันว่า "เก็บประวัติไว้เหมือนเดิม")
    // ถ้ายังมีประวัติอยู่ backend ปฏิเสธด้วย 409 พร้อมบอกจำนวนที่ติดอยู่ → เอาข้อความ
    // นั้นมาเด้งเป็น alert ให้เห็นชัด ไม่ใช่ toast ที่หายไปเองก่อนอ่านทัน
    setConfirmState({
      message: (
        <>
          ลบ Part <strong>ALPL {numberAlpl}</strong> ออกจากตารางใช่ไหม?
        </>
      ),
      onConfirm: async () => {
        setConfirmState(null);
        try {
          await apiDelete(`/api/parts/${numberAlpl}`);
          await reloadPartsAfterMutation();
          bumpTrash();
          closeEditModal();
          toast.show(`ลบ ALPL ${numberAlpl} สำเร็จ`);
        } catch (err) {
          setAlertText(errMsg(err, "ลบ Part ไม่สำเร็จ"));
        }
      },
    });
  }

  // ── Save Measurement ──────────────────────────────────────────────────
  async function saveMeas(e: FormEvent) {
    e.preventDefault();
    if (!formRef.current) return;
    const fd = new FormData(formRef.current);
    const get = (k: string) => ((fd.get(k) as string) ?? "").trim();
    const isEdit = editContext.mode === "edit";
    const errors: Record<string, string> = {};

    const numberAlplRaw = get("number_alpl");
    const nAlpl = Number(numberAlplRaw);
    if (numberAlplRaw === "" || !Number.isInteger(nAlpl) || nAlpl <= 0) {
      errors.number_alpl = "ต้องเป็นเลขจำนวนเต็มบวก";
    } else if (!partsData.some((p) => p.number_alpl === nAlpl)) {
      errors.number_alpl = `ALPL ${nAlpl} ยังไม่ได้ลงทะเบียนในตาราง Parts`;
    }

    let sessionId: number | null = null;
    if (isEdit) {
      const existing = measurementsData.find((m) => m.measurement_id === editContext.key);
      sessionId = existing?.session_id ?? null;
    }

    // ตอน Edit แก้ได้เฉพาะ ALPL กับ Operator เท่านั้น — ช่อง Value X/Y และ Note
    // ถูกย้ายไปอยู่ในกล่อง 🔒 read-only แล้ว (ผลการวัดจริงจากเครื่อง แก้ย้อนหลังไม่ได้)
    let valueX: number | undefined;
    let valueY: number | undefined;
    let operator: string | null = null;
    if (!isEdit) {
      const vx = get("value_x");
      const vy = get("value_y");
      if (vx === "" || isNaN(Number(vx))) errors.value_x = "กรอก Value X เป็นตัวเลข";
      if (vy === "" || isNaN(Number(vy))) errors.value_y = "กรอก Value Y เป็นตัวเลข";
      valueX = Number(vx);
      valueY = Number(vy);
    } else {
      // operator_id ใน DB เป็น NOT NULL — เว้นว่างไม่ได้
      operator = get("operator");
      if (!operator) errors.operator = "เลือก Operator";
    }

    if (Object.keys(errors).length > 0) {
      setFieldErrors(errors);
      if (errors.number_alpl) setAlplNoteConsumed(true);
      return;
    }

    // ไม่ส่ง result — backend คำนวณ OK/NG ใหม่เองเสมอจาก value + tolerance ของ ALPL ที่เลือก
    const payload: Record<string, unknown> = isEdit
      ? { session_id: sessionId, number_alpl: nAlpl, operator }
      : { session_id: sessionId, number_alpl: nAlpl, value_x: valueX, value_y: valueY, note: get("note") || null };

    if (isEdit && editContext.original) {
      const orig = editContext.original as Measurement;
      const alplSame = String(orig.number_alpl ?? null) === String(payload.number_alpl ?? null);
      const operatorSame = String(orig.operator_name ?? null) === String(payload.operator ?? null);
      if (alplSame && operatorSame) {
        closeEditModal();
        return;
      }
    }

    try {
      const res = isEdit
        ? await apiPatch<{ result?: string }>(`/api/measurements/${editContext.key}`, payload)
        : await apiPost<{ result?: string }>("/api/measurements", payload);
      const resultNote = res?.result ? ` (Result: ${res.result})` : "";
      toast.show(isEdit ? `บันทึก Measurement ID ${editContext.key} เรียบร้อยแล้ว${resultNote}` : `เพิ่ม Measurement เรียบร้อยแล้ว${resultNote}`);
      bumpHistory();
      await reloadMeasAfterMutation((editContext.key as number) ?? undefined);
      closeEditModal();
    } catch (err) {
      toast.show(errMsg(err, "บันทึกข้อมูล Measurement ไม่สำเร็จ"));
    }
  }

  function confirmDeleteMeas(measurementId: number) {
    setConfirmState({
      message: (
        <>
          ลบ Measurement <strong>ID {measurementId}</strong> ออกจากตารางใช่ไหม?
        </>
      ),
      onConfirm: async () => {
        setConfirmState(null);
        try {
          await apiDelete(`/api/measurements/${measurementId}`);
          bumpTrash();
          await reloadMeasAfterMutation();
          closeEditModal();
          toast.show(`ลบ Measurement ID ${measurementId} สำเร็จ`);
        } catch (err) {
          setAlertText(errMsg(err, "ลบ Measurement ไม่สำเร็จ"));
        }
      },
    });
  }

  const isEdit = editContext.mode === "edit";
  const reqMark = editContext.mode === "add" ? <span className="req">*</span> : null;
  const partOrig = editContext.table === "parts" ? (editContext.original as Part | null) : null;
  const measOrig = editContext.table === "measurements" ? (editContext.original as Measurement | null) : null;
  const pv = (field: keyof Part) => (partOrig ? (partOrig[field] as string | number | null) ?? "" : "");
  const mv = (field: keyof Measurement) => (measOrig ? (measOrig[field] as string | number | null) ?? "" : "");

  // ค่า read-only ที่ผูกมากับ Part Number ที่เลือกอยู่ตอนนี้ — Handler/Nominal/
  // Tolerance มาจาก part_number ตรงๆ ส่วน Template ต้อง lookup ต่ออีกทอดจาก
  // package_size ของ part_number นั้น (ไม่ได้ผูกกับ part_number โดยตรง)
  const selectedPn = partNumberCatalog.find((x) => x.part_number_name === pnValue) ?? null;
  /* เกณฑ์ตัดสินมาจาก package_size ของ part ตัวนั้น ไม่ใช่จาก part_number เอง */
  const selectedPkg =
    packageSizeCatalog.find((ps) => ps.package_size === selectedPn?.package_size) ?? null;
  const derivedTemplate =
    selectedPkg?.template_name ?? "—";

  return (
    <div className="main-edit">
      {sessionRunning && (
        <div className="mock-banner">
          ⏳ ขณะนี้กำลังวัดอยู่ (Session Running) — ไม่สามารถแก้ไขหรือลบข้อมูล Part / Measurement ได้ กรุณากด Stop session ก่อน
        </div>
      )}

      {/* ═══════════════════════ PARTS TABLE ═══════════════════════ */}
      <section className="card">
        <div className="card-header">
          <div className="card-title">
            Parts <span className="count">({partsTotal})</span>
          </div>
          <button type="button" className="btn-add" onClick={() => openPartModal("add")}>
            + Add Part
          </button>
        </div>

        <div className="filter-bar">
          <input
            type="text"
            placeholder="ค้นหาด้วย ALPL Number..."
            value={partsSearchInput}
            onChange={(e) => onPartsSearchChange(e.target.value)}
          />
          <button type="button" className="btn-clear-filter" onClick={onPartsClearFilter}>
            ✕ Clear Filter
          </button>
        </div>
        <div className="filter-result-note" />

        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                {/* ⚠ `th-derived` (มีกุญแจ 🔒 ต่อท้าย + สีจาง) = คอลัมน์ read-only ที่
                    ระบบ derive มาให้ แก้ที่ตารางนี้ไม่ได้
                    เหลือแค่ Template (มาจาก Package Size) ตัวเดียว
                    Nominal/Tol ไม่อยู่ในตารางนี้ (ต้นฉบับไม่มี) — มันเป็นค่าของ
                    package_size ไปดูที่การ์ด Lookup Tables แทน

                    ⚠ **Handler ไม่ใช่ derived แล้ว** — `parts_specifications` เก็บ
                      `handler_id` ของตัวเอง และฟอร์มมี dropdown ให้แก้ได้จริง
                      (ค่าที่โชว์คือ COALESCE ของ ALPL ก่อน ถ้าไม่มีค่อยของ part_number) */}
                <th>Part ID</th>
                <th>ALPL</th>
                <th>Part Number</th>
                <th>Handler</th>
                <th>Package Size</th>
                <th className="th-derived">Template</th>
                <th>Vendor</th>
                <th>Owner</th>
                <th>PO Number</th>
                <th>Description</th>
                <th>Receive Date</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {partsData.length === 0 ? (
                <tr className="empty-row">
                  <td colSpan={12}>{partsSearchRef.current ? "ไม่พบ Part ที่ตรงกับคำค้นหา" : "ยังไม่มีข้อมูล Parts"}</td>
                </tr>
              ) : (
                partsData.map((p) => (
                  <tr key={p.number_alpl} className={highlight?.table === "parts" && highlight.key === p.number_alpl ? "highlight-row" : ""}>
                    <td>{p.part_id ?? "—"}</td>
                    <td>
                      <strong>{p.number_alpl}</strong>
                    </td>
                    <td>{p.part_number ?? ""}</td>
                    <td>{p.handler ?? ""}</td>
                    <td>{p.package_size ?? ""}</td>
                    <td className="td-derived">{p.template_name ?? ""}</td>
                    <td>{p.vendor ?? ""}</td>
                    <td>{p.owner ?? ""}</td>
                    <td>{p.po_number ?? ""}</td>
                    <td className="desc-cell" title={p.description ?? ""}>
                      {p.description ?? ""}
                    </td>
                    <td>{p.recieve_date ? String(p.recieve_date).slice(0, 10) : ""}</td>
                    <td className="row-actions">
                      <div className="actions-inner">
                        <button
                          className="btn-icon edit"
                          disabled={sessionRunning}
                          title={sessionRunning ? "กำลังวัดอยู่ ไม่สามารถแก้ไขได้" : undefined}
                          onClick={() => openPartModal("edit", p.number_alpl)}
                        >
                          ✎ Edit
                        </button>
                        <button
                          className="btn-icon delete"
                          disabled={sessionRunning}
                          title={sessionRunning ? "กำลังวัดอยู่ ไม่สามารถลบได้" : undefined}
                          onClick={() => confirmDeletePart(p.number_alpl)}
                        >
                          🗑
                        </button>
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
        <div className="pagination-bar">
          <button type="button" className="btn-icon" disabled={partsPage <= 1} onClick={onPartsPrev}>
            ‹ Previous
          </button>
          <span style={{ fontSize: "0.85rem", fontWeight: 600 }}>{pageInfoText(partsPage, partsTotal, partsData.length)}</span>
          <button
            type="button"
            className="btn-icon"
            disabled={(partsPage - 1) * PAGE_SIZE + partsData.length >= partsTotal}
            onClick={onPartsNext}
          >
            Next ›
          </button>
        </div>
      </section>

      {/* ═══════════════════════ MEASUREMENTS TABLE ═══════════════════════ */}
      <section className="card">
        <div className="card-header">
          <div className="card-title">
            Measurements <span className="count">({measTotal})</span>
          </div>
        </div>

        <div className="filter-bar">
          <input
            type="text"
            placeholder="ค้นหาด้วย ALPL Number..."
            value={measSearchInput}
            onChange={(e) => onMeasSearchChange(e.target.value)}
          />
          <input type="date" title="กรองตาม Timestamp (วันที่)" value={measDate} onChange={(e) => onMeasDateChange(e.target.value)} />
          <button type="button" className="btn-clear-filter" onClick={onMeasClearFilter}>
            ✕ Clear Filter
          </button>
        </div>
        <div className="filter-result-note" />

        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                {/* ⚠ ลำดับ/ชื่อคอลัมน์ต้องตรงกับตาราง Measurements หน้า Home
                    (DashboardPage) ทุกตัว **ยกเว้น Image** ที่ไม่เอามา เพราะ
                    หน้านี้เป็นหน้าแก้ข้อมูล ไม่ใช่หน้าดูผล — คนที่อยากดูรูป
                    เปิดจากหน้า Home ซึ่งกดแถวแล้วมีรายงานเต็มให้อยู่แล้ว
                    ถ้าแก้ที่นี่ต้องไปแก้อีกฝั่งด้วย ไม่งั้นสองหน้าจะเล่าคนละเรื่อง

                    🔒 = แก้ไม่ได้ · แก้ได้เฉพาะ ALPL กับ Operator เท่านั้น
                    (ค่าที่วัดมาจริงกับข้อมูลของ session แก้ย้อนหลังไม่ได้) */}
                <th className="th-derived">ID</th>
                <th className="th-derived">Session</th>
                <th>ALPL</th>
                {/* เกณฑ์ที่ใช้ตัดสินการวัดครั้งนั้น — วางไว้ "ก่อน" Value X
                    เพื่อให้อ่านไล่ซ้าย→ขวาได้ว่า "เกณฑ์เท่านี้ วัดได้เท่านี้
                    ผลเลยเป็นแบบนี้" (ลำดับเดียวกับหน้า Home) */}
                <th className="th-derived">Nominal X / Y</th>
                <th className="th-derived">Tol (+/-)</th>
                <th className="th-derived">Offset Tol</th>
                <th className="th-derived">Value X/Y</th>
                <th className="th-derived">Offset X/Y</th>
                <th className="th-derived">Result</th>
                <th className="th-derived">Note</th>
                <th>Operator</th>
                <th className="th-derived">Measure Type</th>
                <th className="th-derived">Timestamp</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {measurementsData.length === 0 ? (
                <tr className="empty-row">
                  <td colSpan={15}>{measSearchRef.current || measDate ? "ไม่พบ Measurement ที่ตรงกับตัวกรอง" : "ยังไม่มีข้อมูล Measurements"}</td>
                </tr>
              ) : (
                measurementsData.map((m) => {
                  const res = m.result || "—";
                  const cls = res === "OK" ? "ok" : res === "NG" ? "ng" : "";
                  const ts = m.timestamp ? new Date(m.timestamp).toLocaleString() : "—";
                  // โหมดของ "แถวนี้" ไม่ใช่โหมดของ session ปัจจุบัน — ตารางนี้
                  // แสดงข้อมูลย้อนหลังที่ปนกันทุกโหมด (กติกาเดียวกับหน้า Home)
                  const isIpm = (m.measure_type ?? "").toUpperCase() === "IPM";
                  return (
                    <tr
                      key={m.measurement_id}
                      className={highlight?.table === "measurements" && highlight.key === m.measurement_id ? "highlight-row" : ""}
                    >
                      <td>{m.measurement_id}</td>
                      <td className="td-derived">{m.session_id ?? ""}</td>
                      <td>
                        <strong>{m.number_alpl}</strong>
                      </td>
                      <td className="td-derived" style={{ whiteSpace: "nowrap" }}>
                        {m.nominal_x != null && m.nominal_y != null
                          ? `${Number(m.nominal_x).toFixed(DP_MM)} / ${Number(m.nominal_y).toFixed(DP_MM)}`
                          : "—"}
                      </td>
                      <td className="td-derived" style={{ whiteSpace: "nowrap" }}>
                        {m.upper_tol != null && m.lower_tol != null
                          ? `+${Number(m.upper_tol).toFixed(DP_MM)} / -${Number(m.lower_tol).toFixed(DP_MM)}`
                          : "—"}
                      </td>
                      {/* IPM ไม่เอา offset มาตัดสิน → คอลัมน์นี้กับ Offset X/Y เป็น "—"
                          ค่ายังอยู่ใน DB ครบ (ดูได้จาก Export/Power BI) แค่ไม่เอามา
                          แสดงเพราะไม่มีส่วนร่วมกับผล OK/NG ของแถวนั้นเลย */}
                      <td className="td-derived">
                        {isIpm ? "—"
                          : m.offset_tol != null ? Number(m.offset_tol).toFixed(DP_OFF)
                          : "ยังไม่ตั้ง"}
                      </td>
                      <td className="td-derived" style={{ whiteSpace: "nowrap" }}>
                        {xyPair(
                          axisValue(m.value_x, m.nominal_x, m.upper_tol, m.lower_tol, m.ok_x),
                          axisValue(m.value_y, m.nominal_y, m.upper_tol, m.lower_tol, m.ok_y),
                        )}
                      </td>
                      <td className="td-derived" style={{ whiteSpace: "nowrap" }}>
                        {isIpm ? "—"
                          : xyPair(
                              offsetValue(m.offset_opx, m.offset_tol, m.ok_opx),
                              offsetValue(m.offset_opy, m.offset_tol, m.ok_opy),
                            )}
                      </td>
                      <td>
                        <span className={`result-badge ${cls}`}>{res}</span>
                      </td>
                      <td className="td-derived">{m.note ?? ""}</td>
                      <td>{m.operator_name ?? ""}</td>
                      <td className="td-derived">{m.measure_type ?? ""}</td>
                      <td className="td-derived">{ts}</td>
                      <td className="row-actions">
                        <div className="actions-inner">
                          <button
                            className="btn-icon edit"
                            disabled={sessionRunning}
                            title={sessionRunning ? "กำลังวัดอยู่ ไม่สามารถแก้ไขได้" : undefined}
                            onClick={() => openMeasModal("edit", m.measurement_id)}
                          >
                            ✎ Edit
                          </button>
                          <button
                            className="btn-icon delete"
                            disabled={sessionRunning}
                            title={sessionRunning ? "กำลังวัดอยู่ ไม่สามารถลบได้" : undefined}
                            onClick={() => confirmDeleteMeas(m.measurement_id)}
                          >
                            🗑
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
        <div className="pagination-bar">
          <button type="button" className="btn-icon" disabled={measPage <= 1} onClick={onMeasPrev}>
            ‹ Previous
          </button>
          <span style={{ fontSize: "0.85rem", fontWeight: 600 }}>{pageInfoText(measPage, measTotal, measurementsData.length)}</span>
          <button
            type="button"
            className="btn-icon"
            disabled={(measPage - 1) * PAGE_SIZE + measurementsData.length >= measTotal}
            onClick={onMeasNext}
          >
            Next ›
          </button>
        </div>
      </section>

      {/* ── Lookup Tables ─────────────────────────────────────────────────
          จัดการตาราง lookup ทั้ง 7 ตัว · ลำดับตรงกับ edit.html คือ
          Parts → Measurements → Lookup Tables → Trash */}
      <LookupTables
        onDeleted={bumpTrash}
        onChanged={() => { loadDropdownData(); bumpHistory(); }}
        onAlert={setAlertText}
        // ใช้ confirm modal ตัวเดียวกับ Parts/Measurements — ปุ่มลบทุกจุดในหน้านี้
        // จะได้ถามยืนยันหน้าตาเหมือนกันหมด ไม่มีจุดไหนลบทันทีโดยไม่ถาม
        // ปิด confirm ก่อนเสมอ ไม่งั้นถ้า action เด้ง alert ต่อ (ลบไม่ได้ 409)
        // จะเห็น 2 modal ซ้อนกันแล้วอ่านไม่ออกว่าต้องกดอันไหน
        onConfirm={(message, action) => setConfirmState({ message, onConfirm: () => { setConfirmState(null); action(); } })}
      />

      {/* ── ประวัติการแก้ไข ─────────────────────────────────────────────
          วางก่อนถังขยะ — เป็นของที่เปิดดูบ่อยกว่า ส่วนถังขยะยังอยู่ท้ายสุด
          ตามต้นฉบับ (เผลอลบแล้วเลื่อนลงมากู้ได้ทันที) */}
      <HistoryCard reloadKey={historyReload} />

      {/* ── ถังขยะ ────────────────────────────────────────────────────────
          วางไว้ท้ายสุดของหน้าโดยตั้งใจ (ตามต้นฉบับ) — เป็นหน้าเดียวกับที่ผู้ใช้
          กดลบ เผลอลบแล้วเลื่อนลงมากู้ได้ทันที ไม่ต้องจำว่าต้องไปหน้าไหน */}
      <TrashCard
        reloadKey={trashReload}
        onPurged={bumpHistory}
        onRestored={async () => {
          bumpHistory();
          // กู้คืนแล้วของกลับเข้าตารางไหนก็ไม่รู้ (Part / Measurement / Lookup)
          // โหลดใหม่ทั้งหมดง่ายกว่าและถูกเสมอ — หน้านี้โหลดทีละหน้าอยู่แล้ว
          // ไม่ได้แพงอะไร
          await Promise.all([
            reloadPartsAfterMutation(),
            reloadMeasAfterMutation(),
            loadDropdownData(),
          ]);
        }}
      />

      {/* Shared datalist: Package Size */}
      <datalist id="package-size-datalist">
        {packageSizeOptions.map((ps) => (
          <option key={ps} value={ps} />
        ))}
      </datalist>

      {/* ── Edit/Add modal (ใช้ร่วมกันทั้ง Parts และ Measurements) ────── */}
      <div className={`modal-overlay${editContext.table ? " open" : ""}`}>
        <div className="edit-modal-box">
          <div className="edit-modal-header">
            <div className="card-title">
              {editContext.table === "parts"
                ? isEdit
                  ? `Edit Part — ALPL ${editContext.key}`
                  : "Add New Part"
                : editContext.table === "measurements"
                  ? isEdit
                    ? `Edit Measurement — ID ${editContext.key}`
                    : "Add New Measurement"
                  : ""}
            </div>
            <button type="button" className="modal-close" onClick={closeEditModal}>
              ✕
            </button>
          </div>
          <form ref={formRef} onSubmit={editContext.table === "parts" ? savePart : saveMeas}>
            <div className="entry-form-grid">
              {editContext.table === "parts" && (
                <>
                  <div className="form-group">
                    <label htmlFor="f-number_alpl">
                      ALPL <span className="req">*</span>
                    </label>
                    <input type="number" id="f-number_alpl" name="number_alpl" defaultValue={pv("number_alpl") || editContext.key || ""} />
                    <div className="field-error">
                      {fieldErrors.number_alpl ? (
                        fieldErrors.number_alpl
                      ) : isEdit && !alplNoteConsumed ? (
                        <span className="field-locked-note">
                          แก้ ALPL ได้ — ระวัง: ถ้า ALPL นี้มีประวัติ session/measurement ผูกอยู่แล้ว การเปลี่ยนจะถูก DB ปฏิเสธ (FK constraint)
                        </span>
                      ) : null}
                    </div>
                  </div>
                  <div className="form-group">
                    <label htmlFor="f-package_size">Package Size {reqMark}</label>
                    <input
                      type="text"
                      id="f-package_size"
                      list="package-size-datalist"
                      value={pkgValue}
                      onChange={(e) => setPkgValue(e.target.value)}
                      placeholder="เลือก Package Size ก่อนถึงจะเลือก Part Number ได้"
                    />
                    <div className="field-error">{fieldErrors.package_size}</div>
                  </div>
                  <div className="form-group">
                    <label htmlFor="f-part_number">Part Number {reqMark}</label>
                    {/* disabled จนกว่าจะมี Package Size ที่หา Part Number เจอ —
                        เลือกก่อนไม่ได้เพราะ catalog ของ Part Number ผูกกับ
                        Package Size อยู่ (ดู schema part_number) */}
                    <select
                      id="f-part_number"
                      value={pnValue}
                      disabled={pnOptions.length === 0}
                      onChange={(e) => setPnValue(e.target.value)}
                    >
                      {/* ข้อความในช่องต้องบอกให้ถูกว่า "ทำไมเลือกไม่ได้" — ยังไม่กรอก
                          Package Size กับกรอกแล้วแต่ Package Size นั้นไม่มี Part
                          Number ผูกอยู่เลย เป็นคนละปัญหาที่แก้คนละทาง */}
                      {!pkgValue.trim() ? (
                        <option value="">-- เลือก Package Size ก่อน --</option>
                      ) : (
                        renderOptions(pnOptions)
                      )}
                    </select>
                    <div className="field-error">
                      {fieldErrors.part_number ? (
                        fieldErrors.part_number
                      ) : (
                        <span className="field-locked-note">
                          Nominal/Tolerance/Template ผูกมากับ Package Size ที่เลือกอัตโนมัติ — ไม่ต้องกรอกแยก
                        </span>
                      )}
                    </div>
                  </div>
                  {/* Handler — เลือกได้เอง ไม่ผูกกับ Part Number แล้ว
                      (ALPL ตัวเดียวกันย้ายเครื่องได้ ส่วน part_number เป็นแค่แคตตาล็อก)
                      เว้นว่างได้ = ยังไม่ระบุ */}
                  <div className="form-group">
                    <label htmlFor="f-handler">Handler</label>
                    <select id="f-handler" name="handler" defaultValue={pv("handler")}>
                      <option value="">-- ยังไม่ระบุ --</option>
                      {handlerOptions.map((h) => <option key={h} value={h}>{h}</option>)}
                    </select>
                    <div className="field-error">{fieldErrors.handler}</div>
                  </div>
                  <div className="form-group">
                    <label htmlFor="f-vendor">Vendor {reqMark}</label>
                    <select id="f-vendor" name="vendor" defaultValue={pv("vendor")}>
                      {renderOptions(vendorOptions)}
                    </select>
                    <div className="field-error">{fieldErrors.vendor}</div>
                  </div>
                  <div className="form-group span-2">
                    <label htmlFor="f-description">Description {reqMark}</label>
                    <input type="text" id="f-description" name="description" defaultValue={pv("description")} />
                    <div className="field-error">{fieldErrors.description}</div>
                  </div>
                  <div className="form-group">
                    <label htmlFor="f-po_number">PO Number {reqMark}</label>
                    <input type="number" id="f-po_number" name="po_number" defaultValue={pv("po_number")} />
                    <div className="field-error">{fieldErrors.po_number}</div>
                  </div>
                  <div className="form-group">
                    <label htmlFor="f-owner">Owner {reqMark}</label>
                    <select id="f-owner" name="owner" defaultValue={pv("owner")}>
                      {renderOptions(ownerOptions)}
                    </select>
                    <div className="field-error">{fieldErrors.owner}</div>
                  </div>
                  <div className="form-group">
                    <label htmlFor="f-recieve_date">Receive Date</label>
                    <input
                      type="date"
                      id="f-recieve_date"
                      name="recieve_date"
                      defaultValue={partOrig?.recieve_date ? String(partOrig.recieve_date).slice(0, 10) : ""}
                    />
                    <div className="field-error">
                      {fieldErrors.recieve_date ? (
                        fieldErrors.recieve_date
                      ) : (
                        <span className="field-locked-note">เว้นว่างได้ (จะถูกบันทึกเป็นค่าว่าง)</span>
                      )}
                    </div>
                  </div>
                  {/* กล่องค่า read-only ที่ derive มาจาก Part Number ที่เลือก —
                      โชว์ให้เห็นว่าเลือกตัวนี้แล้วได้เกณฑ์อะไรตามมา แต่แก้ที่นี่ไม่ได้ */}
                  <div className="form-group span-2">
                    <label>🔒 ค่าที่ผูกมากับ Part Number / Package Size (แก้ที่นี่ไม่ได้)</label>
                    <div className="derived-preview">
                      {selectedPn ? (
                        <>
                          <DerivedCell label="Handler" value={selectedPn.handler ?? "—"} />
                          <DerivedCell label="Template" value={derivedTemplate} />
                          {/* ⚠ เกณฑ์มาจาก Package Size ไม่ใช่ Part Number — ถ้าอ่านจาก
                              selectedPn จะได้ undefined เพราะ endpoint เลิกส่งมาแล้ว */}
                          <DerivedCell label="Nominal X / Y"
                            value={selectedPkg ? `${selectedPkg.nominal_x} / ${selectedPkg.nominal_y}` : "—"} />
                          <DerivedCell label="Tol (+/-)"
                            value={selectedPkg ? `+${selectedPkg.upper_tol} / -${selectedPkg.lower_tol}` : "—"} />
                        </>
                      ) : (
                        <span style={{ color: "var(--muted)" }}>
                          เลือก Part Number เพื่อดู Handler / Template / Nominal / Tolerance ที่ผูกอยู่
                        </span>
                      )}
                    </div>
                    <div className="field-locked-note">
                      ต้องการแก้ค่าพวกนี้ ให้ไปแก้ที่ตาราง Part Number ในหัวข้อ Lookup Tables ด้านล่าง
                    </div>
                  </div>
                </>
              )}

              {editContext.table === "measurements" && (
                <>
                  <div className="form-group">
                    <label htmlFor="f-number_alpl">
                      ALPL <span className="req">*</span>
                    </label>
                    <input type="number" id="f-number_alpl" name="number_alpl" defaultValue={mv("number_alpl")} />
                    <div className="field-error">
                      {fieldErrors.number_alpl ? (
                        fieldErrors.number_alpl
                      ) : isEdit && !alplNoteConsumed ? (
                        <span className="field-locked-note">
                          แก้ ALPL ได้ — ใช้กรณี IPM เลือกชิ้นที่มีอยู่จริงผิดตัว (ต้องเป็น ALPL ที่ลงทะเบียนใน Parts แล้ว)
                        </span>
                      ) : null}
                    </div>
                  </div>
                  {!isEdit && (
                    <>
                      <div className="form-group">
                        <label htmlFor="f-value_x">
                          Value X (mm) <span className="req">*</span>
                        </label>
                        <input type="number" step="0.001" id="f-value_x" name="value_x" defaultValue={mv("value_x")} />
                        <div className="field-error">{fieldErrors.value_x}</div>
                      </div>
                      <div className="form-group">
                        <label htmlFor="f-value_y">
                          Value Y (mm) <span className="req">*</span>
                        </label>
                        <input type="number" step="0.001" id="f-value_y" name="value_y" defaultValue={mv("value_y")} />
                        <div className="field-error">{fieldErrors.value_y}</div>
                      </div>
                    </>
                  )}
                  {isEdit ? (
                    <>
                      <div className="form-group">
                        <label htmlFor="f-operator">
                          Operator <span className="req">*</span>
                        </label>
                        <select id="f-operator" name="operator" defaultValue={mv("operator_name")}>
                          {renderOptions(operatorOptions)}
                        </select>
                        <div className="field-error">{fieldErrors.operator}</div>
                      </div>
                      {/* ผลการวัดจริงจากเครื่อง + ข้อมูลของ session — ดูได้อย่างเดียว
                          แก้ย้อนหลังไม่ได้ทุกกรณี (ไม่ใช่แค่ disabled ช่องกรอกไว้
                          แต่ไม่ส่งไปใน payload เลย — backend ใช้ whitelist อยู่แล้ว) */}
                      <div className="form-group span-2">
                        <label>🔒 ข้อมูลของรายการนี้ (แก้ไม่ได้)</label>
                        <div className="derived-preview">
                          <DerivedCell label="Value X" value={String(mv("value_x") || "—")} />
                          <DerivedCell label="Value Y" value={String(mv("value_y") || "—")} />
                          <DerivedCell label="Note" value={String(mv("note") || "—")} />
                          <DerivedCell label="Measure Type" value={String(mv("measure_type") || "—")} />
                        </div>
                        <div className="field-locked-note">
                          ผลการวัดจริงจากเครื่องกับข้อมูลของ session แก้ย้อนหลังไม่ได้ — Result (OK/NG)
                          จะถูกคำนวณใหม่อัตโนมัติจาก tolerance ของ ALPL ที่เลือก
                        </div>
                      </div>
                    </>
                  ) : (
                    <>
                      <div className="form-group span-2">
                        <label htmlFor="f-note">Note</label>
                        <textarea id="f-note" name="note" defaultValue={mv("note") ?? ""} />
                        <div className="field-error" />
                      </div>
                      <div className="form-group span-2">
                        <div className="field-locked-note">
                          Result (OK/NG) คำนวณอัตโนมัติจาก Value X/Y เทียบกับ tolerance ของ ALPL — ไม่ต้องเลือกเอง
                        </div>
                      </div>
                    </>
                  )}
                </>
              )}
            </div>
            <div className="modal-actions">
              <div>
                {editContext.table === "measurements" && isEdit && (
                  <button
                    type="button"
                    className="btn-delete-inline"
                    onClick={() => editContext.key != null && confirmDeleteMeas(editContext.key)}
                  >
                    🗑 Delete
                  </button>
                )}
              </div>
              <div className="modal-actions-right">
                <button type="button" className="btn-cancel" onClick={closeEditModal}>
                  Cancel
                </button>
                <button type="submit" className="btn-save">
                  ✔ Save
                </button>
              </div>
            </div>
          </form>
        </div>
      </div>

      {/* ── Alert modal (แจ้งเตือนเฉยๆ ไม่มีปุ่ม Cancel) ────────────────
          แยกจาก confirm modal เพราะอันนั้นมีปุ่ม "ลบ" ที่ทำ action จริง ส่วนอันนี้
          แค่โชว์ข้อความแล้วกดตกลงปิดไปเฉยๆ (เช่น ลบไม่ได้เพราะยังมีข้อมูลอ้างอิงอยู่) */}
      <div className={`modal-overlay${alertText ? " open" : ""}`}>
        <div className="confirm-box">
          <p>{alertText}</p>
          <div className="confirm-actions">
            <button type="button" className="btn-save" onClick={() => setAlertText(null)}>
              ตกลง
            </button>
          </div>
        </div>
      </div>

      {/* ── Confirm delete modal ─────────────────────────────────────── */}
      <div className={`modal-overlay${confirmState ? " open" : ""}`}>
        <div className="confirm-box">
          <p>{confirmState?.message}</p>
          <div className="confirm-actions">
            <button type="button" className="btn-cancel" onClick={() => setConfirmState(null)}>
              Cancel
            </button>
            <button type="button" className="btn-delete-inline" onClick={() => confirmState?.onConfirm()}>
              🗑 Delete
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
