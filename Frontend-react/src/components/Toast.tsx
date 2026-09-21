import { createContext, useCallback, useContext, useRef, useState, type ReactNode } from "react";

interface ToastContextValue {
  show: (message: string) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

// ToastProvider: จำลอง showToast() ของ edit.html ต้นฉบับตรงๆ — toast เดียว
// บริเวณกลางล่างจอ (bottom-center) แสดงข้อความล่าสุดแทนที่ข้อความเก่าเสมอ
// (ไม่ใช่ stack หลายอันแบบที่เคยทำผิดไปก่อนหน้านี้) หายเองหลัง 2.6 วินาที
// เหมือนต้นฉบับ (ดู showToast ใน edit.html)
export function ToastProvider({ children }: { children: ReactNode }) {
  const [message, setMessage] = useState<string | null>(null);
  const timerRef = useRef<number | null>(null);

  const show = useCallback((msg: string) => {
    setMessage(msg);
    if (timerRef.current) window.clearTimeout(timerRef.current);
    timerRef.current = window.setTimeout(() => setMessage(null), 5000);
  }, []);

  return (
    <ToastContext.Provider value={{ show }}>
      {children}
      <div className={`toast${message ? " show" : ""}`}>{message ?? ""}</div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast ต้องถูกเรียกภายใน <ToastProvider>");
  return ctx;
}
