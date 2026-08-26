import { useEffect, useState } from "react";
import { apiGet } from "../api/client";

/**
 * ประวัติการแก้ไขข้อมูลของหน้า Edit
 *
 * ตอบคำถามว่า "ค่าที่เห็นอยู่ตอนนี้มาจากไหน" — สำคัญที่สุดกับ package_size /
 * part_number ที่เป็นตัวกำหนดเกณฑ์ OK/NG ของ **ทุกการวัด** แก้ทีเดียวกระทบ
 * ผลย้อนหลังทั้งระบบโดยไม่มีอะไรบนหน้าจอบอก
 *
 * ⚠ ไม่มีคอลัมน์ "ใครแก้" โดยตั้งใจ — ระบบยังไม่มี auth (ดู Known Issues ใน
 *   CLAUDE.md) ใส่ไปก็ว่างทุกแถวจนดูเหมือนระบบพัง
 *
 * ต่างจากถังขยะ (Trash) ตรงที่ถังขยะเก็บ "ตัวข้อมูลไว้กู้คืน" อายุ 30 วัน
 * ส่วนที่นี่เก็บ "บันทึกว่าเกิดอะไรขึ้น" ไม่ได้ใช้กู้คืน — แถวที่ลบและยังมีตัว
 * สำรองอยู่จะมีป้ายโยงไปถังขยะให้
 */

// 10 แถวต่อหน้า — ให้เท่ากับตาราง Parts/Measurements ในหน้าเดียวกัน
// (PAGE_SIZE ใน EditPage) จะได้ไม่มีการ์ดไหนยาวผิดจากเพื่อนจนหน้าเลื่อนยาว
const PAGE = 10;

interface Change { field: string; before?: unknown; after?: unknown }
interface HistoryItem {
  history_id: number;
  edited_at: string | null;
  table_name: string;
  table_label: string;
  action: "add" | "edit" | "delete" | "restore" | "purge";
  ref: string;
  changes: Change[];
  trash_id: string | null;
}

const TABLES = [
  ["", "Every Table"], ["parts", "Parts"], ["measurements", "Measurements"],
  ["package_size", "Package Size"], ["part_number", "Part Number"],
  ["operator", "Operator"], ["owner", "Owner"], ["vendor", "Vendor"],
  ["handler", "Handler"], ["template", "Template"],
] as const;

const ACTION_LABEL: Record<string, string> = {
  add: "Add", edit: "Edit", delete: "Delete",
  // Restore/Purge เป็นเหตุการณ์ของถังขยะ ไม่ใช่การแก้ข้อมูลตรง ๆ — แยกป้ายไว้
  // เพราะ "กู้คืน" ไม่เท่ากับ "มีคนสร้างใหม่" และ "ลบถาวร" ไม่เท่ากับ "ลบ"
  // (ตอนลบครั้งแรกของยังกู้ได้อยู่ ตอน purge คือหายจริง)
  restore: "Restore", purge: "Purge",
};

/** "2026-08-20T14:32:07" / "2026-08-20 14:32:07" → "20/08 14:32:07" */
function fmtTime(v: string | null): string {
  if (!v) return "—";
  const s = String(v).replace("T", " ");
  const [d, t] = s.split(" ");
  const [, mm, dd] = (d ?? "").split("-");
  return dd && mm ? `${dd}/${mm} ${(t ?? "").slice(0, 8)}` : s;
}

const show = (v: unknown) => (v === null || v === undefined || v === "" ? "—" : String(v));

interface Props {
  /** เพิ่มค่านี้ทีละ 1 เพื่อสั่งให้โหลดใหม่ — หน้าแม่เพิ่งแก้/ลบอะไรไป
   *  (EditPage ถือ state เองด้วย useState ไม่ได้ใช้ TanStack Query จึงต่อสายตรงแบบนี้
   *   เหมือนที่ TrashCard ทำ) */
  reloadKey?: number;
}

