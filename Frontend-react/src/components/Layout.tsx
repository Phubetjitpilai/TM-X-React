import { useEffect, useRef, useState } from "react";
import { NavLink, Outlet, useLocation, useSearchParams } from "react-router-dom";
import { useSSE } from "../hooks/useSSE";
import { useSessionState } from "../hooks/useSessionState";

// Layout: topbar เดียวใช้ร่วมกันทุก route แทนการ copy topbar markup ซ้ำ 4 ไฟล์
// (index/edit/export/report-template เดิม) — ใช้ CSS class จริงจาก index.css
// ที่ยกมาจาก shared.css เพื่อให้หน้าตาตรงกับต้นฉบับเป๊ะๆ ไม่ใช่แค่ "คล้ายๆ"

/* ── ป้ายสถานะรวม 2 เรื่องไว้ด้วยกัน ────────────────────────────────────────
   SSE (เบราว์เซอร์ ↔ Backend) กับ DB (Backend ↔ MySQL) — เพราะในมุมผู้ใช้
   "Backend ตอบได้แต่ทำงานไม่ได้" ก็คือใช้งานไม่ได้อยู่ดี แยกเป็น 2 ป้ายจะต้อง
   มองหลายที่และมีโอกาสขัดกันเอง

     online       SSE ต่อได้ + DB ต่อได้         ← ใช้งานได้เต็มที่
     db-offline   SSE ต่อได้ แต่ query ตอบ 503   ← เปิดเว็บได้ แต่โหลดข้อมูลไม่ขึ้น
     offline      SSE หลุด                       ← หนักสุด

   ⚠ SSE หลุดถือว่าหนักกว่าเสมอ — ห้ามให้ผล query มาลดระดับเป็น db-offline
     เพราะตอน Backend ตายสนิท query ก็ล้มเหลวเหมือนกัน แล้วจะกลายเป็นบอกว่า
     "แค่ DB ล่ม" ทั้งที่ทั้งเครื่องไม่ตอบ → ไปไล่หาสาเหตุผิดจุด             */
const BADGE: Record<string, string> = {
  online: "🟢 Server Online",
  offline: "🔴 Server Offline",
  connecting: "🟡 Server Connecting",
  "db-offline": "🟡 DB Offline",
};

const EXPORT_FORMATS = [
  { key: "csv", label: "CSV" },
  { key: "pdf", label: "PDF" },
  { key: "excel", label: "Excel" },
];

export default function Layout() {
  const sse = useSSE();
  const { dbOffline } = useSessionState();
  const location = useLocation();
  const [params] = useSearchParams();
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLSpanElement>(null);

  const status = sse !== "online" ? sse : dbOffline ? "db-offline" : "online";

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
          <NavLink to="/" end className={({ isActive }) => `topbar-link${isActive ? " active" : ""}`}>
            Home
          </NavLink>
          <NavLink to="/edit" className={({ isActive }) => `topbar-link${isActive ? " active" : ""}`}>
            Edit
          </NavLink>

          {/* Export เป็นเมนูย่อย ไม่ใช่ลิงก์ตรง — กดแล้วเลือกรูปแบบก่อน */}
          <span className={`topbar-menu${menuOpen ? " open" : ""}`} ref={menuRef}>
            <span
              className={`topbar-link${isExport ? " active" : ""}`}
              role="button"
              tabIndex={0}
              aria-haspopup="true"
              aria-expanded={menuOpen}
              onClick={(e) => { e.stopPropagation(); setMenuOpen((v) => !v); }}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setMenuOpen((v) => !v); }
              }}
            >
              Export<span className="topbar-caret">▼</span>
            </span>
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
          <span className={`station-badge ${status}`}>{BADGE[status]}</span>
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
