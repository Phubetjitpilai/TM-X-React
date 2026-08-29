import { useQuery } from "@tanstack/react-query";
import { ApiError, apiGet } from "../api/client";

export interface SessionState {
  session_id?: number;
  number_alpl?: number;
  state: "idle" | "running" | "stopped" | "timeout";
  target_count?: number;
  measured_count?: number;
  last_seen?: string;
  started_at?: string;
  ended_at?: string;
  queue_state?: unknown;
  /** true = เห็น Pi ภายใน PI_ONLINE_TIMEOUT · false = เงียบเกินเกณฑ์
   *  null = **ไม่ทราบ** (backend เพิ่ง restart ยังไม่เคยได้ heartbeat เลย)
   *
   *  ⚠ ห้ามยุบ null รวมกับ false — คนละความหมายกันคนละเรื่อง อันหนึ่งคือ
   *    "รู้ว่าตาย" อีกอันคือ "เราไม่รู้" ตอนไล่หาสาเหตุต่างกันมาก
   */
  pi_status?: boolean | null;
  /** Pi กำลังยืนรอสัญญาณทริกเกอร์อยู่ไหม ณ heartbeat ล่าสุด
   *
   *  มีแค่ 2 ค่าไม่เหมือน `pi_status` — ปุ่มกดได้หรือกดไม่ได้เท่านั้น
   *  "ไม่รู้" ต้องแปลว่ากดไม่ได้ ฝั่ง backend จึงยุบให้เหลือ boolean มาแล้ว
   */
  trigger_ready?: boolean;
  /** เปิดปุ่มจำลองทริกเกอร์ไว้ไหม (ALLOW_MANUAL_TRIGGER ฝั่ง backend)
   *  ต่างจาก `trigger_ready` — ตัวนี้บอกว่า "แสดงปุ่มไหม" ไม่ใช่ "กดได้ไหม"
   */
  manual_trigger?: boolean;
}

/**
 * ข้อความบนป้ายสถานะ — **แยกจากค่าใน DB โดยตั้งใจ**
 *
 * ค่าที่เก็บจริงยังเป็น `timeout` เหมือนเดิมทุกจุด (`heartbeat_checker` เขียน,
 * query กรองด้วยค่านี้, CSS ใช้เป็นชื่อคลาส) เปลี่ยนเฉพาะสิ่งที่ตาเห็น
 * ⚠ ห้ามเปลี่ยนค่าใน DB ตาม — จะต้องไล่แก้ทั้ง `shared.py`, ข้อมูลเก่าใน
 *   ตาราง `sessions` และคลาส CSS พร้อมกัน แลกกับสิ่งที่ได้แค่คำบนจอ
 *
 * ทำไม `timeout` → **INTERRUPTED**: "TIMEOUT" บอกแค่ *กลไก* ที่ตรวจเจอ
 * (นับเวลาแล้วครบ) ไม่ได้บอกว่าเกิดอะไรกับงานที่กำลังทำอยู่ — ผู้ใช้หน้างาน
 * อ่านแล้วนึกว่า "วัดนานเกินไป" ทั้งที่ความจริงคือ **การวัดถูกตัดกลางคัน
 * และข้อมูลอาจไม่ครบ** ส่วน *สาเหตุ* ไม่ต้องยัดลงป้ายนี้ เพราะชิป
 * "Raspberry Pi 🔴 Offline" อยู่ถัดไปอีก 2 ช่องบนแถวเดียวกันอยู่แล้ว
 * (ถ้าใช้คำว่า DISCONNECTED จะกลายเป็นบอกเรื่องเดียวกันซ้ำสองที่
 *  แล้วไม่มีใครบอกว่า session ตายไปแล้ว)
 */
const STATE_LABEL: Record<string, string> = {
  idle: "IDLE",
  running: "RUNNING",
  stopped: "STOPPED",
  timeout: "INTERRUPTED",
};

/** ค่าที่ไม่รู้จัก (backend เวอร์ชันใหม่กว่า) ให้โชว์ตัวมันเองตัวใหญ่ ดีกว่าว่างเปล่า */
export const sessionStateLabel = (s: string): string =>
  STATE_LABEL[s] ?? s.toUpperCase();

