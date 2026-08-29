import { useEffect, useRef, useState } from "react";
import { apiGet, apiPost, ApiError } from "../api/client";
import { useSSE } from "../hooks/useSSE";
import { useSessionState, sessionStateLabel } from "../hooks/useSessionState";
import { useToast } from "../components/Toast";
import { useDialog } from "../components/Dialog";
import AlplIcon from "../components/AlplIcon";
import { axisValue, offsetValue, xyPair } from "../components/measurementCells";
import { ReportAxis } from "../components/dashboard/ReportAxis";
import OffsetMap from "../components/dashboard/OffsetMap";
import IpmSummaryModal, { type IpmSummaryRow } from "../components/dashboard/IpmSummaryModal";
import PartEntryModal, { type EntryQueue } from "../components/dashboard/PartEntryModal";

// DashboardPage — พอร์ตจาก Frontend/index.html (TM-X Dashboard) แบบยึด
// โครงสร้าง/ข้อความ/พฤติกรรมตามต้นฉบับเป๊ะๆ (ไม่ใช่ดีไซน์ใหม่ของตัวเอง) —
// เขียนรวมไว้ไฟล์เดียวขนาดใหญ่โดยตั้งใจ (แทนที่จะแยก component ย่อยเยอะๆ)
// เพราะ state ของหน้านี้พันกันหมดทุกส่วน (session/queue/telemetry/parts
// cache) เหมือนต้นฉบับที่เป็น script เดียวในไฟล์เดียวเช่นกัน

const PART_ENTRY_STORAGE_KEY = "tmx_part_entry_state_v1";
const MEAS_PAGE_SIZE = 10;
const ENTRY_MODES = ["ipm", "new", "rework"] as const;
type EntryMode = (typeof ENTRY_MODES)[number];

interface SessionState {
  state: "idle" | "running" | "stopped" | "timeout";
  session_id: number | null;
  measured_count: number;
  target_count: number;
}

interface Part {
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
  image_path?: string | null;
  image_upload_failed?: boolean;
  /** เกณฑ์ที่ใช้ตัดสินการวัดครั้งนั้น — backend เลือกแหล่งให้ตามโหมดแล้ว
   *  (IPM → package_size · New/Rework → part_number) ดู MEASUREMENTS_SELECT
   *  ⚠ offset_tol เป็น null ได้ = โหมด IPM ที่ไม่เอา offset มาตัดสิน */
  nominal_x?: number | null;
  nominal_y?: number | null;
  upper_tol?: number | null;
  lower_tol?: number | null;
  // ⚠ ไม่มี `offset` ตัวเดียวแล้ว — แยกเป็น 2 แกนตั้งแต่ถอดฝั่ง GH ออก
  //   `offset_pos_op` เป็นรหัส 9 ค่าจาก `_get_min_position_label` ฝั่ง backend
  //   (TOP / BOTTOM / LEFT / RIGHT / TOP LEFT / … / CENTER) — บอก "ทิศ"
  //   ส่วน offset_opx/opy เป็น "ขนาด" ไม่มีเครื่องหมาย
  offset_opx?: number | null;
  offset_opy?: number | null;
  offset_pos_op?: string | null;
  offset_tol?: number | null;
  measure_type?: string | null;
}

interface Telemetry {
  number_alpl?: number;
  value_x: number;
  value_y: number;
  /** เกณฑ์ + ผลรายแกนที่ backend ส่งมากับ event — ใช้ ok_* ก่อนเสมอ (แม่นที่สุด)
   *  ค่อยคำนวณเองจาก nominal/tol ถ้า event เก่าไม่มี */
  nominal_x?: number | null;
  nominal_y?: number | null;
  upper_tol?: number | null;
  lower_tol?: number | null;
  offset_tol?: number | null;
  ok_x?: boolean | null;
  ok_y?: boolean | null;
  ok_offset?: boolean | null;
  /** ธงจาก backend ว่า offset ถูกนับเป็นเกณฑ์ไหม — false = โหมด IPM */
  offset_counts?: boolean;
  measure_type?: string | null;
  // ⚠ ไม่มี offset_ghx / offset_ghy / offset_pos_gh แล้ว — เลิกใช้เครื่องมือฝั่ง GH
  //   (ถอดออกจาก MeasurementCreate และตาราง measurements ไปแล้ว) backend
  //   ไม่ได้ส่งมาใน SSE `measurement` อีกต่อไป
  offset_opx?: number | null;
  offset_opy?: number | null;
  offset_pos_op?: string | null;
  result: string;
  measurement_id?: number;
}

/** ป้าย OK/NG รายแกน + ข้อความช่วงที่รับได้
 *
 *  บอกว่า "พังที่แกนไหน" ไม่ใช่รู้แค่ Result รวม — ตอนวัดไม่ผ่านจะได้รู้ทันที
 *  ว่าต้องไปแก้อะไร · ใช้ ok ที่ backend ส่งมาก่อนเสมอ (แม่นที่สุด เพราะเกณฑ์
 *  มาจากคนละตารางตามโหมด) ค่อยคำนวณเองถ้า event เก่าไม่มีค่านั้น
 */
function axisInfo(
  value?: number | null, nominal?: number | null,
  upper?: number | null, lower?: number | null, okFromEvent?: boolean | null,
): { ok: boolean | null; range: string } {
  const ok = okFromEvent != null ? okFromEvent
    : value != null && nominal != null && upper != null && lower != null
      ? value >= nominal - lower && value <= nominal + upper
      : null;
  const range = nominal != null && upper != null && lower != null
    ? `รับได้ ${(nominal - lower).toFixed(3)} – ${(nominal + upper).toFixed(3)}`
    : "";
  return { ok, range };
}

/* ── หน้าตา modal "ไม่ได้รับค่าการวัด" แยกตามสาเหตุ ───────────────────────
 *
 * เลือกจาก `event` (รหัส) ที่ backend แนบมากับ SSE `measure_timeout`
 * **ห้ามเดาจากข้อความใน `detail`** เพราะข้อความเปลี่ยนได้ตลอดโดยไม่มีใครรู้ว่า
 * มีโค้ดฝั่งนี้พึ่งพาอยู่
 *
 * แยกเป็น 2 พฤติกรรม เพราะ "ของยังอยู่ในเครื่องไหม" ต่างกันสิ้นเชิง:
 *
 *   T1_FAILED / GM_NO_VALUE → ยังไม่ได้ค่า **ชิ้นงานยังอยู่ในเครื่อง**
 *                             → "ลองใหม่" = สั่งวัดชิ้นเดิมซ้ำ ปลอดภัย
 *
 *   NO_DB_ROW               → วัดแล้ว ตัดสินแล้ว **MCU คัดแยกออกไปแล้ว**
 *                             → ไม่มีอะไรให้วัดใหม่ · Pi ถือค่าจาก GM อยู่
 *                             → "รับค่าจาก Pi" = ให้ Pi POST ค่านั้นแทน (ไม่มีรูป)
 *                             ⚠ ถ้าเผลอขึ้นปุ่ม "ลองใหม่" ในเคสนี้ จะกลายเป็นวัด
 *                               ชิ้นถัดไปที่เพิ่งไหลเข้ามาแล้วบันทึกเป็นชิ้นนี้
 *
 * event ที่ไม่รู้จัก / เป็น null (Recieve ไม่เคยรายงาน เช่นไม่ได้รันอยู่เลย)
 * → ตกมาที่ค่าเริ่มต้น "ลองใหม่" ซึ่งเป็นตัวเลือกที่ปลอดภัยกว่า
 */
type MtAction = "retry" | "accept";
interface MtView {
  title: string; body: string; question: string; hint: React.ReactNode;
  action: MtAction; actionLabel: string;
}

const MT_RETRY: MtView = {
  title: "⚠ ไม่ได้รับค่าการวัด",
  body: "ไม่ได้รับค่าการวัดกลับมาภายในเวลาที่กำหนด",
  question: "ต้องการให้ลองวัดชิ้นเดิมอีกครั้งหรือไม่?",
  hint: <>สาเหตุที่พบบ่อย — TM-X วัดไม่ติด (ชิ้นงานวางไม่เข้าที่ / เลนส์สกปรก)
        หรือ TM-X ยังไม่พร้อมรับคำสั่งวัด</>,
  action: "retry",
  actionLabel: "ลองใหม่",
};

const MT_ACCEPT: MtView = {
  title: "⚠ ค่าไม่ถึงฐานข้อมูล",
  body: "วัดสำเร็จแล้ว แต่ค่าไม่ถูกบันทึกลงฐานข้อมูลภายในเวลาที่กำหนด",
  question: "ต้องการรับค่าที่ Pi อ่านไว้แทนหรือไม่? (จะไม่มีรูปของชิ้นนี้)",
  hint: <>ชิ้นงานถูกวัดและคัดแยกไปแล้ว จึงวัดใหม่ไม่ได้ — Pi ยังถือค่าไว้ครบ
        <br />สาเหตุที่พบบ่อย — <strong>Recieve_tm-x.py</strong> ไม่ได้รันอยู่
        หรือ TM-X ส่งไฟล์มาไม่ถึงเครื่อง PC</>,
  action: "accept",
  actionLabel: "รับค่าจาก Pi",
};

const mtView = (event?: string | null): MtView =>
  event === "NO_DB_ROW" ? MT_ACCEPT : MT_RETRY;


