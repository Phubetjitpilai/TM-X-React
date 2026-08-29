# หน้า Export — ชื่อ Card + คำอธิบายใต้รูป

**หัวเรื่องรอง (ใต้ชิป Web Application)**
> One wizard for CSV, Excel and PDF — choose the shape, choose the rows, see it before it leaves

---

## ฝั่งซ้าย · CHOOSE THE SHAPE

| ชื่อ Card | คำอธิบายใต้รูป |
|---|---|
| **Select Template** | Start from a saved layout, or build a new one |
| **CSV Template** | Pick the columns you want, in the order you want them |
| **Report Layout** | Lay out PDF and Excel like a spreadsheet — merge cells, place headers and fields |

---

## ฝั่งขวา · CHOOSE THE ROWS

| ชื่อ Card | คำอธิบายใต้รูป |
|---|---|
| **Filter Data** | Narrow by date, ALPL, result, package size and more — before anything leaves |
| **Examine & Export** | The preview is drawn by the same code that builds the file, so what you see is what you get |

---

## แบบสั้น ถ้าที่ว่างไม่พอ

| Card | สั้น |
|---|---|
| Select Template | Saved layouts, or start a new one |
| CSV Template | Choose the columns and their order |
| Report Layout | Design the page like a spreadsheet |
| Filter Data | Narrow the rows before exporting |
| Examine & Export | See exactly what you will get |

---

## เกร็ดที่ควรพูด ไม่ต้องขึ้นสไลด์

**ตัวอย่างกับไฟล์จริงมาจากโค้ดตัวเดียวกัน** — `_render_report()` เป็นตัวกลางของทั้ง preview,
Excel และ PDF ถ้าแยกกันเขียน สิ่งที่เห็นบนจอกับไฟล์ที่ได้จะเพี้ยนกันเงียบ ๆ

**PDF ใช้ตัวพิมพ์ของเบราว์เซอร์** วาดจาก HTML ก้อนเดียวกับ preview ไม่ได้สร้างฝั่ง server
— เหตุผลคือไม่ต้องลง dependency เพิ่มบนเครื่องหน้างาน และหน้าตาตรงกับที่เห็นแน่นอน

**ค่าเริ่มต้นคือ "เฉพาะการวัดล่าสุดของแต่ละ ALPL"** เพราะรายงานส่วนใหญ่ต้องการสถานะปัจจุบัน
ไม่ใช่ประวัติทุกครั้ง — ติ๊กออกได้ถ้าอยากได้ทั้งหมด
