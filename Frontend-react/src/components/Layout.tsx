import { useEffect, useRef, useState } from "react";
import { NavLink, Outlet, useLocation, useSearchParams } from "react-router-dom";
import { useSSE } from "../hooks/useSSE";
import { useSessionState } from "../hooks/useSessionState";

// Layout: topbar เดียวใช้ร่วมกันทุก route แทนการ copy topbar markup ซ้ำ 4 ไฟล์
// (index/edit/export/report-template เดิม) — ใช้ CSS class จริงจาก index.css
// ที่ยกมาจาก shared.css เพื่อให้หน้าตาตรงกับต้นฉบับเป๊ะๆ ไม่ใช่แค่ "คล้ายๆ"

/* ── สถานะบนแถบบน: แยกเป็น 2 ตัว Server / Database ─────────────────────────
   ของเดิมยุบทั้งสองเรื่องเป็นป้ายเดียว 4 ค่า (online / db-offline / offline /
   connecting) ด้วยเหตุผลว่า "ผู้ใช้ไม่ต้องมองหลายที่" — แต่มันแลกมาด้วย
   ปัญหาที่คอมเมนต์เดิมเองก็เตือนไว้: ตอน Backend ตายสนิท query ก็ล้มเหลว
   เหมือน DB ล่ม ป้ายเดียวจึง **พูดความจริงไม่ได้** ต้องเลือกข้างว่าจะโทษใคร

   พอแยกเป็น 2 ตัว ปัญหานั้นหายไปเอง เพราะพูดตรงๆ ได้ว่า "Server ตาย ส่วน DB
   ไม่ทราบเพราะถามไม่ได้" ซึ่งเป็นสถานะที่ถูกต้องจริงๆ

     Server    online / connecting / offline   ← เบราว์เซอร์ ↔ Backend
     Database  online / offline / unknown      ← Backend ↔ MySQL

   ⚠ `unknown` ห้ามวาดเป็นสีแดง — "ถามไม่ได้" ไม่เท่ากับ "พัง" ถ้าทำเป็นแดง
     คนจะวิ่งไปรีสตาร์ต MySQL ทั้งที่ตัวที่ตายจริงคือ uvicorn

   ⚠ Database ที่ปกติ **ไม่แสดงอะไรเลย** (เงียบ = ปกติ) — MySQL หน้างานลง
     เป็น Windows Service อยู่บนเครื่องเดียวกับ backend ปกติจึงต่อติดแทบ
     ตลอดเวลา ป้ายเขียวที่ขึ้นทุกวันคือป้ายที่ไม่มีใครมอง พอถึงวันที่มัน
     ผิดปกติจริงตาก็ข้ามไปแล้ว                                              */
type ServerState = "online" | "connecting" | "offline";
type DbState = "online" | "offline" | "unknown";

const EXPORT_FORMATS = [
  { key: "csv", label: "CSV" },
  { key: "pdf", label: "PDF" },
  { key: "excel", label: "Excel" },
];