// useSessionState: poll GET /api/session/state ทุก 4 วิ — TanStack Query dedupe
// ให้ตาม queryKey อยู่แล้ว เรียกจากหลาย component ก็ยิงจริงแค่ request เดียว
// (ต่างจาก vanilla ที่ index/edit ต่างคนต่าง poll กันเอง)
//
// SSE ช่วยให้อัปเดตไวขึ้นอีกที ส่วน poll เป็นตาข่ายรองรับ — SSE ไม่มี replay
// event ที่ยิงตอนสายหลุดจะหายไปเฉยๆ ต้องมีคนคอยไปถามความจริงกลับมาเป็นระยะ
export function useSessionState() {
  const q = useQuery<SessionState, ApiError>({
    queryKey: ["session-state"],
    queryFn: () => apiGet<SessionState>("/api/session/state"),
    /* ── ถามถี่ขึ้นเฉพาะตอนกำลังวัด ────────────────────────────────────────
       ค่าที่ต้องการความสดที่สุดคือ `trigger_ready` — ปุ่ม ⚡ Trigger ต้องสว่าง
       ทันทีที่ Pi ยืนรอสัญญาณ ไม่งั้นคนหน้างานจะยืนรอปุ่มโดยไม่รู้ว่าต้องรออีกนาน
       แค่ไหน (Pi ยิง heartbeat บอกทันทีที่พร้อมแล้ว ตัวที่ช้าคือฝั่งเราไม่ไปถาม)

       4 วิ ตอน idle ก็พอ เพราะสิ่งเดียวที่เปลี่ยนคือชิป PI กับป้าย DB ซึ่งช้าไป
       สองสามวินาทีไม่มีผลอะไร · ส่วนตอน running ลดเหลือ 1 วิ

       request เพิ่มขึ้น 4 เท่าเฉพาะช่วงวัด ซึ่งรับได้สบายเพราะระบบนี้มีผู้ใช้
       จริงคนเดียว (ดูสไลด์ Scope — วัด 1 ชิ้นทุก ~30 นาที)                   */
    refetchInterval: (query) =>
      query.state.data?.state === "running" ? 1000 : 4000,
    staleTime: 0,
    // ห้าม retry: เส้นนี้ถูกใช้เป็น "เครื่องวัดว่า DB ยังไหวไหม" ด้วย
    // ถ้าปล่อยให้ retry ป้ายจะขึ้น DB Offline ช้ากว่าความจริงหลายวินาที
    retry: false,
  });

  // ── แปลผลให้เป็นสิ่งที่ UI ใช้ได้ตรงๆ ────────────────────────────────────
  // 503 = backend ยังอยู่แต่ต่อ MySQL ไม่ได้ (ดู get_db ฝั่ง backend) — ไม่ใช่
  // backend ตาย ป้ายจึงต้องขึ้น "DB Offline" ไม่ใช่ "Server Offline"
  const dbOffline = q.error?.status === 503;

  // pi_status เดินทางมา 2 ทางแล้วแต่ว่า DB ไหวไหม:
  //   DB ปกติ → อยู่ใน response ปกติ
  //   DB ล่ม   → อยู่ใน body ของ 503 (backend แนบมาให้ เพราะค่านี้อยู่ใน
  //             memory ไม่พึ่ง DB จึงยังถูกต้องอยู่)
  // ต้องแยก "ไม่มีคีย์" ออกจาก "คีย์เป็น null" ให้ขาด — response ที่ไม่มีคีย์นี้
  // เลย (backend เวอร์ชันเก่า / 502 จาก proxy) ต้องได้ undefined → ไม่ทราบ
  const errBody = q.error?.body as
    | { pi_status?: boolean | null; trigger_ready?: boolean; manual_trigger?: boolean }
    | undefined;
  const piStatus: boolean | null | undefined = dbOffline
    ? errBody && "pi_status" in errBody
      ? errBody.pi_status
      : undefined
    : q.data?.pi_status;

  // trigger_ready เดินทางมาทางเดียวกับ pi_status แต่ยุบ undefined เป็น false
  // ตั้งแต่ตรงนี้ — ปุ่มมีแค่ "กดได้" กับ "กดไม่ได้" และ "ไม่รู้" ต้องเป็นกดไม่ได้
  // เสมอ ไม่งั้น backend เวอร์ชันเก่าที่ไม่มีคีย์นี้จะทำให้ปุ่มสว่างค้าง
  const triggerReady: boolean =
    (dbOffline ? errBody?.trigger_ready : q.data?.trigger_ready) ?? false;

  // default false เหมือนกัน — backend ที่ยังไม่มีคีย์นี้ = ไม่ต้องแสดงปุ่ม
  const manualTrigger: boolean =
    (dbOffline ? errBody?.manual_trigger : q.data?.manual_trigger) ?? false;

  return { ...q, dbOffline, piStatus, triggerReady, manualTrigger };
}
