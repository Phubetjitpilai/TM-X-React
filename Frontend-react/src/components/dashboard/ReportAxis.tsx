const fmt = (v?: number | null) => (v != null && !isNaN(Number(v)) ? Number(v).toFixed(3) : "—");

/**
 * การ์ดแสดงค่ารายแกนในรายงาน พร้อมแถบ 3 โซน (ต่ำกว่า / รับได้ / สูงกว่าสเปค)
 *
 * ยกจาก renderAxisReport ใน index.html — แถบบอกด้วย "ตำแหน่ง" แทนตัวเลข
 * ทำให้เห็นทันทีว่าเกินไปนิดเดียวหรือหลุดไปไกล โดยไม่ต้องคำนวณในหัว
 */
export function ReportAxis({
  axis, value, nominal, upperTol, lowerTol,
}: {
  axis: string;
  value?: number | null;
  nominal?: number | null;
  upperTol?: number | null;
  lowerTol?: number | null;
}) {
  const hasSpec = value != null && nominal != null && upperTol != null && lowerTol != null;

  if (!hasSpec) {
    // ไม่มีเกณฑ์จริง ๆ = ALPL นี้ยังไม่ได้ผูกทั้ง Package Size และ Part Number
    // ⚠ ห้ามเขียนว่า "ไปตั้ง Part Number" — โหมด IPM ใช้เกณฑ์จาก Package Size
    //   ได้โดยไม่ต้องมี Part Number ข้อความแบบนั้นจะชี้ผิดจุดสำหรับแถว IPM
    return (
      <div className="rax">
        <div className="rax-head"><span className="rax-name">Actual {axis}</span></div>
        <div className="rax-value">{fmt(value)} <span className="unit">mm</span></div>
        <div className="rax-dev ok">
          ยังไม่ได้ผูกเกณฑ์ให้ ALPL นี้ (Package Size / Part Number) — เทียบสเปคไม่ได้
        </div>
      </div>
    );
  }

  const lo = Number(nominal) - Number(lowerTol);
  const hi = Number(nominal) + Number(upperTol);
  const span = hi - lo;
  const ok = value! >= lo && value! <= hi;

  // โซน "รับได้" กินพื้นที่ 25%–75% ของแถบ · นอกนั้นคือหลุดสเปค
  let pos: number;
  let farSym: { left: number; transform: string; text: string } | null = null;
  if (ok) {
    pos = 25 + ((value! - lo) / span) * 50;
  } else if (value! > hi) {
    const over = (value! - hi) / span;   // หลุดไปกี่เท่าของความกว้างสเปค
    pos = Math.min(97, 75 + over * 25);
    if (over > 1) farSym = { left: pos, transform: "translateX(-160%)", text: "≫" };
  } else {
    const under = (lo - value!) / span;
    pos = Math.max(3, 25 - under * 25);
    if (under > 1) farSym = { left: pos, transform: "translateX(60%)", text: "≪" };
  }

  // ⚠ ตำแหน่ง nominal ต้องคำนวณตามสัดส่วนจริง **ห้ามตรึงไว้ที่ 50%** เพราะ
  //   upper_tol กับ lower_tol ไม่เท่ากัน (เช่น +0.020/-0.010) nominal จึงไม่ได้
  //   อยู่กึ่งกลางช่วงสเปค ตรึงไว้แล้วเส้นกับตัวเลขจะไม่ตรงกับความจริง
  const nomPos = 25 + ((Number(nominal) - lo) / span) * 50;
  // ซ่อน "ตัวเลข" nominal ถ้าใกล้ตัวเลขขอบจนซ้อนกัน (เส้นยังอยู่)
  const showNomTick = Math.abs(nomPos - 25) > 10 && Math.abs(nomPos - 75) > 10;
  const cls = ok ? "ok" : "ng";

  return (
    <div className="rax">
      <div className="rax-head">
        <span className="rax-name">Value {axis}</span>
        <span className={`rax-tag ${cls}`}>{ok ? "OK" : "NG"}</span>
      </div>
      <div className={`rax-value ${cls}`}>{fmt(value)} <span className="unit">mm</span></div>
      <div className="rax-bar">
        <div className="rax-track" />
        <div className="rax-zone" />
        <div className="rax-nom" style={{ left: `${nomPos}%` }} />
        <div className={`rax-mark ${cls}`} style={{ left: `${pos}%` }} />
        {farSym && (
          <span className="rax-far" style={{ left: `${farSym.left}%`, transform: farSym.transform }}>
            {farSym.text}
          </span>
        )}
        <span className="rax-zlabel" style={{ left: "12.5%" }}>ต่ำกว่าสเปค</span>
        <span className="rax-zlabel mid" style={{ left: "50%" }}>ช่วงที่รับได้</span>
        <span className="rax-zlabel" style={{ left: "87.5%" }}>สูงกว่าสเปค</span>
        <span className="rax-tick" style={{ left: "25%" }}>{fmt(lo)}</span>
        {showNomTick && <span className="rax-tick" style={{ left: `${nomPos}%` }}>{fmt(nominal)}</span>}
        <span className="rax-tick" style={{ left: "75%" }}>{fmt(hi)}</span>
      </div>
    </div>
  );
}

