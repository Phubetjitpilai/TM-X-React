import {
  createContext, useCallback, useContext, useEffect, useRef, useState,
  type ReactNode,
} from "react";

/**
 * กล่องยืนยัน/แจ้งเตือนกลางของทั้งแอป — พอร์ตจาก uiConfirm/uiAlert ใน
 * Frontend/shared.js (คลาส .ui-dialog-* ยกมาจาก shared.css ทั้งชุด)
 *
 * ทำไมไม่ใช้ window.confirm/alert:
 *   1. หน้าตาเป็นของเบราว์เซอร์ ไม่เข้ากับหน้าอื่นในระบบ และบางเบราว์เซอร์
 *      มีตัวเลือก "ไม่ต้องแสดงกล่องนี้อีก" ซึ่งพอผู้ใช้ติ๊กแล้วปุ่ม Start จะ
 *      เริ่มวัดทันทีโดยไม่ถามอะไรเลย — อันตรายมากกับ session ที่สั่งเครื่องจริง
 *   2. ใส่ข้อความหลายบรรทัด/ตัวหนา/สีไม่ได้ ทั้งที่กล่องยืนยันของหน้านี้ต้อง
 *      แจกแจงว่าจะวัดกลุ่มไหนบ้าง
 *   3. มันบล็อก event loop ทั้งเส้น — SSE ที่เปิดค้างอยู่จะไม่ถูกประมวลผล
 *      ระหว่างที่กล่องเปิดอยู่
 *
 * ⚠ z-index 400 สูงกว่า .modal-overlay (200) โดยตั้งใจ — เด้งทับ Part Entry
 *   modal ได้เลยโดยไม่ต้องปิดฟอร์มก่อน (ปิดแล้วเปิดใหม่ผู้ใช้จะเห็นฟอร์ม
 *   กระพริบโดยไม่ได้อะไรเพิ่ม)
 */

export interface DialogOptions {
  title?: string;
  okLabel?: string;
  cancelLabel?: string;
  danger?: boolean;
}

interface DialogState extends DialogOptions {
  kind: "confirm" | "alert";
  message: ReactNode;
  resolve: (ok: boolean) => void;
}

interface DialogApi {
  confirm: (message: ReactNode, opts?: DialogOptions) => Promise<boolean>;
  alert: (message: ReactNode, opts?: DialogOptions) => Promise<void>;
}

const DialogCtx = createContext<DialogApi>({
  confirm: async () => false,
  alert: async () => {},
});

export function useDialog() {
  return useContext(DialogCtx);
}

export function DialogProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<DialogState | null>(null);
  const okRef = useRef<HTMLButtonElement>(null);

  const confirm = useCallback(
    (message: ReactNode, opts: DialogOptions = {}) =>
      new Promise<boolean>((resolve) => setState({ kind: "confirm", message, ...opts, resolve })),
    [],
  );

  const alert = useCallback(
    (message: ReactNode, opts: DialogOptions = {}) =>
      new Promise<void>((resolve) =>
        setState({ kind: "alert", message, ...opts, resolve: () => resolve() }),
      ),
    [],
  );

  // ปิดกล่องแล้วส่งคำตอบกลับให้ Promise — ต้องอ่าน state ผ่าน setState แบบ
  // ฟังก์ชัน ไม่ใช่ตัวแปรจาก closure เพราะ handler ถูกผูกไว้ตั้งแต่ render ก่อน
  const done = useCallback((ok: boolean) => {
    setState((s) => {
      s?.resolve(ok);
      return null;
    });
  }, []);

  // Esc = ยกเลิก (กล่องแจ้งเตือนถือว่ารับทราบ) — ให้เหมือนพฤติกรรมที่คนคุ้นเคย
  useEffect(() => {
    if (!state) return;
    okRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") done(state.kind === "alert");
      else if (e.key === "Enter" && state.kind === "alert") done(true);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [state, done]);

  return (
    <DialogCtx.Provider value={{ confirm, alert }}>
      {children}
      {state && (
        <div
          className="ui-dialog-overlay open"
          // คลิกพื้นหลัง = ยกเลิก · เช็ค target ให้ตรงกับตัว overlay เอง ไม่งั้น
          // คลิกในกล่องแล้วเมาส์ขยับออกมาปล่อยข้างนอกจะปิดกล่องทิ้ง
          onClick={(e) => { if (e.target === e.currentTarget) done(state.kind === "alert"); }}
        >
          <div className="ui-dialog-box">
            <div className="ui-dialog-title">
              {state.title ?? (state.kind === "alert" ? "แจ้งเตือน" : "ยืนยันการดำเนินการ")}
            </div>
            <div className="ui-dialog-msg">{state.message}</div>
            <div className="ui-dialog-actions">
              {state.kind === "confirm" && (
                <button type="button" className="ui-dialog-cancel" onClick={() => done(false)}>
                  {state.cancelLabel ?? "ยกเลิก"}
                </button>
              )}
              <button
                ref={okRef}
                type="button"
                className={`ui-dialog-ok${state.danger ? " danger" : ""}`}
                onClick={() => done(true)}
              >
                {state.okLabel ?? (state.kind === "alert" ? "รับทราบ" : "ตกลง")}
              </button>
            </div>
          </div>
        </div>
      )}
    </DialogCtx.Provider>
  );
}
