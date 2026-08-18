import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiPost, ApiError } from "../../api/client";
import { useToast } from "../Toast";
import type { SessionState } from "../../hooks/useSessionState";

// SessionControl: การ์ดบนสุดของ Dashboard
//
// ทุกอย่างอยู่บรรทัดเดียว — ชิปที่ยังไม่มีค่าจะถูก "ซ่อนทั้งชิป" ไม่ใช่โชว์ขีดกลาง
// ไว้ แถบตอน idle จะได้ไม่รกด้วยช่องว่างเปล่า (ตรงตาม renderSessionUI ของต้นฉบับ)

interface Props {
  session: SessionState | undefined;
  /** true = ออนไลน์ · false = เงียบเกินเกณฑ์ · null/undefined = ไม่ทราบ */
  piStatus?: boolean | null;
  /** ป้าย Server เป็น db-offline อยู่ไหม — ใช้บอกเหตุผลบนปุ่ม Start */
  dbOffline?: boolean;
  /** ข้อมูลที่กรอกไว้ในฟอร์ม Part Entry (ถ้ายังไม่มี = กด Start ไม่ได้) */
  hasQueue?: boolean;
  onStart?: () => void;
  starting?: boolean;
}

export default function SessionControl({
  session, piStatus, dbOffline, hasQueue, onStart, starting,
}: Props) {
  const { show } = useToast();
  const qc = useQueryClient();
  const state = session?.state ?? "idle";
  const isRunning = state === "running";

  const stopMutation = useMutation({
    mutationFn: () => apiPost("/api/session/stop", { session_id: session?.session_id }),
    onSuccess: () => {
      show("หยุด session แล้ว");
      qc.invalidateQueries({ queryKey: ["session-state"] });
    },
    onError: (err) => show(err instanceof ApiError ? err.message : "หยุดไม่สำเร็จ"),
  });

  // ── ชิป PI — 3 สถานะไม่ใช่ 2 ────────────────────────────────────────────
  // "ไม่ทราบ" ต้องแยกจาก "ออฟไลน์" ให้ชัด อันหนึ่งคือ "รู้ว่าตาย" อีกอันคือ
  // "เราไม่มีข้อมูล" — ตอนไล่หาสาเหตุคนละเรื่องกันเลย
  //
  // ⚠ ชิปนี้ **ไม่ซ่อนตอน idle** ต่างจากชิปอื่น เพราะประโยชน์หลักคือดูก่อนกด
  //   Start ว่าเครื่องพร้อมไหม ถ้าซ่อนตอนไม่มี session ก็หมดความหมาย
  const piCls = piStatus === true ? "online" : piStatus === false ? "offline" : "unknown";
  const piText = piStatus === true ? "🟢 Online" : piStatus === false ? "🔴 Offline" : "🟡 Connecting";

  // ── ปุ่ม Start ต้องบอก "ติดอะไรอยู่" ไม่ใช่แค่กดไม่ได้เฉยๆ ─────────────
  // ไม่งั้นผู้ใช้จะนึกว่าระบบพัง แล้วไปไล่หาที่ฟอร์ม Part Entry ทั้งที่ปัญหา
  // อยู่ที่เครื่อง · เรียง DB ก่อน Pi เพราะ DB ล่มแล้วกด Start ไม่ได้แน่นอน
  // ไม่ว่า Pi จะเป็นยังไง (start_session ต้องเขียน session ลง DB ก่อน)
  const piOnline = piStatus === true;
  const canStart = !isRunning && !dbOffline && piOnline && !!hasQueue && !starting;
  let startLabel = "▶ Start";
  let startTitle = "";
  if (!isRunning && dbOffline) {
    startLabel = "▶ Start (DB Offline)";
    startTitle = "Backend ต่อฐานข้อมูลไม่ได้ — เริ่มการวัดไม่ได้เพราะต้องเขียน session ลง DB ก่อน · ตรวจว่า MySQL ทำงานอยู่ไหม";
  } else if (!isRunning && !piOnline) {
    startLabel = piStatus === false ? "▶ Start (Pi Offline)" : "▶ Start (Waiting for Pi)";
    startTitle = piStatus === false
      ? "ไม่ได้รับสัญญาณจาก Pi เกินเวลาที่กำหนด — ตรวจว่า Pi.py รันอยู่ไหม · สาย LAN"
      : "ยังไม่เคยได้รับ heartbeat จาก Pi ตั้งแต่ Backend เริ่มทำงาน — รอสักครู่ ถ้าไม่หายให้ตรวจว่า Pi.py รันอยู่ไหม";
  } else if (!isRunning && !hasQueue) {
    startLabel = "▶ Start (กด Save IPM/New/Rework ก่อน)";
    startTitle = "ยังไม่มีคิวที่จะวัด — กรอกฟอร์ม Part Entry แล้วกด Save ก่อน";
  }

  // queue_state เก็บ operator/measure_mode ของ session ที่กำลังวัด — แกะมาโชว์
  const qs = (session?.queue_state ?? null) as { operator?: string; measure_mode?: string } | null;

  return (
    <div className="card">
      <div className="card-title">Session Control</div>
      <div className="session-row">
        <div className="session-chip">
          <span className="sc-label">Status</span>
          <span className={`session-state-badge ${state}`}>{state.toUpperCase()}</span>
        </div>

        {qs?.operator && (
          <div className="session-chip">
            <span className="sc-label">Operator</span>
            <span className="sc-value">{qs.operator}</span>
          </div>
        )}
        {qs?.measure_mode && (
          <div className="session-chip">
            <span className="sc-label">Measure Type</span>
            <span className="sc-value">{qs.measure_mode}</span>
          </div>
        )}
        {session?.session_id != null && (
          <div className="session-chip">
            <span className="sc-label">Session</span>
            <span className="sc-value">{session.session_id}</span>
          </div>
        )}

        <div className="session-chip">
          <span className="sc-label">Raspberry Pi</span>
          <span className={`sc-value sc-pi ${piCls}`}>{piText}</span>
        </div>

        {/* 2 ปุ่ม เห็นทีละตัวตามสถานะ — idle → Start · running → Stop
            (Pause ถูกถอดออกทั้งระบบแล้วเพราะฝั่ง Pi ไม่เคยรองรับ) */}
        <div className="session-btns">
          {isRunning ? (
            <button type="button" className="btn-stop" disabled={stopMutation.isPending} onClick={() => stopMutation.mutate()}>
              ■ Stop
            </button>
          ) : (
            <button type="button" className="btn-start" disabled={!canStart} title={startTitle} onClick={onStart}>
              {startLabel}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
