import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { apiGet, apiPost } from "../api/client";
import { useToast } from "./Toast";
import ConfirmDialog from "./ConfirmDialog";

export interface TrashItem {
  id: string;
  deleted_at: string | null;
  kind: string;
  kind_label: string;
  summary: string;
  has_image: boolean;
  /** เหลืออีกกี่วันก่อนโดนลบถาวรอัตโนมัติ · 0 = วันสุดท้าย · null = คำนวณไม่ได้
   *
   *  ⚠ ค่านี้คำนวณจาก **backend** (`_days_left`) ห้ามคำนวณเองที่นี่เด็ดขาด —
   *    ตัวลบจริง (`_purge_old_deleted`) อ่านวันจาก "ชื่อโฟลเดอร์" (DD-MM-YYYY
   *    พ.ศ.) แล้วแปลง พ.ศ. → ค.ศ. ถ้าฝั่งหน้าเว็บคำนวณเองด้วยตรรกะที่ต่างไป
   *    แม้แต่นิดเดียว ตัวเลขบนจอจะโกหกโดยไม่มีใครรู้ — ผู้ใช้เห็น "เหลือ 3 วัน"
   *    ทั้งที่ของถูกลบไปแล้ว
   */
  days_left: number | null;
}

interface TrashResponse {
  items: TrashItem[];
  total: number;
  retention_days: number;
}

interface TrashCardProps {
  /** เพิ่มค่านี้ทีละ 1 เพื่อสั่งให้โหลดถังขยะใหม่ — ใช้ตอนหน้าแม่เพิ่งลบอะไรไป
   *
   *  ทำไมต้องมี: EditPage จัดการ state ของตัวเองด้วย useState ไม่ได้ใช้ TanStack
   *  Query เลย (พอร์ตตรงมาจาก edit.html) การ invalidateQueries จากในนี้จึงไม่มี
   *  ผลกับมัน และมันก็สั่งให้ถังขยะรีเฟรชเองไม่ได้ — ต้องต่อสายกันตรงๆ แบบนี้
   */
  reloadKey?: number;
  /** เรียกหลังกู้คืนสำเร็จ — ให้หน้าแม่โหลดตารางของตัวเองใหม่
   *  ไม่งั้นแถวที่กู้มาจะยังไม่โผล่จนกว่าจะรีเฟรชหน้า แล้วผู้ใช้จะกดกู้ซ้ำ
   */
  onRestored?: () => void;
}

export function useTrash(reloadKey = 0) {
  return useQuery<TrashResponse>({
    queryKey: ["deleted", reloadKey],
    queryFn: () => apiGet<TrashResponse>("/api/deleted"),
    staleTime: 0,
  });
}

/** ถังขยะ — ของที่ลบไปแล้วยังกู้คืนได้จนกว่าจะครบกำหนด
 *
 *  วางไว้ท้ายสุดของหน้า Edit โดยตั้งใจ (ตามต้นฉบับ) — เป็นหน้าเดียวกับที่ผู้ใช้
 *  กดลบ เผลอลบแล้วเลื่อนลงมากู้ได้ทันที ไม่ต้องจำว่าต้องไปหน้าไหน
 */
