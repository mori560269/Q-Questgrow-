import { useSyncExternalStore } from "react";

type T = { id: number; text: string };
let items: T[] = [];
const subs = new Set<() => void>();
const emit = () => subs.forEach((s) => s());

export function toast(text: string) {
  const id = Date.now() + Math.random();
  items = [...items, { id, text }];
  emit();
  setTimeout(() => {
    items = items.filter((t) => t.id !== id);
    emit();
  }, 2800);
}

export function Toaster() {
  const list = useSyncExternalStore(
    (l) => {
      subs.add(l);
      return () => subs.delete(l);
    },
    () => items,
  );
  return (
    <div className="toasts" role="status" aria-live="polite">
      {list.map((t) => (
        <div className="toast" key={t.id}>
          {t.text}
        </div>
      ))}
    </div>
  );
}
