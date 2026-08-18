/** ไอคอน ALPL — ชิ้นงานสี่เหลี่ยมพร้อม contact pin 6 จุดรอบข้าง
 *
 *  ใช้ในตาราง Measurements เป็นปุ่มเปิดรายงานของแถวที่มีรูป
 *
 *  📌 ฝั่ง vanilla เก็บพิกัดชุดนี้ไว้ **2 ที่** — `<symbol id="icon-alpl">` ใน
 *     index.html กับไฟล์ assets/alpl-icon.svg แล้วเขียนคอมเมนต์เตือนไว้ว่า
 *     "แก้ที่ไหนต้องแก้อีกที่ด้วย" ฝั่งนี้ทำเป็น component เดียวจบ ไม่มีให้ลืม
 *     (เป็นเหตุผลหนึ่งที่ย้ายมา React ตั้งแต่แรก)
 */
export default function AlplIcon() {
  return (
    // overflow:visible กันเบราว์เซอร์เฉือนขอบไอคอนถ้าคำนวณ viewport ไม่ตรงกับ
    // กล่องปุ่มพอดี — ค่าเริ่มต้นของ <svg> คือ overflow:hidden ซึ่งจะตัดด้านขวา/
    // ด้านล่างหายไปเงียบ ๆ โดยไม่มีอะไรบอก
    <svg viewBox="0 0 100 100" width="100%" height="100%" preserveAspectRatio="xMidYMid meet" aria-hidden="true">
      <rect width="100" height="100" rx="20" fill="#B3B3B3" />
      <rect x="20" y="20" width="60" height="60" rx="5" fill="#D9D9D9" />
      <rect x="25" y="25" width="50" height="50" rx="5" fill="#757575" />
      <circle cx="11" cy="15" r="5" fill="#767676" />
      <circle cx="11.5" cy="50.5" r="2.5" fill="#767676" />
      <circle cx="11" cy="85" r="5" fill="#767676" />
      <circle cx="89" cy="15" r="5" fill="#767676" />
      <circle cx="89.5" cy="50.5" r="2.5" fill="#767676" />
      <circle cx="89" cy="85" r="5" fill="#767676" />
    </svg>
  );
}
