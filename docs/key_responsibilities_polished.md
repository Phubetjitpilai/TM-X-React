# Key Responsibilities — ข้อความที่เกลาแล้ว

> หลักที่ใช้: คอลัมน์นี้ตอบ **"ทำอะไร"** อย่างเดียว
> ส่วน **"ทำไป​ทำไม"** มีคอลัมน์ Objective รับอยู่แล้ว — ไม่ต้องเล่าซ้ำ

---

## สไลด์ 50 · Backend (Core Service)

| Module | Key Responsibilities |
|---|---|
| Measurement Session Control | • Receive Start / Stop from the web<br>• Send the measurement plan to the Pi<br>• Detect when the Pi or the database drops out |
| Validation & Decision | • Receive values from the Data Receiver<br>• Decide OK / NG<br>• Apply IPM or New / Rework criteria by mode |
| Data Management | • Store results in the database, images on disk<br>• Edit and delete records<br>• Keep deleted records for 30 days<br>• Log every change with before / after |
| Real-Time Monitoring | • Push live results to the web over SSE |
| Export Data | • Export filtered results as CSV, Excel or PDF |

---

## สไลด์ 52 · Backend (Data Receiver)

| Module | Key Responsibilities |
|---|---|
| FTP Server | • Receive values (.txt) and images (.bmp) from the TM-X |
| Pair each image with its value | • Match image N with line N of the .txt<br>• Discard the image and report if no line arrives within 5 s |
| Filter invalid data | • Treat any of the 8 values below −9000 as a failed measurement<br>• Discard the value, delete the image and report it |
| Forward to Core Service | • Check a session is running, otherwise discard<br>• Post the values, then upload the image |

---

## สไลด์ 54 · Backend (Image Server)

| Module | Key Responsibilities |
|---|---|
| Serve images to Power BI | • Return the stored image when a link is clicked<br>• Run on its own port (8080) |
| Restrict access by IP | • Answer the internal subnet only — every other address gets 403 |
| Block path traversal | • Resolve every path and reject anything outside the image folder |

---

## สไลด์ 56 · Edge Controller

| Module | Key Responsibilities |
|---|---|
| Receive commands from Core Service | • Receive Start with the plan — ALPL queue · TM-X program · limits<br>• Receive Stop / Retry / Accept from the operator |
| Control the TM-X (TCP) | • Once per session — R0, PW,1,nnn<br>• Per piece — MRS, T1, GM,3,0 |
| Judge and send to MCU | • Compare against the limits from the Core Service<br>• Send OK / NG to the MCU<br>• Confirm the value reached the database before the next piece |
| Error handling | • Report the cause to the Core Service<br>• Let the operator retry up to 3 times<br>• Stop and report the reason if it still fails |
| Heartbeat | • Send a heartbeat every 2 s |
