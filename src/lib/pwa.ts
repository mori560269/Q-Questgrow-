// PWA まわりの状態：インストール可否・オフライン・新バージョンの有無
import { useSyncExternalStore } from "react";

type BeforeInstallPromptEvent = Event & {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
};

type PwaState = {
  installEvent: BeforeInstallPromptEvent | null;
  installed: boolean;
  online: boolean;
  waitingWorker: ServiceWorker | null;
};

const isStandalone = () =>
  window.matchMedia("(display-mode: standalone)").matches || (navigator as { standalone?: boolean }).standalone === true;

let state: PwaState = {
  installEvent: null,
  installed: typeof window !== "undefined" && isStandalone(),
  online: typeof navigator === "undefined" ? true : navigator.onLine,
  waitingWorker: null,
};
const subs = new Set<() => void>();
const set = (p: Partial<PwaState>) => {
  state = { ...state, ...p };
  subs.forEach((s) => s());
};

export function usePwa(): PwaState {
  return useSyncExternalStore(
    (l) => {
      subs.add(l);
      return () => subs.delete(l);
    },
    () => state,
  );
}

export const isIos = () => /iphone|ipad|ipod/i.test(navigator.userAgent) && !("MSStream" in window);

export async function promptInstall(): Promise<boolean> {
  const e = state.installEvent;
  if (!e) return false;
  await e.prompt();
  const { outcome } = await e.userChoice;
  set({ installEvent: null, installed: outcome === "accepted" });
  return outcome === "accepted";
}

export function applyUpdate() {
  state.waitingWorker?.postMessage("skipWaiting");
}

export function initPwa() {
  window.addEventListener("beforeinstallprompt", (e) => {
    e.preventDefault(); // ブラウザ標準のミニバーを出さず、アプリ内のバナーから案内する
    set({ installEvent: e as BeforeInstallPromptEvent });
  });
  window.addEventListener("appinstalled", () => set({ installed: true, installEvent: null }));
  window.addEventListener("online", () => set({ online: true }));
  window.addEventListener("offline", () => set({ online: false }));

  // 開発中は Vite の HMR と競合するので本番ビルドのみ登録
  if (!import.meta.env.PROD || !("serviceWorker" in navigator)) return;

  window.addEventListener("load", async () => {
    const reg = await navigator.serviceWorker.register("/sw.js");
    const track = (w: ServiceWorker | null) => {
      if (!w) return;
      w.addEventListener("statechange", () => {
        // 既に旧バージョンが動いている時だけ「更新あり」を出す（初回インストール時は出さない）
        if (w.state === "installed" && navigator.serviceWorker.controller) set({ waitingWorker: w });
      });
    };
    if (reg.waiting && navigator.serviceWorker.controller) set({ waitingWorker: reg.waiting });
    track(reg.installing);
    reg.addEventListener("updatefound", () => track(reg.installing));

    let reloaded = false;
    navigator.serviceWorker.addEventListener("controllerchange", () => {
      if (reloaded) return;
      reloaded = true;
      window.location.reload();
    });
  });
}
