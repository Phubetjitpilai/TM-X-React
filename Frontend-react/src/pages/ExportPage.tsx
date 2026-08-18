import { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiDelete, apiGet, apiPatch, apiPost } from "../api/client";
import { useToast } from "../components/Toast";
import { useDialog } from "../components/Dialog";
import ExportFilters, {
  EMPTY_FILTERS, hasAnyFilter, toParams, validateAlpl,
  type FilterState, type MultiKey,
} from "../components/export/ExportFilters";
import TemplateModal, { type ExportColumn } from "../components/export/TemplateModal";

// ExportPage — พอร์ตจาก Frontend/export.html (wizard 3 ขั้น)
//
// หน้านี้ใช้ร่วมกันทั้ง CSV / PDF / Excel ผ่าน ?format= ต่างกันแค่
//   · ชนิดเทมเพลตที่เลือกในขั้นที่ 1 (แยกลิสต์กันคนละชนิด)
//   · ไฟล์ที่ได้ตอนขั้นที่ 3
// ส่วนขั้นกรองข้อมูลใช้ตัวเดียวกันหมด

type Format = "csv" | "pdf" | "excel";
const FORMAT_LABEL: Record<Format, string> = { csv: "CSV", pdf: "PDF", excel: "Excel" };
const FILE_EXT: Record<Format, string> = { csv: ".csv", pdf: ".pdf", excel: ".xlsx" };

interface Template {
  export_template_id: number;
  name: string;
  kind: string;
  columns: string[];
  /** ผังตาราง — มีเฉพาะเทมเพลตชนิด pdf/excel (csv ใช้ columns เรียงเป็นแถวแทน) */
  layout?: { grid?: any[][]; nRows?: number; nCols?: number } | null;
  is_default: boolean;
}

const STEPS = ["Select Template", "Filter Data", "Examine & Export"];

/** ช่องข้อมูลที่ถูกใช้ในผังรายงาน เรียงตามลำดับที่เจอ (ซ้าย→ขวา บน→ล่าง)
 *
 *  ⚠ เทมเพลตชนิด pdf/excel **ไม่มี** รายการคอลัมน์เรียงเป็นแถวแบบ CSV —
 *    มันกระจายอยู่ตามเซลล์ในผัง ต้องไล่อ่านเอง ถ้าใช้ `t.columns` เหมือน CSV
 *    ชิปจะว่างเปล่าและเลขคอลัมน์ขึ้น 0 ทุกใบ (ของเดิมฝั่ง React เป็นแบบนั้น)
 *  ownerOf: ยุบลูกของบล็อกให้เป็นบล็อกตัวเดียว (value_x → tolerance_spec)
 *    เพื่อให้ชิปตรงกับสิ่งที่เห็นตอนจัดผัง ไม่ใช่แตกเป็นช่องย่อยเต็มไปหมด */
function layoutFields(layout: Template["layout"], catalog: ExportColumn[]): string[] {
  const ownerOf = (key: string) =>
    catalog.find((c) => c.block?.data?.some((d) => d.key === key))?.key ?? key;
  const out: string[] = [];
  (layout?.grid ?? []).forEach((row) =>
    (row ?? []).forEach((cell: any) => {
      const key = cell && (cell.hdr || cell.spec || cell.f);
      if (!key) return;
      const owner = ownerOf(key);
      if (!out.includes(owner)) out.push(owner);
    }),
  );
  return out;
}

/** ตัวอักษรที่ Windows ห้ามใช้ในชื่อไฟล์ — ถ้าปล่อยผ่านไป เบราว์เซอร์จะเซฟไม่ได้
 *  หรือเปลี่ยนชื่อให้เองเงียบๆ แล้วผู้ใช้จะหาไฟล์ไม่เจอ
 *  \ / : * ? " < > | ห้ามทั้งหมด · จุดกับเว้นวรรคท้ายชื่อก็ห้าม (Explorer ตัดทิ้ง) */
