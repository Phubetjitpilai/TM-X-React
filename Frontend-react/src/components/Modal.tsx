import type { ReactNode } from "react";

interface ModalProps {
  title: string;
  onClose: () => void;
  children: ReactNode;
  maxWidth?: number;
}

// Modal: popup กลางที่ EditPage (Add/Edit Part, Add/Edit Measurement) และ
// DashboardPage (Part Entry, Report) เรียกใช้ร่วมกัน — เดิม index.html/edit.html
// ต่างคน copy markup ของ overlay+box เอง คนละชุด
// ⚠⚠ คลาส `open` ต้องติดมากับ .modal-overlay เสมอ
//   `.modal-overlay` ตั้ง `display: none` ไว้เป็นค่าเริ่มต้น แล้วเปิดด้วย
//   `.modal-overlay.open { display: flex }` — กติกานี้ยกมาจากฝั่ง vanilla ที่
//   overlay ค้างอยู่ใน DOM ตลอดแล้วสลับคลาสเอา
//
//   ฝั่ง React เรา conditional render อยู่แล้ว (component เกิดก็ต่อเมื่อจะโชว์)
//   แต่ถ้าลืมคลาสนี้ มันจะถูกวาดลง DOM จริงโดยที่ display:none ผลคือ
//   **กดปุ่มแล้วเหมือนไม่มีอะไรเกิดขึ้น** ไม่มี error ให้เห็นเลยสักตัว
//   (เจอจริงที่ปุ่ม 🗑 Delete ในถังขยะหน้า Edit — ConfirmDialog ถูก render
//    แต่มองไม่เห็น) ที่อื่นในโปรเจกต์เขียน `open` กันหมดแล้ว เหลือแต่ที่นี่
export default function Modal({ title, onClose, children, maxWidth = 640 }: ModalProps) {
  return (
    <div className="modal-overlay open" onClick={onClose}>
      <div className="modal-box" style={{ maxWidth }} onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div className="card-title" style={{ marginBottom: 0 }}>
            {title}
          </div>
          <button type="button" className="modal-close" onClick={onClose} title="Close">
            ✕
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}
