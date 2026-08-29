# Summary — ข้อความแบบย่อหน้า

**Six months, in one page**

---

**THE JOB**

ALPL plates are inspected in the PM Kit room before they go back onto a test handler. Until now that meant an operator working the KEYENCE TM-X panel by hand, reading each measurement off the screen and writing it down. The readings lived on paper, so there was nothing to search later and no image to look back at.

**WHAT WAS BUILT**

The system replaces that with one screen. The operator enters the parts, presses Start, and from there the edge controller drives the TM-X while the values and images come back on their own — every reading stored with the picture the camera took. One service holds all the state and makes the pass or fail decision, so the machine and the database can never disagree. Records can be corrected, exported as CSV, Excel or PDF, and read in Power BI without waiting for anyone to send them.

**WHAT HAD TO CHANGE**

Two things forced the design to move. Company policy would not let a Raspberry Pi onto the corporate network, so the PC became the server and the Pi became an edge controller beside the machine. And once the camera was ready it measured on its own schedule and pushed a stream of images at us, until it was switched to an external trigger so that nothing is measured without one explicit command per part.

**WHERE IT STANDS**

Four of the eight parts are finished — the core service, the data receiver, the image server and the database. Three are on track: the web interface, the Power BI dashboard, and the integration with the MCU. The measuring program in the TM-X starts today, and next week the PC server goes onto the floor so operators can run real parts on it.

---

**Everything the software has to do already works end to end. What is left is the last hardware signal, and the first real week in the hands of the people who will use it.**
