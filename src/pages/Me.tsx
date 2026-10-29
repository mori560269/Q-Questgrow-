import { useNavigate } from "react-router-dom";
import { Avatar } from "../components/Avatar";
import { SubHeader } from "../components/SubHeader";
import { toast } from "../components/Toast";
import type { Role } from "../data/event";
import { actions, useStore } from "../lib/store";

export function MePage() {
  const me = useStore((s) => s.me);
  const nav = useNavigate();

  const setRole = (role: Role) => {
    actions.updateProfile({ role });
    toast(role === "staff" ? "スタッフモードに切り替えました（下部タブに「運営」が表示されます）" : "来場者モードに切り替えました");
  };

  return (
    <>
      <SubHeader title="プロフィール" />
      <div className="page">
        <div className="card center">
          <div className="row" style={{ justifyContent: "center" }}>
            <Avatar name={me.name} hue={me.hue} size={80} />
          </div>
          <input
            className="input center"
            style={{ marginTop: 12, fontWeight: 700 }}
            value={me.name}
            onChange={(e) => actions.updateProfile({ name: e.target.value })}
            aria-label="表示名"
          />
          <input
            className="input center"
            style={{ marginTop: 8 }}
            value={me.title}
            placeholder="肩書き（例: デザイナー / 大学生）"
            onChange={(e) => actions.updateProfile({ title: e.target.value })}
            aria-label="肩書き"
          />
          <textarea
            className="input"
            style={{ marginTop: 8 }}
            rows={2}
            value={me.bio}
            placeholder="ひとこと自己紹介"
            onChange={(e) => actions.updateProfile({ bio: e.target.value })}
            aria-label="自己紹介"
          />
        </div>

        <div className="section"><h2>モード</h2></div>
        <div className="card">
          <div className="seg">
            <button className={me.role === "attendee" ? "on" : ""} onClick={() => setRole("attendee")}>来場者</button>
            <button className={me.role === "staff" ? "on" : ""} onClick={() => setRole("staff")}>運営スタッフ</button>
          </div>
          <p className="small muted" style={{ marginBottom: 0, lineHeight: 1.6 }}>
            デモ用の切り替えです。本番ではスタッフアカウントの認証で運営機能を開放します。
            別タブで「来場者」と「運営」を開くと、配信・遅延・問い合わせがリアルタイムで同期します。
          </p>
          {me.role === "staff" && (
            <button className="btn dark block" style={{ marginTop: 10 }} onClick={() => nav("/ops")}>運営ダッシュボードへ</button>
          )}
        </div>

        <div className="section"><h2>デモデータ</h2></div>
        <div className="card">
          <button
            className="btn secondary block"
            onClick={() => {
              if (!confirm("予約・つながり・問い合わせなどのデモデータをすべて初期化しますか？")) return;
              actions.reset();
              toast("初期化しました");
            }}
          >
            デモデータを初期化
          </button>
        </div>
      </div>
    </>
  );
}
