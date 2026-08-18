import { BrowserRouter, Routes, Route } from "react-router-dom";
import Layout from "./components/Layout";
import { ToastProvider } from "./components/Toast";
import { DialogProvider } from "./components/Dialog";
import DashboardPage from "./pages/DashboardPage";
import EditPage from "./pages/EditPage";
import ExportPage from "./pages/ExportPage";
import ReportTemplatePage from "./pages/ReportTemplatePage";

// App: SPA เดียว + React Router ตามที่ตกลงกันไว้ (ดู CLAUDE.md หัวข้อ
// Frontend Framework Migration) route "/", "/edit", "/export" อยู่ใน React
// app เดียวกัน แชร์ Layout/topbar เดียวกัน แทนการแยก build 3 ไฟล์ html แบบเดิม
export default function App() {
  return (
    <ToastProvider>
      {/* DialogProvider อยู่นอก Router — กล่องยืนยันต้องอยู่ได้ทุกหน้า และเป็น
          overlay ระดับ document ไม่ผูกกับ route ไหน */}
      <DialogProvider>
      <BrowserRouter>
        <Routes>
          <Route element={<Layout />}>
            <Route index element={<DashboardPage />} />
            <Route path="edit" element={<EditPage />} />
            <Route path="export" element={<ExportPage />} />
            {/* ตัวจัดผังรายงาน PDF/Excel — เปิดต่อจากขั้นที่ 1 ของ Export
                (?format=pdf|excel · ?id=N เมื่อเข้ามาแก้ของเดิม) */}
            <Route path="report-template" element={<ReportTemplatePage />} />
          </Route>
        </Routes>
      </BrowserRouter>
      </DialogProvider>
    </ToastProvider>
  );
}
