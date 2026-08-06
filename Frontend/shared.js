/* ============================================================================
   shared.js — โค้ดที่ทุกหน้าใช้ร่วมกัน
   ============================================================================
   ของพวกนี้เคยถูกก๊อปไว้ครบชุดในทั้ง 4 หน้า (index / edit / export /
   report-template) เวลาแก้ทีต้องไล่แก้หลายที่ แล้วมักลืมที่ใดที่หนึ่ง
   ตัวอย่างที่เกิดจริงมาแล้ว:
     - แก้ CSS ของแถบเมนูบน แล้วพลาดจนเมนูเพี้ยนพร้อมกัน 3 หน้าโดยไม่มี error
     - `API` ตั้งเป็น http://localhost:8000 ตายตัวทั้ง 4 ไฟล์ พอเปิดหน้าเว็บ
       ผ่าน IP ของเครื่องในวง ทุกอย่างกลายเป็น cross-origin แล้ว SSE ถูกบล็อก
       ป้ายสถานะค้างที่ Offline ตลอด

   วิธีใช้: ใส่บรรทัดนี้ใน <head> ของทุกหน้า "ก่อน" <script> ของหน้านั้น
       <script src="shared.js"></script>
   ทุกอย่างในไฟล์นี้เป็น global ตั้งใจให้เรียกได้ตรงๆ (ไม่มี build step
   ไม่มี module bundler — เปิดไฟล์ แก้ เซฟ รีเฟรช จบ)
   ============================================================================ */

/* ── ที่อยู่ของ API ────────────────────────────────────────────────────────
   หน้าเว็บนี้ถูกเปิดได้หลายทาง และแต่ละทาง backend อยู่คนละที่กัน:

     เปิดยังไง                          origin ของหน้า        backend อยู่ที่
     ─────────────────────────────────  ────────────────────  ──────────────────
     backend เสิร์ฟเอง (ปกติ/หน้างาน)    127.0.0.1:8000        origin เดียวกัน
     Live Server ของ VS Code            127.0.0.1:5500        :8000 ของ host เดิม
     Vite dev server                    localhost:5173        :8000 ของ host เดิม
     เปิดไฟล์ตรงๆ                        file:// (ไม่มี origin) localhost:8000

   เคยตั้งเป็น http://localhost:8000 ตายตัว → เปิดผ่าน IP ในวงแล้วพัง
   เคยตั้งเป็น location.origin เฉยๆ      → เปิดผ่าน Live Server แล้วพัง
   จึงต้องดูจากพอร์ต: ถ้าอยู่ที่พอร์ตของ backend อยู่แล้วก็ใช้ origin เดิม
   ถ้าไม่ใช่ (แปลว่ากำลัง dev อยู่) ให้ชี้ไปที่ :8000 ของ host เดียวกัน

   บังคับเองได้ด้วยการเติม ?api=http://192.168.1.50:8000 ต่อท้าย URL ครั้งเดียว
   (จำไว้ให้ในเบราว์เซอร์นั้น) หรือล้างค่าด้วย ?api= เปล่าๆ */
const API = (() => {
  const BACKEND_PORT = '8000';
  const clean = u => String(u).replace(/\/+$/, '');
  try {
    const q = new URLSearchParams(location.search).get('api');
    if (q !== null) {
      if (q) { localStorage.setItem('tmx_api', clean(q)); return clean(q); }
      localStorage.removeItem('tmx_api');
    }
    const saved = localStorage.getItem('tmx_api');
    if (saved) return clean(saved);
  } catch (e) { /* โหมด private บางตัวห้ามใช้ localStorage — ข้ามไปใช้ค่าที่เดาเอา */ }

  if (location.protocol.startsWith('http')) {
    return location.port === BACKEND_PORT
      ? location.origin
      : `${location.protocol}//${location.hostname}:${BACKEND_PORT}`;
  }
  return `http://localhost:${BACKEND_PORT}`;
})();

/* ── ค่าคงที่ของการเทียบสเปก ───────────────────────────────────────────────
   ต้องมี epsilon เพราะเลขทศนิยมของ JS เพี้ยนที่หลักท้ายๆ (3.02 - 0.01 ได้
   3.0100000000000002) และ MySQL เก็บ FLOAT แบบไม่ตรงเป๊ะอยู่แล้ว (3.02 ถูก
   เก็บเป็น 3.0199999809265137) ถ้าเทียบตรงๆ ค่าที่อยู่ขอบพอดีจะถูกตัดสินว่า NG
   ทั้งที่ควรเป็น OK — ต้องตรงกับ _TOL_EPS ฝั่ง backend เสมอ */
