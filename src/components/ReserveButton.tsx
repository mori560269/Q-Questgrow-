import type { Session } from "../data/event";
import { statusOf, waitlistPosition } from "../lib/reservation";
import { actions, liveState, seatsLeft, useStore } from "../lib/store";
import { toast } from "./Toast";

export function ReserveButton({ session, small = false }: { session: Session; small?: boolean }) {
  const s = useStore((x) => x);
  const mine = statusOf(s.ledger, session.id, s.me.id);
  const st = liveState(session, s);
  const cls = `btn ${small ? "sm" : "block"}`;

  if (!session.requiresReservation) return null;
  if (st === "done" || st === "cancelled") return <button className={`${cls} secondary`} disabled>受付終了</button>;

  if (mine) {
    const pos = waitlistPosition(s.ledger, session.id, s.me.id);
    return (
      <button
        className={`${cls} secondary`}
        onClick={(e) => {
          e.preventDefault();
          if (!confirm(mine === "booked" ? "予約をキャンセルしますか？" : "キャンセル待ちを取り消しますか？")) return;
          actions.cancel(session);
          toast(mine === "booked" ? "予約をキャンセルしました" : "キャンセル待ちを取り消しました");
        }}
      >
        {mine === "booked" ? "予約済み ✓" : `待ち ${pos}番目`}
      </button>
    );
  }

  const full = seatsLeft(session, s) <= 0;
  return (
    <button
      className={`${cls} ${full ? "ghost" : ""}`}
      onClick={(e) => {
        e.preventDefault();
        const r = actions.reserve(session);
        if (r.ok) toast(r.status === "booked" ? "🎟️ 予約しました！マイプランに追加されました" : "キャンセル待ちに登録しました。空きが出たら自動で繰り上がります");
        else if (r.reason === "conflict") toast(`⚠️ 「${r.conflictWith?.title}」と時間が重なっています`);
      }}
    >
      {full ? "キャンセル待ち" : "予約する"}
    </button>
  );
}
