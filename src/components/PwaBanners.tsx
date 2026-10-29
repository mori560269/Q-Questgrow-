import { useState } from "react";
import { applyUpdate, isIos, promptInstall, usePwa } from "../lib/pwa";
import { Icon } from "./Icon";

const DISMISS_KEY = "tedx-install-dismissed";

/** オフライン表示と新バージョン通知（全画面共通） */
export function PwaStatus() {
  const { online, waitingWorker } = usePwa();
  return (
    <>
      {!online && <div className="offline-bar">オフラインです。保存済みの予約・チケット・マップは引き続き使えます</div>}
      {waitingWorker && (
        <div className="update-bar">
          <span>新しいバージョンがあります</span>
          <button className="btn sm" onClick={applyUpdate}>更新</button>
        </div>
      )}
    </>
  );
}

/** ホーム画面への追加を案内するカード（ホームに表示） */
export function InstallCard() {
  const { installEvent, installed } = usePwa();
  const [dismissed, setDismissed] = useState(() => {
    try {
      return localStorage.getItem(DISMISS_KEY) === "1";
    } catch {
      return false;
    }
  });
  const ios = isIos();
  if (installed || dismissed || (!installEvent && !ios)) return null;

  const dismiss = () => {
    setDismissed(true);
    try {
      localStorage.setItem(DISMISS_KEY, "1");
    } catch {
      // 保存できなくても今回は閉じる
    }
  };

  return (
    <div className="card row install-card" style={{ marginTop: 14 }}>
      <img src="/icons/icon-192.png" width={48} height={48} alt="" style={{ borderRadius: 12 }} />
      <div className="grow">
        <b style={{ fontSize: 14 }}>ホーム画面に追加</b>
        <div className="small muted" style={{ lineHeight: 1.5 }}>
          {installEvent ? "アプリとしてすぐ開けて、電波が弱くてもチケットを表示できます" : "共有ボタン（□↑）→「ホーム画面に追加」でアプリとして使えます"}
        </div>
      </div>
      {installEvent && (
        <button className="btn sm" onClick={promptInstall}>追加</button>
      )}
      <button className="icon-btn" style={{ background: "transparent", color: "var(--muted)", width: 28, height: 28 }} onClick={dismiss} aria-label="閉じる">
        <Icon name="x" size={16} />
      </button>
    </div>
  );
}
