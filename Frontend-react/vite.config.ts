import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// ตอน dev รัน backend (uvicorn) แยกที่ port 8000 และ Vite dev server ที่ 5173
// proxy /api/* ไปที่ backend ตรงนี้เลย เพื่อให้โค้ดฝั่ง React เรียก fetch("/api/...")
// แบบ relative path ได้เหมือนกันทั้ง dev และ production (ตอน build จริง React
// กับ backend มาจาก origin เดียวกันอยู่แล้ว เพราะ main.py เสิร์ฟไฟล์ build
// เอง — ดู CLAUDE.md หัวข้อ Frontend Framework Migration)
export default defineConfig({
  plugins: [react()],
  server: {
    host : true,
    proxy: {
      // ⚠⚠ ต้องเป็น 127.0.0.1 ห้ามเปลี่ยนกลับเป็น localhost เด็ดขาด
      //
      // proxy ตัวนี้รันอยู่ใน Node และตั้งแต่ Node 17 เป็นต้นมา `localhost`
      // ถูก resolve เป็น ::1 (IPv6) ก่อน แต่ uvicorn รันด้วย --host 0.0.0.0
      // ซึ่งฟังเฉพาะ IPv4 → ทุก request ไปเคาะ ::1 ก่อนแล้วล้มเหลว ค่อย fallback
      // มา IPv4 **เสียเวลาทุกครั้งที่เรียก**
      //
      // หน้า Dashboard poll ทุก 4 วิ + SSE + คำขอตอนเปิดหน้าอีกสิบกว่าตัว
      // ค่าปรับตรงนี้จึงทบกันจนรู้สึกได้ว่าช้าลงชัดเจน
      // (สมัยยังเป็น .html เคยเจอเรื่องเดียวกันแล้วแก้ด้วยวิธีนี้มาแล้ว)
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
      // รูปผลการวัดถูกเสิร์ฟจาก static mount /media/alpl ของ backend
      // `/api/image-url/{id}` คืน path มาเป็น "/media/alpl/..." แล้วเอาไปใส่
      // <img src> ตรงๆ — ถ้าไม่ proxy เส้นนี้ ตอน dev รูปจะ 404 ทุกใบ
      // เพราะ Vite ไม่รู้จัก path นี้ (ตอน build จริงไม่มีปัญหา เพราะ backend
      // เสิร์ฟทั้งหน้าเว็บและรูปจาก origin เดียวกัน)
      "/media": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
});
