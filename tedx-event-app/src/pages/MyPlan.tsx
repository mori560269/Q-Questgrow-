import { Link } from "react-router-dom";
import { Qr } from "../components/Qr";
import { SessionCard } from "../components/SessionCard";
import { EVENT, SESSIONS } from "../data/event";
import { liveState, myBookings, useStore } from "../lib/store";

export function MyPlanPage() {
  const s = useStore((x) => x);
  const booked = myBookings(s);
  const waiting = SESSIONS.filter((x) => s.ledger.waitlist[x.id]?.includes(s.me.id));
  const checkedIn = Boolean(s.checkins[s.ticketCode]);

  return (
    <>
      <header className="hero compact">
        <div className="brand">マイプラン</div>
        <p style={{ marginTop: 4 }}>チケットと今日の予定</p>
      </header>
      <div className="page" style={{ marginTop: 12 }}>
        <div className="ticket">
          <div className="t-top">
            <div className="small" style={{ opacity: 0.7 }}>ADMISSION TICKET</div>
            <div style={{ fontWeight: 900, fontSize: 20, margin: "4px 0" }}>{EVENT.name}</div>
            <div className="small" style={{ opacity: 0.8 }}>{EVENT.dateLabel} ・ 9:30 開場</div>
          </div>
          <div className="t-cut" />
          <div className="t-bottom">
            <Qr value={s.ticketCode} />
            <div className="grow">
              <div className="small muted">参加者</div>
              <b>{s.me.name}</b>
              <div className="small muted" style={{ marginTop: 8 }}>チケット番号</div>
              <code style={{ fontWeight: 700 }}>{s.ticketCode}</code>
              <div style={{ marginTop: 8 }}>
                {checkedIn ? <span className="chip ok">✓ チェックイン済み</span> : <span className="chip warn">受付でQRを提示</span>}
              </div>
            </div>
          </div>
        </div>

        <div className="section"><h2>予約済み（{booked.length}）</h2></div>
        <div className="timeline">
          {booked.map((x) => {
            const st = liveState(x, s);
            return (
              <div key={x.id} className={`tl-item ${st === "live" ? "now" : ""} ${st === "done" ? "done" : ""}`} style={{ marginBottom: 10 }}>
                <SessionCard session={x} />
              </div>
            );
          })}
        </div>
        {booked.length === 0 && (
          <div className="empty">
            まだ予約がありません。<br />
            <Link to="/programs" className="link">プログラムを探す →</Link>
          </div>
        )}

        {waiting.length > 0 && (
          <>
            <div className="section"><h2>キャンセル待ち（{waiting.length}）</h2></div>
            <div className="stack">
              {waiting.map((x) => (
                <SessionCard key={x.id} session={x} />
              ))}
            </div>
          </>
        )}
      </div>
    </>
  );
}
