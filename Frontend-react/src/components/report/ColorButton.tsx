import { useEffect, useRef, useState, type ReactNode } from "react";

/**
 * ปุ่มสีแบบ Excel — พอร์ตจาก wireColorButton() ใน report-template.html
 *
 * ตัวปุ่มหลัก = ใช้ "สีล่าสุด" ทันที · ลูกศร = เปิดจานสี
 *
 * ⚠ แถบสีใต้ปุ่มคือ "สีที่ใช้ล่าสุด" ไม่ใช่สีของเซลล์ที่เลือกอยู่ (พฤติกรรม
 *   เดียวกับ Excel) — ห้ามเอาสีของเซลล์มาเขียนทับตอนคลิกเซลล์อื่น ไม่งั้น
 *   สีล่าสุดหายทุกครั้งที่ย้ายช่อง กดปุ่มซ้ำแล้วได้สีไม่ตรงที่คิด
 */

/** แต่ละคอลัมน์ = สีหลัก 1 สี + เฉดอ่อน/เข้ม 5 ระดับ (ชุดเดียวกับ Office) */
const THEME_COLORS = [
  ["#FFFFFF", "#F2F2F2", "#D9D9D9", "#BFBFBF", "#A6A6A6", "#808080"],
  ["#000000", "#808080", "#595959", "#404040", "#262626", "#0D0D0D"],
  ["#E7E6E6", "#D0CECE", "#AEAAAA", "#757171", "#3B3838", "#161616"],
  ["#44546A", "#D6DCE4", "#ADB9CA", "#8496B0", "#333F4F", "#222A35"],
  ["#4472C4", "#D9E2F3", "#B4C6E7", "#8EAADB", "#2F5597", "#1F3864"],
  ["#ED7D31", "#FBE5D5", "#F7CBAC", "#F4B183", "#C55A11", "#833C0B"],
  ["#A5A5A5", "#EDEDED", "#DBDBDB", "#C9C9C9", "#7B7B7B", "#525252"],
  ["#FFC000", "#FFF2CC", "#FFE699", "#FFD966", "#BF9000", "#7F6000"],
  ["#5B9BD5", "#DDEBF6", "#BDD7EE", "#9DC3E6", "#2E75B5", "#1F4E79"],
  ["#70AD47", "#E2EFD9", "#C5E0B3", "#A8D08D", "#538135", "#375623"],
];
const STANDARD_COLORS = [
  "#C00000", "#FF0000", "#FFC000", "#FFFF00", "#92D050",
  "#00B050", "#00B0F0", "#0070C0", "#002060", "#7030A0",
];

interface Props {
  /** fill = มีตัวเลือก "No Fill" · color = มีตัวเลือก "Automatic" */
  kind: "fill" | "color";
  title: string;
  glyph: ReactNode;
  initial: string;
  /** hex = ลงสีนั้น · null = ล้างสีกลับเป็นค่าเริ่มต้น */
  onPick: (hex: string | null) => void;
}

export default function ColorButton({ kind, title, glyph, initial, onPick }: Props) {
  const [last, setLast] = useState(initial);
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLSpanElement>(null);
  const pickerRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => { if (!wrapRef.current?.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("click", close);
    return () => document.removeEventListener("click", close);
  }, [open]);

  const use = (hex: string | null) => {
    if (hex) setLast(hex);
    onPick(hex);
  };

  const Swatch = ({ hex }: { hex: string }) => (
    <button
      type="button" className="sw" style={{ background: hex }} title={hex}
      onClick={() => { setOpen(false); use(hex); }}
    />
  );

  return (
    <span className="colorbtn" ref={wrapRef}>
      <span className="main" title={title} onClick={() => use(last)}>
        {glyph}
        <span className="bar" style={{ background: last }} />
      </span>
      <button type="button" className="car" title={`เลือก${kind === "fill" ? "สีพื้น" : "สีตัวอักษร"}`}
        onClick={(e) => { e.stopPropagation(); setOpen((v) => !v); }}>▼</button>
      <input
        ref={pickerRef} type="color" value={last}
        onChange={(e) => use(e.target.value)}
      />
      {open && (
        <div className="cpanel open">
          {kind === "color" && (
            <>
              <div className="crow" onClick={() => { setOpen(false); use(null); }}>
                <span className="box" style={{ background: "#000" }} />Automatic
              </div>
              <hr />
            </>
          )}
          <div className="cpl">Theme Colors</div>
          <div className="cgrid">{THEME_COLORS.map((col) => <Swatch key={col[0]} hex={col[0]} />)}</div>
          <div className="cgrid tint">
            {[1, 2, 3, 4, 5].map((i) => THEME_COLORS.map((col) => <Swatch key={`${i}-${col[0]}`} hex={col[i]} />))}
          </div>
          <div className="cpl" style={{ marginTop: ".55rem" }}>Standard Colors</div>
          <div className="cgrid">{STANDARD_COLORS.map((h) => <Swatch key={h} hex={h} />)}</div>
          {kind === "fill" && (
            <>
              <hr />
              <div className="crow" onClick={() => { setOpen(false); use(null); }}>
                <span className="box" style={{ background: "#fff" }} />No Fill
              </div>
            </>
          )}
          <hr />
          <div className="crow" onClick={() => { setOpen(false); pickerRef.current?.click(); }}>
            <span className="box" style={{ background: "linear-gradient(135deg,#e74c3c,#f1c40f,#2ecc71,#3498db)" }} />
            More Colors…
          </div>
        </div>
      )}
    </span>
  );
}