export default function TrashCard({ reloadKey = 0, onRestored }: TrashCardProps) {
  const { data, isLoading, refetch } = useTrash(reloadKey);
  const qc = useQueryClient();
  const toast = useToast();
  const [confirmPurge, setConfirmPurge] = useState<TrashItem | null>(null);

  const items = data?.items ?? [];
  const retentionDays = data?.retention_days ?? 30;

  const restore = useMutation({
    mutationFn: (id: string) => apiPost("/api/deleted/restore", { id }),
    onSuccess: () => {
      toast.show("กู้คืนข้อมูลเรียบร้อยแล้ว");
      refetch();
      qc.invalidateQueries({ queryKey: ["session-state"] });
      onRestored?.();   // ให้หน้าแม่โหลดตารางของตัวเองใหม่
    },
    onError: (e: Error) => toast.show(`กู้คืนไม่สำเร็จ — ${e.message}`),
  });

  const purge = useMutation({
    mutationFn: (id: string) => apiPost("/api/deleted/remove", { id }),
    // ลบถาวรไม่ได้แตะฐานข้อมูลเลย (แถวถูกลบไปตั้งแต่ตอนกดลบครั้งแรกแล้ว
    // ตรงนี้แค่ทิ้งตัวสำรอง) จึงไม่ต้องบอกให้หน้าแม่โหลดตารางใหม่
    onSuccess: () => { toast.show("ลบถาวรแล้ว"); refetch(); },
    onError: (e: Error) => toast.show(`ลบไม่สำเร็จ — ${e.message}`),
  });

  return (
    <section className="card" id="trash-section">
      <div className="card-header">
        <div className="card-title">
          🗑 TRASH <span className="count">{items.length ? `(${items.length})` : ""}</span>
        </div>
      </div>
      <div className="filter-result-note">
        ข้อมูลที่ลบจะถูกเก็บไว้ที่นี่ {retentionDays} วัน กดกู้คืนได้ตลอด — เกินกำหนดจะถูกลบถาวรอัตโนมัติ
      </div>

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              {/* หัวตารางเป็นอังกฤษให้ตรงกับตารางอื่นในหน้านี้ */}
              <th style={{ width: 170 }}>Deleted At</th>
              <th style={{ width: 130 }}>Type</th>
              <th>Details</th>
              <th style={{ width: 110 }}>Days Left</th>
              <th style={{ width: 220 }} />
            </tr>
          </thead>
          <tbody>
            {isLoading ? (
              <tr className="empty-row"><td colSpan={5}>กำลังโหลด…</td></tr>
            ) : items.length === 0 ? (
              <tr className="empty-row"><td colSpan={5}>ถังขยะว่าง — ยังไม่มีข้อมูลที่ถูกลบ</td></tr>
            ) : (
              items.map((it) => (
                <tr key={it.id}>
                  {/* deleted_at เป็น "YYYY-MM-DD HH:MM:SS" อยู่แล้ว ตัดวินาทีออกให้อ่านง่าย */}
                  <td style={{ whiteSpace: "nowrap" }}>
                    {(it.deleted_at ?? "").slice(0, 16).replace("T", " ")}
                  </td>
                  <td>{it.kind_label}</td>
                  <td>
                    {it.summary}
                    {it.has_image && <span title="มีไฟล์รูปเก็บไว้ด้วย"> 🖼</span>}
                  </td>
                  <td style={{ whiteSpace: "nowrap" }}><DaysLeft value={it.days_left} /></td>
                  <td className="trash-actions">
                    <button
                      type="button"
                      className="btn-restore"
                      disabled={restore.isPending}
                      onClick={() => restore.mutate(it.id)}
                    >
                      ↩ Restore
                    </button>
                    <button
                      type="button"
                      className="btn-purge"
                      title="ลบถาวร กู้คืนไม่ได้อีก"
                      disabled={purge.isPending}
                      onClick={() => setConfirmPurge(it)}
                    >
                      🗑 Delete
                    </button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* ลบถาวรกู้ไม่ได้อีก — ต้องถามก่อนเสมอ ต่างจากปุ่มลบปกติที่ยังมีถังขยะรับไว้ */}
      {confirmPurge && (
        <ConfirmDialog
          title="ลบถาวร"
          message={`ลบ "${confirmPurge.summary}" ออกจากถังขยะถาวร?\n\nกู้คืนไม่ได้อีก${
            confirmPurge.has_image ? " และไฟล์รูปที่เก็บคู่กันจะถูกลบไปด้วย" : ""
          }`}
          confirmLabel="ลบถาวร"
          danger
          onConfirm={() => { purge.mutate(confirmPurge.id); setConfirmPurge(null); }}
          onCancel={() => setConfirmPurge(null)}
        />
      )}
    </section>
  );
}

/** 0 = วันสุดท้าย (รอบตรวจถัดไปลบ) · ≤3 = เน้นสีแดงให้รีบตัดสินใจ · null = ไม่ทราบ */
function DaysLeft({ value }: { value: number | null }) {
  if (value == null) return <>—</>;
  if (value === 0) return <span className="trash-soon">Last day</span>;
  if (value <= 3) return <span className="trash-soon">{value} days</span>;
  return <>{value} days</>;
}
