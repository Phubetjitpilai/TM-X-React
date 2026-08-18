import { useToast } from "../Toast";

export interface IpmSummaryRow {
  x: number | null;
  y: number | null;
}

/** ทศนิยม 3 ตำแหน่งเสมอ — ให้ตรงกับความละเอียดที่ TM-X ส่งมา (+0005.047) */
const fmtMm = (v: number | null) => (v == null ? "" : Number(v).toFixed(3));

/**
 * สรุปผล IPM ตอนวัดครบ — ตารางสำหรับคัดลอกไปวางใน Excel
 *
 * โหมด IPM คนหน้าเครื่องต้องเอาค่าไปกรอกใน Excel ของตัวเองต่อ การให้ก๊อปทีเดียว
 * ทั้งชุดเร็วกว่าไล่อ่านจากตาราง Measurements ทีละแถวมาก
 */
export default function IpmSummaryModal({
  rows, onClose,
}: {
  rows: IpmSummaryRow[];
  onClose: () => void;
}) {
  const { show } = useToast();

  /**
   * คัดลอกเป็น TSV — คั่นคอลัมน์ด้วย Tab ขึ้นแถวด้วย \n
   * วางใน Excel แล้วแตกเป็น 2 คอลัมน์ × N แถวอัตโนมัติ (ไม่ต้องใช้ Text to Columns)
   */
  async function copy() {
    const tsv = rows
      .map((r, i) => `ALPL${i + 1}X=${fmtMm(r.x)}mm\tY=${fmtMm(r.y)}mm`)
      .join("\n");
    try {
      await navigator.clipboard.writeText(tsv);
      show(`คัดลอกแล้ว ${rows.length} แถว — วางใน Excel ได้เลย`);
    } catch {
      // ⚠ clipboard API ใช้ไม่ได้ถ้าเปิดผ่าน http จากเครื่องอื่น (ต้อง https หรือ
      //   localhost) ซึ่งเป็นกรณีปกติของระบบนี้ — โอเปอเรเตอร์เปิดจากเครื่องอื่น
      //   ในไลน์ผ่าน IP ของ PC ถอยไปใช้วิธีเดิมที่ทำงานได้ทุกที่
      const ta = document.createElement("textarea");
      ta.value = tsv;
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      try {
        document.execCommand("copy");
        show(`คัดลอกแล้ว ${rows.length} แถว — วางใน Excel ได้เลย`);
      } catch {
        show("คัดลอกไม่สำเร็จ — ลากเลือกข้อความในตารางแล้วกด Ctrl+C แทน");
      }
      document.body.removeChild(ta);
    }
  }

  return (
    <div className="modal-overlay open">
      <div className="pe-modal-box" style={{ maxWidth: 560 }}>
        <div className="pe-modal-header">
          <div className="card-title">
            สรุปผลการวัด <span className="count">วัดครบ {rows.length} ชิ้น</span>
          </div>
          <button className="pe-modal-close" title="Close" onClick={onClose}>✕</button>
        </div>

        <div className="table-wrap">
          <table className="ipm-summary-table">
            <tbody>
              {rows.map((r, i) => (
                <tr key={i}>
                  <td>ALPL{i + 1}X={fmtMm(r.x)}mm</td>
                  <td>Y={fmtMm(r.y)}mm</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="entry-actions" style={{ justifyContent: "space-between", alignItems: "center" }}>
          <span style={{ fontSize: "0.78rem", color: "var(--muted)" }}>
            คัดลอกแล้ววางใน Excel ได้ 2 คอลัมน์ทันที
          </span>
          <button type="button" className="btn-submit-entry" onClick={copy}>
            📋 คัดลอกข้อความ
          </button>
        </div>
      </div>
    </div>
  );
}