const TOL_EPS = 1e-6;

/** ค่านี้อยู่ในสเปกไหม — คืน null ถ้าข้อมูลไม่ครบ (ยังไม่ได้ตั้ง Part Number) */
function withinTolerance(value, nominal, upperTol, lowerTol) {
  if (value == null || nominal == null || upperTol == null || lowerTol == null) return null;
  const lo = Number(nominal) - Number(lowerTol);
  const hi = Number(nominal) + Number(upperTol);
  return Number(value) >= lo - TOL_EPS && Number(value) <= hi + TOL_EPS;
}

/* ── ตัวช่วยเล็กๆ ─────────────────────────────────────────────────────────── */

/**
 * แปลง url ที่ได้จาก /api/image-url ให้ชี้ไปที่ backend เสมอ
 *
 * ⚠ ห้ามเอา data.url ไปใส่ <img src> ตรงๆ — backend คืนมาเป็น path สัมพัทธ์
 *   ("/media/alpl/31-07-2569/100_....jpg") ซึ่งเบราว์เซอร์จะไปขอจาก **origin
 *   ของหน้าเว็บ** ไม่ใช่จาก API:
 *     - เปิดที่ localhost:8000        → บังเอิญตรง เลยดูเหมือนใช้ได้
 *     - เปิดที่ 127.0.0.1:5500 (Live Server) → ไปขอที่ :5500 → 404 รูปแตก
 *     - เปิดจาก PC เครื่องอื่นในวง LAN      → เหมือนกัน รูปแตกทุกใบ
 *   ต่างจาก fetch() ที่เขียน `${API}/api/...` ไว้ชัดเจนอยู่แล้ว จุดนี้เลยหลุด
 *   มานาน เพราะบนเครื่อง dev ที่เปิดจาก :8000 มันใช้ได้พอดี
 *
 * รองรับข้อมูลเก่าที่เก็บ URL เต็มไว้ในคอลัมน์ image_path ด้วย (ยุค MinIO เช่น
 * "http://172.20.10.4:8080/images/test.png") — เจอแบบนั้นให้คืนค่าเดิมไปเลย
 */
