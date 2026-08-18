import { useEffect, useRef, useState } from "react";

export type SSEStatus = "connecting" | "online" | "offline";

// ชื่อ event ทั้งหมดที่ backend ยิงผ่าน /api/stream — ต้อง sync กับของจริงเสมอ
// (ดูทุกจุดที่เรียก push_event() ใน Backend-server/routers/ กับ shared.py)
//
// ⚠ event ที่ไม่ได้ประกาศไว้ที่นี่จะถูกทิ้งเงียบๆ ไม่มี error ให้เห็น เพราะเรา
//   addEventListener ตามรายชื่อในลิสต์ล่างเท่านั้น — เคยขาดไป 4 ตัว
//   (measure_timeout / station_event / station_online / pi_status) แล้วหน้าเว็บ
//   ไม่ตอบสนองเลยตอน Pi ขอคำตอบ ทั้งที่ backend ยิงมาแล้ว
export type SSEEventName =
  | "session_started"
  | "measurement"
  | "session_stopped"
  | "session_complete"
  | "session_timeout"
  | "image_updated"
  | "measure_timeout"
  | "station_event"
  | "station_online"
  | "pi_status"
  | "ping";

const EVENT_NAMES: SSEEventName[] = [
  "session_started",
  "measurement",
  "session_stopped",
  "session_complete",
  "session_timeout",
  "image_updated",
  "measure_timeout",
  "station_event",
  "station_online",
  "pi_status",
  "ping",
];

type Handler = (data: any) => void;
type Handlers = Partial<Record<SSEEventName, Handler>>;

/* ── connection เดียวใช้ร่วมทั้งแอป ─────────────────────────────────────────
   เดิม useSSE() สร้าง EventSource ใหม่ทุกครั้งที่ถูกเรียก และมันถูกเรียก 2 ที่
   (Layout + DashboardPage) = เปิดสาย 2 เส้นต่อ 1 แท็บ ทั้งที่ docstring ของ
   ตัวมันเองเขียนไว้ว่าควรเรียกจุดเดียว

   ทำไมถึงต้องแก้: เบราว์เซอร์จำกัด 6 connection ต่อโดเมน SSE ที่ค้างสายกิน
   โควตานั้นไปเรื่อยๆ เปิด 3 แท็บก็เต็มแล้ว request อื่นจะค้างรอคิวโดยไม่มี
   error อะไรให้เห็น — อาการคือ "เว็บช้าเป็นบางที" ซึ่งไล่หาสาเหตุยากมาก

   วิธี: เก็บสายไว้ที่ระดับโมดูล ใครเรียก useSSE() ก็แค่มาลงทะเบียน handler
   ไว้ในทะเบียนกลาง ตัวสุดท้ายที่เลิกใช้เป็นคนปิดสาย                         */
let sharedES: EventSource | null = null;
let refCount = 0;
let sharedStatus: SSEStatus = "connecting";
const subscribers = new Set<Handlers>();
const statusListeners = new Set<(s: SSEStatus) => void>();

function setSharedStatus(s: SSEStatus) {
  if (sharedStatus === s) return;
  sharedStatus = s;
  statusListeners.forEach((fn) => fn(s));
}

function openShared() {
  if (sharedES) return;
  const es = new EventSource("/api/stream");
  sharedES = es;

  es.onopen = () => setSharedStatus("online");
  es.onerror = () => {
    // EventSource พยายาม reconnect เองอยู่แล้ว — เราแค่ปรับป้ายระหว่างที่ยัง
    // ต่อไม่ติด ห้ามเรียก es.close() เองเพราะจะตัด auto-reconnect ทิ้งไปเลย
    setSharedStatus("offline");
  };

  EVENT_NAMES.forEach((name) => {
    es.addEventListener(name, (evt) => {
      if (name === "ping") return; // keep-alive เฉยๆ ไม่มี payload
      const raw = (evt as MessageEvent).data;
      let parsed: unknown;
      try {
        parsed = raw ? JSON.parse(raw) : undefined;
      } catch (err) {
        console.error(`useSSE: parse event "${name}" failed`, err);
        return;
      }
      // ยิงให้ทุกคนที่ลงทะเบียนไว้ — คนละหน้าสนใจคนละ event กัน
      subscribers.forEach((h) => h[name]?.(parsed));
    });
  });
}

function closeSharedIfIdle() {
  if (refCount > 0 || !sharedES) return;
  sharedES.onopen = null;
  sharedES.onerror = null;
  sharedES.close();
  sharedES = null;
  sharedStatus = "connecting";
}

/**
 * ลงทะเบียนรับ event จาก /api/stream แล้วคืนสถานะการเชื่อมต่อไปโชว์เป็นป้าย
 *
 * เรียกได้หลายที่โดยไม่เปลืองสาย — ทุกคนใช้ connection เดียวกัน
 *
 * ⚠ เรื่อง StrictMode: ตอน dev React จะ mount → unmount → mount ทันทีเพื่อ
 *   จับ effect ที่ cleanup ไม่สะอาด ของเดิมไม่ได้ล้าง es.onopen/es.onerror
 *   ตอน cleanup สายที่ถูกปิดไปแล้วจึงยังยิง onerror กลับมาแก้ state ได้ ผลคือ
 *       สายที่ 2 ต่อติด → setStatus("online")   🟢
 *       onerror ของสายที่ 1 เพิ่งมาถึง → setStatus("offline")   🔴 ทับทิ้ง
 *   เป็น race ที่สลับผลได้ทุกครั้งที่รีเฟรช บางทีเขียวบางทีแดงโดยไม่มีเหตุผล
 *   ตอนนี้ closeSharedIfIdle() ล้าง handler ทั้งคู่ก่อนปิดเสมอ
 */
export function useSSE(handlers: Handlers = {}): SSEStatus {
  const [status, setStatus] = useState<SSEStatus>(sharedStatus);
  const handlersRef = useRef<Handlers>(handlers);
  handlersRef.current = handlers;

  useEffect(() => {
    // ห่อด้วย object คงที่ที่อ่านผ่าน ref — handler เปลี่ยนได้ทุก render
    // โดยไม่ต้องต่อสายใหม่
    const proxy: Handlers = {};
    EVENT_NAMES.forEach((name) => {
      proxy[name] = (data) => handlersRef.current[name]?.(data);
    });

    subscribers.add(proxy);
    statusListeners.add(setStatus);
    refCount += 1;
    openShared();
    setStatus(sharedStatus);

    return () => {
      subscribers.delete(proxy);
      statusListeners.delete(setStatus);
      refCount -= 1;
      closeSharedIfIdle();
    };
  }, []);

  return status;
}
