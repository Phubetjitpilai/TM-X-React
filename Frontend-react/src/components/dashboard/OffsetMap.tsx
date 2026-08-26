/**
 * OffsetMap — ผังบอกว่าชิ้นงานเบียดไปทางไหนและไกลแค่ไหน
 *
 * กรอบนอก = socket พร้อม contact pin · กรอบใน = ชิ้นงาน · วงกลมกลวง = จุดกึ่งกลาง
 * ตามสเปค · จุดทึบ = ตำแหน่งจริง · วงประ = เขตที่ยังรับได้ (รัศมี = offset_tol)
 *
 * ╔═══ ทำไมต้องขยายภาพ ═══════════════════════════════════════════════════╗
 * offset จริงราว 0.018 mm บนชิ้นงาน 5 mm = **0.36%** ถ้าวาดตามอัตราส่วนจริง
 * จุดกับวงกลมจะซ้อนกันสนิท มองไม่ออกเลยว่าเยื้องไปทางไหน
 *
 * จึงสเกลด้วย `offset_tol` แทน — ระยะที่เท่ากับเพดานพอดีไปอยู่ที่ขอบวงประเสมอ
 * ไม่ว่า ALPL นั้นจะตั้ง tolerance ไว้เท่าไร "ใกล้ขอบ = ใกล้หลุด" จึงอ่านได้
 * เหมือนกันทุกแถว เทียบข้ามชิ้นงานได้ตรง ๆ
 * ╚═══════════════════════════════════════════════════════════════════════╝
 *
 * ⚠ ทิศมาจาก `posCode` ที่ backend คำนวณ **ไม่ได้เดาจากเครื่องหมายของตัวเลข**
 *   เพราะ offset_opx/offset_opy ที่ TM-X ส่งมาเป็น "ขนาด" ไม่ใช่พิกัดมีทิศ
 *   (ดู `_get_min_position_label` — มันดูว่ามุมไหนแคบที่สุด แล้วสรุปเป็นทิศ)
 */

import type { CSSProperties } from "react";

/** เวกเตอร์ทิศของแต่ละรหัส — y เป็นบวกลงล่างตามระบบพิกัดของ SVG */
const DIRS: Record<string, { ux: number; uy: number; th: string }> = {
  "TOP":          { ux:  0,     uy: -1,     th: "บน" },
  "BOTTOM":       { ux:  0,     uy:  1,     th: "ล่าง" },
  "LEFT":         { ux: -1,     uy:  0,     th: "ซ้าย" },
  "RIGHT":        { ux:  1,     uy:  0,     th: "ขวา" },
  "TOP LEFT":     { ux: -0.707, uy: -0.707, th: "บนซ้าย" },
  "TOP RIGHT":    { ux:  0.707, uy: -0.707, th: "บนขวา" },
  "BOTTOM LEFT":  { ux: -0.707, uy:  0.707, th: "ล่างซ้าย" },
  "BOTTOM RIGHT": { ux:  0.707, uy:  0.707, th: "ล่างขวา" },
  "CENTER":       { ux:  0,     uy:  0,     th: "ตรงกลาง" },
};

const fmt = (v?: number | null) =>
  v != null && !isNaN(Number(v)) ? Math.abs(Number(v)).toFixed(3) : "—";

interface Props {
  offsetX?: number | null;
  offsetY?: number | null;
  /** รหัส 9 ค่าจาก backend เช่น "TOP RIGHT" — ดู _get_min_position_label */
  posCode?: string | null;
  offsetTol?: number | null;
  measureType?: string | null;
  /** ชื่อการ์ด — ใส่แล้วป้าย OK/NG จะย้ายขึ้นไปอยู่บรรทัดเดียวกับชื่อ
   *  (Live Telemetry ใช้ "Offset Opening" · ReportModal ไม่ต้องใส่) */
  title?: string;
  /** true = ย่อเหลือแต่ผัง ไม่มีตัวเลข (ใช้ในคอลัมน์ตาราง) */
  compact?: boolean;
}

