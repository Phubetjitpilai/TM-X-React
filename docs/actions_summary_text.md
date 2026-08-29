# Actions Summary — ข้อความที่เกลาแล้ว

| Layer | Reason |
|---|---|
| Web Application | Control the TM-X and show measurement results as they happen |
| Core Service | Keep all session state and decide OK / NG, so the machine and the database always agree |
| Data Receiver | Receive values and images from the TM-X over FTP and forward them to the Core Service |
| Image Server | Serve the measurement images that the Power BI dashboard links to |
| Database | Store every measurement so the results outlive the session |
| Edge Controller | Send commands to the TM-X over TCP and exchange signals with the MCU |
| Power BI Dashboard | Let viewers pull the numbers themselves instead of waiting for an operator |

---

## ทางเลือก B — เติมเหตุผลสั้น ๆ ต่อท้าย (ถ้าอยากให้ตรงกับหัวคอลัมน์ "Reason")

| Layer | Reason |
|---|---|
| Web Application | Replace operating the KEYENCE screen by hand — one place to start, stop and watch |
| Core Service | Keep every pass / fail rule in one place, so the machine can never disagree with the database |
| Data Receiver | Take results and images straight from the TM-X, so the Edge Controller never carries them |
| Image Server | Serve images by URL, so the dashboard never needs access to the file system |
| Database | Keep the record that reports and Power BI read from, long after the session ends |
| Edge Controller | Reach the two machine protocols the PC cannot — TCP to the TM-X, Serial to the MCU |
| Power BI Dashboard | Let viewers pull the numbers themselves instead of waiting for an operator |
