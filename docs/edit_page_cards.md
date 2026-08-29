# หน้า Edit — ชื่อ Card + คำอธิบายใต้รูป

**หัวเรื่องรอง (ใต้ชิป Web Application · Edit)**
> Data can be corrected — and every correction can be undone

---

## ฝั่งซ้าย · WHAT CAN BE CHANGED

| ชื่อ Card | คำอธิบายใต้รูป |
|---|---|
| **Parts** | Register a new ALPL, or correct the specification it was set up with |
| **Measurements** | The ALPL and the operator can be fixed — the measured values stay locked |
| **Lookup Tables** | The lists behind every dropdown, kept in one place so no name is typed twice |

---

## ฝั่งขวา · WHAT PROTECTS IT

| ชื่อ Card | คำอธิบายใต้รูป |
|---|---|
| **History** | Every change is recorded with the value before and after it |
| **Trash** | Deleted records are not gone — they stay recoverable for 30 days |

---

## แบบสั้น ถ้าที่ว่างไม่พอ

| Card | สั้น |
|---|---|
| Parts | Register and correct ALPL specifications |
| Measurements | Correct the entry, never the reading |
| Lookup Tables | One list per dropdown |
| History | Every change, before and after |
| Trash | Deleted, not gone — 30 days to undo |

---

## ⚠ อย่าเขียนว่า "who changed it"

ระบบ**ยังไม่มี auth** และตาราง History ก็ไม่มีคอลัมน์ผู้ใช้ (ในภาพมีแค่
EDITED AT · TABLE · ACTION · ITEM · DETAILS)

เขียนได้แค่ **"อะไรเปลี่ยน และเปลี่ยนจากอะไรเป็นอะไร"** เท่านั้น
ถ้าเผลอเขียนว่าบันทึกว่าใครแก้ จะโดนจับได้ทันทีที่เปิดหน้าจอจริง
