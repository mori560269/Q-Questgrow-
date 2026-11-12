import { Link } from "react-router-dom";
import { KIND_LABEL, SPEAKERS, ZONES, type Session, type SessionKind } from "../data/event";
import { effective, liveState, seatsLeft, useStore } from "../lib/store";
import { statusOf } from "../lib/reservation";
import { fmt } from "../lib/time";
import { ReserveButton } from "./ReserveButton";

export const KIND_COLOR: Record<SessionKind, string> = {
  talk: "#e62b1e",
  workshop: "#3a6df0",
  tour: "#12a46b",
  networking: "#f2a516",
  performance: "#9b5cff",
};

export function SeatBadge({ session }: { session: Session }) {
  const s = useStore((x) => x);
  if (!session.requiresReservation) return <span className="chip">予約不要</span>;
  const left = seatsLeft(session, s);
  if (left <= 0) return <span className="chip red">満席・キャンセル待ち可</span>;
  if (left <= Math.max(3, session.capacity * 0.1)) return <span className="chip warn">残りわずか {left}席</span>;
  return <span className="chip ok">空席あり</span>;
}

export function StatusChip({ session }: { session: Session }) {
  const s = useStore((x) => x);
  const st = liveState(session, s);
  if (st === "live") return <span className="chip live">LIVE</span>;
  if (st === "cancelled") return <span className="chip red">中止</span>;
  if (st === "done") return <span className="chip">終了</span>;
  return null;
}

export function SessionCard({ session, compact = false }: { session: Session; compact?: boolean }) {
  const s = useStore((x) => x);
  const { start, end, delay } = effective(session, s);
  const st = liveState(session, s);
  const room = ZONES.find((z) => z.id === session.roomId)?.name;
  const speakers = SPEAKERS.filter((sp) => session.speakerIds.includes(sp.id));
  const mine = statusOf(s.ledger, session.id, s.me.id);

  return (
    <div className={`card session ${st === "cancelled" ? "cancelled" : ""}`}>
      <div className="kind-bar" style={{ background: KIND_COLOR[session.kind] }} />
      <div className="time">
        {fmt(start)}
        <small>{fmt(end)}</small>
        {delay > 0 && <div className="delayed">+{delay}分</div>}
      </div>
      <div className="body">
      <Link to={`/programs/${session.id}`} style={{ display: "block" }}>
        <div className="row wrap" style={{ gap: 6 }}>
          <span className="chip" style={{ color: KIND_COLOR[session.kind] }}>{KIND_LABEL[session.kind]}</span>
          <StatusChip session={session} />
          {mine === "booked" && <span className="chip dark">予約済み</span>}
          {mine === "waitlisted" && <span className="chip info">キャンセル待ち</span>}
        </div>
        <h3>{session.title}</h3>
        <div className="meta">
          {room}
          {speakers.length > 0 && ` ・ ${speakers.map((sp) => sp.name).join("、")}`}
        </div>
      </Link>
        {!compact && (
          <div className="row between" style={{ marginTop: 8 }}>
            <SeatBadge session={session} />
            {st !== "done" && st !== "cancelled" && <ReserveButton session={session} small />}
          </div>
        )}
      </div>
    </div>
  );
}
