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
}

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
    refetchInterval: 4000,
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
  const errBody = q.error?.body as { pi_status?: boolean | null } | undefined;
  const piStatus: boolean | null | undefined = dbOffline
    ? errBody && "pi_status" in errBody
      ? errBody.pi_status
      : undefined
    : q.data?.pi_status;

  return { ...q, dbOffline, piStatus };
}