/**
 * การ์ด Offset — ไม่มี nominal เทียบแค่เพดานตัวเดียว จึงมีแถบ **2 โซน** ไม่ใช่ 3
 * เพราะ offset ไม่มี "ต่ำกว่าสเปค" (ยิ่งน้อยยิ่งดี 0 คือดีที่สุด)
 */
export function ReportOffset({
  offset, offsetTol, measureType,
}: {
  offset?: number | null;
  offsetTol?: number | null;
  measureType?: string | null;
}) {
  if (offset == null) return null;

  // โหมด IPM: ไม่แสดงการ์ดนี้เลย — ค่ายังอยู่ใน DB ครบ (ดูได้จาก Export/Power BI)
  // แค่ไม่เอามารกหน้ารายงานที่คนหน้าเครื่องใช้ตัดสินใจ เพราะมันไม่มีส่วนร่วมกับ
  // ผล OK/NG ของแถวนั้นเลย — เหตุผลเดียวกับที่ซ่อนใน Live Telemetry
  if ((measureType ?? "").toUpperCase() === "IPM") return null;

  // มีค่าแต่ยังไม่ได้ตั้งเกณฑ์ → โชว์ค่าเฉย ๆ ไม่มีแถบ ไม่มีป้าย OK/NG
  // (วาดแถบให้ทั้งที่ไม่มีเกณฑ์จะชวนให้อ่านว่า "ผ่าน" ทั้งที่ไม่เคยตรวจ)
  if (offsetTol == null) {
    return (
      <div className="rax">
        <div className="rax-head"><span className="rax-name">Offset</span></div>
        <div className="rax-value">{fmt(offset)} <span className="unit">mm</span></div>
        <div className="rax-dev ok">ยังไม่ได้ตั้ง Offset Tol</div>
      </div>
    );
  }

  const tol = Number(offsetTol);
  const val = Math.abs(Number(offset));
  const ok = val <= tol;
  const cls = ok ? "ok" : "ng";
  // ให้เพดานอยู่ที่ 75% ของความกว้าง เท่ากับขอบบนของการ์ด X/Y — อ่านเทียบกันได้
  const pos = ok ? (val / tol) * 75 : Math.min(97, 75 + ((val - tol) / tol) * 25);

  return (
    <div className="rax">
      <div className="rax-head">
        <span className="rax-name">Offset</span>
        <span className={`rax-tag ${cls}`}>{ok ? "OK" : "NG"}</span>
      </div>
      <div className={`rax-value ${cls}`}>{fmt(offset)} <span className="unit">mm</span></div>
      <div className="rax-bar">
        <div className="rax-track" />
        <div className="rax-zone offset" />
        <div className={`rax-mark ${cls}`} style={{ left: `${pos}%` }} />
        <span className="rax-zlabel mid" style={{ left: "37.5%" }}>ช่วงที่รับได้</span>
        <span className="rax-zlabel" style={{ left: "87.5%" }}>สูงกว่าสเปค</span>
        <span className="rax-tick" style={{ left: "0%" }}>0.000</span>
        <span className="rax-tick" style={{ left: "75%" }}>{fmt(tol)}</span>
      </div>
    </div>
  );
}