function mediaUrl(u) {
  if (!u) return '';
  if (/^https?:\/\//i.test(u)) return u;
  return API + (u.startsWith('/') ? u : '/' + u);
}

/* ── กล่องยืนยัน/แจ้งเตือนกลาง ────────────────────────────────────────────
   ใช้แทน confirm()/alert() ของเบราว์เซอร์ทุกจุด เพราะกล่องของเบราว์เซอร์:
     - หน้าตาไม่เข้ากับหน้าเว็บเลย (ขึ้นว่า "127.0.0.1:8000 says" นำหน้าเสมอ)
     - จัดรูปแบบข้อความไม่ได้ ตัวหนา/ขึ้นบรรทัดใหม่ทำไม่ได้
     - บล็อกทั้งหน้าจอ ทำให้ SSE/timer ที่รันอยู่หยุดค้างไปด้วย
     - บางเบราว์เซอร์ให้ผู้ใช้ติ๊ก "ไม่ต้องแสดงอีก" แล้วกล่องจะหายไปเลย

   สร้าง element ครั้งแรกที่เรียกแล้วใช้ซ้ำ — หน้าไหนก็เรียกได้โดยไม่ต้องมี
   markup ของตัวเอง (ดูสไตล์ที่ shared.css) */
let _dialogEl = null;

function _ensureDialog() {
  if (_dialogEl) return _dialogEl;
  _dialogEl = document.createElement('div');
  _dialogEl.className = 'ui-dialog-overlay';
  _dialogEl.innerHTML =
    '<div class="ui-dialog-box">' +
      '<div class="ui-dialog-title"></div>' +
      '<div class="ui-dialog-msg"></div>' +
      '<div class="ui-dialog-actions">' +
        '<button type="button" class="ui-dialog-cancel"></button>' +
        '<button type="button" class="ui-dialog-ok"></button>' +
      '</div>' +
    '</div>';
  document.body.appendChild(_dialogEl);
  return _dialogEl;
}

/**
 * กล่องยืนยัน — คืน Promise<boolean>
 *
 * @param {string} message  ข้อความ (ใส่ HTML ได้ · ผู้เรียกต้อง escape เอง)
 * @param {object} [opts]   { title, okLabel, cancelLabel, danger }
 */
function uiConfirm(message, opts = {}) {
  const { title = 'ยืนยันการดำเนินการ', okLabel = 'ตกลง',
          cancelLabel = 'ยกเลิก', danger = false } = opts;
  const el = _ensureDialog();
  el.querySelector('.ui-dialog-title').textContent = title;
  el.querySelector('.ui-dialog-msg').innerHTML     = message;
  const ok     = el.querySelector('.ui-dialog-ok');
  const cancel = el.querySelector('.ui-dialog-cancel');
  ok.textContent     = okLabel;
  ok.className       = 'ui-dialog-ok' + (danger ? ' danger' : '');
  cancel.textContent = cancelLabel;
  cancel.style.display = '';
  el.classList.add('open');

  return new Promise(resolve => {
    const done = v => {
      el.classList.remove('open');
      ok.onclick = cancel.onclick = el.onclick = null;
      document.removeEventListener('keydown', onKey);
      resolve(v);
    };
    // Esc = ยกเลิก · คลิกพื้นหลัง = ยกเลิก — ให้เหมือนพฤติกรรมที่คนคุ้นเคย
    const onKey = e => { if (e.key === 'Escape') done(false); };
    document.addEventListener('keydown', onKey);
    el.onclick = e => { if (e.target === el) done(false); };
    ok.onclick     = () => done(true);
    cancel.onclick = () => done(false);
    ok.focus();
  });
}

/** กล่องแจ้งเตือน (ปุ่มเดียว) — คืน Promise ที่ resolve เมื่อผู้ใช้กดรับทราบ */
function uiAlert(message, opts = {}) {
  const { title = 'แจ้งเตือน', okLabel = 'รับทราบ' } = opts;
  const el = _ensureDialog();
  el.querySelector('.ui-dialog-title').textContent = title;
  el.querySelector('.ui-dialog-msg').innerHTML     = message;
  const ok     = el.querySelector('.ui-dialog-ok');
  const cancel = el.querySelector('.ui-dialog-cancel');
  ok.textContent = okLabel;
  ok.className   = 'ui-dialog-ok';
  cancel.style.display = 'none';     // แจ้งเตือนเฉยๆ ไม่มีอะไรให้ยกเลิก
  el.classList.add('open');

  return new Promise(resolve => {
    const done = () => {
      el.classList.remove('open');
      ok.onclick = el.onclick = null;
      document.removeEventListener('keydown', onKey);
      resolve();
    };
    const onKey = e => { if (e.key === 'Escape' || e.key === 'Enter') done(); };
    document.addEventListener('keydown', onKey);
    el.onclick = e => { if (e.target === el) done(); };
    ok.onclick = done;
    ok.focus();
  });
}

/** กันข้อความจากผู้ใช้/DB ไปพังโครง HTML ตอนเอาไปต่อสตริง */
function escapeHtml(text) {
  return String(text ?? '').replace(/[&<>"']/g, c => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
}

/** อ่านข้อความ error จาก response ของ FastAPI (ฟิลด์ detail) — ถ้าอ่านไม่ได้
    ค่อยใช้ข้อความสำรอง ไม่ปล่อยให้ผู้ใช้เห็น "[object Object]" */
async function errText(response, fallback = 'เกิดข้อผิดพลาด') {
  try {
    const d = await response.json();
    if (typeof d?.detail === 'string') return d.detail;
    if (Array.isArray(d?.detail)) return d.detail.map(x => x.msg || JSON.stringify(x)).join(', ');
  } catch (e) { /* ตอบมาไม่ใช่ JSON — ใช้ข้อความสำรองพร้อมรหัสสถานะ */ }
  // ต่อท้ายรหัส HTTP เสมอเมื่อไม่มี detail — เคยตัดออกไปแล้วเสียเวลาไล่บั๊กนาน
  // (ยิง limit เกินเพดานได้ 422 กลับมา แต่ข้อความบอกแค่ "ดึงข้อมูลไม่สำเร็จ")
  return `${fallback} (HTTP ${response.status})`;
}

/** ตัวเลขทศนิยม 3 ตำแหน่ง — ช่องว่างถ้าไม่มีค่า */
const fmtNum = (v, digits = 3) => (v == null || v === '' ? '' : Number(v).toFixed(digits));

/* ── Toast ────────────────────────────────────────────────────────────────
   ต้องมี <div class="toast" id="toast"></div> อยู่ในหน้า ถ้าไม่มีจะสร้างให้เอง
   มีชื่อเรียก 2 ชื่อ (showToast / toast) เพราะแต่ละหน้าเคยตั้งชื่อไม่ตรงกัน
   เก็บไว้ทั้งคู่เพื่อไม่ต้องไล่แก้จุดเรียกทั้งหมด */
let _toastTimer = null;
/**
 * แถบแจ้งเตือนล่างจอ — ใส่ปุ่มให้กดได้ด้วย (เช่น "เลิกทำ" หลังลบ)
 *
 * @param {string} message  ข้อความ
 * @param {number|string|object} [opts]
 *        number  → เวลาที่แสดง (ms) — รูปแบบเดิม ยังใช้ได้เหมือนเดิมทุกจุด
 *        string  → ชนิด ('success'/'error') เก็บไว้เผื่อใส่สีทีหลัง ไม่ถือเป็นเวลา
 *        object  → { ms, action: { label, onClick } }
 *
 * ⚠ ที่ต้องรับ string ด้วยเพราะมีโค้ดเรียก showToast(msg, 'error') อยู่จริง
 *   ของเดิมเอาไปใส่ setTimeout ตรงๆ ซึ่ง Number('error') = NaN → toast หาย
 *   ทันทีไม่ทันอ่าน (บั๊กเงียบ ไม่มี error ใน console ให้เห็นเลย)
 */
function showToast(message, opts) {
  let ms = 2600, action = null;
  if (typeof opts === 'number') ms = opts;
  else if (opts && typeof opts === 'object') {
    action = opts.action || null;
    // มีปุ่มให้กด → ต้องอยู่นานพอให้อ่านแล้วตัดสินใจ 2.6 วิสั้นเกินไป
    ms = opts.ms ?? (action ? 7000 : 2600);
  }

  let el = document.getElementById('toast');
  if (!el) {
    el = document.createElement('div');
    el.id = 'toast';
    el.className = 'toast';
    document.body.appendChild(el);
  }

  el.textContent = '';
  const span = document.createElement('span');
  span.textContent = message;      // ใช้ textContent เสมอ กันข้อความจาก DB/error พัง HTML
  el.appendChild(span);

  if (action) {
    const btn = document.createElement('button');
    btn.className = 'toast-action';
    btn.textContent = action.label;
    // ผูก onClick ของ "รอบนี้" ติดไปกับปุ่มตอนสร้างเลย — ถ้ากดลบรัวๆ toast ตัวใหม่
    // จะแทนที่ตัวเก่าทั้งก้อนพร้อมปุ่มใหม่ ปุ่มจึงชี้ไปที่รายการที่แสดงอยู่เสมอ
    btn.onclick = () => {
      el.classList.remove('show');
      clearTimeout(_toastTimer);
      action.onClick();
    };
    el.appendChild(btn);
  }

  el.classList.toggle('has-action', !!action);
  el.classList.add('show');
  clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => el.classList.remove('show'), ms);
}
function toast(message, opts) { return showToast(message, opts); }

/* ── ป้ายสถานะการเชื่อมต่อ + SSE ──────────────────────────────────────────
   ทุกหน้าโชว์ป้ายเดียวกันที่มุมขวาบน หน้าที่ไม่ได้ใช้ข้อมูลสดก็ยังเปิด SSE ค้าง
   ไว้เพื่อรู้ว่า backend ยังตอบอยู่ไหม */
/** สถานะการเชื่อมต่อล่าสุด — อ่านได้จากทุกหน้า */
let stationStatus = 'connecting';

/**
 * อัปเดตป้ายสถานะ + ยิง event `station-status` ให้หน้าที่สนใจ
 *
 * ⚠ ต้องยิง event ด้วย ไม่ใช่แค่เปลี่ยนข้อความบนป้าย — หน้า Home ใช้สถานะนี้
 * ตัดสินว่าปุ่ม Start กดได้ไหม ตอนย้ายฟังก์ชันนี้มาไว้ส่วนกลางครั้งแรกผมทำแค่
 * เปลี่ยนป้าย ตัวแปรที่หน้า Home ใช้จึงค้างที่ 'connecting' ตลอด ปุ่ม Start
 * เลยกดไม่ได้เลยทั้งที่ป้ายขึ้นว่า Online
 */
function setStationBadge(status) {
  stationStatus = status;
  const el = document.getElementById('station-badge');
  if (el) {
    const map = { online: '🟢 Online', offline: '🔴 Offline', connecting: '🟡 Connecting' };
    el.textContent = map[status] || status;
    el.className = `station-badge ${status}`;
  }
  document.dispatchEvent(new CustomEvent('station-status', { detail: status }));
}

/**
 * เชื่อม SSE พร้อมต่อใหม่อัตโนมัติเมื่อหลุด และคุมป้ายสถานะให้ด้วย
 *
 * @param {object}   opts
 * @param {object}   opts.events     แผนที่ชื่อ event -> ฟังก์ชันรับข้อมูล (parse JSON ให้แล้ว)
 * @param {Function} opts.onOpen     เรียกทุกครั้งที่ "ต่อสำเร็จ" ทั้งครั้งแรกและตอน reconnect
 * @param {Function} opts.onRestore  เรียกตอนหน้าถูกเรียกกลับมาจากปุ่ม Back (ดูด้านล่าง)
 *
 * เรื่อง onOpen สำคัญกว่าที่คิด: SSE ไม่มี replay/backfill เลย ถ้าหลุดกลางคัน
 * event ที่ backend ยิงออกไปตอนนั้นจะหายไปเฉยๆ โดยไม่มีทางรู้ หน้าที่ถือสถานะอยู่
 * (เช่น Dashboard) ต้องใช้จังหวะนี้ไปดึงสถานะจริงจาก backend มาเทียบใหม่ทุกครั้ง
 * ไม่งั้นปุ่ม Start/Pause จะค้างสถานะเก่าไม่ยอมเคลียร์
 *
 * ── ทำไมต้องปิดตอนออกจากหน้า ────────────────────────────────────────────
 * SSE เป็น connection ที่ "ค้างเปิดถาวร" และ HTTP/1.1 ให้เบราว์เซอร์เปิดไปที่
 * origin เดียวกันได้พร้อมกันแค่ 6 เส้น ถ้าไม่ปิดของเก่าตอนเปลี่ยนหน้า มันจะสะสม
 * ขึ้นเรื่อยๆ (เปิด 6 หน้า = ค้าง 6 เส้น) แล้ว "ไม่เหลือช่องให้ request อื่นเลย"
 * หน้าเว็บค้างสนิท — เกิดขึ้นจริงมาแล้วตอนสลับหน้าเร็วๆ จากเครื่องในวง LAN
 *
 * ใช้ pagehide ไม่ใช่ beforeunload เพราะ beforeunload ทำให้เบราว์เซอร์ปิด
 * BFCache ทั้งระบบ (กด Back จะช้าลงทุกหน้า)
 *
 * ── ทำไมต้องมี pageshow ─────────────────────────────────────────────────
 * pagehide ยิงตอนหน้าถูกเก็บเข้า BFCache ด้วย พอผู้ใช้กด Back เบราว์เซอร์เอา
 * หน้าเดิมกลับมาทั้งหน้าโดย "ไม่ยิง DOMContentLoaded อีก" — ถ้าไม่ต่อ SSE กลับ
 * หน้าจะดูปกติทุกอย่างแต่ข้อมูลสดตายสนิท ป้ายค้าง Online ทั้งที่ไม่ได้ต่ออยู่
 * ซึ่งเป็นบั๊กที่หายากกว่าอาการค้างเดิมเสียอีก เพราะไม่มีอะไรฟ้อง
 *
 * onRestore มีไว้ให้หน้าที่แสดงข้อมูลสด (Home/Edit) สั่งโหลดข้อมูลใหม่ตอนกด Back
 * — หน้าที่มีงานค้างในหน่วยความจำ (ตัวแก้ผังรายงาน) ห้ามใส่ เดี๋ยวงานที่ทำอยู่หาย
 */
function connectSSE(opts = {}) {
  const { events = {}, onOpen, onRestore } = opts;
  let es = null;
  let retryTimer = null;

  const open = () => {
    clearTimeout(retryTimer);
    retryTimer = null;
    if (es) { es.close(); es = null; }
    setStationBadge('connecting');
    es = new EventSource(`${API}/api/stream`);
    es.onopen = () => { setStationBadge('online'); if (onOpen) onOpen(); };
    es.onerror = () => {
      setStationBadge('offline');
      clearTimeout(retryTimer);
      retryTimer = setTimeout(open, 3000);
    };
    Object.entries(events).forEach(([name, handler]) => {
      es.addEventListener(name, e => {
        let data = null;
        try { data = e.data ? JSON.parse(e.data) : null; } catch (err) { data = e.data; }
        handler(data, e);
      });
    });
  };

  // ปิดให้สนิท: ทั้งตัว connection และ timer ที่นัดต่อใหม่ไว้
  // (ถ้าไม่เคลียร์ timer มันจะไปเปิดเส้นใหม่อีก 3 วิถัดมาทั้งที่หน้าไปแล้ว)
  const close = () => {
    clearTimeout(retryTimer);
    retryTimer = null;
    if (es) { es.close(); es = null; }
  };

  open();

  window.addEventListener('pagehide', close);
  window.addEventListener('pageshow', e => {
    // persisted = true เท่านั้น คือ "กลับมาจาก BFCache" — ตอนโหลดหน้าครั้งแรก
    // pageshow ก็ยิงเหมือนกัน (persisted=false) ถ้าไม่เช็คจะต่อซ้ำเป็น 2 เส้น
    if (!e.persisted) return;
    open();
    if (onRestore) onRestore();
  });

  return { close, reconnect: open };
}

/* ── แถบเมนูบน ────────────────────────────────────────────────────────────
   เปิด/ปิด dropdown ของ Export และไฮไลต์หน้าที่กำลังเปิดอยู่ให้อัตโนมัติ
   โดยดูจากชื่อไฟล์ใน URL — ไม่ต้องไปใส่ class="active" เองในแต่ละหน้าอีก
   (เดิมใส่มือ แล้วลืมอัปเดตตอนเพิ่มหน้าใหม่) */
function initTopbar() {
  const menu = document.getElementById('export-menu');
  const btn = document.getElementById('export-menu-btn');
  if (menu && btn) {
    const setOpen = open => {
      menu.classList.toggle('open', open);
      btn.setAttribute('aria-expanded', open ? 'true' : 'false');
    };
    btn.addEventListener('click', e => { e.stopPropagation(); setOpen(!menu.classList.contains('open')); });
    btn.addEventListener('keydown', e => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setOpen(!menu.classList.contains('open')); }
    });
    document.addEventListener('click', e => { if (!menu.contains(e.target)) setOpen(false); });
    document.addEventListener('keydown', e => { if (e.key === 'Escape') setOpen(false); });
  }

  // ไฮไลต์หน้าปัจจุบัน — report-template ถือเป็นส่วนหนึ่งของ Export
  const page = (location.pathname.split('/').pop() || 'index.html').toLowerCase();
  const format = new URLSearchParams(location.search).get('format');
  const isExport = page.startsWith('export') || page.startsWith('report-template');

  document.querySelectorAll('.topbar-nav .topbar-link').forEach(a => {
    const href = (a.getAttribute('href') || '').split('?')[0].toLowerCase();
    a.classList.toggle('active', !!href && href === page);
  });
  if (isExport && btn) btn.classList.add('active');
  document.querySelectorAll('#export-menu .topbar-dropdown a').forEach(a => {
    const f = new URLSearchParams((a.getAttribute('href') || '').split('?')[1] || '').get('format');
    a.classList.toggle('active', isExport && !!format && f === format);
  });
}

/* ── ตาราง lookup ─────────────────────────────────────────────────────────
   ทุกหน้าที่มีฟอร์มต้องดึงรายการพวกนี้มาทำ dropdown เหมือนกันหมด
   ดึงทีเดียวแล้ว cache ไว้ในหน่วยความจำของแท็บนั้น — เรียกซ้ำได้ไม่ยิงซ้ำ
   ส่ง force = true ถ้าเพิ่งเพิ่ม/แก้ค่าใน lookup แล้วอยากได้ของใหม่ */
let _lookupCache = null;
async function loadLookups(force = false) {
  if (_lookupCache && !force) return _lookupCache;
  const get = async path => {
    try {
      const r = await fetch(`${API}${path}`);
      return r.ok ? await r.json() : [];
    } catch (e) { return []; }
  };
  const [operators, owners, vendors, handlers, templates, packageSizes, partNumbers] =
    await Promise.all([
      get('/api/operators'), get('/api/owners'), get('/api/vendors'),
      get('/api/handlers'), get('/api/templates'), get('/api/package-sizes'),
      get('/api/part-numbers/all'),
    ]);
  _lookupCache = { operators, owners, vendors, handlers, templates, packageSizes, partNumbers };
  return _lookupCache;
}