export default function DashboardPage() {
  // ── Session ────────────────────────────────────────────────────────
  const [session, setSession] = useState<SessionState>({ state: "idle", session_id: null, measured_count: 0, target_count: 1 });
  const sessionRef = useRef(session);
  sessionRef.current = session;

  // ── Telemetry / Camera preview ───────────────────────────────────────
  const [telemetry, setTelemetry] = useState<Telemetry | null>(null);
  /** ค่า telemetry ล่าสุด "ณ ตอนนี้จริง ๆ" — savePartEntryState() ต้องอ่านจากตัวนี้
   *
   *  ⚠ ห้ามให้ savePartEntryState() อ่านตัวแปร `telemetry` ตรง ๆ เด็ดขาด
   *    setTelemetry() ไม่ได้อัปเดตทันที ค่าใน closure ยังเป็นของ render เดิมอยู่
   *    พอ resetTelemetry() เรียก setTelemetry(null) แล้วเรียก save ต่อทันที
   *    สิ่งที่ถูกเขียนลง localStorage คือค่า "ก่อนล้าง" → จอล้างจริงตอนกด แต่
   *    พอ refresh ค่าเดิมโผล่กลับมา เหมือนปุ่ม Clear ไม่ทำงาน (อาการที่เจอจริง) */
  const telemetryRef = useRef<Telemetry | null>(null);
  /** ตั้งค่า telemetry — ใช้ตัวนี้แทน setTelemetry() ทุกที่ เพื่อให้ ref ตรงกับ state เสมอ */
  const applyTelemetry = (v: Telemetry | null) => { telemetryRef.current = v; setTelemetry(v); };
  const [lastImageMeasurementId, setLastImageMeasurementId] = useState<number | null>(null);
  /** เหตุผลเดียวกับ telemetryRef — รูปที่ค้างใน Camera Preview ก็ถูกเซฟกลับด้วย
   *  ค่าเก่าเหมือนกัน กด Clear แล้ว refresh รูปเดิมจึงโผล่กลับมา */
  const lastImageIdRef = useRef<number | null>(null);
  const applyLastImageId = (v: number | null) => { lastImageIdRef.current = v; setLastImageMeasurementId(v); };
  const [cameraImgUrl, setCameraImgUrl] = useState<string | null>(null);
  /** รูปที่กำลังเปิดดูเต็มจอ — null = ไม่ได้เปิด
   *  แยกจาก cameraImgUrl เพราะรูปใน Camera Preview เปลี่ยนเองทุกครั้งที่วัดชิ้นใหม่
   *  ถ้าผูกกันไว้ รูปที่กำลังซูมดูอยู่จะโดนสลับกลางคันตอนชิ้นถัดไปมาถึง */
  const [zoomImgUrl, setZoomImgUrl] = useState<string | null>(null);

  // ── Stats ─────────────────────────────────────────────────────────────
  const [stats, setStats] = useState({ total: 0, ok: 0, ng: 0 });
  /** ผล OK/NG รายชิ้นเรียงตามลำดับในคิว — ใช้ระบายสีชิปในแถบคิว
   *  เก็บเป็น ref เพราะ syncQueueStrip อ่านตอนถูกเรียกจาก async ไม่ผ่าน render
   *
   *  ⚠ ถูกเซฟลง localStorage ด้วย (savePartEntryState) — ref เปล่าทุกครั้งที่
   *    component เกิดใหม่ (refresh · HMR ตอน dev) ถ้าไม่เซฟไว้ แถบคิวจะลืมผล
   *    ที่วัดไปแล้วทั้งหมด */
  const resultsRef = useRef<string[]>([]);

  /** ชิ้นที่ i ควรเป็นชิปสีอะไร — **ทางเดียว** ที่ควรใช้ตัดสิน
   *
   *  ⚠ ห้ามเขียน `results[i] === "NG" ? "ng" : "ok"` อีก — `undefined` (ยังไม่รู้ผล)
   *    จะตกไปเป็น "ok" เขียวติ๊กถูก ทั้งที่ของจริงอาจ NG ทุกชิ้น เคยเกิดจริงมาแล้ว
   *    ตอนรีเฟรชหน้ากลาง session แล้วชิปขึ้นเขียวหมดสวนทางกับ Progress ที่ขึ้น NG
   *
   *  ระบบตรวจคุณภาพ "ไม่รู้" ต้องไม่แปลว่า "ผ่าน" เด็ดขาด — คืน `done` (เทา เส้นประ)
   *  ให้เห็นชัดว่าวัดไปแล้วแต่หน้านี้ตอบผลไม่ได้
   */
  function chipStateFor(i: number): "ok" | "ng" | "done" {
    const r = resultsRef.current[i];
    return r === "NG" ? "ng" : r === "OK" ? "ok" : "done";
  }

  /** จอ Live Telemetry ถูกสั่งล้างไว้สำหรับ session ไหน
   *
   *  ⚠ จำเป็นเพราะการล้าง state เฉย ๆ **ไม่พอ** — loadSessionState() ทำงานทุก 5 วิ
   *    แล้วเรียก syncQueueStrip()/updateStats() ซึ่งจะไปดึงคิวกับสถิติของ session
   *    นั้นกลับมาเติมใหม่ภายในไม่กี่วินาที ผู้ใช้จะเห็นของที่เพิ่งล้างโผล่กลับมาเอง
   *
   *  ผูกกับ session_id ไม่ใช่ boolean เฉย ๆ — พอขึ้น session ใหม่ธงจะหมดผลเอง
   *  โดยไม่ต้องล้างให้ (คนละ session แล้ว ไม่มีเหตุผลที่จะซ่อนของใหม่)
   *
   *  null = ไม่ได้ล้างอะไรไว้ · ตัวเลข = session นั้นถูกสั่งล้างจอไว้
   */
  const [ipmSummary, setIpmSummary] = useState<IpmSummaryRow[] | null>(null);
  const clearedSidRef = useRef<number | null>(null);
  const isTelemetryCleared = () =>
    clearedSidRef.current != null && clearedSidRef.current === sessionRef.current.session_id;

  /** modal ตอน Pi ยิง T1 แล้วไม่ได้รับค่ากลับมาภายในเวลาที่กำหนด
   *
   *  ⚠ **Pi ค้างรอคำตอบอยู่จริง ๆ** ไม่ใช่แค่แจ้งเตือน — จึงตั้งใจไม่มีปุ่มปิด (✕)
   *    และคลิกพื้นหลังปิดไม่ได้ ถ้าปิดทิ้งเฉย ๆ session จะค้างโดยไม่มีใครรู้
   *  มีนับถอยหลัง — ไม่ตอบภายในเวลาจะหยุดให้อัตโนมัติ ดีกว่าปล่อยเครื่องค้าง
   *  ข้ามคืนเพราะคนเดินออกจากหน้าจอไปแล้ว
   */
  // เวลาที่ให้คนตัดสินใจก่อนหยุดให้อัตโนมัติ (วินาที) — ปรับตรงนี้ที่เดียว
  //
  // ⚠ ต้อง **น้อยกว่า** `ASK_USER_TIMEOUT` ของ Pi/mockup (ตั้งไว้ 90 วิใน .env)
  //   เพราะฝั่งนั้นคือตาข่ายกันค้างตอนไม่มีใครเปิดหน้าเว็บอยู่เลย ถ้าตัวนี้ยาว
  //   กว่า Pi จะยอมแพ้ไปก่อนแล้วปุ่มในโมดัลจะกดไม่ติด (backend ตอบ 404
  //   "ไม่พบคำถามค้าง") ทั้งที่หน้าจอยังนับถอยหลังอยู่
  const MT_ANSWER_TIMEOUT = 60;
  const [mtModal, setMtModal] = useState<
    { session_id: number; piece?: number; target?: number; number_alpl?: number; detail?: string; event?: string} | null
  >(null);
  const [mtLeft, setMtLeft] = useState(MT_ANSWER_TIMEOUT);
  const mtTimerRef = useRef<number | null>(null);
  /** นับว่าส่งคำตอบใน modal ไปที่ Pi ไม่สำเร็จติดกันกี่ครั้ง
   *
   *  ใช้ `useRef` ไม่ใช่ `useState` เพราะเป็นค่าที่ใช้ **ตัดสินใจภายใน** อย่างเดียว
   *  ไม่ได้เอาไปวาดบนจอ — ถ้าใช้ state จะ re-render ทั้งหน้าโดยเปล่าประโยชน์
   *  และค่าที่อ่านได้ใน closure ของ catch อาจเป็นค่าเก่า
   */
  const mtFailRef = useRef(0);
  /** แถบคิว ALPL — ok/ng = วัดแล้วรู้ผล · done = วัดแล้วแต่หน้านี้ไม่รู้ผล ·
   *  now = กำลังวัด · wait = ยังไม่ถึงคิว
   *  ซ่อนทั้งแถบเมื่อคิวมีตัวเดียว (เช่น IPM ชิ้นเดียว) เพราะไม่มีอะไรให้ดู
   *
   *  ⚠ `done` มีไว้เพื่อ **ห้ามเดาผลเป็นเขียว** — ดู chipStateFor() ข้างล่าง */
  const [queueStrip, setQueueStrip] = useState<
    { alpl: number; state: "ok" | "ng" | "done" | "now" | "wait" }[]
  >([]);

  // ── Parts cache (ใช้ validate ALPL + report modal — ไม่มีตารางแสดงในหน้านี้) ──
  const partsRef = useRef<Part[]>([]);

  // ── Dropdown lookups (Operator/Owner/Vendor/Handler/Package Size) ────
  // โหลดครั้งเดียวตอนเปิดหน้าจาก endpoint ของแต่ละตัวจริงๆ (เหมือน index.html
  // ต้นฉบับ) ไม่ใช่ derive จาก parts cache (เดิมทำผิดไป — ทำให้ Operator ไม่มี
  // ตัวเลือกเลยเพราะ parts ไม่มี field operator, และ Handler/Vendor/Owner/
  // Package Size ก็โชว์ไม่ครบเพราะเห็นแค่ค่าที่เคยผูกกับ part ที่โหลดมาแล้ว)
  const [operatorOptions, setOperatorOptions] = useState<string[]>([]);
  const [ownerOptions, setOwnerOptions] = useState<string[]>([]);
  const [vendorOptions, setVendorOptions] = useState<string[]>([]);
  const [packageSizeOptions, setPackageSizeOptions] = useState<string[]>([]);
  const [partNumberCatalog, setPartNumberCatalog] = useState<{ part_number_name: string; package_size: string }[]>([]);

  // ── Part Entry queues ────────────────────────────────────────────────
  /** คิวเดียวใช้ทั้ง 3 โหมด — โครง groups[] เหมือนกันหมด ต่างแค่ field ในกลุ่ม
   *
   *  ⚠ เดิมแยกเป็น ipmQueue/newQueue/reworkQueue คนละก้อน ทำให้ทุกจุดที่ใช้ต้อง
   *    เขียน 3 สาขาเสมอ (เช็คว่าอันไหนไม่ null → หยิบตัวนั้น) พอเพิ่มโหมดหรือแก้
   *    ตรรกะทีก็ต้องไล่แก้ 3 ที่ทุกครั้ง
   */
  const [entryQueue, setEntryQueue] = useState<EntryQueue | null>(null);
  const entryQueueRef = useRef<EntryQueue | null>(null);
  entryQueueRef.current = entryQueue;


  // ── Part Entry modal / toggle ────────────────────────────────────────
  const [peModalOpen, setPeModalOpen] = useState(false);
  const [, setEntryMode] = useState<EntryMode | null>(null);
  const [peSummaryOpen, setPeSummaryOpen] = useState(false);





  // ── Confirm modal (Promise-based, ใช้ตอน IPM เจอ ALPL ที่ยังไม่เคยลงทะเบียน) ──
  const [confirmModal, setConfirmModal] = useState<{ message: string } | null>(null);
  const confirmResolveRef = useRef<((v: boolean) => void) | null>(null);
  function resolveConfirmModal(result: boolean) {
    setConfirmModal(null);
    confirmResolveRef.current?.(result);
    confirmResolveRef.current = null;
  }

  // ── Measurements table (server-side pagination + filter) ─────────────
  const [measurements, setMeasurements] = useState<Measurement[]>([]);
  const [measTotal, setMeasTotal] = useState(0);
  const [measPage, setMeasPage] = useState(1);
  const [measFilterAlplInput, setMeasFilterAlplInput] = useState("");
  const measFilterAlplRef = useRef("");
  const [measFilterDate, setMeasFilterDate] = useState("");
  const measSearchTimer = useRef<number | null>(null);
  const [highlightId, setHighlightId] = useState<number | null>(null);

  // ── Report modal ───────────────────────────────────────────────────────
  const [reportModal, setReportModal] = useState<{ measurement: Measurement; part: Part | null; imageUrl: string | null; imageState: "loading" | "ok" | "none" } | null>(null);

  const { show: showToast } = useToast();
  const dialog = useDialog();

  const stationStatus = useSSE({
    session_started: (d) => onSessionStarted(d),
    measurement: (d) => onNewMeasurement(d),
    session_stopped: (d) => onSessionStopped(d),
    session_complete: (d) => onSessionComplete(d),
    session_timeout: () => onSessionTimeout(),
    image_updated: (d) => onImageUpdated(d),
    measure_timeout: (d) => onMeasureTimeout(d),
    station_event: (d) => onStationEvent(d),
  });
  const stationStatusRef = useRef(stationStatus);
  stationStatusRef.current = stationStatus;

  // ── สถานะ Pi + DB ────────────────────────────────────────────────────────
  // มาจาก /api/session/state ที่ poll อยู่แล้วทุก 4 วิ — ไม่ได้เพิ่ม request ใหม่
  // (useSessionState dedupe ให้ตาม queryKey แม้ Layout จะเรียกซ้ำอีกที)
  const { piStatus, dbOffline: dbDown, triggerReady, manualTrigger } = useSessionState();
  const piOnline = piStatus === true;
  const dbOffline = !!dbDown;

  /* ── ปุ่มจำลองสัญญาณทริกเกอร์ — ใช้ระหว่างที่ยังไม่ได้ต่อ MCU ──────────────
     ยิงไปที่ Backend ไม่ใช่ที่ Pi โดยตรง (ดูเหตุผลใน manual_trigger ฝั่ง backend)

     ⚠ ปุ่มยังกดพลาดจังหวะได้ถึงแม้จะสว่างอยู่ — heartbeat มาทุก 2 วิ แล้วหน้าเว็บ
       poll ทุก 4 วิ ค่าที่เห็นจึงเก่าได้ถึง ~6 วินาที จังหวะอาจเปลี่ยนไปแล้ว
       ตอนที่กด **จึงต้องมี toast บอกเหตุผลเสมอ** ห้ามให้ปุ่มเงียบ ไม่งั้น
       operator จะกดรัวแล้วคิดว่าระบบพัง                                      */
  async function sendManualTrigger() {
    try {
      await apiPost("/api/session/trigger", { session_id: session?.session_id });
      showToast("⚡ ส่งสัญญาณแล้ว");
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : "ส่งสัญญาณไม่สำเร็จ");
    }
  }

  // ── localStorage persistence (ipmQueue/newQueue/reworkQueue/telemetry) ──
  function savePartEntryState() {
    try {
      localStorage.setItem(
        PART_ENTRY_STORAGE_KEY,
        JSON.stringify({
          entryQueue: entryQueueRef.current,
          lastTelemetry: telemetryRef.current,
          lastImageMeasurementId: lastImageIdRef.current,
          // ผล OK/NG รายชิ้น — ต้องรอดการ refresh เหมือน lastTelemetry ไม่งั้น
          // แถบคิวจะลืมผลทั้งแถวแล้วชิปกลายเป็น "ไม่รู้ผล" ทั้งที่เพิ่งวัดไปเอง
          results: resultsRef.current,
          // "ล้างจอ" ต้องรอดการ refresh — ไม่งั้น poll รอบแรกหลังโหลดหน้าจะดึงคิว
          // กับตัวเลขของ session เดิมกลับมาทันที เหมือนไม่เคยกดล้าง
          // เก็บเป็น session_id ไม่ใช่ boolean จะได้ปลดตัวเองเมื่อขึ้น session ใหม่
          clearedSid: clearedSidRef.current,
        }),
      );
    } catch {
      /* localStorage อาจใช้ไม่ได้ — ไม่ critical ปล่อยผ่าน */
    }
  }

  // ══════════════════════════════════════════════════════════════════
  // Data loaders
  // ══════════════════════════════════════════════════════════════════
  /** โหลด Part ทั้งหมดแบบวนทีละหน้า
   *
   *  ⚠ ของเดิมยิง `/api/parts?limit=100000` ทีเดียว ซึ่ง **พังตั้งแต่ request แรก**
   *    เพราะ backend ตั้งเพดานไว้ `Query(10, ge=1, le=1000)` — เกินเพดานได้
   *    **422 Unprocessable Entity** ทุกครั้ง ตาราง Parts จึงว่างตลอดโดยไม่มีใคร
   *    สังเกต (catch กลืน error ไว้แล้ว log อย่างเดียว)
   *
   *  วนทีละ PARTS_PAGE เหมือน fetchAllParts() ของ vanilla — ต้องไม่เกินเพดาน
   */
  async function refreshParts(): Promise<Part[]> {
    const PARTS_PAGE = 1000; // ต้องไม่เกินเพดานของ /api/parts (le=1000)
    try {
      const out: Part[] = [];
      for (let offset = 0, total = Infinity; offset < total; offset += PARTS_PAGE) {
        const d = await apiGet<{ items: Part[]; total: number }>("/api/parts", {
          limit: PARTS_PAGE,
          offset,
        });
        out.push(...(d.items ?? []));
        total = d.total ?? out.length;
        if (!d.items?.length) break; // กันวนไม่รู้จบถ้า backend คืน total เพี้ยน
      }
      partsRef.current = out;
      return out;
    } catch (e) {
      console.warn("refreshParts:", e);
      return partsRef.current;
    }
  }


  async function loadMeasurementsPage(page = measPage, alpl = measFilterAlplRef.current, date = measFilterDate) {
    const params: Record<string, string | number> = { limit: MEAS_PAGE_SIZE, offset: (page - 1) * MEAS_PAGE_SIZE };
    if (alpl) params.number_alpl = alpl;
    if (date) {
      params.date_from = `${date} 00:00:00`;
      params.date_to = `${date} 23:59:59`;
    }
    try {
      const d = await apiGet<{ items: Measurement[]; total: number }>("/api/measurements", params);
      setMeasurements(d.items ?? []);
      setMeasTotal(d.total ?? 0);
    } catch (e) {
      console.warn("loadMeasurementsPage:", e);
    }
  }

  async function updateStats(sid: number | null) {
    if (isTelemetryCleared()) { setStats({ total: 0, ok: 0, ng: 0 }); return; }
    if (sid == null) {
      setStats({ total: 0, ok: 0, ng: 0 });
      return;
    }
    try {
      const [totalD, okD, ngD] = await Promise.all([
        apiGet<{ total: number }>("/api/measurements", { session_id: sid, limit: 1 }).catch(() => ({ total: 0 })),
        apiGet<{ total: number }>("/api/measurements", { session_id: sid, result: "OK", limit: 1 }).catch(() => ({ total: 0 })),
        apiGet<{ total: number }>("/api/measurements", { session_id: sid, result: "NG", limit: 1 }).catch(() => ({ total: 0 })),
      ]);
      // เช็คธงอีกรอบ "หลัง await" — ผู้ใช้อาจกด Clear ระหว่างที่ fetch ยังค้างอยู่
      // ถ้าไม่เช็ค response ที่มาถึงทีหลังจะเขียนทับของที่เพิ่งล้าง
      if (isTelemetryCleared()) { setStats({ total: 0, ok: 0, ng: 0 }); return; }
      setStats({ total: totalD.total ?? 0, ok: okD.total ?? 0, ng: ngD.total ?? 0 });
    } catch (e) {
      console.warn("updateStats:", e);
    }
  }

  async function loadDropdownData() {
    const [operators, owners, vendors, packageSizes, partNumbers] = await Promise.all([
      apiGet<{ operator_name: string }[]>("/api/operators").catch(() => []),
      apiGet<{ owner_name: string }[]>("/api/owners").catch(() => []),
      apiGet<{ vendor_name: string }[]>("/api/vendors").catch(() => []),
      apiGet<{ package_size: string }[]>("/api/package-sizes").catch(() => []),
      // catalog part number พร้อม package size — ใช้กรอง Part Number ตามขนาด
      // ที่เลือกในกลุ่มนั้น (cascade) ดู partNumbersFor ที่ส่งให้ PartEntryModal
      apiGet<{ part_number_name: string; package_size: string }[]>("/api/part-numbers/all").catch(() => []),
    ]);
    setOperatorOptions(operators.map((o) => o.operator_name));
    setOwnerOptions(owners.map((o) => o.owner_name));
    setVendorOptions(vendors.map((v) => v.vendor_name));
    setPackageSizeOptions(packageSizes.map((p) => p.package_size));
    setPartNumberCatalog(partNumbers);
  }

  async function loadSessionState() {
    try {
      const d = await apiGet<Partial<SessionState>>("/api/session/state");
      updateSession(d);
      syncQueueStrip(d);
    } catch (e) {
      console.warn("loadSessionState:", e);
    }
  }

  // updateSession: merge ค่าใหม่เข้ากับ session เดิม + เช็คว่าคิว Part Entry
  // ที่ค้างอยู่ "หมดอายุ" ไปแล้วหรือยัง (ผูกกับ session_id ที่จบไปแล้ว) —
  // เทียบ session_id ตรงๆ แทนการเช็คแค่ transition สด เพื่อครอบคลุมเคส
  // เปิดหน้า/refresh หลัง session จบไปแล้ว (ดู comment เดิมใน index.html)
  function updateSession(data: Partial<SessionState>) {
    const merged = { ...sessionRef.current, ...data } as SessionState;
    setSession(merged);
    sessionRef.current = merged;

    const queue = entryQueueRef.current;
    const queueIsStale = !!queue && queue.session_id != null && !(merged.state === "running" && merged.session_id === queue.session_id);
    if (queueIsStale) {
      clearAllQueuesAndForms();
    }
    updateStats(merged.session_id);
  }

  function clearAllQueuesAndForms() {
    // ฟอร์มถูกล้างเองตอนปิด modal (state อยู่ใน PartEntryModal) — ตรงนี้เหลือแค่
    // ล้างคิวที่ค้างอยู่ ต่างจากเดิมที่ต้องรีเซ็ต state ของ 3 ฟอร์มทีละตัว
    setEntryQueue(null);
    entryQueueRef.current = null;
    savePartEntryState();
    setEntryMode(null);
  }

  function resetTelemetry() {
    applyTelemetry(null);
    setCameraImgUrl(null);
    applyLastImageId(null);
    savePartEntryState();
  }

  /** ปุ่ม 🧹 Clear ของ Live Telemetry — ล้างเฉพาะสิ่งที่แสดงบนจอ
   *
   *  ไม่แตะฐานข้อมูลเลย ผลวัดที่บันทึกไปแล้วยังอยู่ครบในตาราง Measurements
   *  ด้านล่าง · ล้างแถบคิวกับตัวนับด้วยเพื่อให้ทั้งการ์ดกลับไปเป็นสภาพว่าง
   *  พร้อมกัน ไม่ใช่ล้างครึ่งเดียวแล้วเหลือของค้างดูสับสน
   */
  function clearTelemetry() {
    resetTelemetry();
    resultsRef.current = [];
    setQueueStrip([]);
    setStats({ total: 0, ok: 0, ng: 0 });
    // ตั้งธงไว้ ไม่งั้น poll รอบถัดไปเติมคิว/สถิติกลับมาภายใน 5 วิ
    clearedSidRef.current = sessionRef.current.session_id ?? null;
    savePartEntryState();
  }

  /** ปุ่ม 🧹 Clear ของ Part Entry — ล้างคิวที่กรอกไว้ทั้ง 3 โหมด
   *
   *  ล้าง localStorage ด้วย ไม่งั้นรีเฟรชหน้าแล้วคิวเก่าจะกลับมาเอง —
   *  ผู้ใช้กด Clear แล้วเห็นของหาย พอ refresh กลับมาใหม่จะงงหนัก
   */
  /* Part Entry ถามยืนยันก่อนล้าง — กรอกใหม่เสียเวลากว่ามาก โดยเฉพาะตอนมีหลาย
     กลุ่ม (ต่างจาก Clear ของ Live Telemetry ที่ไม่ถาม เพราะกดดูย้อนหลังได้
     ทันทีจากตาราง Measurements ด้านล่าง ไม่มีอะไรหายจริง) */
  async function clearPartEntry() {
    if (!await dialog.confirm(
      <>
        คิวที่กรอกไว้จะถูกล้างทิ้ง ต้องกรอกใหม่ก่อนกด Start
        <br />
        <span style={{ color: "var(--muted)" }}>ไม่กระทบข้อมูลที่บันทึกลงฐานข้อมูลแล้ว</span>
      </>,
      { title: "ล้างข้อมูล Part Entry", okLabel: "🧹 ล้างข้อมูล", danger: true },
    )) return;
    setEntryQueue(null);
    entryQueueRef.current = null;
    savePartEntryState();
  }

  // ── SSE handlers ───────────────────────────────────────────────────
  /** สร้าง/อัปเดตแถบคิวจาก queue_state ที่ backend แนบมากับ session/state
   *
   *  ⚠ ตำแหน่งปัจจุบันใช้ measured_count เป็นตัวชี้ ไม่ได้ถาม Pi — เพราะ Pi
   *    ไม่รู้ด้วยซ้ำว่ากำลังวัด ALPL ตัวไหน (backend เป็นคนจับคู่จากตำแหน่งใน
   *    คิวของตัวเอง ดู session_queues ใน main.py)
   */
  function syncQueueStrip(st: any) {
    // ผู้ใช้กด 🧹 Clear ไว้ — ต้องค้างว่างไว้ ไม่ใช่โหลดกลับมาใหม่
    if (isTelemetryCleared()) { setQueueStrip([]); return; }
    const raw = st?.queue_state;
    if (!raw) { setQueueStrip([]); return; }
    let q: any = null;
    try { q = typeof raw === "string" ? JSON.parse(raw) : raw; } catch { return; }
    const list: number[] = q?.queue ?? q?.alpl ?? (q?.groups ?? []).flatMap((g: any) => g.alpl ?? []);
    if (!Array.isArray(list) || list.length === 0) { setQueueStrip([]); return; }
    const done = st?.measured_count ?? 0;
    setQueueStrip(
      list.map((alpl, i) => ({
        alpl,
        // ผลของชิ้นที่วัดไปแล้วมาจาก resultsRef ที่สะสมจาก SSE (+ กู้จาก
        // localStorage ตอน mount) — ถ้ายังไม่รู้ผลจริงๆ chipStateFor คืน "done"
        state: i < done ? chipStateFor(i)
             : i === done && st?.state === "running" ? "now"
             : "wait",
      })),
    );
  }

  function onSessionStarted(d: any) {
    resetTelemetry();
    updateSession({ state: "running", session_id: d.session_id, measured_count: 0, target_count: d.target_count });
  }
  async function onNewMeasurement(d: any) {
    // มีของใหม่จริงแล้ว → ปลดธง "ล้างจอไว้" ให้จอกลับมาแสดงตามปกติเอง
    clearedSidRef.current = null;

    // ⚠ ค่ามาถึงระหว่างที่ modal เปิดรอคำตอบอยู่ (FTP ส่งช้ากว่า MEASURE_TIMEOUT
    //   แต่มาถึงจริง) → ปิด modal ทิ้งเงียบ ๆ เพราะคำถามหมดความหมายแล้ว
    //   ถ้าไม่ปิด ผู้ใช้อาจกด "รับค่าจาก Pi" ทั้งที่ค่าลง DB ไปแล้ว → 2 แถวต่อ
    //   ชิ้นเดียว → position ขยับ 2 → ALPL เลื่อนทั้งคิว
    //   (Pi เช็ค measured_count ซ้ำก่อน POST อยู่แล้ว — ตัวนี้เป็นชั้นกันที่สอง
    //    และทำให้ผู้ใช้ไม่ต้องมานั่งงงว่าจะกดอะไรดี)
    // ⚠ ห้ามเรียก showToast() ข้างใน updater ของ setMtModal — updater ต้องเป็น
    //   ฟังก์ชันบริสุทธิ์ StrictMode เรียกมัน **2 ครั้ง** ตอน dev (toast เด้ง 2 อัน)
    //   และการ setState ของ ToastProvider ระหว่างที่ DashboardPage กำลัง render
    //   ทำให้ React โยน "Cannot update a component while rendering a different one"
    //   อ่านค่าปัจจุบันจาก closure ได้อยู่แล้ว เพราะ useSSE เก็บ handler ล่าสุด
    //   ไว้ใน ref (อัปเดตทุก render)
    if (mtTimerRef.current) { window.clearInterval(mtTimerRef.current); mtTimerRef.current = null; }
    if (mtModal) {
      showToast("ค่ามาถึงแล้ว — ปิดคำถามอัตโนมัติ");
      setMtModal(null);
    }

    updateSession({ measured_count: d.measured, target_count: d.target });
    applyTelemetry(d);
    // เก็บผลรายชิ้นไว้ระบายสีชิปในแถบคิว — d.measured คือลำดับที่ 1..n
    if (d.measured > 0) resultsRef.current[d.measured - 1] = d.result;
    setQueueStrip((prev) =>
      prev.map((q, i) =>
        i < d.measured ? { ...q, state: chipStateFor(i) }
        : i === d.measured ? { ...q, state: "now" as const }
        : q,
      ),
    );
    savePartEntryState();
    updateStats(sessionRef.current.session_id);
    if (measPage === 1 && !measFilterAlplRef.current && !measFilterDate) {
      await loadMeasurementsPage(1, "", measFilterDate);
      setHighlightId(d.measurement_id);
      window.setTimeout(() => setHighlightId((h) => (h === d.measurement_id ? null : h)), 2600);
    }
  }
  function onMeasureTimeout(d: any) {
    setMtModal(d);
    setMtLeft(MT_ANSWER_TIMEOUT);
    // คำถามใหม่ = เริ่มนับใหม่ · ไม่งั้นความล้มเหลวจากชิ้นก่อนหน้าจะสะสมข้ามชิ้น
    // แล้วเด้ง dialog "เครื่องไม่ตอบสนอง" ตั้งแต่กดพลาดครั้งแรกของชิ้นใหม่
    mtFailRef.current = 0;
    if (mtTimerRef.current) window.clearInterval(mtTimerRef.current);

    // ⚠ นับถอยหลังด้วยตัวแปรใน closure ไม่ใช่ค่าใน updater ของ setMtLeft —
    //   ของเดิมเรียก resolveMeasureTimeout() (ซึ่ง setState หลายตัว + ยิง fetch)
    //   อยู่ข้างใน updater ที่ต้องเป็นฟังก์ชันบริสุทธิ์ StrictMode เรียก updater
    //   2 ครั้งตอน dev → หยุด session ซ้อนกัน 2 ครั้ง
    let left = MT_ANSWER_TIMEOUT;
    mtTimerRef.current = window.setInterval(() => {
      left -= 1;
      setMtLeft(left);
      if (left <= 0) {
        if (mtTimerRef.current) { window.clearInterval(mtTimerRef.current); mtTimerRef.current = null; }
        resolveMeasureTimeout("stop");
      }
    }, 1000);
  }

  /** เครื่องหน้างานรายงานว่าเกิดอะไรขึ้น (Pi หรือ Recieve_tm-x.py)
   *
   *  ⚠ **ไม่ใช่ตัวที่เด้ง modal** — modal มาจาก `measure_timeout` เท่านั้น
   *    ตัวนี้คือการ "แจ้งให้รู้" เฉย ๆ บางเรื่องแจ้งแล้วจบ ไม่มีใครต้องตอบ
   *    (เช่น IMAGE_UPLOAD_FAILED ที่ค่าลง DB ไปแล้ว แค่รูปไม่ขึ้น)
   *
   *  ก่อนหน้านี้ backend ยิง event นี้ออกมาตลอดแต่ **ไม่มีใครรับ** — สาเหตุ
   *  ของปัญหาเดินทางไปถึงเบราว์เซอร์แล้วตกพื้นเงียบ ๆ ทุกครั้ง
   */
  function onStationEvent(d: any) {
    const detail = d?.detail ? `: ${d.detail}` : "";
    showToast(`⚠ ${d?.event ?? "STATION_EVENT"}${detail}`);
  }

  // ⚠ ถอด "ข้ามชิ้นนี้" (action `continue`) ออกแล้ว — 22 ส.ค. 2569
  //   `Pi.py` ไม่เคยรองรับ action นั้นเลย (ตอบ 400) กดแล้ว backend ขยับตำแหน่ง
  //   คิวไปเรียบร้อยแต่สั่ง Pi ไม่ผ่าน → คิวเหลื่อมหนึ่งช่องถาวรโดยไม่มีใครรู้
  async function resolveMeasureTimeout(action: "stop" | "retry" | "accept") {
    if (mtTimerRef.current) { window.clearInterval(mtTimerRef.current); mtTimerRef.current = null; }
    const sid = mtModal?.session_id ?? null;
    setMtModal(null);
    if (sid == null) return;

    // เลือกหยุด (หรือหมดเวลา) → วิ่งเข้า POST /api/session/stop เส้นเดียวกับ
    // ปุ่ม Stop ทุกประการ ตั้งใจไม่ให้มีทางที่สองที่ปิด session ได้
    //
    // ⚠ เรียก `doStopSession` ไม่ใช่ `stopSession` — ตัวหลังมี dialog ถามยืนยัน
    //   ซึ่งผิดทั้ง 2 กรณีที่มาถึงตรงนี้: หมดเวลา 60 วิ (ไม่มีคนอยู่ให้กด → ค้าง
    //   ตลอดกาล ไม่มีอะไรหยุดเลย) และกด "หยุดการวัด" ในโมดัล (เพิ่งเลือกไปหมาด ๆ)
    //   ⚠ ส่ง sid ของโมดัลไปด้วย ไม่ใช้ `session.session_id` จาก state เพราะ
    //     closure อาจถือค่าเก่าอยู่ ณ จังหวะที่ timer ยิง
    if (action === "stop") { await doStopSession(sid); return; }

    try {
      await apiPost(`/api/session/${action}`, { session_id: sid });
      mtFailRef.current = 0;        // ส่งผ่านแล้ว เริ่มนับใหม่
    } catch (e: any) {
      // 502 = backend ยิง /command ไปแล้วแต่ Pi ไม่รับ — Pi ยังบล็อกรอคำตอบอยู่
      // เฉย ๆ ไม่มีอะไรเดินหน้า ถ้าเงียบไว้ผู้ใช้จะยืนรอเครื่องที่ไม่มีวันขยับ
      // (backend คืนคำถามค้างให้แล้ว กดซ้ำได้)
      mtFailRef.current += 1;

      /* ── 2 ครั้งแรกให้ลองใหม่ · ครั้งที่ 3 เลิกแนะนำให้กดซ้ำ ────────────────
         อาจเป็นเน็ตสะดุดชั่วคราวจริง ๆ จึงควรให้โอกาสก่อน — แต่ถ้าพลาด 3 ครั้ง
         ติดกันแปลว่าเครื่องไม่ตอบสนองแล้ว **กดอีกกี่ครั้งก็ไม่มีทางสำเร็จ**
         ต้องเปลี่ยนคำแนะนำจาก "กดใหม่" เป็น "ไปจัดการที่เครื่อง" ไม่งั้นผู้ใช้
         จะกดวนอยู่จนกว่า backend จะ mark timeout เอง (5-20 วิ) โดยไม่รู้ว่า
         ควรทำอะไรต่อ

         ใช้ dialog ไม่ใช่ toast เพราะต้องกดรับทราบ — เป็นคำแนะนำที่ต้องลงมือทำ
         ไม่ใช่แค่รายงานสถานะ (กติกาเดียวกับกรณี Stop สั่งไม่ผ่าน)            */
      if (mtFailRef.current >= 3) {
        dialog.alert(
          `ส่งคำตอบไปที่เครื่องไม่สำเร็จ ${mtFailRef.current} ครั้งติดกัน\n\n${e?.message ?? ""}\n\n` +
          `เครื่องไม่ตอบสนองแล้ว — กด Stop แล้วทำการ Restart Raspberry Pi ` +
          `(ถอดสายไฟแล้วเสียบใหม่ โปรแกรมจะรันเองตอนเปิดเครื่อง)`,
          { title: "⚠ เครื่องไม่ตอบสนอง", danger: true },
        );
      } else {
        showToast(`ส่งคำตอบไม่สำเร็จ: ${e?.message ?? ""} — กดใหม่อีกครั้ง หรือกด Stop`);
      }
    }
  }

  function onSessionStopped(d?: { agent_error?: string | null }) {
    resetTelemetry();
    resultsRef.current = [];
    updateSession({ state: "stopped" });
    clearAllQueuesAndForms();

    // แท็บที่ **ไม่ได้เป็นคนกด Stop** ก็ต้องรู้ด้วยว่าเครื่องอาจยังวัดต่ออยู่
    // (คนกดได้เห็นจาก response ของตัวเองไปแล้วใน doStopSession)
    if (d?.agent_error) {
      dialog.alert(
        `session ถูกหยุดแล้ว แต่สั่งเครื่องไม่สำเร็จ\n\n${d.agent_error}\n\n` +
        `เครื่องอาจยังวัดต่ออยู่ — กรุณาตรวจที่เครื่อง`,
        { title: "⚠ ต้องไปหยุดที่เครื่อง", danger: true },
      );
    }
  }
  function onSessionComplete(d: any) {
    // เก็บ session_id ไว้ "ก่อน" clearAllQueuesAndForms() — ตัวนั้นล้าง state ทิ้ง
    const sid = d.session_id ?? sessionRef.current.session_id;
    resetTelemetry();
    updateSession({ state: "stopped", measured_count: d.measured, target_count: d.target });
    clearAllQueuesAndForms();
    showIpmSummary(sid);
  }

  /** เด้งสรุปผลตอนวัดครบ — เฉพาะโหมด IPM
   *
   *  ⚠ เช็คโหมดจาก measure_type "ในข้อมูลที่ดึงมา" ไม่ใช่จาก state ipmQueue ฝั่ง
   *    หน้าเว็บ เพราะ state นั้นหายได้หลายทาง: refresh หน้ากลาง session · เปิด
   *    จากอีกเครื่อง · clearAllQueuesAndForms() ทำงานไปก่อนแล้ว — พอหายจะแยก
   *    ไม่ออกว่ารอบที่จบเป็นโหมดอะไร แล้ว popup จะไม่เด้งโดยไม่มีอะไรบอกสาเหตุ
   */
  async function showIpmSummary(sessionId: number | null | undefined) {
    if (sessionId == null) return;
    try {
      const d = await apiGet<{ items: any[] }>("/api/measurements", { session_id: sessionId, limit: 1000 });
      const items = d.items ?? [];
      if (!items.length || items[0].measure_type !== "IPM") return;
      // API เรียงใหม่→เก่า แต่ตารางต้องเรียงตามลำดับที่วัดจริง (เก่า→ใหม่)
      items.sort((a, b) => a.measurement_id - b.measurement_id);
      setIpmSummary(items.map((m) => ({ x: m.value_x, y: m.value_y })));
    } catch (e) {
      console.warn("showIpmSummary:", e);
    }
  }
  function onSessionTimeout() {
    resetTelemetry();
    updateSession({ state: "timeout" });
    clearAllQueuesAndForms();
  }
  async function onImageUpdated(d: any) {
    setMeasurements((prev) => prev.map((m) => (m.measurement_id === d.measurement_id ? { ...m, image_path: d.image_path, image_upload_failed: !!d.upload_failed } : m)));
    if (d.upload_failed) return;
    await updateCameraPreview(d.measurement_id);
  }

  async function updateCameraPreview(measurementId: number) {
    try {
      const data = await apiGet<{ url: string }>(`/api/image-url/${measurementId}`);
      setCameraImgUrl(data.url);
      applyLastImageId(measurementId);
      savePartEntryState();
    } catch (e) {
      // /api/image-url ปัจจุบันเป็นแค่ stub (ตอบ 404 เสมอ — ดู CLAUDE.md) —
      // ล้มเหลวเงียบๆ เหมือนต้นฉบับ ปล่อยให้ Camera Preview โชว่ placeholder ต่อไป
      console.warn("updateCameraPreview:", e);
    }
  }

  // ปิดรูปเต็มจอด้วย Esc — ผูก listener เฉพาะตอนเปิดอยู่ จะได้ไม่ค้างไว้ทั้งหน้า
  useEffect(() => {
    if (!zoomImgUrl) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setZoomImgUrl(null); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [zoomImgUrl]);

  // ── Mount: โหลดข้อมูลเริ่มต้น + restore localStorage + polling สำรอง ──────
  useEffect(() => {
    try {
      const raw = localStorage.getItem(PART_ENTRY_STORAGE_KEY);
      if (raw) {
        const d = JSON.parse(raw);
        if (d.entryQueue) { setEntryQueue(d.entryQueue); entryQueueRef.current = d.entryQueue; }
        if (d.lastTelemetry) applyTelemetry(d.lastTelemetry);
        // กู้ผลรายชิ้นก่อน loadSessionState() ตัวแรกจะเรียก syncQueueStrip
        if (Array.isArray(d.results)) resultsRef.current = d.results;
        clearedSidRef.current = d.clearedSid ?? null;
        if (d.lastImageMeasurementId) {
          applyLastImageId(d.lastImageMeasurementId);
          updateCameraPreview(d.lastImageMeasurementId);
        }
      }
    } catch (e) {
      console.warn("loadPartEntryState:", e);
    }

    (async () => {
      await Promise.all([loadSessionState(), loadMeasurementsPage(1, "", ""), refreshParts(), loadDropdownData()]);
    })();

    const t = window.setInterval(loadSessionState, 5000);
    return () => window.clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── Measurements filter/pagination handlers ───────────────────────────
  function onMeasSearchChange(value: string) {
    setMeasFilterAlplInput(value);
    if (measSearchTimer.current) window.clearTimeout(measSearchTimer.current);
    measSearchTimer.current = window.setTimeout(async () => {
      measFilterAlplRef.current = value.trim();
      setMeasPage(1);
      await loadMeasurementsPage(1, measFilterAlplRef.current, measFilterDate);
    }, 300);
  }
  async function onMeasDateChange(value: string) {
    setMeasFilterDate(value);
    setMeasPage(1);
    await loadMeasurementsPage(1, measFilterAlplRef.current, value);
  }
  async function onMeasClearFilter() {
    if (measSearchTimer.current) window.clearTimeout(measSearchTimer.current);
    setMeasFilterAlplInput("");
    measFilterAlplRef.current = "";
    setMeasFilterDate("");
    setMeasPage(1);
    await loadMeasurementsPage(1, "", "");
  }
  async function onMeasPrev() {
    if (measPage <= 1) return;
    const p = measPage - 1;
    setMeasPage(p);
    await loadMeasurementsPage(p, measFilterAlplRef.current, measFilterDate);
  }
  async function onMeasNext() {
    if ((measPage - 1) * MEAS_PAGE_SIZE + measurements.length >= measTotal) return;
    const p = measPage + 1;
    setMeasPage(p);
    await loadMeasurementsPage(p, measFilterAlplRef.current, measFilterDate);
  }

  // ══════════════════════════════════════════════════════════════════
  // Session Start / Stop
  // ══════════════════════════════════════════════════════════════════
  // สัดส่วนแถบ OK/NG — หารด้วย target_count ไม่ใช่ measured_count เพื่อให้ส่วน
  // ที่ "ยังไม่วัด" เหลือเป็นพื้นเทาให้เห็น (ถ้าหารด้วยที่วัดแล้วแถบจะเต็ม 100%
  // ตั้งแต่ชิ้นแรก แล้วมองไม่ออกว่าเหลืออีกกี่ชิ้น)
  // ถูกสั่งล้างไว้ → แถบต้องว่างด้วย ไม่งั้นแถบเขียวยังเต็มอยู่ทั้งที่ตัวเลขเป็นขีด
  const barTotal = isTelemetryCleared() ? 0 : (session.target_count || stats.total || 0);
  const barOkPct = barTotal ? (stats.ok / barTotal) * 100 : 0;
  const barNgPct = barTotal ? (stats.ng / barTotal) * 100 : 0;

  const hasQueue = !!entryQueue;

  /* ── ทำไมเช็ค `!== "offline"` ไม่ใช่ `=== "online"` ──────────────────────
     `stationStatus` เริ่มต้นเป็น "connecting" เสมอ และเปลี่ยนเป็น "online"
     ก็ต่อเมื่อ `es.onopen` ทำงาน — แต่ตอนเปิดหน้าครั้งแรก แอปยิงคำขอพรวดเดียว
     เป็นสิบตัว (parts · measurements · lookup 5 ตัว · session/state) เบราว์เซอร์
     จำกัดการเชื่อมต่อต่อโดเมนไว้ราว 6 ช่อง **สาย SSE จึงต้องต่อคิว** กว่าจะเปิด

     ของเดิมใช้ `=== "online"` ผลคือปุ่ม Start ถูกล็อกค้างอยู่หลายวินาทีตอนเปิด
     หน้าครั้งแรก แล้วพอกด Save รอบต่อไปกลับปลดล็อกทันที (เพราะสายเปิดค้างแล้ว)
     — อาการที่หาสาเหตุยากมากเพราะดูเหมือนเกี่ยวกับปุ่ม Save ทั้งที่ไม่ใช่

     **"connecting" ไม่ใช่สถานะล้มเหลว** จึงไม่ควรบล็อก ปลอดภัยเพราะ `piOnline`
     แข็งแรงกว่าอยู่แล้ว — เป็น true ได้ก็ต่อเมื่อ poll สำเร็จ *และ* backend ตอบ
     ว่า Pi ยังมีชีวิต ซึ่งพิสูจน์ว่า backend ติดต่อได้แน่นอน ไม่ต้องรอสายที่สอง
     มายืนยันซ้ำ (กติกาเดียวกับป้ายสถานะใน Layout.tsx ที่แก้ไปแล้ว)          */
  const canStart =
    session.state !== "running" && stationStatus !== "offline" && !dbOffline && piOnline && hasQueue;

  // ปุ่มต้องบอก "ติดอะไรอยู่" ไม่ใช่แค่กดไม่ได้เฉยๆ — ไม่งั้นผู้ใช้จะนึกว่าระบบพัง
  // แล้วไปไล่หาที่ฟอร์ม Part Entry ทั้งที่ปัญหาอยู่ที่เครื่อง
  // เรียง DB ก่อน Pi เพราะ DB ล่มแล้วกด Start ไม่ได้แน่นอนไม่ว่า Pi จะเป็นยังไง
  // (start_session ต้องเขียน session ลง DB ก่อน) และเป็นอย่างเดียวที่ผู้ใช้แก้เองได้
  // ⚠ ทุกเงื่อนไขใน canStart ต้องมีสาขาของตัวเองที่นี่ ไม่งั้นปุ่มจะถูกล็อก
  //   โดยที่ป้ายยังขึ้นว่าพร้อมใช้งาน — ของเดิม stationStatus ไม่มีสาขาเลย
  //   ปุ่มเลยขึ้น "▶ Start (IPM ×3)" ดูปกติทุกอย่างแต่กดไม่ได้ tooltip ก็ว่าง
  const startLabel =
    session.state === "running"   ? "▶ Start"
    : dbOffline                   ? "▶ Start (DB Offline)"
    : stationStatus === "offline" ? "▶ Start (Server Offline)"
    : piStatus === false          ? "▶ Start (Pi Offline)"
    : !piOnline                   ? "▶ Start (Waiting for Pi)"
    : entryQueue                  ? `▶ Start (${entryQueue.mode} ×${entryQueue.list.length})`
    :                               "▶ Start (กด Save ก่อน)";

  const startTitle =
    dbOffline                     ? "Backend ต่อฐานข้อมูลไม่ได้ — เริ่มการวัดไม่ได้เพราะต้องเขียน session ลง DB ก่อน · ตรวจว่า MySQL ทำงานอยู่ไหม"
    : stationStatus === "offline" ? "ขาดการเชื่อมต่อกับ Backend — ตรวจว่า uvicorn ยังรันอยู่ไหม · ลองรีเฟรชหน้าเว็บ"
    : piStatus === false          ? "ไม่ได้รับสัญญาณจาก Pi เกินเวลาที่กำหนด — ตรวจว่า Pi.py รันอยู่ไหม · สาย LAN"
    : !piOnline                   ? "ยังไม่เคยได้รับ heartbeat จาก Pi ตั้งแต่ Backend เริ่มทำงาน — รอสักครู่ ถ้าไม่หายให้ตรวจว่า Pi.py รันอยู่ไหม"
    : !hasQueue                   ? "ยังไม่มีคิวที่จะวัด — กรอกฟอร์ม Part Entry แล้วกด Save ก่อน"
    :                               "";

  // Operator / Measure Type ของ session ที่กำลังวัด — แกะจาก queue_state ที่
  // backend แนบมากับ /api/session/state (ไม่ได้เก็บเป็นคอลัมน์แยกในตาราง sessions)
  const qState = (session as any).queue_state;
  const parsedQueue = (() => {
    if (!qState) return null;
    try { return typeof qState === "string" ? JSON.parse(qState) : qState; } catch { return null; }
  })();
  const sessionOperator = parsedQueue?.operator ?? parsedQueue?.groups?.[0]?.operator ?? null;
  const sessionMode = parsedQueue?.measure_mode ?? parsedQueue?.mode ?? null;

  // ── ผลรายแกนของค่าที่เพิ่งวัด ────────────────────────────────────────────
  const axX = axisInfo(telemetry?.value_x, telemetry?.nominal_x, telemetry?.upper_tol, telemetry?.lower_tol, telemetry?.ok_x);
  const axY = axisInfo(telemetry?.value_y, telemetry?.nominal_y, telemetry?.upper_tol, telemetry?.lower_tol, telemetry?.ok_y);


  async function startFromQueue() {
    const q = entryQueue;
    if (!q) return;

    // สรุปทีละกลุ่มก่อนยืนยัน — ผู้ใช้ต้องเห็นว่าชิ้นไหนอยู่กลุ่มไหน ไม่ใช่เห็น
    // แค่เลขรวมกันพรืดเดียว (กลุ่มคือสิ่งที่กำหนดว่า Part แต่ละตัวจะได้ config อะไร)
    const ok = await dialog.confirm(
      <>
        เริ่ม session ด้วยคิว <strong>{q.mode}</strong> จำนวน <strong>{q.list.length} ALPL</strong>
        <br />
        <br />
        {q.groups.map((g, gi) => {
          const bits = [g.package_size, g.part_number].filter(Boolean).join(" · ");
          return (
            <div key={gi}>
              กลุ่มที่ {gi + 1}: {g.number_alpl.join(", ")}
              {bits ? <span style={{ opacity: 0.7 }}> ({bits})</span> : null}
            </div>
          );
        })}
      </>,
      { title: "เริ่มการวัด", okLabel: "▶ เริ่มวัด" },
    );
    if (!ok) return;

    // payload แบบกลุ่ม — backend คลี่เป็นคิวเส้นเดียวเองพร้อมจำว่าชิ้นไหนอยู่
    // กลุ่มไหน (ดู _flatten_groups / _group_config_for) · Operator อยู่นอกกลุ่ม
    // เพราะใช้ร่วมกันทั้ง session
    const body = { Measure_Type: q.mode, Operator: q.operator, groups: q.groups };

    try {
      const data = await apiPost<{ session_id: number; target_count: number }>("/api/session/start", body);
      // ⚠ ผูก session_id กับคิว "ก่อน" เรียก updateSession() — ไม่งั้นการเช็คว่า
      //   คิวเก่าค้างอยู่ไหม (queueIsStale) จะเห็น session_id ไม่ตรงแล้วล้างคิว
      //   ที่เพิ่ง start ทิ้งทันที
      const bound = { ...q, session_id: data.session_id };
      setEntryQueue(bound);
      entryQueueRef.current = bound;
      savePartEntryState();
      updateSession({ state: "running", session_id: data.session_id, measured_count: 0, target_count: data.target_count });
      refreshParts();
    } catch (e) {
      dialog.alert(e instanceof ApiError ? e.message : "เริ่ม session ไม่สำเร็จ", { title: "เริ่มการวัดไม่สำเร็จ" });
    }
  }


  /** หยุด session จริง ๆ — **ไม่ถามยืนยัน**
   *
   *  ⚠ แยกออกจาก `stopSession()` เพราะบางเส้นทาง "ตัดสินใจไปแล้ว" ห้ามถามซ้ำ:
   *    • โมดัลนับถอยหลังครบ 60 วิ → มีไว้สำหรับตอน **ไม่มีคนอยู่** ถ้าเด้ง
   *      confirm ขึ้นมามันจะค้างรอคนกดตลอดกาล = ไม่มีอะไรหยุดเลย
   *    • ผู้ใช้กด "หยุดการวัด" ในโมดัล → เพิ่งเลือกไปหมาด ๆ ถามซ้ำไม่มีประโยชน์
   */
  async function doStopSession(sid?: number | null) {
    try {
      /* ⚠ ต้องอ่าน `agent_error` ในผลลัพธ์ด้วย — backend ตอบ 200 แม้สั่ง Pi ไม่ผ่าน
         เพราะฝั่ง DB หยุดสำเร็จจริง กดซ้ำก็ไม่ช่วยอะไร **catch จึงไม่ทำงาน**

         แต่ "สั่ง Pi ไม่ผ่าน" แปลว่า **เครื่องอาจยังวัดต่ออยู่จริง** ทั้งที่ระบบ
         บอกว่าจบแล้ว — ของจะไหลต่อโดยไม่มีใครบันทึก ซึ่งอันตรายกว่ากรณี Start
         พังมาก (ดูคอมเมนต์ใน stop_session ฝั่ง backend)

         backend บันทึก STOP_NOT_DELIVERED ลง DB และ broadcast SSE ไว้ให้แล้ว
         ขาดแค่ฝั่งนี้ที่ต้องเอามาบอกคน                                        */
      const r = await apiPost<{ ok: boolean; agent_error?: string | null }>(
        "/api/session/stop", { session_id: sid ?? session.session_id });

      if (r?.agent_error) {
        dialog.alert(
          `ระบบหยุด session ให้แล้ว แต่สั่งเครื่องไม่สำเร็จ\n\n${r.agent_error}\n\n` +
          `เครื่องอาจยังวัดต่ออยู่ และค่าที่วัดหลังจากนี้จะไม่ถูกบันทึก — ` +
          `กรุณาไปหยุดที่เครื่องเอง`,
          { title: "⚠ ต้องไปหยุดที่เครื่อง", danger: true },
        );
      }
    } catch (e) {
      dialog.alert(e instanceof ApiError ? e.message : "หยุด session ไม่สำเร็จ", { title: "หยุดการวัดไม่สำเร็จ" });
    }
  }

  /** ปุ่ม Stop บน Session Control — ถามยืนยันก่อน เพราะกดโดนง่ายระหว่างวัดอยู่ */
  async function stopSession() {
    if (!await dialog.confirm("หยุด session ที่กำลังวัดอยู่ตอนนี้",
                              { title: "หยุดการวัด", okLabel: "■ หยุด", danger: true })) return;
    await doStopSession();
  }


  function openPeModal() {
    setPeModalOpen(true);
  }







  // ══════════════════════════════════════════════════════════════════
  // Report modal (คลิกแถวในตาราง Measurements)
  // ══════════════════════════════════════════════════════════════════
  async function openReportModal(measurementId: number) {
    const m = measurements.find((x) => x.measurement_id === measurementId);
    if (!m) return;
    let part: Part | null = null;
    try {
      part = await apiGet<Part>(`/api/parts/${m.number_alpl}`);
    } catch {
      part = partsRef.current.find((p) => p.number_alpl === m.number_alpl) ?? null;
    }
    setReportModal({ measurement: m, part, imageUrl: null, imageState: m.image_path ? "loading" : "none" });
    if (m.image_path) {
      try {
        const data = await apiGet<{ url: string }>(`/api/image-url/${measurementId}`);
        setReportModal((prev) => (prev && prev.measurement.measurement_id === measurementId ? { ...prev, imageUrl: data.url, imageState: "ok" } : prev));
      } catch {
        setReportModal((prev) => (prev && prev.measurement.measurement_id === measurementId ? { ...prev, imageState: "none" } : prev));
      }
    }
  }

  const isRunning = session.state === "running";
  const canEditQueue = session.state !== "running";

  return (
    <div className="layout">
      <main className="main">
        {/* Section 1 — Session Control */}
        <section>
          <div className="card">
            <div className="card-title">Session Control</div>
            {/* ทุกอย่างอยู่บรรทัดเดียว — ชิปที่ยังไม่มีค่าถูกซ่อนทั้งชิป ไม่ใช่โชว์
                ขีดกลางไว้ แถบตอน idle จะได้ไม่รกด้วยช่องว่างเปล่า */}
            <div className="session-row">
              <div className="session-chip">
                <span className="sc-label">Status</span>
                {/* คลาสยังใช้ค่าดิบ (`timeout`) — เปลี่ยนเฉพาะข้อความ ดู sessionStateLabel */}
                <span className={`session-state-badge ${session.state}`}>{sessionStateLabel(session.state)}</span>
              </div>
              {sessionOperator && (
                <div className="session-chip">
                  <span className="sc-label">Operator</span>
                  <span className="sc-value">{sessionOperator}</span>
                </div>
              )}
              {sessionMode && (
                <div className="session-chip">
                  <span className="sc-label">Measure Type</span>
                  <span className="sc-value">{sessionMode}</span>
                </div>
              )}
              {session.session_id != null && (
                <div className="session-chip">
                  <span className="sc-label">Session</span>
                  <span className="sc-value">{session.session_id}</span>
                </div>
              )}
              {/* ⚠ ชิป PI ไม่ซ่อนตอน idle ต่างจากชิปอื่น — ประโยชน์หลักคือดูก่อน
                  กด Start ว่าเครื่องพร้อมไหม ซ่อนตอนไม่มี session ก็หมดความหมาย */}
              <div className="session-chip">
                <span className="sc-label">Raspberry Pi</span>
                <span className={`sc-value sc-pi ${piOnline ? "online" : piStatus === false ? "offline" : "unknown"}`}>
                  {piOnline ? "🟢 Online" : piStatus === false ? "🔴 Offline" : "🟡 Connecting"}
                </span>
              </div>
              <div className="session-btns">
                <button className="btn-start" disabled={!canStart} title={startTitle} onClick={startFromQueue}>
                  {startLabel}
                </button>
                {isRunning && manualTrigger && (
                  <button
                    className="btn-trigger"
                    disabled={!triggerReady}
                    title={
                      triggerReady
                        ? "ส่งสัญญาณให้เริ่มวัดชิ้นนี้ (แทน MCU ชั่วคราว)"
                        : "ยังไม่ถึงจังหวะ — ระบบกำลังโหลดโปรแกรมวัด หรือกำลังรอผลของชิ้นก่อนหน้าอยู่"
                    }
                    onClick={sendManualTrigger}
                  >
                    ⚡ Trigger
                  </button>
                )}
                {isRunning && (
                  <button className="btn-stop" onClick={stopSession}>
                    ■ Stop
                  </button>
                )}
              </div>
            </div>
          </div>
        </section>

        {/* Section 2 — Live View */}
        <section>
          <div className="live-view-grid">
            <div className="card">
              <div className="telemetry-header">
                <div className="card-title" style={{ marginBottom: 0 }}>
                  Live Telemetry
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                  <span className="telemetry-alpl-badge">ALPL {telemetry?.number_alpl ?? "—"}</span>
                  {/* ล้างเฉพาะสิ่งที่แสดงบนจอ ไม่แตะฐานข้อมูล — ผลวัดที่บันทึกไปแล้ว
                      ยังอยู่ครบในตาราง Measurements ด้านล่าง
                      ⚠ ล็อกตอน running เพราะล้างกลางคันแล้ว SSE ตัวถัดไปจะเติม
                        กลับมาครึ่งๆ กลางๆ ดูสับสนกว่าเดิม */}
                  <button
                    type="button"
                    className="btn-clear"
                    disabled={isRunning}
                    title={isRunning ? "กดไม่ได้ระหว่างกำลังวัด — กด Stop ก่อน"
                                     : "ล้างค่าที่แสดงอยู่ ไม่กระทบข้อมูลที่บันทึกแล้ว"}
                    onClick={clearTelemetry}
                  >
                    🧹 Clear
                  </button>
                </div>
              </div>
              <div className="telemetry-grid">
                <div className="telemetry-xy-col">
                  <div className="telemetry-cell x">
                    <div className="tc-head">
                      <span className="tc-label">Value X</span>
                      {axX.ok != null && <span className={`tc-axis ${axX.ok ? "ok" : "ng"}`}>{axX.ok ? "OK" : "NG"}</span>}
                    </div>
                    <div className="tc-value">
                      {telemetry ? telemetry.value_x.toFixed(3) : "—"}
                      <span> mm</span>
                    </div>
                    <div className="tc-range">{telemetry ? axX.range : ""}</div>
                  </div>
                  <div className="telemetry-cell y">
                    <div className="tc-head">
                      <span className="tc-label">Value Y</span>
                      {axY.ok != null && <span className={`tc-axis ${axY.ok ? "ok" : "ng"}`}>{axY.ok ? "OK" : "NG"}</span>}
                    </div>
                    <div className="tc-value">
                      {telemetry ? telemetry.value_y.toFixed(3) : "—"}
                      <span> mm</span>
                    </div>
                    <div className="tc-range">{telemetry ? axY.range : ""}</div>
                  </div>
                  {/* ── Offset 2 แกน — ซ่อนทั้งคู่ในโหมด IPM ─────────────────
                      IPM ใช้เกณฑ์จากตาราง `package_size` ซึ่ง **ไม่เอา offset
                      มาตัดสิน OK/NG เลย** (ดู `_offset_limit` ฝั่ง backend)
                      ค่ายังถูกบันทึกลง DB ครบ ดูได้จาก Export/Power BI แค่ไม่เอา
                      มารกหน้าจอที่คนหน้าเครื่องใช้ตัดสินใจ — เหตุผลเดียวกับที่
                      `ReportAxis` ซ่อนการ์ด Offset ในโหมดนี้อยู่แล้ว

                      ⚠ ใช้ `offset_counts` จาก backend เป็นหลัก (มันคือคำตอบของ
                        `_offset_limit` ตัวจริง) แล้วค่อย fallback ไปดูโหมดของ
                        session — ห้ามเทียบ `sessionMode === "IPM"` อย่างเดียว
                        เพราะกฎว่าโหมดไหนนับ offset อยู่ที่ backend ที่เดียว
                        ถ้าวันหลังกฎเปลี่ยน หน้าเว็บจะตามเองโดยไม่ต้องแก้

                      ⚠ fallback ดูโหมด **เฉพาะตอน state = running** เท่านั้น
                        `sessionMode` แกะมาจาก `queue_state` ของ session ล่าสุด
                        ซึ่ง **ค้างอยู่ต่อหลัง session จบ** ถ้าเช็คโหมดตลอดเวลา
                        พอวัด IPM จบแล้วกด Clear การ์ดจะหายไปเลย ทั้งที่จอว่าง
                        ไม่มีค่าอะไรให้ซ่อน — เหลือช่องโหว่ในเลย์เอาต์แทน
                        ตอนว่าง/จบแล้วจึงโชว์โครงเปล่าไว้เสมอ

                      ⚠ ถอดช่อง GH-X / GH-Y ออกแล้ว — เลิกใช้เครื่องมือฝั่ง GH
                        (ถอดออกจาก MeasurementCreate + ตาราง measurements) */}
                </div>
                <div className={`telemetry-result-col${telemetry ? (telemetry.result === "OK" ? " ok" : " ng") : ""}`}>
                  <div className="telemetry-result-label">Result</div>
                  <div className={`telemetry-result-value${telemetry ? (telemetry.result === "OK" ? " ok" : " ng") : ""}`}>{telemetry?.result ?? "—"}</div>
                </div>
                {/* ⚠ ต้องเป็นลูกโดยตรงของ `.telemetry-grid` — ถ้าไปอยู่ใน
                    `.telemetry-xy-col` (ซึ่งเป็น flex column) `grid-column` จะ
                    ไม่มีผลเลย การ์ดจะแคบอยู่ในคอลัมน์ซ้ายเหมือนเดิม */}
                {(telemetry?.offset_counts ??
                  (session.state === "running"
                    ? (sessionMode ?? "").toUpperCase() !== "IPM"
                    : true)) && (
                  <div className="telemetry-cell offset telemetry-offset-cell">
                    <OffsetMap
                      title="Offset Opening"
                      offsetX={telemetry?.offset_opx}
                      offsetY={telemetry?.offset_opy}
                      posCode={telemetry?.offset_pos_op}
                      offsetTol={telemetry?.offset_tol}
                      measureType={telemetry?.measure_type}
                    />
                  </div>
                )}
              </div>
              {/* แถบคิว ALPL — **ซ่อนเฉพาะตอนไม่มีคิวเลย** เท่านั้น
                  ⚠ เดิม vanilla ซ่อนเมื่อคิว ≤ 1 ด้วยเหตุผลว่า "ตัวเดียวไม่มีอะไร
                    ให้ดู" แล้วเลิกทำ เพราะไม่จริงในการใช้งาน — ชิปตัวเดียวยังบอกได้
                    ว่า ALPL ไหนกำลังวัด/วัดไปแล้วผลเป็นอะไร และกดเปิดรายงานได้
                    ที่สำคัญคือมันหาย ๆ โผล่ ๆ ตามจำนวนชิ้นในรอบ ทำให้เลย์เอาต์ของ
                    การ์ดนี้ไม่นิ่ง คนใช้จำไม่ได้ว่าแถบนี้อยู่ตรงไหน */}
              {queueStrip.length > 0 && (
                <div className="telemetry-queue">
                  <div className="tq-label">Queue</div>
                  <div className="tq-strip">
                    {queueStrip.map((q, i) => (
                      <span key={`${q.alpl}-${i}`} className={`tq-chip ${q.state}`}>
                        {q.state === "now" && <span className="tq-dot" />}
                        {(q.state === "ok" || q.state === "ng" || q.state === "done") && (
                          <span
                            className="tq-ico"
                            title={q.state === "done" ? "วัดแล้ว — หน้านี้ยังไม่รู้ผล ดูที่ตาราง Measurements" : undefined}
                          >
                            {q.state === "ng" ? "✕" : q.state === "done" ? "?" : "✓"}
                          </span>
                        )}
                        {q.alpl}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {/* แถบสัดส่วนผลการวัดของ session ปัจจุบัน: เขียว=OK แดง=NG เทา=ยังไม่วัด
                  บอกครบ 3 อย่างในภาพเดียวโดยไม่ต้องอ่านตัวเลข */}
              <div className="telemetry-bar">
                <div className="tb-ok" style={{ width: `${barOkPct}%` }} />
                <div className="tb-ng" style={{ width: `${barNgPct}%` }} />
              </div>
              <div className="telemetry-footer">
                <span>Progress</span>
                <span className="telemetry-counts">
                  <span className="tcount ok">{stats.ok} OK</span>
                  <span className="tcount-sep">·</span>
                  <span className="tcount ng">{stats.ng} NG</span>
                  <span className="tcount-sep">·</span>
                  {/* isTelemetryCleared(): ผู้ใช้กด 🧹 Clear ไว้ — ต้องค้างที่ขีด
                      ไม่งั้นรอบ poll ถัดไปจะเขียน "1 / 1 measured" กลับมาเอง
                      (ตัวเลขนี้มาจาก session ไม่ใช่ stats จึงไม่โดน guard ชุดเดิม) */}
                  <strong>
                    {isTelemetryCleared() || session.state === "idle" || !session.session_id
                      ? "— / — measured"
                      : `${session.measured_count} / ${session.target_count} measured`}
                  </strong>
                </span>
              </div>
            </div>

            <div className="card">
              <div className="card-title">Camera Preview</div>
              <div className="camera-preview-box">
                {cameraImgUrl ? (
                  <img
                    src={cameraImgUrl}
                    alt={`Latest capture (measurement #${lastImageMeasurementId})`}
                    title="คลิกเพื่อดูเต็มจอ"
                    onClick={() => setZoomImgUrl(cameraImgUrl)}
                  />
                ) : (
                  <>
                    <span className="camera-preview-icon">🖼</span>
                    <span>No image yet</span>
                  </>
                )}
              </div>
            </div>
          </div>
        </section>

        {/* Section 3 — Stats: ย้ายไปอยู่ในแถบล่างของการ์ด Live Telemetry แล้ว
            (Total ซ้ำกับ "x / y measured" ที่มีอยู่เดิม จึงเหลือแค่ OK/NG +
             แถบสัดส่วน) — ตรงกับ index.html ที่ถอด section นี้ออกไปแล้ว */}

        {/* Section 4 — Part Entry */}
        <section>
          <div className="card">
            <div className="pe-card-header">
              <div className="card-title" style={{ marginBottom: 0 }}>
                Part Entry
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                  {entryQueue && (
                    <span className={`pe-mode-badge-lg ${entryQueue.mode.toLowerCase()}`}>
                      {entryQueue.mode}
                    </span>
                  )}
                {/* ล้างคิวที่กรอกไว้ทั้งหมด — ล็อกตอน running เพราะคิวระหว่างวัด
                    คือของที่ backend ถืออยู่จริง ล้างฝั่งหน้าเว็บอย่างเดียวจะทำให้
                    สองฝั่งไม่ตรงกัน แล้วผลวัดที่ตามมาจะไปแปะกับ ALPL ผิดตัว */}
                <button
                  type="button"
                  className="btn-clear"
                  disabled={isRunning}
                  title={isRunning ? "กดไม่ได้ระหว่างกำลังวัด — กด Stop ก่อน"
                                   : "ล้างคิว Part Entry ที่กรอกไว้ทั้งหมด"}
                  onClick={clearPartEntry}
                >
                  🧹 Clear
                </button>
              </div>
            </div>

            {!entryQueue ? (
              <>
                <div className="pe-empty">ยังไม่มีข้อมูล Part Entry ค้างอยู่ — กด "New Entry" เพื่อเตรียมคิว IPM, ลงทะเบียน Part ใหม่ หรือส่ง Rework</div>
                <div style={{ marginTop: "1rem", textAlign: "center" }}>
                  <button className="btn-pe-action" onClick={openPeModal}>
                    + New Entry
                  </button>
                </div>
              </>
            ) : (
                <div className="pe-summary-dropdown">
                  <button type="button" className="pe-summary-toggle" onClick={() => setPeSummaryOpen((v) => !v)}>
                    <span className="pe-summary-toggle-left">
                      <span>ALPL: {entryQueue!.list.join(", ")}</span>
                    </span>
                    <span className={`pe-summary-arrow${peSummaryOpen ? " open" : ""}`}>▼</span>
                  </button>
                  <div className={`pe-summary-body${peSummaryOpen ? " open" : ""}`}>
                    {/* แสดงทีละกลุ่ม — ของเดิมโชว์ field ชุดเดียวเพราะมีได้กลุ่มเดียว
                        ตอนนี้ต้องบอกให้ได้ว่า ALPL ไหนใช้ config ชุดไหน ไม่งั้น
                        ผู้ใช้ตรวจก่อนกด Start ไม่ได้ว่ากรอกถูกกลุ่มหรือเปล่า */}
                    <div className="pe-summary-grid">
                      <span className="pg-label">Operator</span>
                      <span className="pg-value">{entryQueue!.operator}</span>
                    </div>
                    {entryQueue!.groups.map((g, gi) => (
                      <div key={gi} className="pe-summary-grid" style={{ marginTop: "0.6rem" }}>
                        <span className="pg-label">กลุ่มที่ {gi + 1}</span>
                        <span className="pg-value">{(g.number_alpl as number[]).join(", ")}</span>
                        {Object.entries(g)
                          .filter(([k, v]) => k !== "number_alpl" && v !== "" && v != null)
                          .map(([k, v]) => (
                            <span key={k} style={{ display: "contents" }}>
                              <span className="pg-label">{k.replace(/_/g, " ")}</span>
                              <span className="pg-value">{String(v)}</span>
                            </span>
                          ))}
                      </div>
                    ))}
                    <div className="pe-summary-actions">
                      {canEditQueue && (
                        <button className="btn-pe-action" onClick={openPeModal}>✎ Edit</button>
                      )}
                    </div>
                  </div>
                </div>
            )}
          </div>
        </section>

        {/* Section 5 — Measurements Table */}
        <section>
          <div className="card">
            <div className="card-header">
              <div className="card-title">
                Measurements <span className="count">({measTotal})</span>
              </div>
            </div>
            <div className="filter-bar">
              <input type="text" placeholder="ค้นหาด้วย ALPL Number..." value={measFilterAlplInput} onChange={(e) => onMeasSearchChange(e.target.value)} />
              <input type="date" title="กรองตาม Timestamp (วันที่)" value={measFilterDate} onChange={(e) => onMeasDateChange(e.target.value)} />
              <button className="btn-clear-filter" onClick={onMeasClearFilter}>
                ✕ Clear Filter
              </button>
            </div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>ID</th>
                    <th>Session</th>
                    <th>ALPL</th>
                    {/* เกณฑ์ที่ใช้ตัดสินการวัดครั้งนั้น — แหล่งขึ้นกับโหมด
                        (IPM → package_size · New/Rework → part_number) backend
                        เลือกให้แล้วใน MEASUREMENTS_SELECT
                        วางไว้ "ก่อน" Value X เพื่อให้อ่านไล่ซ้าย→ขวาได้ว่า
                        "เกณฑ์เท่านี้ วัดได้เท่านี้ ผลเลยเป็นแบบนี้" */}
                    <th className="th-spec">Nominal X / Y</th>
                    <th className="th-spec">Tol (+/-)</th>
                    <th className="th-spec">Offset Tol</th>
                    {/* รวม X กับ Y ไว้ช่องเดียว — ระบายสีแยกทีละแกน จะได้เห็น
                        ทันทีว่าแกนไหนเป็นตัวที่ทำให้ทั้งแถวเป็น NG
                        (ตาราง Edit ใช้ชุดเดียวกัน ดู measurementCells.tsx) */}
                    <th>Value X/Y</th>
                    <th>Offset X/Y</th>
                    <th>Result</th>
                    <th>Note</th>
                    <th>Operator</th>
                    <th>Measure Type</th>
                    <th>Image</th>
                    <th>Timestamp</th>
                  </tr>
                </thead>
                <tbody>
                  {measurements.length === 0 ? (
                    <tr className="empty-row">
                      <td colSpan={15}>{measFilterAlplRef.current || measFilterDate ? "ไม่พบ Measurement ที่ตรงกับตัวกรอง" : "No measurements"}</td>
                    </tr>
                  ) : (
                    measurements.map((m) => {
                      const ts = m.timestamp ? new Date(m.timestamp).toLocaleString() : "—";
                      const res = m.result || "—";
                      const cls = res === "OK" ? "ok" : res === "NG" ? "ng" : "";
                      // โหมดของ "แถวนี้" ไม่ใช่โหมดของ session ปัจจุบัน — ตารางนี้
                      // แสดงข้อมูลย้อนหลังที่ปนกันทุกโหมด
                      const isIpm = (m.measure_type ?? "").toUpperCase() === "IPM";
                      return (
                        <tr key={m.measurement_id} data-clickable className={highlightId === m.measurement_id ? "highlight-new" : ""} onClick={() => openReportModal(m.measurement_id)}>
                          <td>{m.measurement_id}</td>
                          <td>{m.session_id ?? "—"}</td>
                          <td>{m.number_alpl}</td>
                          <td className="td-spec">
                            {m.nominal_x != null && m.nominal_y != null
                              ? `${Number(m.nominal_x).toFixed(3)} / ${Number(m.nominal_y).toFixed(3)}`
                              : "—"}
                          </td>
                          <td className="td-spec">
                            {m.upper_tol != null && m.lower_tol != null
                              ? `+${Number(m.upper_tol).toFixed(3)} / -${Number(m.lower_tol).toFixed(3)}`
                              : "—"}
                          </td>
                          {/* ── โหมด IPM ไม่เอา offset มาตัดสิน → 2 คอลัมน์นี้เป็น "—"
                              ค่ายังอยู่ใน DB ครบ (ดูได้จาก Export/Power BI) แค่ไม่
                              เอามาแสดงในตารางที่คนหน้าเครื่องใช้ตัดสินใจ เพราะมัน
                              ไม่มีส่วนร่วมกับผล OK/NG ของแถวนั้นเลย — กติกาเดียวกับ
                              ที่ Live Telemetry กับ ReportModal ซ่อนการ์ด Offset

                              ⚠ ดูจาก `measure_type` ของ **แถวนั้น** ไม่ใช่โหมดของ
                                session ปัจจุบัน — ตารางแสดงข้อมูลย้อนหลังปนกันทุกโหมด */}
                          <td className="td-spec">
                            {isIpm ? "—"
                              : m.offset_tol != null ? Number(m.offset_tol).toFixed(3)
                              : "ยังไม่ตั้ง"}
                          </td>
                          <td style={{ whiteSpace: "nowrap" }}>
                            {xyPair(
                              axisValue(m.value_x, m.nominal_x, m.upper_tol, m.lower_tol),
                              axisValue(m.value_y, m.nominal_y, m.upper_tol, m.lower_tol),
                            )}
                          </td>
                          {/* ⚠ ตั้งใจไม่ใส่ผัง <OffsetMap compact> ตรงนี้ — ตารางนี้มี
                              คอลัมน์เยอะอยู่แล้ว รูปเล็ก ๆ ซ้ำทุกแถวทำให้แถวสูงขึ้น
                              และเบียดคอลัมน์อื่นโดยได้ข้อมูลเพิ่มน้อย · ทิศทางดูได้
                              จากรายงานที่กดเปิดทีละแถวอยู่แล้ว */}
                          <td style={{ whiteSpace: "nowrap" }}>
                            {isIpm ? "—"
                              : xyPair(
                                  offsetValue(m.offset_opx, m.offset_tol),
                                  offsetValue(m.offset_opy, m.offset_tol),
                                )}
                          </td>
                          <td>
                            <span className={`result-badge ${cls}`}>{res}</span>
                          </td>
                          <td>{m.note ?? ""}</td>
                          <td>{m.operator_name ?? ""}</td>
                          <td>{m.measure_type ?? ""}</td>
                          <td className="img-cell">
                            {/* 3 สถานะ: มีรูปแล้ว / Agent อัปโหลดไม่สำเร็จครบ 3 ครั้ง /
                                ยังไม่มีรูป — กรณีสุดท้าย **ปล่อยว่างไปเลย ไม่ใส่ขีด**
                                คอลัมน์นี้มีแค่ "มีรูป/ไม่มีรูป" การมีไอคอนโผล่เฉพาะ
                                แถวที่มีรูปอ่านง่ายกว่าขีดจาง ๆ เต็มคอลัมน์ (ต่างจาก
                                คอลัมน์ Note ที่ขีดสื่อว่า "กรอกได้แต่ยังไม่ได้กรอก") */}
                            {m.image_path ? (
                              <button
                                className="img-btn-inner"
                                title="View report"
                                onClick={(e) => { e.stopPropagation(); openReportModal(m.measurement_id); }}
                              >
                                <AlplIcon />
                              </button>
                            ) : m.image_upload_failed ? (
                              <span className="no-img upload-failed" title="Agent อัปโหลดรูปไม่สำเร็จหลังลอง 3 ครั้ง">⚠ Failed</span>
                            ) : (
                              ""
                            )}
                          </td>
                          <td style={{ whiteSpace: "nowrap" }}>{ts}</td>
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
              <span style={{ fontSize: "0.85rem", fontWeight: 600, color: "var(--muted)" }}>
                {measTotal === 0 ? "ไม่มีรายการ" : `แสดง ${(measPage - 1) * MEAS_PAGE_SIZE + 1}–${(measPage - 1) * MEAS_PAGE_SIZE + measurements.length} จาก ${measTotal} รายการ`}
              </span>
              <button type="button" className="btn-icon" disabled={(measPage - 1) * MEAS_PAGE_SIZE + measurements.length >= measTotal} onClick={onMeasNext}>
                Next ›
              </button>
            </div>
          </div>
        </section>
      </main>

      {/* ── Measurement Report modal ─────────────────────────────────── */}
      {/* สรุปผล IPM ตอนวัดครบ — ตารางสำหรับคัดลอกไปวางใน Excel */}
      {ipmSummary && ipmSummary.length > 0 && (
        <IpmSummaryModal rows={ipmSummary} onClose={() => setIpmSummary(null)} />
      )}

      {/* ── Measure timeout ────────────────────────────────────────────────
          ⚠ ตั้งใจ **ไม่มีปุ่มปิด (✕) และคลิกพื้นหลังปิดไม่ได้** เพราะเครื่องฝั่ง Pi
            กำลังค้างรอคำตอบอยู่จริง ๆ ถ้าปิดทิ้งเฉย ๆ session จะค้างโดยไม่มีใครรู้
          หน้าตา/ปุ่มเปลี่ยนตาม `event` ที่ backend แนบมา — ดู MT_VIEW */}
      {mtModal && (() => {
        const v = mtView(mtModal.event);
        return (
        <div className="modal-overlay open">
          <div className="pe-modal-box" style={{ maxWidth: 480 }}>
            <div className="pe-modal-header">
              <div className="card-title">{v.title}</div>
            </div>
            <div style={{ fontSize: "0.9rem", lineHeight: 1.7, marginBottom: "0.75rem" }}>
              {mtModal.number_alpl != null && <>ALPL <strong>{mtModal.number_alpl}</strong> </>}
              (ชิ้นที่ <strong>{mtModal.piece ?? "—"}/{mtModal.target ?? "—"}</strong>)
              {" "}{v.body}
              {mtModal.detail && (
                <><br /><span style={{ color: "var(--warn)" }}>สาเหตุ: {mtModal.detail}</span></>
              )}
              <br />{v.question}
              <br />
              <span style={{ color: "var(--muted)", fontSize: "0.8rem" }}>
                จะหยุดการวัดอัตโนมัติใน {mtLeft} วินาที
              </span>
            </div>
            <div style={{
              fontSize: "0.8rem", lineHeight: 1.6, color: "var(--muted)",
              background: "var(--surface2)", border: "1px solid var(--border)",
              borderRadius: "var(--radius)", padding: "0.6rem 0.75rem", marginBottom: "1.25rem",
            }}>
              {v.hint}
            </div>
            <div className="entry-actions" style={{ justifyContent: "flex-end" }}>
              <button type="button" className="btn-edit-entry" onClick={() => resolveMeasureTimeout("stop")}>
                หยุดการวัด
              </button>
              <button type="button" className="btn-submit-entry" onClick={() => resolveMeasureTimeout(v.action)}>
                {v.actionLabel}
              </button>
            </div>
          </div>
        </div>
        );
      })()}

      {/* ── Measurement report ──────────────────────────────────────────────
          แถวบน: รูป (ซ้าย) + การ์ดผลรายแกนพร้อมแถบเทียบสเปค (ขวา)
          แถวล่าง: ข้อมูล Part แบบอ้างอิง (ไม่ใช่สิ่งที่คนเปิดหน้านี้มาหา) */}
      <div className={`modal-overlay${reportModal ? " open" : ""}`}>
        <div className="report-modal-box">
          {reportModal && (() => {
            const m = reportModal.measurement;
            const part = reportModal.part;
            const verdict = m.result === "OK" ? "ok" : m.result === "NG" ? "ng" : "";
            // เกณฑ์เอาจากแถว measurement ก่อน (backend เลือกแหล่งตามโหมดให้แล้ว)
            // ค่อยถอยไปใช้ของ part ถ้าแถวเก่าไม่มี — ห้ามใช้ของ part เป็นหลัก
            // เพราะ part อาจถูกแก้ทีหลัง แล้วรายงานจะไม่ตรงกับตอนวัดจริง
            const nomX = m.nominal_x ?? part?.nominal_x;
            const nomY = m.nominal_y ?? part?.nominal_y;
            const upTol = m.upper_tol ?? part?.upper_tol;
            const loTol = m.lower_tol ?? part?.lower_tol;
            const specRows: [string, string][] = [
              ["Vendor", part?.vendor || "—"],
              ["Owner", part?.owner || "—"],
              ["PO number", part?.po_number != null ? String(part.po_number) : "—"],
              ["Template", part?.template_name || "—"],
              ["Receive date", part?.recieve_date ? new Date(part.recieve_date).toLocaleDateString() : "—"],
              ["Operator", m.operator_name || "—"],
              ["Measure type", m.measure_type || "—"],
              ["Note", m.note || "—"],
            ];
            return (
              <>
                <div className="report-header">
                  <div>
                    <div className="report-header-title">Measurement report — ALPL {m.number_alpl}</div>
                    <div className="report-header-sub">
                      {m.timestamp ? new Date(m.timestamp).toLocaleString() : "—"} ·{" "}
                      {m.session_id != null ? `Session #${m.session_id}` : "Session —"} · {m.operator_name || "—"}
                    </div>
                  </div>
                  <div className="report-header-right">
                    <span className={`report-verdict ${verdict}`}>{m.result || "—"}</span>
                    <button className="report-close" title="Close" onClick={() => setReportModal(null)}>✕</button>
                  </div>
                </div>

                <div className="report-body">
                  <div className="report-image-cell">
                    {reportModal.imageState === "loading" ? (
                      <span className="report-no-image">Loading…</span>
                    ) : reportModal.imageState === "ok" && reportModal.imageUrl ? (
                      <img src={reportModal.imageUrl} alt={`Measurement #${m.measurement_id} image`} />
                    ) : (
                      <span className="report-no-image">No image</span>
                    )}
                  </div>
                  <div className="report-axes">
                    <ReportAxis axis="X" value={m.value_x} nominal={nomX} upperTol={upTol} lowerTol={loTol} />
                    <ReportAxis axis="Y" value={m.value_y} nominal={nomY} upperTol={upTol} lowerTol={loTol} />
                    <OffsetMap
                      offsetX={m.offset_opx}
                      offsetY={m.offset_opy}
                      posCode={m.offset_pos_op}
                      offsetTol={m.offset_tol}
                      measureType={m.measure_type}
                    />
                  </div>
                </div>

                <div className="report-specs">
                  {specRows.map(([label, value]) => (
                    <div key={label}>
                      <div className="rs-label">{label}</div>
                      <div className="rs-value">{value}</div>
                    </div>
                  ))}
                  <div className="rs-full">
                    <div className="rs-label">Description</div>
                    <div className="rs-value">{part?.description || "—"}</div>
                  </div>
                </div>
              </>
            );
          })()}
        </div>
      </div>

      {/* ── Confirm modal (Promise-based — IPM เจอ ALPL ที่ยังไม่เคยลงทะเบียน) ── */}
      <div className={`modal-overlay${confirmModal ? " open" : ""}`}>
        <div className="pe-modal-box" style={{ maxWidth: 480 }}>
          <div className="pe-modal-header">
            <div className="card-title">ยืนยันการดำเนินการ</div>
          </div>
          <div style={{ fontSize: "0.9rem", lineHeight: 1.6, marginBottom: "1.25rem" }}>{confirmModal?.message}</div>
          <div className="entry-actions" style={{ justifyContent: "flex-end" }}>
            <button type="button" className="btn-edit-entry" onClick={() => resolveConfirmModal(false)}>
              ยกเลิก
            </button>
            <button type="button" className="btn-submit-entry" onClick={() => resolveConfirmModal(true)}>
              ดำเนินการต่อ
            </button>
          </div>
        </div>
      </div>

      {/* ── Part Entry modal ─────────────────────────────────────────── */}
      {/* ── Part Entry ─────────────────────────────────────────────────────
          ฟอร์มเดียวใช้ทั้ง 3 โหมด กรอกได้หลายกลุ่ม (ดู PartEntryModal/EntryGroups)
          แทนที่ของเดิมที่แยกเป็น 3 ฟอร์มโหมดละชุด กลุ่มละ 1 ชุดเท่านั้น */}
      {peModalOpen && (
        <PartEntryModal
          operators={operatorOptions}
          vendors={vendorOptions}
          owners={ownerOptions}
          packageSizes={packageSizeOptions}
          partNumbersFor={(pkg) =>
            Array.from(
              new Set(
                partNumberCatalog
                  .filter((r) => !pkg || r.package_size === pkg)
                  .map((r) => r.part_number_name),
              ),
            ).sort()
          }
          onNotify={showToast}
          confirmRegister={async (items) =>
            dialog.confirm(
              <>
                <strong>ALPL ต่อไปนี้ยังไม่เคยบันทึกมาก่อน</strong>
                <br />
                {items.map((it) => (
                  <div key={it.alpl}>• ALPL {it.alpl} → Package Size "{it.package_size || "—"}"</div>
                ))}
                <br />
                จะลงทะเบียนให้ตอนวัดชิ้นนั้นสำเร็จ แล้ววัดต่อเลยไหม
              </>,
              { title: "มี ALPL ที่ยังไม่ลงทะเบียน", okLabel: "ลงทะเบียนแล้ววัดต่อ" },
            )
          }
          onSave={(q) => {
            setEntryQueue(q);
            entryQueueRef.current = q;
            savePartEntryState();
            setPeModalOpen(false);
          }}
          onClose={() => setPeModalOpen(false)}
        />
      )}

      {/* ดูรูปเต็มจอ — คลิกที่ไหนก็ปิด (รูปเองก็ปิด เพราะ cursor เป็น zoom-out ทั้งจอ) */}
      {zoomImgUrl && (
        <div className="img-zoom" onClick={() => setZoomImgUrl(null)}>
          <img src={zoomImgUrl} alt="Measurement image, full size" />
          <span className="img-zoom-hint">คลิกที่ใดก็ได้ หรือกด Esc เพื่อปิด</span>
        </div>
      )}
    </div>
  );
}
