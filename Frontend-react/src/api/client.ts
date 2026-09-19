// ตัว fetch กลางที่ทุก hook/page เรียกใช้ — ใช้ relative path ("/api/...") เสมอ
// ไม่ hardcode host เพราะ:
//   - ตอน dev: Vite proxy (ดู vite.config.ts) ส่ง /api/* ไปที่ backend
//     (localhost:8000) ให้อัตโนมัติ
//   - ตอน production: main.py เสิร์ฟทั้งไฟล์ build ของ React และ API จาก
//     origin เดียวกัน (ดู CLAUDE.md หัวข้อ Frontend Framework Migration)
//     relative path เลยใช้ได้ตรงๆ โดยไม่ต้องรู้ IP/port ของเครื่อง server เลย

export class ApiError extends Error {
  status: number;
  /** body ดิบที่ backend ส่งมากับ error — เก็บไว้ทั้งก้อน ไม่ใช่แค่ detail
   *
   *  จำเป็นเพราะ 503 ของ /api/session/state แนบข้อมูลที่ยังใช้ได้มาด้วย:
   *      {"detail": "...", "db": false, "pi_status": true}
   *  `pi_status` อยู่ใน memory ของ backend ไม่พึ่ง DB จึงยังถูกต้องอยู่แม้
   *  MySQL ดับ — ถ้าโยนทิ้งไปเหลือแค่ข้อความ ชิป Pi จะกลายเป็น "ไม่ทราบ"
   *  ทั้งที่ backend ตอบได้ว่า Pi ยังมีชีวิตอยู่
   */
  body?: unknown;
  constructor(message: string, status: number, body?: unknown) {
    super(message);
    this.status = status;
    this.body = body;
  }
}

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    // backend ส่ง error กลับมาเป็น {"detail": "..."} เสมอ (FastAPI HTTPException
    // แบบมาตรฐาน) — ดึงข้อความนั้นมาแสดงให้ผู้ใช้อ่านรู้เรื่อง แทนที่จะโชว์
    // แค่ "Request failed"
    let detail = res.statusText;
    let body: unknown;
    try {
      body = await res.json();
      const d = (body as { detail?: string })?.detail;
      if (d) detail = d;
    } catch {
      // response ไม่ใช่ JSON (เช่น 500 ดิบๆ) — ใช้ statusText ต่อไป
    }
    throw new ApiError(detail, res.status, body);
  }
  return res.json() as Promise<T>;
}

export async function apiGet<T>(path: string, params?: Record<string, string | number | undefined>): Promise<T> {
  const qs = params
    ? "?" +
      new URLSearchParams(
        Object.entries(params)
          .filter(([, v]) => v !== undefined && v !== "")
          .map(([k, v]) => [k, String(v)]),
      ).toString()
    : "";
  const res = await fetch(`${path}${qs}`);
  return handleResponse<T>(res);
}

/** นอนรอ `ms` — ตื่นทันทีถ้า `signal` ถูก abort ระหว่างนั้น
 *
 *  ⚠ ต้องตื่นเองได้ ห้ามปล่อยให้ timer เดินจนครบ — ตอนผู้ใช้สลับหน้าไปแล้ว
 *    ถ้ายังค้างอยู่ 8 วิ แล้วค่อยไปยิง request ต่อ จะเสียเปล่าและมีโอกาส
 *    setState ใส่ component ที่ unmount ไปแล้ว
 */
function sleepAbortable(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    const timer = setTimeout(resolve, ms);
    signal?.addEventListener(
      "abort",
      () => { clearTimeout(timer); resolve(); },
      { once: true },
    );
  });
}

export interface GetRetryOptions {
  /** ลองกี่ครั้ง — **ค่าเริ่มต้นคือไม่จำกัด** หยุดเมื่อสำเร็จหรือถูก abort เท่านั้น */
  tries?: number;
  /** ใช้หยุดการลองเมื่อ component unmount (ดูตัวอย่างใน DashboardPage) */
  signal?: AbortSignal;
  /** เรียกทุกครั้งที่ยิงแล้วพลาด — ใช้ขึ้นข้อความเตือนทันทีโดยไม่ต้องรอผลสุดท้าย */
  onFail?: (attempt: number) => void;
}

/** ยิง GET ที่คืนลิสต์ **แล้วลองใหม่จนกว่าจะได้** — คืน `null` เฉพาะตอนถูก abort
 *  (หรือครบ `tries` ถ้าผู้เรียกกำหนดเพดานไว้เอง)
 *
 *  ใช้กับ **ข้อมูลตั้งต้นที่โหลดตอนเปิดหน้า** (dropdown ของ operator / vendor /
 *  package size ฯลฯ) ซึ่งมักถูกยิงพอดีกับช่วงที่ MySQL ยังบูตไม่เสร็จหลังรีสตาร์ท
 *
 *  ⚠ **คืน `null` ไม่ใช่ `[]` โดยตั้งใจ** — ผู้เรียกต้องแยก "โหลดไม่สำเร็จ" ออก
 *    จาก "ตารางว่างจริง" ให้ได้ · ของเดิมเขียน `.catch(() => [])` ซึ่งยุบสอง
 *    อย่างนี้เป็นอันเดียวกัน ผลคือ dropdown ว่างเปล่าโดยไม่มีอะไรบอกว่าผิดปกติ
 *    แล้วผู้ใช้เข้าใจว่า "ระบบไม่มีข้อมูลนี้" ทั้งที่จริงคือ "ถามไม่ติด"
 *
 *  ⚠ **ห้ามใช้กับ endpoint ที่เปลี่ยนข้อมูล** — ลองซ้ำ POST/PATCH = ทำซ้ำของจริง
 *
 *  ⚠ **ไม่จำกัดจำนวนครั้ง จึงต้องส่ง `signal` มาด้วยเสมอ** ไม่งั้นลูปจะเดินต่อ
 *    หลังผู้ใช้สลับหน้าไปแล้ว กินทรัพยากรทิ้งไว้ตลอดอายุแท็บ
 *
 *  หน่วง 1 → 2 → 4 → 8 → 8 → 8 ... วิ (ชนเพดาน 8 วิแล้วคงที่) = ยิงประมาณ
 *  นาทีละ 7 ครั้งตอนรอยาว ซึ่งบน LAN ไม่มีนัยสำคัญ
 */
export async function apiGetRetry<T>(
  path: string,
  opts: GetRetryOptions = {},
): Promise<T[] | null> {
  const { tries = Infinity, signal, onFail } = opts;
  for (let i = 0; i < tries; i++) {
    if (signal?.aborted) return null;
    try {
      return await apiGet<T[]>(path);
    } catch {
      onFail?.(i + 1);
      if (signal?.aborted || i === tries - 1) return null;
      await sleepAbortable(Math.min(1000 * 2 ** i, 8000), signal);
    }
  }
  return null;
}

export async function apiPost<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  return handleResponse<T>(res);
}

export async function apiPatch<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(path, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return handleResponse<T>(res);
}

export async function apiDelete<T>(path: string): Promise<T> {
  const res = await fetch(path, { method: "DELETE" });
  return handleResponse<T>(res);
}
