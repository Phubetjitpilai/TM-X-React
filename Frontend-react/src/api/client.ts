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
