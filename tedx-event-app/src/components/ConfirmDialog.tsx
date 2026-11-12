import { useSyncExternalStore } from "react";

// window.confirm() は埋め込み表示（WebView・iframe）で無効化されることがあるため、アプリ内ダイアログで確認する
type Pending = { message: string; okLabel: string; danger: boolean; resolve: (ok: boolean) => void };

let pending: Pending | null = null;
const subs = new Set<() => void>();
const emit = () => subs.forEach((s) => s());

export function confirmDialog(message: string, opts: { okLabel?: string; danger?: boolean } = {}): Promise<boolean> {
  pending?.resolve(false);
  return new Promise((resolve) => {
    pending = { message, okLabel: opts.okLabel ?? "OK", danger: opts.danger ?? false, resolve };
    emit();
  });
}

function close(ok: boolean) {
  pending?.resolve(ok);
  pending = null;
  emit();
}

export function ConfirmHost() {
  const p = useSyncExternalStore(
    (l) => {
      subs.add(l);
      return () => subs.delete(l);
    },
    () => pending,
  );
  if (!p) return null;
  return (
    <div className="dialog-backdrop" onClick={() => close(false)}>
      <div className="dialog" role="alertdialog" aria-modal="true" aria-labelledby="confirm-msg" onClick={(e) => e.stopPropagation()}>
        <p id="confirm-msg">{p.message}</p>
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button className="btn secondary" onClick={() => close(false)} autoFocus>やめる</button>
          <button className={`btn ${p.danger ? "" : "dark"}`} onClick={() => close(true)}>{p.okLabel}</button>
        </div>
      </div>
    </div>
  );
}