export default function OffsetMap({
  offsetX, offsetY, posCode, offsetTol, measureType, title, compact = false,
}: Props) {
  // โหมด IPM ไม่เอา offset มาตัดสิน OK/NG เลย (ดู _offset_limit ฝั่ง backend)
  // ค่ายังอยู่ใน DB ครบ ดูได้จาก Export/Power BI แค่ไม่เอามารกหน้าจอที่คนหน้า
  // เครื่องใช้ตัดสินใจ
  if ((measureType ?? "").toUpperCase() === "IPM") return null;

  const hasValue = offsetX != null && offsetY != null;
  const dir = DIRS[(posCode ?? "").toUpperCase().trim()] ?? null;
  const tol = offsetTol != null && Number(offsetTol) > 0 ? Number(offsetTol) : null;

  // ── เรขาคณิตของผัง (viewBox 120×120) ──────────────────────────────────
  const C = 60;        // จุดกึ่งกลาง
  const R_MIN = 7;     // ระยะขั้นต่ำเมื่อ "เยื้องแต่น้อยมาก" — ดูข้างล่าง
  const R_TOL = 17;    // รัศมีวงประ = ระยะที่เท่ากับ offset_tol พอดี
  const R_MAX = 34;    // ไกลสุดที่ยอมให้จุดออกไป — เกินกว่านี้ตรึงไว้ที่นี่

  const mag = hasValue ? Math.hypot(Number(offsetX), Number(offsetY)) : 0;
  const ratio = tol ? mag / tol : 0.5;

  // ╔═══ ทำไมไม่ใช้ `ratio × R_TOL` ตรง ๆ ══════════════════════════════════╗
  // สัดส่วนตรง ๆ ทำให้ชิ้นที่เยื้องน้อย (0.002 จากเพดาน 0.030 = 9%) ขยับแค่
  // **1.6 px** — ตามองไม่เห็น กรอบในดูเหมือนอยู่กลางเป๊ะ แยกไม่ออกจาก CENTER
  // ทั้งที่มันเบียดไปทางหนึ่งจริง ๆ ซึ่งเป็นข้อมูลชิ้นเดียวที่ผังนี้มีไว้บอก
  //
  // จึงบีบช่วง 0–100% ของเพดานให้ไปอยู่ที่ R_MIN–R_TOL แทน 0–R_TOL
  // "เยื้องนิดเดียว" จึงยังเห็นทิศ ส่วน "ชนขอบวงประ = ชนเพดานพอดี" ยังจริงอยู่
  //
  // ⚠ แลกมาด้วยการที่ระยะบนภาพ **ไม่เป็นสัดส่วนตรงกับตัวเลข** — อ่านว่า
  //   "เบียดทางไหน + ใกล้หลุดแค่ไหน" ได้ แต่อ่านว่า "เยื้องกี่เท่าของอีกชิ้น"
  //   ไม่ได้ · ตัวเลข OP-X/OP-Y ข้าง ๆ ทำหน้าที่นั้นอยู่แล้ว
  //
  // CENTER (dir.ux/uy = 0) ไม่ได้รับผลกระทบ — คูณด้วยศูนย์ยังอยู่กลางเหมือนเดิม
  // ╚═══════════════════════════════════════════════════════════════════════╝
  const dist = !dir ? 0
    : ratio <= 1
      ? R_MIN + ratio * (R_TOL - R_MIN)                        // ในเกณฑ์
      : R_TOL + Math.min(ratio - 1, 1) * (R_MAX - R_TOL);      // หลุดเกณฑ์
  // ⚠ ต้องเป็น `dir?.` — `dir` เป็น null ได้จริงและเกิดบ่อยด้วย:
  //   Live Telemetry ก่อนวัดชิ้นแรก (`telemetry` ยังเป็น null → posCode undefined)
  //   หรือแถวเก่าใน DB ที่ posCode เป็น "-" / "Top Right" แบบเดิมซึ่งไม่ตรง DIRS
  //   ถ้าเขียน `dir.ux` ตรง ๆ จะได้ TypeError แล้ว **ทั้งหน้าเว็บขาว** เพราะ
  //   ยังไม่มี error boundary ครอบ (ดู console: "Cannot read properties of null")
  const cx = C + (dir?.ux ?? 0) * dist;
  const cy = C + (dir?.uy ?? 0) * dist;
  const isFar = tol != null && ratio > 2;

  // ⚠ ok เป็น null ได้ — "ยังไม่ได้ตั้งเกณฑ์" ต่างจาก "ตรวจแล้วผ่าน"
  //   วาดวงประ/ป้าย OK ให้ทั้งที่ไม่มีเกณฑ์จะชวนอ่านว่าผ่าน ทั้งที่ไม่เคยตรวจ
  const ok = !hasValue || tol == null
    ? null
    : Math.abs(Number(offsetX)) <= tol && Math.abs(Number(offsetY)) <= tol;

  // ⚠⚠ ต้องใช้ตัวแปรสีของโปรเจกต์นี้เท่านั้น (`--ok` / `--ng` / `--muted` …
  //   ดู :root ใน index.css) **ห้ามใช้ชื่อจาก design system อื่น** เช่น
  //   `--text-success` / `--border-strong` — `var()` ที่หาไม่เจอทำให้ `stroke`
  //   กลายเป็น `none` (กรอบกับพินหายทั้งหมด) และ `fill` ตกไปเป็นสีดำ
  //   โดยไม่มี error ให้เห็นเลยสักบรรทัด
  const col = ok === null ? "var(--muted)" : ok ? "var(--ok)" : "var(--ng)";
  const bg  = ok === null ? "var(--surface2)" : ok ? "var(--ok-bg)" : "var(--ng-bg)";

  const size = compact ? 44 : 108;
  const diagram = (
    <svg
      width={size} height={size} viewBox="0 0 120 120"
      role="img" style={{ flexShrink: 0 }}
    >
      <title>
        {hasValue && dir
          ? `ชิ้นงานเบียดไปทาง${dir.th}${ok === false ? " เกินเกณฑ์" : ""}`
          : "ไม่มีค่าการวัด"}
      </title>
      <rect x="8" y="8" width="104" height="104" rx="9"
            fill="none" stroke="var(--muted)" strokeOpacity="0.45" strokeWidth="1.5" />
      {!compact && [27, 60, 93].map((y) => (
        <g key={y}>
          <circle cx="21" cy={y} r="4.5" fill="none" stroke="var(--muted)" strokeOpacity="0.4" />
          <circle cx="99" cy={y} r="4.5" fill="none" stroke="var(--muted)" strokeOpacity="0.4" />
        </g>
      ))}
      <line x1="60" y1="12" x2="60" y2="108" stroke="var(--muted)" strokeOpacity="0.3" strokeDasharray="3 3" />
      <line x1="12" y1="60" x2="108" y2="60" stroke="var(--muted)" strokeOpacity="0.3" strokeDasharray="3 3" />
      {tol != null && (
        <circle cx="60" cy="60" r={R_TOL} fill="none"
                stroke="var(--muted)" strokeOpacity="0.5" strokeDasharray="2 3" />
      )}
      <rect
        x={cx - 18} y={cy - 18} width="36" height="36" rx="5"
        fill={hasValue ? bg : "none"}
        stroke={hasValue ? col : "var(--muted)"} strokeWidth="1.5"
        strokeOpacity={hasValue ? 1 : 0.4}
        strokeDasharray={hasValue ? undefined : "4 3"}
      />
      <circle cx="60" cy="60" r="3" fill="var(--surface)"
              stroke="var(--muted)" strokeWidth="1.5" />
      {hasValue && <circle cx={cx} cy={cy} r="4.5" fill={col} />}
      {isFar && (
        <text x={cx} y={cy - 10} fontSize="12" fill={col} textAnchor="middle">≫</text>
      )}
    </svg>
  );

  if (compact) return diagram;

  // แกนที่ค่าน้อยกว่าอีกแกนมาก ๆ ไม่ใช่ประเด็น — หรี่ลงให้สายตาไปที่ตัวที่สำคัญ
  const ax = Math.abs(Number(offsetX ?? 0));
  const ay = Math.abs(Number(offsetY ?? 0));
  const big = Math.max(ax, ay) || 1;
  const overX = tol != null && ax > tol;
  const overY = tol != null && ay > tol;

  const numStyle = (dim: boolean, over: boolean): CSSProperties => ({
    fontFamily: "'Courier New', monospace",
    fontSize: "1.15rem",
    fontWeight: 700,
    opacity: dim ? 0.45 : 1,
    color: over ? "var(--ng)" : "var(--text)",
  });
  const capStyle: CSSProperties = { fontSize: "0.7rem", color: "var(--muted)" };

  // ── ทิศ: โชว์เป็น "POSITION : <รหัสดิบ>" ─────────────────────────────────
  // ใช้รหัสจาก backend ตรง ๆ ไม่แปลเป็นไทย เพื่อให้ตรงกับสิ่งที่เก็บใน DB และ
  // ที่ Export/Power BI แสดง — คนหน้างานจะได้ไม่ต้องจำคำ 2 ชุดสำหรับของเดียวกัน
  // (คำไทยยังอยู่ใน <title> ของ SVG ให้ screen reader อ่าน)
  // ⚠ ยังไม่มีค่า → ขีดกลางเฉย ๆ ไม่ต้องอธิบาย — บรรทัดนี้ขึ้นค้างตั้งแต่เปิด
  //   หน้าเว็บก่อนวัดชิ้นแรก ถ้าเขียน "ไม่มีค่าการวัด" จะอ่านเหมือนมีอะไรผิดปกติ
  //   ทั้งที่แค่ยังไม่ถึงเวลา · ช่อง OP-X/OP-Y ข้าง ๆ ก็เป็น "—" อยู่แล้ว
  const posText = !hasValue ? "—"
    : tol == null ? "ยังไม่ได้ตั้ง Offset Tol"
    : (posCode ?? "—");

  return (
    // ⚠ ต้องมีคลาส `rax` — ในหน้ารายงานมันวางเรียงกับการ์ด Value X / Value Y
    //   ซึ่งใช้คลาสนี้เอาขอบกับ padding ไม่ใส่แล้วการ์ดนี้จะลอยไม่มีกรอบใบเดียว
    //   ส่วนใน Live Telemetry มี `.telemetry-offset-cell .rax { border: none }`
    //   รีเซ็ตทิ้งอยู่แล้ว เพราะพื้นหลัง/มุมมาจาก `.telemetry-cell` ที่ครอบอีกที
    <div className="rax">
      {/* แถวหัว — ชื่อการ์ดกับป้ายผลอยู่บรรทัดเดียวกัน
          ⚠ ป้าย OK/NG ต้องอยู่แถวนี้ ไม่ใช่แถว POSITION ข้างล่าง เพราะมันเป็น
            ผลของ "ทั้งการ์ด" ไม่ใช่ของบรรทัด POSITION บรรทัดเดียว
          สไตล์เขียน inline ไม่ใช้ `.tc-label` เพราะคลาสนั้นถูก scope ไว้ใต้
          `.telemetry-cell` — พอเอา component ไปใช้ใน ReportModal จะไม่ติด */}
      {title && (
        <div style={{
          display: "flex", alignItems: "center", justifyContent: "space-between",
          gap: "0.75rem", marginBottom: "0.5rem",
        }}>
          <span style={{ fontSize: "0.7rem", color: "var(--muted)" }}>{title}</span>
          {ok !== null && (
            <span className={`rax-tag ${ok ? "ok" : "ng"}`}>{ok ? "OK" : "NG"}</span>
          )}
        </div>
      )}
      <div style={{ display: "flex", gap: "1rem", alignItems: "center" }}>
        {diagram}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "0.75rem" }}>
            <span style={{ fontSize: "0.95rem", color: "var(--text)" }}>
              <strong>POSITION</strong> : {posText}
            </span>
            {/* ไม่มี title = ใช้แบบเดี่ยว (ReportModal) ป้ายจึงมาอยู่แถวนี้แทน */}
            {!title && ok !== null && (
              <span className={`rax-tag ${ok ? "ok" : "ng"}`}>{ok ? "OK" : "NG"}</span>
            )}
          </div>
          {/* 3 ช่องกระจายเต็มความกว้าง — `1fr` เท่ากันหมดเพื่อให้หัวข้อกับตัวเลข
              เรียงตรงเป็นคอลัมน์ ไม่เหลื่อมตามความยาวของคำ ("Tolerance" ยาวกว่า
              "OP-X" เกือบเท่าตัว ถ้าใช้ flex+gap จะดันช่องขวาไปกองมุม) */}
          <div style={{
            display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))",
            gap: "0.75rem", marginTop: "0.5rem",
          }}>
            <div>
              <div style={capStyle}>OP-X</div>
              <div style={numStyle(ax / big < 0.27, overX)}>{fmt(offsetX)}</div>
            </div>
            <div>
              <div style={capStyle}>OP-Y</div>
              <div style={numStyle(ay / big < 0.27, overY)}>{fmt(offsetY)}</div>
            </div>
            <div>
              <div style={capStyle}>Tolerance</div>
              <div style={{ ...numStyle(false, false), color: "var(--muted)" }}>
                {tol != null ? tol.toFixed(3) : "—"}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