// eslint-disable-next-line no-control-regex
const BAD_FNAME_CHARS = /[\\/:*?"<>|\x00-\x1f]/g;

function sanitizeFilename(raw: string): string {
  return String(raw || "").replace(BAD_FNAME_CHARS, "").replace(/[. ]+$/, "").trim();
}

/** อ่านข้อความ error จาก response ของ backend ({"detail": "..."}) */
async function errText(r: Response, fallback: string): Promise<string> {
  try {
    const d = await r.json();
    return d?.detail || fallback;
  } catch {
    return fallback;
  }
}

export default function ExportPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const format = ((params.get("format") ?? "csv").toLowerCase() as Format) ?? "csv";
  const label = FORMAT_LABEL[format] ?? "CSV";

  const toast = useToast();
  const dialog = useDialog();
  const qc = useQueryClient();

  const [step, setStep] = useState(1);
  const [selectedTplId, setSelectedTplId] = useState<number | null>(null);
  const [filters, setFilters] = useState<FilterState>(EMPTY_FILTERS);
  const [modalOpen, setModalOpen] = useState(false);
  const [editingTpl, setEditingTpl] = useState<Template | null>(null);
  /** ข้อความชั่วคราวแทนบรรทัดนับจำนวน ระหว่างกำลังสร้างไฟล์/เตรียมพิมพ์ */
  const [busyNote, setBusyNote] = useState<string | null>(null);
  /** ผังรายงานแบบเต็ม (full=1) ที่รอพิมพ์ — วาดลง #print-root แล้วสั่ง print */
  const [printData, setPrintData] = useState<any>(null);

  // จำชื่อไฟล์ล่าสุดแยกตามรูปแบบ — export ซ้ำด้วยชื่อเดิมได้โดยไม่ต้องพิมพ์ใหม่
  // (ต้นฉบับใช้ localStorage key `tmx_export_filename_<format>` เหมือนกัน)
  const fnameKey = `tmx_export_filename_${format}`;
  const [filename, setFilename] = useState("");
  /** เตือนตอนผู้ใช้พิมพ์ตัวอักษรต้องห้าม — โชว์ 2.5 วิแล้วหายเอง */
  const [fnameWarn, setFnameWarn] = useState(false);
  useEffect(() => {
    setFilename(localStorage.getItem(fnameKey) ?? "");
  }, [fnameKey]);

  const cleanName = sanitizeFilename(filename);

  /** กรองตัวอักษรต้องห้ามทิ้งทันทีขณะพิมพ์ พร้อมคงตำแหน่งเคอร์เซอร์ไว้
   *  ไม่ให้เด้งไปท้ายช่อง (อาการที่เกิดถ้าแค่ setState ด้วยค่าที่กรองแล้ว) */
  function onFilenameChange(e: React.ChangeEvent<HTMLInputElement>) {
    const el = e.target;
    const raw = el.value;
    const cleaned = raw.replace(BAD_FNAME_CHARS, "");
    setFilename(cleaned);
    if (cleaned !== raw) {
      const pos = Math.max(0, (el.selectionStart ?? raw.length) - (raw.length - cleaned.length));
      requestAnimationFrame(() => el.setSelectionRange(pos, pos));
      setFnameWarn(true);
      window.setTimeout(() => setFnameWarn(false), 2500);
    }
  }

  // เซฟชื่อไฟล์ทุกครั้งที่เปลี่ยน ไม่ใช่รอตอนกดดาวน์โหลด — ผู้ใช้พิมพ์ชื่อไว้
  // แล้วเปลี่ยนใจไปกรองต่อ พอกลับมาชื่อต้องยังอยู่
  useEffect(() => {
    if (!cleanName) return;
    try { localStorage.setItem(fnameKey, cleanName); } catch { /* โหมดส่วนตัว */ }
  }, [cleanName, fnameKey]);

  // ── ข้อมูลตั้งต้น ────────────────────────────────────────────────────────
  const columnsQ = useQuery<ExportColumn[]>({
    queryKey: ["export-columns", format],
    queryFn: () => apiGet<ExportColumn[]>("/api/export/columns", { kind: format }),
  });

  const templatesQ = useQuery<Template[]>({
    queryKey: ["export-templates", format],
    queryFn: () => apiGet<Template[]>("/api/export/templates", { kind: format }),
  });

  // เลือกตัว default ให้อัตโนมัติตอนเปิดหน้าครั้งแรก
  useEffect(() => {
    const list = templatesQ.data;
    if (!list?.length || selectedTplId != null) return;
    setSelectedTplId((list.find((t) => t.is_default) ?? list[0]).export_template_id);
  }, [templatesQ.data, selectedTplId]);

  // ตัวเลือกของ multi-select — ดึงจาก lookup table จริงใน DB
  // ถ้าดึงตัวไหนไม่ได้ ก็แค่ช่องนั้นว่าง ช่องอื่นยังใช้ได้ปกติ (เหมือนต้นฉบับ)
  const optionsQ = useQuery({
    queryKey: ["export-filter-options"],
    queryFn: async () => {
      const get = async (path: string) => {
        try { return await apiGet<any[]>(path); } catch { return []; }
      };
      const [ops, vendors, owners, handlers, pkgs, parts] = await Promise.all([
        get("/api/operators"), get("/api/vendors"), get("/api/owners"),
        get("/api/handlers"), get("/api/package-sizes"), get("/api/part-numbers/all"),
      ]);
      const names = (rows: any[], key: string) =>
        Array.from(new Set(rows.map((r) => r[key]).filter((v) => v != null).map(String))).sort();
      return {
        options: {
          result: ["OK", "NG"],
          // ⚠ มีแค่ IPM กับ New เท่านั้น (ตรงกับต้นฉบับ) — โหมด Rework ถูกบันทึก
          //   ลง DB เป็น New + note ส่วน "Manual" ไม่มีทางเกิดแล้วเพราะไม่มีปุ่ม
          //   เพิ่ม measurement เองใน UI · ใส่ค่าที่ไม่มีในข้อมูลจริงจะได้ช่องกรอง
          //   ที่เลือกแล้วผลลัพธ์ว่างเสมอ ซึ่งดูเหมือนระบบพัง
          measure_type: ["IPM", "New"],
          operator: names(ops, "operator_name"),
          vendor: names(vendors, "vendor_name"),
          owner: names(owners, "owner_name"),
          handler: names(handlers, "handler_name"),
          package_size: names(pkgs, "package_size"),
          part_number: [],   // ว่างไว้จนกว่าจะเลือก Package Size (cascade)
        } as Record<MultiKey, string[]>,
        partNumberCatalog: parts.map((r) => ({
          part_number_name: String(r.part_number_name ?? ""),
          package_size: String(r.package_size ?? ""),
        })),
      };
    },
  });

  const qs = useMemo(() => toParams(filters, selectedTplId), [filters, selectedTplId]);
  const alplError = validateAlpl(filters.alpl);

  /* สั่งพิมพ์หลังผังฉบับเต็มถูกวาดลง #print-root แล้วเท่านั้น
   * ⚠ ต้องรอ React commit DOM ก่อน — ถ้าเรียก window.print() ต่อท้าย fetch เลย
   *   หน้าต่างพิมพ์จะเปิดมาโดยที่ #print-root ยังว่างอยู่ (ได้กระดาษเปล่า) */
  useEffect(() => {
    if (!printData) return;
    const restore = document.title;
    // เบราว์เซอร์เอา document.title ไปเป็นชื่อไฟล์ที่เสนอในหน้าต่างพิมพ์ —
    // สั่งชื่อไฟล์ PDF ตรงๆ จากโค้ดไม่ได้ ต้องผ่านทางนี้ทางเดียว
    document.title = cleanName || printData.template_name || "report";
    window.print();
    document.title = restore;
    setPrintData(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [printData]);

  // ── preview ─────────────────────────────────────────────────────────────
  // ยิงเฉพาะตอนอยู่ขั้นที่ 2-3 และมีเทมเพลตแล้ว · ALPL ผิดรูปแบบก็ไม่ต้องยิง
  const canPreview = step >= 2 && selectedTplId != null && !alplError;
  const previewQ = useQuery({
    queryKey: ["export-preview", format, qs.toString()],
    queryFn: () => {
      const p = new URLSearchParams(qs);
      if (format === "csv") {
        // ไม่ตั้ง limit เอง — backend ตัดให้ตามค่าของมัน แล้วบอกกลับมาว่าตัดกี่แถว
        // (ถ้าตั้งเองเลขในข้อความ "แสดงตัวอย่าง N แถวแรก" จะไม่ตรงกับที่ backend ทำ)
        return apiGet<{ columns: string[]; rows: any[][]; total: number; template_name: string }>(
          `/api/export/preview?${p}`,
        );
      }
      p.set("full", "0");
      return apiGet<any>(`/api/export/report-preview?${p}`);
    },
    enabled: canPreview,
  });

  // ── เทมเพลต CRUD ────────────────────────────────────────────────────────
  const refreshTpl = () => qc.invalidateQueries({ queryKey: ["export-templates", format] });

  const saveTpl = useMutation({
    mutationFn: async ({ name, columns }: { name: string; columns: string[] }) => {
      if (editingTpl) {
        return apiPatch(`/api/export/templates/${editingTpl.export_template_id}`, { name, columns });
      }
      return apiPost<Template>("/api/export/templates", { name, columns, kind: format });
    },
    onSuccess: (res: any) => {
      toast.show(editingTpl ? "บันทึกการแก้ไขแล้ว" : "สร้าง Template แล้ว");
      if (!editingTpl && res?.export_template_id) setSelectedTplId(res.export_template_id);
      setModalOpen(false);
      setEditingTpl(null);
      refreshTpl();
    },
    onError: (e: Error) => toast.show(`บันทึกไม่สำเร็จ — ${e.message}`),
  });

  const dupTpl = useMutation({
    mutationFn: (id: number) => apiPost<Template>(`/api/export/templates/${id}/duplicate`),
    onSuccess: (res: any) => {
      toast.show("คัดลอก Template แล้ว");
      if (res?.export_template_id) setSelectedTplId(res.export_template_id);
      refreshTpl();
    },
    onError: (e: Error) => toast.show(`คัดลอกไม่สำเร็จ — ${e.message}`),
  });

  const delTpl = useMutation({
    mutationFn: (id: number) => apiDelete(`/api/export/templates/${id}`),
    onSuccess: (_d, id) => {
      toast.show("ลบ Template แล้ว");
      if (selectedTplId === id) setSelectedTplId(null);
      refreshTpl();
    },
    onError: (e: Error) => toast.show(`ลบไม่สำเร็จ — ${e.message}`),
  });

  // ── ดาวน์โหลด ───────────────────────────────────────────────────────────
  /** ดาวน์โหลด Excel ผ่าน fetch แทนการเปลี่ยน location ตรงๆ
   *  จะได้อ่านข้อความ error จาก backend มาโชว์เป็น toast ได้ (เช่นตอนข้อมูล
   *  เกินเพดาน REPORT_MAX_ROWS) — ถ้าเปลี่ยน location เลย ผู้ใช้จะเจอหน้า
   *  error ดิบๆ ของเบราว์เซอร์แทน แล้วหน้าที่กรอกไว้ก็หายไปด้วย */
  async function downloadXlsx(p: URLSearchParams) {
    setBusyNote("กำลังสร้างไฟล์ Excel…");
    try {
      const r = await fetch(`/api/export/xlsx?${p}`);
      if (!r.ok) { toast.show(await errText(r, "สร้างไฟล์ไม่สำเร็จ")); return; }
      const blob = await r.blob();
      // ชื่อจากผู้ใช้มาก่อนเสมอ — Content-Disposition ของ backend เป็นแค่ตัวสำรอง
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${cleanName}${FILE_EXT.excel}`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      toast.show("ต่อ Backend ไม่ได้");
    } finally {
      setBusyNote(null);
    }
  }

  /** พิมพ์เป็น PDF — ใช้ตัวพิมพ์ของเบราว์เซอร์แทนการสร้าง PDF ฝั่ง backend
   *  เพราะภาษาไทยแสดงถูกแน่นอน (ไลบรารีฝั่ง server ต้องฝังฟอนต์เอง ไม่งั้นได้
   *  สี่เหลี่ยม) และสิ่งที่เห็นใน preview = สิ่งที่ได้ในไฟล์ เพราะวาดจาก HTML
   *  ก้อนเดียวกัน
   *
   *  ⚠ ต้องดึง full=1 ก่อนพิมพ์ — preview ถูกตัดที่ REPORT_PREVIEW_LIMIT แถว
   *    ถ้าพิมพ์จากของที่เห็นบนจอ ไฟล์ที่ได้จะขาดแถวไปเงียบๆ
   *  ⚠ ชื่อไฟล์ PDF สั่งจากโค้ดตรงๆ ไม่ได้ — เบราว์เซอร์เอา document.title ไป
   *    เป็นชื่อที่เสนอในหน้าต่างพิมพ์ ทางนี้ทางเดียว */
  async function printReport(p: URLSearchParams) {
    setBusyNote("กำลังเตรียมไฟล์สำหรับพิมพ์…");
    try {
      p.set("full", "1");
      const r = await fetch(`/api/export/report-preview?${p}`);
      if (!r.ok) { toast.show(await errText(r, "เตรียมไฟล์ไม่สำเร็จ")); return; }
      setPrintData(await r.json());
    } catch {
      toast.show("ต่อ Backend ไม่ได้");
    } finally {
      setBusyNote(null);
    }
  }

  function doDownload() {
    const p = new URLSearchParams(qs);
    p.set("filename", cleanName);
    try { localStorage.setItem(fnameKey, cleanName); } catch { /* โหมดส่วนตัวเขียนไม่ได้ */ }

    if (format === "excel") { void downloadXlsx(p); return; }
    if (format === "pdf") { void printReport(p); return; }
    // CSV: ให้เบราว์เซอร์โหลดไฟล์ตรงๆ จาก endpoint
    window.location.href = `/api/export/csv?${p}`;
  }

  async function onClickDownload() {
    if (!cleanName || total === 0) return;
    // ไม่ได้กรองอะไรเลย = กำลังจะดึงข้อมูลทั้งระบบ — ถามยืนยันก่อน กันเผลอกด
    // แล้วได้ไฟล์ใหญ่เกินคาด (โดยเฉพาะตอนติ๊ก "เฉพาะล่าสุด" ออกด้วย)
    if (!hasAnyFilter(filters)) {
      const scope = filters.latestOnly ? "การวัดล่าสุดของทุก ALPL" : "ประวัติการวัดทั้งหมดทุกครั้ง";
      const ok = await dialog.confirm(
        <>
          <strong>ยังไม่ได้ตั้งตัวกรองไว้เลย</strong>
          <br />
          <br />
          กำลังจะ Export {scope}
          <br />
          จำนวน <strong>{(total ?? 0).toLocaleString()} แถว</strong>
        </>,
        { title: "ยืนยันการ Export", okLabel: "Export" },
      );
      if (!ok) return;
    }
    doDownload();
  }

  /** ข้อความ error เรื่อง ALPL ที่มาจาก backend — แยกจาก error อื่นเพราะต้อง
   *  ไปโผล่ใต้ช่อง ALPL ไม่ใช่ที่บรรทัดนับจำนวน */
  const serverAlplError =
    previewQ.isError && (previewQ.error as Error).message.includes("ALPL")
      ? (previewQ.error as Error).message
      : null;

  /** เปิดตัวแก้เทมเพลต — csv ใช้ modal เลือกคอลัมน์ · pdf/excel ไปหน้าจัดผัง
   *  แบบสเปรดชีต (report-template) เพราะรายงานไม่ได้เรียงคอลัมน์เป็นแถวเดียว
   *
   *  ⚠ ห้ามให้ pdf/excel ตกมาใช้ modal เลือกคอลัมน์เด็ดขาด — modal นั้นส่ง
   *    {name, columns} ไป PATCH ซึ่งไม่มี layout_json ติดไปด้วย ผังที่ผู้ใช้
   *    จัดไว้จะถูกทับหายทั้งใบโดยที่หน้าจอขึ้นว่า "บันทึกแล้ว" ตามปกติ */
  function openTemplateEditor(t: Template | null) {
    if (format === "csv") {
      setEditingTpl(t);
      setModalOpen(true);
      return;
    }
    const q = new URLSearchParams({ format });
    if (t) q.set("id", String(t.export_template_id));
    navigate(`/report-template?${q}`);
  }

  const templates = templatesQ.data ?? [];
  const total: number | undefined = previewQ.data?.total;
  const templateName: string | undefined = previewQ.data?.template_name;

  /** ข้อความปุ่มดาวน์โหลด — บอกจำนวนแถวจริงที่จะได้ ไม่ใช่ป้ายนิ่งๆ
   *  ผู้ใช้จะได้เห็นตั้งแต่ก่อนกดว่าไฟล์จะมีกี่แถว (และรู้ทันทีถ้าเป็น 0) */
  const downloadLabel =
    total === 0 ? "⤓ ไม่มีข้อมูลให้ดาวน์โหลด"
    : format === "pdf" ? `🖨 พิมพ์เป็น PDF${total != null ? ` (${total} แถว)` : ""}`
    : `⤓ ดาวน์โหลด ${label}${total != null ? ` (${total} แถว)` : ""}`;

  return (
    <div className="main-edit">
      <div className="card">
        <div className="card-head">Export · {label}</div>

        <div className="steps">
          {STEPS.map((s, i) => {
            const n = i + 1;
            const cls = step === n ? "step on" : step > n ? "step done" : "step";
            return (
              <span key={s} style={{ display: "flex", alignItems: "center", gap: "0.6rem" }}>
                {i > 0 && <span>→</span>}
                <span className={cls}>
                  <span className="num">{n}</span>
                  {s}
                </span>
              </span>
            );
          })}
        </div>

        {/* ── ขั้นที่ 1 — เลือก Template ─────────────────────────────────── */}
        {step === 1 && (
          <section>
            {templatesQ.isLoading ? (
              <div className="filter-result-note">กำลังโหลด Template…</div>
            ) : templates.length === 0 ? (
              <div className="empty">ยังไม่มี Template — กดปุ่มด้านล่างเพื่อสร้าง</div>
            ) : (
              templates.map((t) => {
                // เทมเพลตค่าเริ่มต้นแก้/ลบไม่ได้ — เป็นตัวสำรองที่ต้องมีเหลืออยู่
                // เสมอ ไม่งั้นผู้ใช้ลบหมดแล้วเปิดหน้ามาไม่มีอะไรให้เลือก
                const lock = t.is_default;
                // csv → columns_json (เรียงตามลำดับในไฟล์)
                // pdf/excel → ไล่อ่านจากผัง เพราะคอลัมน์กระจายอยู่ในเซลล์
                const keys = format === "csv" ? t.columns : layoutFields(t.layout, columnsQ.data ?? []);
                const sizeText = format === "csv"
                  ? `${t.columns.length} คอลัมน์`
                  : `${keys.length} คอลัมน์ · ${t.layout?.nRows ?? 0} แถว × ${t.layout?.nCols ?? 0} ช่อง`;
                return (
                  <div
                    key={t.export_template_id}
                    className={`tpl${selectedTplId === t.export_template_id ? " sel" : ""}`}
                    onClick={() => setSelectedTplId(t.export_template_id)}
                  >
                    <div className="tpl-head">
                      <span className="tpl-name">{t.name}</span>
                      {lock && <span className="badge lock">🔒 ค่าเริ่มต้น</span>}
                      <span className="badge">{sizeText}</span>
                      <span className="tpl-acts" onClick={(e) => e.stopPropagation()}>
                        <button
                          type="button"
                          className="btn-mini"
                          disabled={lock}
                          title={lock ? "เทมเพลตค่าเริ่มต้นแก้ไขไม่ได้" : ""}
                          onClick={() => openTemplateEditor(t)}
                        >
                          Edit
                        </button>
                        <button type="button" className="btn-mini" onClick={() => dupTpl.mutate(t.export_template_id)}>
                          Duplicate
                        </button>
                        <button
                          type="button"
                          className="btn-mini del"
                          disabled={lock}
                          title={lock ? "เทมเพลตค่าเริ่มต้นลบไม่ได้" : ""}
                          onClick={async () => {
                            const ok = await dialog.confirm(
                              <>ลบ Template <strong>"{t.name}"</strong></>,
                              { title: "ลบ Template", okLabel: "🗑 ลบ", danger: true },
                            );
                            if (ok) delTpl.mutate(t.export_template_id);
                          }}
                        >
                          Delete
                        </button>
                      </span>
                    </div>
                    <div className="chips">
                      {keys.map((k) => {
                        const col = columnsQ.data?.find((c) => c.key === k);
                        return (
                          <span key={k} className={`chip${col?.group === "ข้อมูลการวัด" ? " meas" : ""}`}>
                            {col?.label ?? k}
                          </span>
                        );
                      })}
                    </div>
                  </div>
                );
              })
            )}

            <button type="button" className="btn-add-tpl" onClick={() => openTemplateEditor(null)}>
              + Create New Template
            </button>

            <div className="actions">
              <span />
              <button
                type="button"
                className="btn-primary"
                disabled={selectedTplId == null}
                title={selectedTplId == null ? "เลือก Template ก่อน" : ""}
                onClick={() => setStep(2)}
              >
                Next · Filter Data
              </button>
            </div>
          </section>
        )}

        {/* ── ขั้นที่ 2–3 — กรอง + ตรวจสอบ ──────────────────────────────── */}
        {step >= 2 && (
          <section>
            <ExportFilters
              value={filters}
              onChange={setFilters}
              options={optionsQ.data?.options ?? ({} as Record<MultiKey, string[]>)}
              partNumberCatalog={optionsQ.data?.partNumberCatalog ?? []}
              onClear={() => setFilters(EMPTY_FILTERS)}
              serverAlplError={serverAlplError}
            />

            {/* บรรทัดสรุป — ต้องบอกว่าใช้ Template ไหน เจอกี่แถว และตัวอย่างที่เห็น
                ถูกตัดไหม ไม่งั้นผู้ใช้เห็นตาราง 300 แถวแล้วนึกว่าไฟล์จะได้แค่นั้น */}
            <div className="count">
              {busyNote ? busyNote
                : alplError ? "แก้ช่อง ALPL ให้ถูกรูปแบบก่อน"
                : previewQ.isLoading ? "กำลังโหลด…"
                : previewQ.isError ? (serverAlplError ? "—" : (previewQ.error as Error).message)
                : previewQ.data ? (
                  <>
                    Template <strong>{templateName}</strong> · พบ <strong>{total}</strong> รายการ
                    {format !== "csv" && <> · แบ่ง <strong>{previewQ.data.groups ?? 0}</strong> กลุ่มตามสเปก Tolerance</>}
                    {format !== "csv" && previewQ.data.truncated && (
                      <span style={{ color: "var(--warn)" }}>
                        {" "}· ตัวอย่างแสดงแค่ {previewQ.data.shown} แถวแรก (ไฟล์จริงได้ครบทุกแถว)
                      </span>
                    )}
                    {format === "csv" && previewQ.data.rows?.length
                      ? ` · แสดงตัวอย่าง ${previewQ.data.rows.length} แถวแรก`
                      : ""}
                  </>
                ) : "—"}
            </div>


            {format === "csv" ? (
              <div className="pv-wrap">
                <table>
                  <thead>
                    <tr>{(previewQ.data?.columns ?? []).map((c: string) => <th key={c}>{c}</th>)}</tr>
                  </thead>
                  <tbody>
                    {previewQ.data?.rows?.length ? (
                      previewQ.data.rows.map((row: any[], i: number) => (
                        <tr key={i}>{row.map((cell, j) => <td key={j}>{cell == null ? "" : String(cell)}</td>)}</tr>
                      ))
                    ) : (
                      <tr>
                        <td className="empty" colSpan={previewQ.data?.columns?.length || 1}>
                          ไม่มีข้อมูลที่ตรงกับตัวกรอง
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="pv-wrap rpt-wrap">
                <ReportSheet data={previewQ.data} />
              </div>
            )}

            <div className="actions">
              <button type="button" className="btn-ghost" onClick={() => setStep(1)}>
                ← เปลี่ยน Template
              </button>

              {/* ช่องชื่อไฟล์วางติดกับปุ่มโดยตั้งใจ — ถ้าไปวางบนสุดจะมีตัวกรองกับ
                  ตัวอย่างข้อมูลยาวๆ คั่น พอเลื่อนลงมาถึงปุ่มก็ลืมไปแล้ว */}
              <div className="fname-group">
                <label className="fname-label">
                  ชื่อไฟล์ <span className="req">*</span>
                </label>
                <div className="fname-row">
                  <input
                    type="text"
                    placeholder="เช่น IPM-Report-2026-08"
                    autoComplete="off"
                    value={filename}
                    onChange={onFilenameChange}
                  />
                  <span className="fname-ext">{FILE_EXT[format]}</span>
                </div>
              </div>

              <button
                type="button"
                className="btn-primary"
                disabled={!cleanName || !!alplError || total === 0 || busyNote != null}
                onClick={onClickDownload}
              >
                {downloadLabel}
              </button>
            </div>
            <div className={`fname-hint${fnameWarn ? " warn" : ""}`}>
              {fnameWarn
                ? 'ตัวอักษร \\ / : * ? " < > | ใช้ในชื่อไฟล์ไม่ได้'
                : cleanName
                  ? `จะได้ไฟล์ชื่อ ${cleanName}${FILE_EXT[format]}`
                  : "กรอกชื่อไฟล์ก่อนถึงจะกดดาวน์โหลดได้"}
            </div>
          </section>
        )}
      </div>

      {modalOpen && (
        <TemplateModal
          editing={editingTpl}
          catalog={columnsQ.data ?? []}
          saving={saveTpl.isPending}
          onSave={(name, columns) => saveTpl.mutate({ name, columns })}
          onClose={() => { setModalOpen(false); setEditingTpl(null); }}
        />
      )}

      {/* ── ที่วางผังรายงานตอนสั่งพิมพ์ ──────────────────────────────────
          @media print ซ่อนทุกอย่างยกเว้นบล็อกนี้ (ดู index.css)

          ⚠ วาดลงหน้านี้แล้วสั่ง print เลย ไม่เปิดหน้าต่างใหม่ เพราะ
            1) ไม่โดน pop-up blocker
            2) ไม่ต้องประกอบ HTML ทั้งหน้าเป็นสตริง ซึ่งพลาดง่ายมาก      */}
      <div id="print-root">{printData && <ReportSheet data={printData} />}</div>
    </div>
  );
}

/** สไตล์ 1 เซลล์ตามที่ผู้ใช้จัดไว้ในผัง — ยกจาก cellStyle() ใน export.html
 *  ตัวต่อตัว รวมทั้ง indent ที่แปลงเป็น padding-left */
export function reportCellStyle(s: any = {}): React.CSSProperties {
  return {
    fontFamily: s.font || undefined,
    fontSize: `${s.size || 11}pt`,
    fontWeight: s.bold ? 700 : undefined,
    fontStyle: s.italic ? "italic" : undefined,
    textDecoration: s.underline ? "underline" : undefined,
    background: s.fill || undefined,
    color: s.color || undefined,
    textAlign: s.align || "center",
    verticalAlign: s.valign || "middle",
    paddingLeft: s.indent ? `${0.4 + s.indent * 0.7}rem` : undefined,
  };
}

/** วาดผังรายงาน (PDF/Excel) จากผลของ /api/export/report-preview
 *
 *  ⚠ รูปทรงที่ backend คืนมาคือ `{nCols, rows: [[{v, s, span?, hidden?, data?,
 *    head?}]]}` (ดู _render_report / _cell_out ใน routers/export.py)
 *    **ไม่ใช่** `{grid: [[{text, style, colspan, ...}]]}` — ของเดิมฝั่ง React
 *    อ่านคีย์ที่ไม่มีอยู่จริง เลยขึ้น "ยังไม่มีผังรายงาน" ทุกครั้งทั้งที่ backend
 *    ส่งข้อมูลมาครบ
 *
 *  สไตล์ทุกตัวมาจากผังที่ผู้ใช้จัดไว้ ไม่ได้ hardcode ที่นี่ — เซลล์ที่มีเนื้อหา
 *  ได้เส้นขอบหนา (.bx) เหมือนที่ openpyxl ใส่ให้ในไฟล์ .xlsx
 */
export function ReportSheet({ data }: { data: any }) {
  if (!data?.rows?.length) {
    return <div className="empty">ไม่มีข้อมูลที่ตรงกับตัวกรอง</div>;
  }
  return (
    <table className="rpt-sheet">
      <tbody>
        {data.rows.map((row: any[], r: number) => (
          <tr key={r}>
            {row.map((cell: any, c: number) => {
              if (cell?.hidden) return null;   // ถูกกลืนจากการผสานเซลล์
              const sp = cell?.span ?? { r: 1, c: 1 };
              // เซลล์ที่ "มีเนื้อหาจริง" เท่านั้นที่ได้เส้นขอบ — ช่องเว้นว่างใน
              // ผังต้องไม่มีกรอบ ไม่งั้นรายงานจะเต็มไปด้วยตารางเปล่า
              const filled = (cell?.v && String(cell.v).trim()) || cell?.data || cell?.head;
              return (
                <td
                  key={c}
                  className={filled ? "bx" : undefined}
                  colSpan={sp.c > 1 ? sp.c : undefined}
                  rowSpan={sp.r > 1 ? sp.r : undefined}
                  style={reportCellStyle(cell?.s)}
                >
                  {cell?.v ?? ""}
                </td>
              );
            })}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