export default function Layout() {
  const sse = useSSE();
  const { dbOffline, isSuccess, isError } = useSessionState();
  const location = useLocation();
  const [params] = useSearchParams();
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLSpanElement>(null);

  /* ── ป้ายสถานะ: ตัดสินจาก 2 แหล่ง ไม่ใช่ SSE อย่างเดียว ────────────────────
     ของเดิม `sse !== "online" ? sse : ...` มีปัญหา 2 ข้อที่เจอจริง:

     1. **ขึ้น "Server Connecting" นาน** — ป้ายรอ `EventSource.onopen` อย่างเดียว
        แต่ตอนเปิดหน้า แอปยิง request พรวดเดียวเป็นสิบตัว (parts ทีละหน้า ·
        measurements · lookup 5 ตัว · session/state) เบราว์เซอร์จำกัด 6
        connection ต่อโดเมน สาย SSE เลยต้อง **ต่อคิว** รอช่องว่าง ทั้งที่
        backend ตอบ /api/session/state ได้ตั้งแต่วินาทีแรกแล้ว
        → ถ้า poll สำเร็จ ก็คือ backend ตอบได้จริง ไม่ต้องรอ SSE

     2. **กะพริบ 🟡 DB Offline ↔ 🟢 Server Online ตอน DB ล่ม** — เดิมอ่านว่า
        "ไม่ใช่ 503 = ปกติ" ซึ่งผิด เพราะ error ที่ไม่มี HTTP status (fetch
        ล้มระดับเครือข่าย / proxy ตัด / 500 ตอน DB ตายกลาง query) จะได้
        `dbOffline === false` แล้วป้ายเด้งกลับเป็นเขียวทั้งที่ยังใช้งานไม่ได้
        → ตอนนี้ "เขียว" ต้องมาจาก **poll สำเร็จจริง** เท่านั้น
          ห้ามอนุมานจาก "ไม่มี error"

     3. **ลำดับความสำคัญเดิมกลับหัว** — ของเดิมให้ `sse` มาก่อน `poll` ทั้งสองทาง
        (`sse === "offline"` เป็นเงื่อนไขแรกสุด และ `sse === "online"` เป็นตัว
        ตัดสินว่าเป็น db-offline) ซึ่งผิดทั้งคู่ เพราะ **สองตัวนี้ไม่ได้รู้เรื่อง
        พร้อมกัน**:

            poll  = ไปเคาะจริงทุก 4 วิ            → รู้ทันทีที่ backend ตาย
            sse   = ค่าที่ค้างไว้ รอ event มาปลุก → รู้ช้ากว่าได้ถึง 25 วิ
                    (backend ส่ง keep-alive ห่าง 25 วิ — session.py `timeout=25`
                     ถ้าเบราว์เซอร์ยังไม่ได้ลองอ่านสาย ก็ยังไม่รู้ว่าปลายทางตาย)

        อาการที่เกิดจริง 2 แบบ:
          · ปิด backend → ขึ้น "Server online + Database offline" ทั้งที่ MySQL
            ไม่เกี่ยวอะไรเลย (`sse` ยังค้างว่า online → เข้าเส้น db-offline
            โดยไม่ได้ดู status code ด้วยซ้ำ เพราะ `||` ลัดวงจรไปก่อน)
          · เปิด backend กลับ → ยังค้าง "Server offline" ทั้งที่ poll ผ่านแล้ว

     กติกาใหม่: **เชื่อ poll เสมอ · `sse` เป็นแค่ตัวเสริมตอนยังไม่เคย poll สำเร็จ** */
  const server: ServerState =
    isSuccess ? "online"              // poll ผ่าน = backend ตอบได้ จบ ไม่ต้องดูอย่างอื่น
    : dbOffline ? "online"            // 503 = backend ตอบได้ แค่ต่อ MySQL ไม่ติด
    : isError ? "offline"             // พังแบบอื่น (500 จาก proxy / เน็ตหลุด) = ไม่ตอบ
    : sse === "offline" ? "offline"   // ยังไม่เคย poll สำเร็จ แถม SSE ก็พัง
    : "connecting";

  /* DB สรุปจาก status code เท่านั้น — 503 คือคำตอบจากปาก backend เองว่าต่อ
     MySQL ไม่ได้ ส่วน error อื่นแปลว่า "เราถามไม่ถึง" ไม่ใช่ "DB พัง"

     ⚠ `unknown` ห้ามวาดเป็นสีแดง — ถ้าทำเป็นแดง คนจะวิ่งไปรีสตาร์ต MySQL
       ทั้งที่ตัวที่ตายจริงคือ uvicorn                                    */
  const db: DbState =
    dbOffline ? "offline"
    : isSuccess ? "online"
    : "unknown";

  // report-template ถือเป็นส่วนหนึ่งของ Export (เปิดต่อจากขั้นที่ 1)
  const isExport =
    location.pathname.startsWith("/export") || location.pathname.startsWith("/report-template");

  // ⚠ ชื่อบนแถบเป็น "TM-X Control System" คงที่ทุกหน้า ตรงตาม vanilla ทั้ง 4 ไฟล์
  //   (index/edit/export/report-template เขียนเหมือนกันหมด) — ไม่เปลี่ยนตามหน้า
  //   เพราะตัวบอกว่าอยู่หน้าไหนคือเมนูที่ถูกไฮไลต์ ไม่ใช่ชื่อบนหัว
  //   ของเดิมฝั่ง React เปลี่ยนชื่อตามหน้า ทำให้ความกว้างฝั่งซ้ายขยับไปมา
  //   แล้วเมนูกลางเลื่อนตามทุกครั้งที่สลับหน้า

  // ปิดเมนูเมื่อคลิกที่อื่นหรือกด Escape — ต้อง cleanup ทั้งคู่ ไม่งั้น listener
  // ค้างสะสมทุกครั้งที่ re-render
  useEffect(() => {
    if (!menuOpen) return;
    const onClick = (e: MouseEvent) => {
      if (!menuRef.current?.contains(e.target as Node)) setMenuOpen(false);
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setMenuOpen(false); };
    document.addEventListener("click", onClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("click", onClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [menuOpen]);

  // ล็อกทั้งหน้าเฉพาะ Edit/Export — หน้า Home ไม่ล็อกเพราะโอเปอเรเตอร์ต้องดู
  // Live Telemetry ระหว่างวัดต่อไปได้ (ปุ่มที่เขียน DB อย่าง Start ถูกล็อก
  // แยกอยู่แล้วใน SessionControl)
  const lockPage = dbOffline && location.pathname !== "/";

  return (
    <>
      <header className="topbar">
        <div className="topbar-left">
          <div className="topbar-brand">
            {/* ไฟล์อยู่ที่ public/assets — ถ้าหายไป onError ซ่อน <img> ให้เอง
                แถบบนจะได้ไม่พังและไม่ขึ้นไอคอนรูปแตก */}
            <img
              className="topbar-logo"
              src="/assets/ADI-LOGO.svg"
              alt="Analog Devices"
              onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = "none"; }}
            />
            <div className="topbar-title">
              TM-X <span>Control System</span>
            </div>
          </div>
        </div>

        <nav className="topbar-nav">
          {/* ⚠ ชื่อเมนูเป็น "Measure" แต่ route ยังเป็น "/" เหมือนเดิม — เปลี่ยนแค่
              ข้อความที่ผู้ใช้เห็น ให้เข้าชุดกับ Edit/Export ที่เป็นคำกริยาทั้งคู่
              (ห้ามเปลี่ยน `to="/"` เป็น "/measure" เพราะจะพัง bookmark เดิม
              และ StaticFiles ตอน deploy ต้องมี fallback ให้ path ใหม่ด้วย) */}
          <NavLink to="/" end className={({ isActive }) => `topbar-link${isActive ? " active" : ""}`}>
            Measure
          </NavLink>
          <NavLink to="/edit" className={({ isActive }) => `topbar-link${isActive ? " active" : ""}`}>
            Edit
          </NavLink>

          {/* Export เป็นเมนูย่อย ไม่ใช่ลิงก์ตรง — กดแล้วเลือกรูปแบบก่อน */}
          <span className={`topbar-menu${menuOpen ? " open" : ""}`} ref={menuRef}>
            {/* ⚠ ต้องเป็น <button> จริง ห้ามใช้ <span role="button"> (ต้นฉบับ vanilla
                เขียนแบบนั้น เพราะสมัยนั้นสร้าง markup ด้วย innerHTML)

                <span> คือ "ข้อความธรรมดา" — ลากคลุมได้ ดับเบิลคลิกเลือกคำได้
                และพอใส่ tabIndex ให้โฟกัสได้ด้วย เบราว์เซอร์จะวาง **เคอร์เซอร์
                ข้อความ (คาเร็ต)** ลงไปกลางคำว่า "Export" ทำให้หน้าตาเหมือน
                ช่องพิมพ์ข้อความทั้งที่เป็นปุ่ม

                <button> ได้มาให้ฟรีทั้งหมด: กด Enter/Space ได้เอง · เลือก
                ข้อความไม่ได้ · โฟกัสได้โดยไม่ต้องใส่ tabIndex · screen reader
                อ่านว่าเป็นปุ่มโดยไม่ต้องประกาศ role                        */}
            <button
              type="button"
              className={`topbar-link${isExport ? " active" : ""}`}
              aria-haspopup="true"
              aria-expanded={menuOpen}
              onClick={(e) => { e.stopPropagation(); setMenuOpen((v) => !v); }}
            >
              Export<span className="topbar-caret">▼</span>
            </button>
            <span className="topbar-dropdown">
              {EXPORT_FORMATS.map((f) => (
                <NavLink
                  key={f.key}
                  to={`/export?format=${f.key}`}
                  /* ⚠ ต้องใช้ className แบบ "ฟังก์ชัน" เท่านั้น ห้ามส่งเป็น string
                     หรือ undefined — NavLink จะเติมคลาส `active` ให้เองอัตโนมัติ
                     และมันดูแค่ **pathname** ไม่ดู query string ทั้ง 3 ตัวชี้ไป
                     `/export` เหมือนกันหมด จึงติดไฟพร้อมกันทั้ง CSV/PDF/Excel
                     แบบฟังก์ชันคือค่าที่คืนถูกใช้ตรง ๆ ไม่มีการเติมอะไรให้ */
                  className={() =>
                    isExport && (params.get("format") ?? "csv") === f.key ? "active" : ""
                  }
                  onClick={() => setMenuOpen(false)}
                >
                  {f.label}
                </NavLink>
              ))}
            </span>
          </span>
        </nav>

        <div className="topbar-right">
          {/* aria-live: ให้ screen reader ประกาศเองเมื่อสถานะเปลี่ยน โดยไม่ต้อง
              ให้ผู้ใช้เลื่อนไปหา — "polite" คือรอจนพูดประโยคปัจจุบันจบก่อน */}
          <span className="station-status" aria-live="polite">
            <span className={`station-badge ${server}`}>Server {server}</span>

            {/* Database: เงียบตอนปกติ โผล่เฉพาะตอนล่มหรือตอนถามไม่ได้ */}
            {db === "offline" && <span className="station-badge db-offline">Database offline</span>}
            {db === "unknown" && server === "offline" && (
              <span className="station-badge unknown">Database unknown</span>
            )}
          </span>
        </div>
      </header>

      {/* ปิดการใช้งานทั้งบล็อกด้วย <fieldset disabled> — ปุ่ม/ช่องกรอกทุกตัว
          ข้างในถูกปิดหมดโดยอัตโนมัติ รวมถึงตัวที่ render ขึ้นมาทีหลังด้วย
          (ฝั่ง vanilla ต้องใช้ MutationObserver ไล่ปิดเอง เพราะไม่มีอะไร
          ครอบแบบนี้ให้) · เมนูบนอยู่นอก fieldset จึงยังกดออกจากหน้าได้ */}
      {lockPage && (
        <div className="db-lock-banner">
          ⛔ ต่อฐานข้อมูลไม่ได้ — ดูข้อมูลเดิมได้ แต่บันทึก/แก้ไข/ลบไม่ได้จนกว่าจะเชื่อมต่อได้อีกครั้ง
        </div>
      )}
      <fieldset className="page-lock" disabled={lockPage}>
        <Outlet />
      </fieldset>
    </>
  );
}