export default function HistoryCard({ reloadKey = 0 }: Props) {
  const [items, setItems] = useState<HistoryItem[]>([]);
  const [total, setTotal] = useState(0);
  const [ready, setReady] = useState(true);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [table, setTable] = useState("");
  const [action, setAction] = useState("");
  const [date, setDate] = useState("");
  /** แถวที่กางดู diff อยู่ — เก็บเป็น id ไม่ใช่ index เพราะลิสต์เปลี่ยนได้ */
  const [openId, setOpenId] = useState<number | null>(null);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    const params: Record<string, string | number> = { limit: PAGE, offset: (page - 1) * PAGE };
    if (table) params.table_name = table;
    if (action) params.action = action;
    if (date) { params.date_from = date; params.date_to = date; }
    apiGet<{ items: HistoryItem[]; total: number; ready: boolean }>("/api/history", params)
      .then((d) => {
        if (!alive) return;
        setItems(d.items ?? []);
        setTotal(d.total ?? 0);
        setReady(d.ready !== false);
      })
      .catch(() => { if (alive) { setItems([]); setTotal(0); } })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [page, table, action, date, reloadKey]);

  // เปลี่ยนตัวกรองแล้วต้องกลับหน้า 1 — ไม่งั้นค้างอยู่หน้า 5 ของผลลัพธ์ที่มี 2 แถว
  const setFilter = (fn: () => void) => { fn(); setPage(1); setOpenId(null); };

  const from = total === 0 ? 0 : (page - 1) * PAGE + 1;
  const to = (page - 1) * PAGE + items.length;

  return (
    <section className="card" id="history-section">
      <div className="card-header">
        <div className="card-title">
          History <span className="count">{total ? `(${total})` : ""}</span>
        </div>
        <div style={{ display: "flex", gap: "0.4rem" }}>
          <select value={table} onChange={(e) => setFilter(() => setTable(e.target.value))} style={{ minWidth: 140 }}>
            {TABLES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
          <select value={action} onChange={(e) => setFilter(() => setAction(e.target.value))} style={{ minWidth: 116 }}>
            <option value="">Every Action</option>
            <option value="add">Add</option>
            <option value="edit">Edit</option>
            <option value="delete">Delete</option>
            <option value="restore">Restore</option>
            <option value="purge">Purge</option>
          </select>
          <input type="date" value={date} onChange={(e) => setFilter(() => setDate(e.target.value))} />
        </div>
      </div>

      <div className="filter-result-note">
        บันทึกทุกครั้งที่มีการเพิ่ม/แก้ไข/ลบผ่านหน้านี้ — กดที่แถวเพื่อดูค่าก่อน/หลังแบบเต็ม
        {!ready && " · ยังไม่มีตาราง edit_history ในฐานข้อมูล (รัน sql-tools/add_edit_history.sql ก่อน)"}
      </div>

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              {/* หัวตารางเป็นอังกฤษให้ตรงกับตารางอื่นในหน้านี้ (Parts /
                  Measurements / Lookup Tables / Trash ใช้อังกฤษกันหมด)
                  "Edited At" ล้อกับ "Deleted At" ของถังขยะโดยตั้งใจ */}
              <th style={{ width: 130 }}>Edited At</th>
              <th style={{ width: 130 }}>Table</th>
              <th style={{ width: 90 }}>Action</th>
              <th style={{ width: 130 }}>Item</th>
              <th>Details</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr className="empty-row"><td colSpan={5}>กำลังโหลด…</td></tr>
            ) : items.length === 0 ? (
              <tr className="empty-row">
                <td colSpan={5}>{table || action || date ? "ไม่พบประวัติที่ตรงกับตัวกรอง" : "ยังไม่มีประวัติการแก้ไข"}</td>
              </tr>
            ) : (
              items.map((it) => {
                const open = openId === it.history_id;
                // แถว edit โชว์ diff ของฟิลด์แรกเป็นตัวอย่าง ที่เหลือรออยู่ในแถวที่กางออก
                const head = it.changes[0];
                return (
                  <FragmentRow
                    key={it.history_id}
                    item={it}
                    head={head}
                    open={open}
                    onToggle={() => setOpenId(open ? null : it.history_id)}
                  />
                );
              })
            )}
          </tbody>
        </table>
      </div>

      <div className="pagination-bar">
        <button type="button" className="btn-icon" disabled={page <= 1} onClick={() => { setPage(page - 1); setOpenId(null); }}>
          ‹ Previous
        </button>
        <span style={{ fontSize: "0.85rem", fontWeight: 600 }}>
          {total === 0 ? "ไม่มีรายการ" : `แสดง ${from}–${to} จาก ${total} รายการ`}
        </span>
        <button type="button" className="btn-icon" disabled={to >= total} onClick={() => { setPage(page + 1); setOpenId(null); }}>
          Next ›
        </button>
      </div>
    </section>
  );
}

function FragmentRow({ item, head, open, onToggle }: {
  item: HistoryItem; head?: Change; open: boolean; onToggle: () => void;
}) {
  const more = item.changes.length - 1;
  return (
    <>
      <tr data-clickable onClick={onToggle} style={{ cursor: "pointer" }}>
        <td style={{ whiteSpace: "nowrap" }} className="td-derived">{fmtTime(item.edited_at)}</td>
        <td>{item.table_label}</td>
        <td><span className={`hist-badge ${item.action}`}>{ACTION_LABEL[item.action] ?? item.action}</span></td>
        <td><strong>{item.ref}</strong></td>
        <td>
          {head ? <ChangeLine c={head} /> : <span className="td-derived">—</span>}
          {more > 0 && <span className="hist-more"> +{more} ฟิลด์</span>}
          {/* ⚠ ขึ้นเฉพาะ action delete — แถว restore/purge ก็มี trash_id ติดมาด้วย
              (ใช้โยงว่าเป็นของชิ้นไหน) แต่ของไม่ได้อยู่ในถังแล้ว ถ้าโชว์ป้ายนี้
              จะบอกผิดว่ายังกู้คืนได้ */}
          {item.action === "delete" && item.trash_id && <span className="hist-trash">อยู่ในถังขยะ</span>}
        </td>
      </tr>
      {open && (
        <tr>
          <td colSpan={5} style={{ background: "var(--surface2)" }}>
            <div className="hist-detail">
              {item.changes.length === 0
                ? <span className="td-derived">ไม่มีรายละเอียดที่บันทึกไว้</span>
                : item.changes.map((c) => <div key={c.field}><ChangeLine c={c} /></div>)}
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

/** "package_size 3x4 → 4x4" · add มีแต่ค่าใหม่ · delete มีแต่ค่าเดิม */
function ChangeLine({ c }: { c: Change }) {
  const hasB = "before" in c;
  const hasA = "after" in c;
  return (
    <>
      <span className="hist-field">{c.field}</span>{" "}
      {hasB && <span className="hist-before">{show(c.before)}</span>}
      {hasB && hasA && <span className="hist-arrow"> → </span>}
      {hasA && <span className="hist-after">{show(c.after)}</span>}
    </>
  );
}
