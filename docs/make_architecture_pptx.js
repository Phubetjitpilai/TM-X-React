/* สร้างสไลด์ System Architecture เป็น .pptx ที่แก้ไขได้ (ทุกกล่อง/เส้นเป็น shape จริง)
 *
 * รันด้วย:  node make_architecture_pptx.js
 * ต้องมี:   npm install pptxgenjs
 *
 * ⚠ พิกัดทั้งหมดอ้างอิงจาก docs/system_architecture_v2.svg (canvas 1600x800)
 *   แล้วย่อลงสไลด์ 13.3x7.5 นิ้วด้วยตัวคูณ K — ถ้าจะแก้ผัง ให้แก้ที่ SVG ก่อน
 *   แล้วค่อยลอกพิกัดมาที่นี่ จะได้ไม่มี 2 แหล่งที่เพี้ยนกันเอง
 */
const pptxgen = require("pptxgenjs");

const NAVY = "0F2E4C", BLUE = "2E7BA6", ORANGE = "C1651B";
const ZONE = "F5F8FA", WHITE = "FFFFFF", MUTED = "7A8794";
const FONT = "Arial";

const K = 13.3 / 1600;          // SVG unit → inch
const OY = 0.18;                // ขยับลงมาจากขอบบน (นิ้ว)
const X = v => v * K;
const Y = v => v * K + OY;
const S = v => v * K;

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE";     // 13.3 x 7.5 นิ้ว — ต้องตั้งก่อน addSlide เสมอ
const s = pres.addSlide();

/* ── หัวสไลด์ ─────────────────────────────────────────────────────────── */
s.addText("System Architecture", {
  x: X(40), y: Y(28), w: S(700), h: S(46),
  fontFace: FONT, fontSize: 26, bold: true, color: NAVY,
  align: "left", valign: "middle", margin: 0, isTextBox: true,
});

/* ── โซน 4 กลุ่ม (กรอบ + แถบหัวสีเข้ม) ─────────────────────────────────── */
const zones = [
  { x:  40, y: 200, w: 260, h: 355, t: "MEASUREMENT HARDWARE", fs: 8.5 },
  { x: 330, y: 200, w: 240, h: 355, t: "RASPBERRY PI",         fs: 9.5 },
  { x: 650, y: 200, w: 500, h: 355, t: "PC SERVER",            fs: 9.5 },
  { x:1180, y: 200, w: 370, h: 355, t: "USERS",                fs: 9.5 },
];
zones.forEach(z => {
  s.addShape(pres.ShapeType.rect, {
    x: X(z.x), y: Y(z.y), w: S(z.w), h: S(z.h),
    fill: { color: ZONE }, line: { color: NAVY, width: 1 },
  });
  s.addShape(pres.ShapeType.rect, {
    x: X(z.x), y: Y(z.y), w: S(z.w), h: S(34),
    fill: { color: NAVY }, line: { color: NAVY, width: 1 },
  });
  s.addText(z.t, {
    x: X(z.x), y: Y(z.y), w: S(z.w), h: S(34),
    fontFace: FONT, fontSize: z.fs, bold: true, color: WHITE,
    align: "center", valign: "middle", margin: 0, isTextBox: true,
  });
});

/* ── กล่องส่วนประกอบ ──────────────────────────────────────────────────── */
const boxes = [
  { x:  60, y: 255, w: 220, h: 60, c: ORANGE, t: "TM-X Controller",    sub: "192.168.10.11" },
  { x:  60, y: 405, w: 220, h: 60, c: ORANGE, t: "MCU" },
  { x: 350, y: 320, w: 220, h: 80, c: BLUE,   t: "Edge Controller",    sub: "Pi.py · 192.168.10.12" },
  { x: 675, y: 255, w: 220, h: 65, c: BLUE,   t: "Core Service",       sub: ":8000 · 192.168.10.10" },
  { x: 675, y: 345, w: 220, h: 65, c: BLUE,   t: "Data Receiver",      sub: ":21" },
  { x: 675, y: 445, w: 220, h: 65, c: BLUE,   t: "Power BI Gateway" },
  { x: 935, y: 345, w: 200, h: 70, c: BLUE,   t: "Database",           sub: "MySQL" },
  { x: 935, y: 445, w: 200, h: 65, c: BLUE,   t: "Image Server",       sub: ":8080" },
  { x:1200, y: 255, w: 330, h: 75, c: BLUE,   t: "Web Application",    sub: "Operator" },
  { x:1200, y: 425, w: 330, h: 75, c: BLUE,   t: "Power BI Dashboard", sub: "Viewer" },
  { x:1200, y: 100, w: 330, h: 55, c: ORANGE, t: "ADI Router",         sub: "172.20.10.0/24" },
  { x: 100, y: 620, w: 660, h: 58, c: ORANGE, t: "Network Switch",     sub: "Ethernet · 192.168.10.0/24" },
];
boxes.forEach(b => {
  s.addShape(pres.ShapeType.rect, {
    x: X(b.x), y: Y(b.y), w: S(b.w), h: S(b.h),
    fill: { color: b.c }, line: { color: b.c, width: 0.5 },
  });
  const runs = [{ text: b.t, options: { fontSize: 10.5, bold: true, breakLine: !!b.sub } }];
  if (b.sub) runs.push({ text: b.sub, options: { fontSize: 8.5, bold: false } });
  s.addText(runs, {
    x: X(b.x), y: Y(b.y), w: S(b.w), h: S(b.h),
    fontFace: FONT, color: WHITE, align: "center", valign: "middle",
    margin: 0, isTextBox: true,
  });
});

