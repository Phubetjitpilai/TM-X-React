import { useEffect, useRef, useState } from "react";

/**
 * Dropdown เลือกได้หลายค่า สำหรับใช้เป็น **ช่องหนึ่งในแถวของตาราง**
 * ช่องปิดโชว์สรุป กดแล้วกางเป็นรายการติ๊กถูก
 *
 * ⚠ **คนละตัวกับ `MultiSelect.tsx`** ที่หน้า Export ใช้ — ตัวนั้นเป็นช่อง *กรอง*
 *   ที่มี label ของตัวเอง ปุ่ม "เลือกทั้งหมด/ล้าง" และตีความ "ไม่เลือกอะไรเลย"
 *   ว่า **เอาทั้งหมด** ส่วนตัวนี้เป็นช่อง *กรอกข้อมูล* ที่ "ไม่เลือกเลย" แปลว่า
 *   **ไม่มีเครื่องผูกอยู่จริงๆ** — ความหมายกลับกันคนละเรื่อง จึงห้ามยุบรวมกัน
 *   (คลาส CSS ก็แยกกัน: ตัวนี้ `msc-` ตัวนั้น `ms-`)
 *
 * ⚠ **ห้ามเปลี่ยนไปใช้ `<select multiple>` ของ HTML** ถึงจะเขียนสั้นกว่ามาก:
 *   เบราว์เซอร์วาดมันเป็นกล่องรายการที่กางค้างตลอด ไม่ใช่ dropdown (กินความสูง
 *   3-4 บรรทัดในทุกแถว) และ**ต้อง Ctrl+คลิกถึงจะเลือกหลายอันได้ — คลิกธรรมดา
 *   ที่ตัวที่สองจะล้างตัวแรกทิ้ง** ซึ่งคนหน้างานไม่มีทางเดาถูก
 */
export default function MultiSelectCell({
  options,
  value,
  onChange,
  disabled = false,
  placeholder = "ยังไม่ได้เลือก",
  minWidth = "170px",
}: {
  options: string[];
  value: string[];
  onChange: (next: string[]) => void;
  disabled?: boolean;
  /** ข้อความตอนยังไม่ได้เลือกอะไรเลย — แสดงโทนเตือน ไม่ใช่สีปกติ */
  placeholder?: string;
  minWidth?: string;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  /* ปิดเมื่อคลิกที่อื่นหรือกด Escape
     ⚠ ต้อง cleanup ทั้งคู่ ไม่งั้น listener ค้างสะสมทุกครั้งที่เปิด-ปิด
       (ตารางมีหลายแถว ยิ่งสะสมเร็ว) */
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

  function toggle(name: string) {
    // เรียงผลลัพธ์เสมอ — ลำดับที่ผู้ใช้กดไม่ควรมีผลกับสิ่งที่ส่งไป backend
    // ไม่งั้นประวัติการแก้ไขจะขึ้นว่า "แก้ไข" ทั้งที่ชุดเดิมเป๊ะ แค่สลับที่กัน
    const next = value.includes(name)
      ? value.filter((v) => v !== name)
      : [...value, name].sort();
    onChange(next);
  }

  const empty = value.length === 0;

  return (
    <div className="msc" ref={rootRef} style={{ minWidth }}>
      <button
        type="button"
        className={`msc-toggle${open ? " open" : ""}${empty ? " empty" : ""}`}
        disabled={disabled}
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={(e) => { e.stopPropagation(); setOpen((v) => !v); }}
      >
        <span className="msc-summary">{empty ? placeholder : value.join(", ")}</span>
        <span className="msc-caret">{open ? "▴" : "▾"}</span>
      </button>

      {open && (
        <div className="msc-panel" role="listbox">
          {options.length === 0 ? (
            <div className="msc-empty">ไม่มีตัวเลือก</div>
          ) : (
            options.map((o) => (
              /* ⚠ ต้องเป็น <label> ครอบ checkbox — คลิกที่ตัวหนังสือก็ติ๊กได้
                 ถ้าใช้ <div> ต้องคลิกโดนกล่องเล็กๆ เท่านั้นถึงจะติด */
              <label key={o} className={`msc-item${value.includes(o) ? " on" : ""}`}>
                <input
                  type="checkbox"
                  checked={value.includes(o)}
                  onChange={() => toggle(o)}
                />
                {o}
              </label>
            ))
          )}
        </div>
      )}
    </div>
  );
}
