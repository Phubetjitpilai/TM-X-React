import { useEffect, useRef, useState } from "react";
import { orderForDatalist } from "../utils/datalistOrder";

interface MultiSelectProps {
  label: string;
  options: string[];
  /** ค่าที่เลือกอยู่ — ควบคุมจากข้างนอกทั้งหมด (controlled component) */
  selected: string[];
  onChange: (next: string[]) => void;
  disabled?: boolean;
  /** ข้อความบอกเงื่อนไขที่ต้องทำก่อน เช่น "เลือก Package Size ก่อน" */
  hint?: string;
  /** ข้อความตอนไม่มีตัวเลือกให้เลือก — อธิบายสาเหตุได้ ไม่ใช่แค่ "ว่าง" */
  emptyText?: string;
}

/**
 * ช่องกรองแบบติ๊กเลือกได้หลายค่า — ยกมาจาก buildMulti/renderMulti ใน export.html
 *
 * ทำเป็น component กลางเพราะหน้า Export ใช้หลายช่อง (Package Size, Part Number,
 * Operator, Vendor, ...) ฝั่ง vanilla ต้องสร้าง DOM เองด้วย innerHTML + ผูก
 * onclick ผ่าน global function (multiToggle/multiAll) เพราะไม่มี component
 *
 * ⚠ "ไม่เลือกอะไรเลย" = "เอาทั้งหมด" ไม่ใช่ "ไม่เอาสักอัน" — ตรงกับพฤติกรรม
 *   ของ vanilla และของ backend ที่มองว่า filter ว่าง = ไม่กรอง ถ้าตีความสลับ
 *   ผู้ใช้จะได้ไฟล์เปล่าตอนเปิดหน้ามาครั้งแรกโดยไม่รู้ว่าทำอะไรผิด
 */
export default function MultiSelect({
  label,
  options,
  selected,
  onChange,
  disabled = false,
  hint,
  emptyText = "ไม่มีตัวเลือก",
}: MultiSelectProps) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const rootRef = useRef<HTMLDivElement>(null);

  // ปิดเมื่อคลิกที่อื่นหรือกด Escape — ผูก listener เฉพาะตอนเปิดอยู่เท่านั้น
  // จะได้ไม่มี listener ค้างอยู่ทั้งหน้าเวลามีช่องแบบนี้หลายช่อง
  // ล้างคำค้นทุกครั้งที่ปิดแผง — เปิดมารอบหน้าต้องเห็นลิสต์เต็มเสมอ ไม่งั้น
  // จะเห็นลิสต์ถูกกรองค้างจากคำที่พิมพ์ไว้เมื่อกี้แล้วนึกว่าตัวเลือกหายไป
  useEffect(() => { if (!open) setQuery(""); }, [open]);

  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("click", onClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("click", onClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  // ตัดค่าที่เลือกไว้แต่หายไปจากตัวเลือกใหม่ออก (เช่น Part Number หลังเปลี่ยน
  // Package Size) ไม่งั้นจะกรองด้วยค่าที่ผู้ใช้มองไม่เห็นแล้ว — หาสาเหตุยากมาก
  // เพราะหน้าจอบอกว่า "ทั้งหมด" แต่ผลลัพธ์กลับหายไปเฉยๆ
  useEffect(() => {
    const kept = selected.filter((v) => options.includes(v));
    if (kept.length !== selected.length) onChange(kept);
  }, [options]); // eslint-disable-line react-hooks/exhaustive-deps

  const toggle = (value: string, on: boolean) =>
    onChange(on ? [...selected, value] : selected.filter((v) => v !== value));

  /* ── ช่องพิมพ์ค้นหา ──────────────────────────────────────────────────────
     ลิสต์ Package Size / Part Number ยาวเกินกว่าจะกวาดตาหา — พิมพ์แล้วกรอง
     ให้เหลือเฉพาะที่ตรง เร็วกว่าเลื่อนหาเยอะ โดยยัง **ติ๊กได้หลายค่าเหมือนเดิม**

     ⚠ ล้างคำค้นทุกครั้งที่ปิดแผง ไม่งั้นเปิดมารอบหน้าจะเห็นลิสต์ถูกกรองค้างอยู่
       จากคำที่พิมพ์ไว้เมื่อกี้ แล้วนึกว่าตัวเลือกหายไป                        */
  const q = query.trim().toLowerCase();
  const shown = q
    ? orderForDatalist(options.filter((o) => o.toLowerCase().includes(q)), query)
    : options;

  return (
    <div className="fg">
      <label>
        {label}
        {hint && <span className="hint">{hint}</span>}
      </label>
      <div className={`ms${open ? " open" : ""}`} ref={rootRef}>
        <button
          type="button"
          className="ms-btn"
          disabled={disabled}
          onClick={(e) => { e.stopPropagation(); setOpen((v) => !v); }}
        >
          <span className={`ms-txt${selected.length === 0 ? " none" : ""}`}>
            {selected.length === 0 ? "ทั้งหมด" : selected.join(", ")}
          </span>
          {selected.length > 0 && <span className="ms-n">{selected.length}</span>}
        </button>

        <div className="ms-panel">
          {options.length === 0 ? (
            <div className="ms-empty">{emptyText}</div>
          ) : (
            <>
              <input
                className="ms-search"
                type="text"
                placeholder="พิมพ์เพื่อค้นหา…"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                /* ⚠ กัน Escape ทะลุไปหา listener ที่ปิดแผง — คนพิมพ์ผิดแล้วกด Esc
                   ตั้งใจจะล้างคำค้น ไม่ได้ตั้งใจปิดแผงทิ้งทั้งอัน */
                onKeyDown={(e) => {
                  if (e.key === "Escape" && query) { e.stopPropagation(); setQuery(""); }
                }}
              />
              <div className="ms-tools">
                {/* "เลือกทั้งหมด" = ทั้งหมดที่เห็นอยู่ตอนนี้ ไม่ใช่ทั้งลิสต์ —
                    ถ้ากรองอยู่แล้วกดปุ่มนี้ คนคาดหวังว่าได้เฉพาะที่กรองไว้ */}
                <button type="button" onClick={() => onChange([...new Set([...selected, ...shown])])}>
                  {q ? "เลือกที่เห็น" : "เลือกทั้งหมด"}
                </button>
                <button type="button" onClick={() => onChange([])}>ล้าง</button>
              </div>
              {shown.length === 0 ? (
                <div className="ms-empty">ไม่พบ "{query}"</div>
              ) : (
                shown.map((o) => (
                  <label className="ms-opt" key={o}>
                    <input
                      type="checkbox"
                      checked={selected.includes(o)}
                      onChange={(e) => toggle(o, e.target.checked)}
                    />
                    {o}
                  </label>
                ))
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
