# Summary — 7 ย่อหน้าสั้น (เกลาแล้ว)

**1 · Current flow**
An ALPL is taken out of the kit, placed on the glass, aligned by hand and matched to a program. The operator reads each value off the screen and writes it down — eight pieces take about 2.55 minutes.

**2 · Problem**
Those records live in Excel, split across sheets with no standard naming, and the specifications are not stored anywhere central — to see them you have to go and ask the operator. Worse, the numbers themselves cannot be trusted: **we found 700 of 1,978 parts — 35.39% — recorded with the wrong result.**

**3 · New flow**
In the new flow the operator fills in what is being measured and presses Start. The edge controller loads the program and triggers each part, and the TM-X sends the value and the image straight to the PC. Nobody reads a number off a screen.

**4 · Scope**
A week of records showed the HT shape is measured far more often than the others, so that is where the system is aimed first. At 16 to 20 parts a day — roughly 5,000 a year — the volume is small enough to run on a local PC beside the machine, so no company server was needed.

**5 · Action**
The system is made of eight parts: the web application, core service, data receiver, image server, database, edge controller, the Power BI dashboard, and the measuring program in the TM-X.

**6 · Current progress**
Four are finished, three are on track, and one has not started.

**7 · Next progress**
The measuring program in the TM-X starts today. Next week the PC server goes onto the floor so operators can run real parts on it.

---

**Everything the software has to do already works end to end — what is left is the last hardware signal, and the first real week on the floor.**
