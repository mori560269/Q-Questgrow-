import { Link, useParams } from "react-router-dom";
import { Avatar } from "../components/Avatar";
import { Icon } from "../components/Icon";
import { ReserveButton } from "../components/ReserveButton";
import { KIND_COLOR, SeatBadge, StatusChip } from "../components/SessionCard";
import { SubHeader } from "../components/SubHeader";
import { toast } from "../components/Toast";
import { KIND_LABEL, SESSIONS, SPEAKERS, ZONES } from "../data/event";
import { findConflict, statusOf } from "../lib/reservation";
import { actions, effective, seatsLeft, useStore } from "../lib/store";
import { fmtRange } from "../lib/time";

export function ProgramDetailPage() {
  const { id } = useParams();
  const s = useStore((x) => x);
  const session = SESSIONS.find((x) => x.id === id);
  if (!session) return <div className="empty">プログラムが見つかりません</div>;

  const { start, end, delay } = effective(session, s);
  const room = ZONES.find((z) => z.id === session.roomId)!;
  const speakers = SPEAKERS.filter((sp) => session.speakerIds.includes(sp.id));
  const mine = statusOf(s.ledger, session.id, s.me.id);
  const conflict = !mine ? findConflict(s.ledger, SESSIONS, session, s.me.id) : undefined;
  const left = seatsLeft(session, s);
  const filled = session.capacity - Math.max(0, left);

  return (
    <>
      <SubHeader title={KIND_LABEL[session.kind]} />
      <div className="page">
        <div className="card" style={{ background: `linear-gradient(150deg, ${KIND_COLOR[session.kind]}, #141a3a 75%)`, color: "#fff" }}>
          <div className="row wrap" style={{ gap: 6 }}>
            <span className="chip dark">{KIND_LABEL[session.kind]}</span>
            <StatusChip session={session} />
            {session.tags.map((t) => (
              <span key={t} className="chip" style={{ background: "#ffffff22", color: "#fff" }}>#{t}</span>
            ))}
          </div>
          <h2 style={{ fontSize: 21, lineHeight: 1.4, margin: "12px 0 8px" }}>{session.title}</h2>
          <div className="row small" style={{ opacity: 0.9 }}>
            <Icon name="clock" size={16} /> {fmtRange(start, end)}
            {delay > 0 && <b style={{ color: "#ffb4ab" }}>（{delay}分遅れ）</b>}
          </div>
          <div className="row small" style={{ opacity: 0.9, marginTop: 4 }}>
            <Icon name="pin" size={16} /> {room.name}
          </div>
        </div>

        <div className="card">
          <p style={{ margin: 0, lineHeight: 1.8, fontSize: 14 }}>{session.description}</p>
        </div>

        {session.requiresReservation && (
          <div className="card">
            <div className="row between">
              <b>予約状況</b>
              <SeatBadge session={session} />
            </div>
            <div className="meter" style={{ margin: "10px 0 6px" }}>
              <i style={{ width: `${(filled / session.capacity) * 100}%`, background: left <= 0 ? "var(--danger)" : "var(--navy-2)" }} />
            </div>
            <div className="small muted">
              定員 {session.capacity}名 ・ 残り {Math.max(0, left)}席
              {(s.ledger.waitlist[session.id]?.length ?? 0) > 0 && ` ・ キャンセル待ち ${s.ledger.waitlist[session.id].length}名`}
            </div>
            {conflict && (
              <div className="banner warn" style={{ marginTop: 10 }}>
                ⚠️ 予約済みの「{conflict.title}」と時間が重なっています
              </div>
            )}
            <div style={{ marginTop: 12 }}>
              <ReserveButton session={session} />
            </div>
            {mine === "waitlisted" && (
              <button
                className="link"
                style={{ marginTop: 10 }}
                onClick={() => {
                  actions.releaseSeat(session);
                  toast("デモ：他の参加者が1席キャンセルしました");
                }}
              >
                デモ：誰かがキャンセルして空席が出たら？
              </button>
            )}
          </div>
        )}

        {speakers.length > 0 && (
          <>
            <div className="section"><h2>登壇者</h2></div>
            {speakers.map((sp) => (
              <div key={sp.id} className="card row" style={{ alignItems: "flex-start" }}>
                <Avatar name={sp.name} hue={sp.hue} size={52} />
                <div className="grow">
                  <b>{sp.name}</b>
                  <div className="small muted">{sp.title}</div>
                  <p className="small" style={{ margin: "6px 0 0", lineHeight: 1.6 }}>{sp.bio}</p>
                </div>
              </div>
            ))}
          </>
        )}

        <Link to={`/map?to=${room.id}`} className="card row" style={{ marginTop: 12 }}>
          <span className="q-ic" style={{ width: 44, height: 44, borderRadius: 14, display: "grid", placeItems: "center", background: "#f1f2f8" }}>
            <Icon name="route" />
          </span>
          <div className="grow">
            <b>{room.name}への行き方</b>
            <div className="small muted">マップでルートを表示</div>
          </div>
          <span className="muted">›</span>
        </Link>
      </div>
    </>
  );
}
