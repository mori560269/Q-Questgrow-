import type { Session } from "../data/event";
import { overlaps } from "./time";

// 予約台帳。sessionId -> 予約者IDの配列 / キャンセル待ち配列（先着順）
export type Ledger = {
  booked: Record<string, string[]>;
  waitlist: Record<string, string[]>;
};

export type ReserveResult =
  | { ok: true; status: "booked" | "waitlisted"; ledger: Ledger }
  | { ok: false; reason: "already" | "conflict" | "not_required"; conflictWith?: Session };

export const emptyLedger = (): Ledger => ({ booked: {}, waitlist: {} });

export function bookedCount(ledger: Ledger, sessionId: string, baseline = 0): number {
  return baseline + (ledger.booked[sessionId]?.length ?? 0);
}

export function statusOf(ledger: Ledger, sessionId: string, userId: string): "booked" | "waitlisted" | null {
  if (ledger.booked[sessionId]?.includes(userId)) return "booked";
  if (ledger.waitlist[sessionId]?.includes(userId)) return "waitlisted";
  return null;
}

export function waitlistPosition(ledger: Ledger, sessionId: string, userId: string): number {
  return (ledger.waitlist[sessionId]?.indexOf(userId) ?? -1) + 1;
}

/** ユーザーが予約済みのセッションのうち、時間が重なるもの */
export function findConflict(ledger: Ledger, sessions: Session[], target: Session, userId: string): Session | undefined {
  return sessions.find(
    (s) => s.id !== target.id && ledger.booked[s.id]?.includes(userId) && overlaps(s, target),
  );
}

/**
 * 予約する。定員に達していればキャンセル待ちに登録する。
 * baseline は事前販売分など、このアプリ外ですでに埋まっている席数。
 */
export function reserve(
  ledger: Ledger,
  sessions: Session[],
  session: Session,
  userId: string,
  baseline = 0,
): ReserveResult {
  if (!session.requiresReservation) return { ok: false, reason: "not_required" };
  if (statusOf(ledger, session.id, userId)) return { ok: false, reason: "already" };
  const conflictWith = findConflict(ledger, sessions, session, userId);
  if (conflictWith) return { ok: false, reason: "conflict", conflictWith };

  const full = bookedCount(ledger, session.id, baseline) >= session.capacity;
  const key = full ? "waitlist" : "booked";
  return {
    ok: true,
    status: full ? "waitlisted" : "booked",
    ledger: { ...ledger, [key]: { ...ledger[key], [session.id]: [...(ledger[key][session.id] ?? []), userId] } },
  };
}

/** キャンセルする。予約枠が空いたらキャンセル待ちの先頭を繰り上げる。 */
export function cancel(
  ledger: Ledger,
  session: Session,
  userId: string,
  baseline = 0,
): { ledger: Ledger; promoted: string | null } {
  const booked = (ledger.booked[session.id] ?? []).filter((u) => u !== userId);
  let waitlist = (ledger.waitlist[session.id] ?? []).filter((u) => u !== userId);
  let promoted: string | null = null;
  if (waitlist.length > 0 && baseline + booked.length < session.capacity) {
    promoted = waitlist[0];
    booked.push(promoted);
    waitlist = waitlist.slice(1);
  }
  return {
    ledger: {
      booked: { ...ledger.booked, [session.id]: booked },
      waitlist: { ...ledger.waitlist, [session.id]: waitlist },
    },
    promoted,
  };
}
