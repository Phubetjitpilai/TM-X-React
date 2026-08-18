import { useState } from "react";

export interface ExportColumn {
  key: string;
  label: string;
  group: string;
  block?: { data?: { key: string; label: string }[] };
}

interface Props {
  /** null = สร้างใหม่ · object = แก้ตัวที่มีอยู่ */
  editing: { export_template_id: number; name: string; columns: string[] } | null;
  catalog: ExportColumn[];
  onSave: (name: string, columns: string[]) => void;
  onClose: () => void;
  saving?: boolean;
}

/** สร้าง/แก้เทมเพลต — ชื่อ + เลือกคอลัมน์ + เรียงลำดับด้วยการลาก
 *
 *  ยกจาก renderPicker/bindDrag ใน export.html · ใช้ HTML5 drag and drop ธรรมดา
 *  ไม่ต้องพึ่ง library เหมือนต้นฉบับ
 */
export default function TemplateModal({ editing, catalog, onSave, onClose, saving }: Props) {
  const [name, setName] = useState(editing?.name ?? "");
  const [columns, setColumns] = useState<string[]>(editing?.columns ?? []);
  const [dragFrom, setDragFrom] = useState<number | null>(null);

  const labelOf = (key: string) =>
    catalog.find((c) => c.key === key)?.label ??
    catalog.flatMap((c) => c.block?.data ?? []).find((d) => d.key === key)?.label ??
    key;

  const toggle = (key: string, on: boolean) =>
    setColumns((prev) => (on ? (prev.includes(key) ? prev : [...prev, key]) : prev.filter((k) => k !== key)));

  // จัดกลุ่มตามแหล่งข้อมูลเหมือนต้นฉบับ — Map รักษาลำดับที่ backend ส่งมา
  const groups = new Map<string, ExportColumn[]>();
  catalog.forEach((c) => {
    if (!groups.has(c.group)) groups.set(c.group, []);
    groups.get(c.group)!.push(c);
  });

  function drop(to: number) {
    if (dragFrom == null || dragFrom === to) return;
    setColumns((prev) => {
      const next = [...prev];
      const [moved] = next.splice(dragFrom, 1);
      next.splice(to, 0, moved);
      return next;
    });
    setDragFrom(null);
  }

  const canSave = name.trim().length > 0 && columns.length > 0 && !saving;

  return (
    <div className="overlay open" onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="modal">
        <div className="modal-head">
          <div className="card-head" style={{ margin: 0 }}>
            {editing ? "แก้ไข Template" : "Template ใหม่"}
          </div>
          <button type="button" className="modal-close" onClick={onClose}>✕</button>
        </div>

        <div className="fg">
          <label>ชื่อ Template</label>
          <input
            type="text"
            placeholder="เช่น รายงานประจำวัน"
            value={name}
            onChange={(e) => setName(e.target.value)}
            autoFocus
          />
        </div>

        <div className="picker">
          <div className="pk-box">
            <div className="pk-title">เลือกคอลัมน์ที่ต้องการ</div>
            {[...groups.entries()].map(([g, cols]) => (
              <div key={g}>
                <div className="pk-group">{g}</div>
                {cols.map((c) => (
                  <label className="pk-item" key={c.key}>
                    <input
                      type="checkbox"
                      checked={columns.includes(c.key)}
                      onChange={(e) => toggle(c.key, e.target.checked)}
                    />
                    {c.label}
                  </label>
                ))}
              </div>
            ))}
          </div>

          <div className="pk-box">
            <div className="pk-title">ลำดับคอลัมน์ในไฟล์ (ลากสลับได้)</div>
            {columns.length === 0 ? (
              <div style={{ fontSize: "0.78rem", color: "var(--muted)", padding: "0.5rem 0" }}>
                ยังไม่ได้เลือกคอลัมน์
              </div>
            ) : (
              columns.map((k, i) => (
                <div
                  key={k}
                  className={`ord-item${dragFrom === i ? " drag" : ""}`}
                  draggable
                  onDragStart={() => setDragFrom(i)}
                  onDragEnd={() => setDragFrom(null)}
                  onDragOver={(e) => e.preventDefault()}
                  onDrop={() => drop(i)}
                >
                  <span className="ord-grip">⠿</span>
                  {labelOf(k)}
                  <button type="button" className="ord-x" title="เอาออก" onClick={() => toggle(k, false)}>
                    ✕
                  </button>
                </div>
              ))
            )}
          </div>
        </div>

        <div className="actions">
          <button type="button" className="btn-ghost" onClick={onClose}>ยกเลิก</button>
          <button
            type="button"
            className="btn-primary"
            disabled={!canSave}
            title={
              !name.trim() ? "กรอกชื่อ Template ก่อน"
              : columns.length === 0 ? "เลือกคอลัมน์อย่างน้อย 1 ช่อง"
              : ""
            }
            onClick={() => onSave(name.trim(), columns)}
          >
            บันทึก Template
          </button>
        </div>
      </div>
    </div>
  );
}
