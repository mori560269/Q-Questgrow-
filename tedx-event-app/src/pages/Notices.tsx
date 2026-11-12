import { useEffect } from "react";
import { SubHeader } from "../components/SubHeader";
import { actions, useStore } from "../lib/store";
import { fmt } from "../lib/time";

export function NoticesPage() {
  const s = useStore((x) => x);
  useEffect(() => {
    if (s.notices.some((n) => !n.read)) actions.markNoticesRead();
  }, [s.notices]);

  return (
    <>
      <SubHeader title="お知らせ" />
      <div className="page">
        <div className="section" style={{ marginTop: 4 }}><h2>運営からのお知らせ</h2></div>
        <div className="stack">
          {s.announcements.map((a) => (
            <div key={a.id} className={`banner ${a.level}`} style={{ display: "block" }}>
              <div className="small" style={{ fontWeight: 700 }}>{fmt(a.at)} {a.level === "urgent" ? "【重要】" : ""}</div>
              <div>{a.ja}</div>
              <div className="small" style={{ opacity: 0.75, marginTop: 4 }}>{a.en}</div>
            </div>
          ))}
        </div>
        <div className="section"><h2>あなたへの通知</h2></div>
        <div className="card">
          {s.notices.length === 0 && <div className="empty">通知はありません</div>}
          {s.notices.map((n, i) => (
            <div key={n.id}>
              {i > 0 && <div className="divider" />}
              <div className="row" style={{ alignItems: "flex-start" }}>
                <span className="small muted" style={{ width: 40 }}>{fmt(n.at)}</span>
                <span className="small grow" style={{ lineHeight: 1.6 }}>{n.text}</span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </>
  );
}