/* Power BI Service — กรอบประ แทนบริการบนคลาวด์ที่อยู่นอกระบบเรา */
s.addShape(pres.ShapeType.roundRect, {
  x: X(1180), y: Y(620), w: S(370), h: S(90), rectRadius: 0.45,
  fill: { color: WHITE }, line: { color: ORANGE, width: 1.5, dashType: "dash" },
});
s.addText(
  [{ text: "Power BI Service", options: { fontSize: 11, bold: true, breakLine: true } },
   { text: "Microsoft cloud",  options: { fontSize: 8.5 } }],
  { x: X(1180), y: Y(620), w: S(370), h: S(90),
    fontFace: FONT, color: ORANGE, align: "center", valign: "middle",
    margin: 0, isTextBox: true });

/* ── เส้นเชื่อม ───────────────────────────────────────────────────────────
 * ทุกเส้นในผังนี้เป็นแนวตั้งหรือแนวนอนล้วน จึงวาดทีละท่อนได้ตรงไปตรงมา
 * หัวลูกศรใส่เฉพาะท่อนสุดท้าย (และท่อนแรกถ้าเป็นลูกศร 2 หัว)
 */
function seg(x1, y1, x2, y2, opt = {}) {
  const horiz = y1 === y2;
  const line = { color: NAVY, width: 1.25 };
  if (opt.end)   line.endArrowType   = "triangle";
  if (opt.begin) line.beginArrowType = "triangle";
  const o = {
    x: X(Math.min(x1, x2)), y: Y(Math.min(y1, y2)),
    w: horiz ? S(Math.abs(x2 - x1)) : 0,
    h: horiz ? 0 : S(Math.abs(y2 - y1)),
    line,
  };
  if (horiz && x2 < x1) o.flipH = true;
  if (!horiz && y2 < y1) o.flipV = true;
  s.addShape(pres.ShapeType.line, o);
}
/** วาดเส้นหักศอกจากลิสต์จุด — หัวลูกศรลงท่อนสุดท้าย */
function poly(pts, { end = true, begin = false } = {}) {
  for (let i = 0; i < pts.length - 1; i++) {
    seg(pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1], {
      end:   end   && i === pts.length - 2,
      begin: begin && i === 0,
    });
  }
}
function tag(cx, cy, text, w = 90) {
  s.addText(text, {
    x: X(cx - w / 2), y: Y(cy - 9), w: S(w), h: S(18),
    fontFace: FONT, fontSize: 7, bold: true, color: NAVY,
    align: "center", valign: "middle", margin: 0, isTextBox: true,
    fill: { color: WHITE },
  });
}

poly([[280,270],[600,270],[600,377],[675,377]]);              tag(430, 262, "FTP  results + images", 150);
poly([[350,345],[315,345],[315,300],[280,300]]);              tag(315, 325, "TCP", 40);
poly([[350,375],[315,375],[315,435],[280,435]], {begin:true}); tag(315, 408, "Signal", 50);
poly([[570,360],[630,360],[630,287],[675,287]], {begin:true}); tag(630, 330, "HTTP", 45);
poly([[785,345],[785,320]]);
poly([[895,300],[915,300],[915,380],[935,380]], {begin:true});
poly([[935,400],[915,400],[915,477],[895,477]]);
poly([[895,275],[1200,275]]);                                 tag(1050, 265, "SSE", 40);
poly([[1200,310],[895,310]]);                                 tag(1050, 336, "HTTP", 45);
poly([[1200,475],[1135,475]]);                                tag(1168, 455, "HTTP", 45);
poly([[850,510],[850,665],[1180,665]]);                       tag(1010, 656, "HTTPS", 48);
poly([[1365,620],[1365,500]]);                                tag(1365, 563, "HTTPS", 48);
poly([[1365,155],[1365,200]]);
poly([[1200,127],[900,127],[900,200]], {begin:true});         tag(1050, 117, "Company LAN", 85);
poly([[170,620],[170,555]], {begin:true});
poly([[460,620],[460,555]], {begin:true});
poly([[700,620],[700,555]], {begin:true});

/* ── คำอธิบายสี ──────────────────────────────────────────────────────── */
const legend = [
  { x:  40, c: BLUE,   t: "Software components" },
  { x: 240, c: ORANGE, t: "Hardware and external services" },
  { x: 530, c: NAVY,   t: "Network boundary" },
];
legend.forEach(l => {
  s.addShape(pres.ShapeType.rect, {
    x: X(l.x), y: Y(746), w: S(17), h: S(17),
    fill: { color: l.c }, line: { color: l.c, width: 0.5 },
  });
  s.addText(l.t, {
    x: X(l.x + 26), y: Y(742), w: S(300), h: S(24),
    fontFace: FONT, fontSize: 9, color: NAVY,
    align: "left", valign: "middle", margin: 0, isTextBox: true,
  });
});
s.addText("Arrows show which way data travels · labels show the protocol", {
  x: X(720), y: Y(742), w: S(600), h: S(24),
  fontFace: FONT, fontSize: 8.5, color: MUTED,
  align: "left", valign: "middle", margin: 0, isTextBox: true,
});

s.addNotes(
  "ทุกกล่องและทุกเส้นเป็น shape ของ PowerPoint แก้ไขได้โดยตรง\n" +
  "ผังต้นฉบับอยู่ที่ docs/system_architecture_v2.svg — ถ้าแก้ผังใหญ่ให้แก้ที่นั่นก่อน"
);

pres.writeFile({ fileName: process.argv[2] || "system_architecture.pptx" })
  .then(f => console.log("เขียนไฟล์แล้ว:", f));
