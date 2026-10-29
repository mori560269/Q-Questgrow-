// アプリ全体の状態。デモでは localStorage に保存し、BroadcastChannel で
// 同じブラウザの別タブ（例: 参加者画面と運営画面）とリアルタイム同期する。
// 本番ではここを API + WebSocket（または Firestore 等）に置き換える。

import { useSyncExternalStore } from "react";
import { PEOPLE, SESSIONS, type Person, type Session } from "../data/event";
import { cancel as cancelLedger, emptyLedger, reserve as reserveLedger, type Ledger } from "./reservation";
import type { Triage } from "./nlp";

export type LiveState = "scheduled" | "live" | "done" | "cancelled";

export type Announcement = { id: string; at: number; ja: string; en: string; level: "info" | "warn" | "urgent" };

export type Inquiry = {
  id: string;
  at: number;
  fromId: string;
  fromName: string;
  text: string;
  triage: Triage;
  status: "open" | "in_progress" | "resolved";
  reply?: string;
};

export type ChatMessage = { id: string; at: number; from: string; to: string; text: string };

export type Notice = { id: string; at: number; text: string; read: boolean };

export type State = {
  version: number;
  me: Person;
  ticketCode: string;
  ledger: Ledger;
  /** アプリ外（事前販売・他の参加者）で埋まっている席数 */
  baseline: Record<string, number>;
  delays: Record<string, number>;
  cancelled: Record<string, boolean>;
  /** ゾーンごとの混雑度 0..1（運営が更新 / 将来はセンサー連携） */
  crowd: Record<string, number>;
  checkins: Record<string, number>;
  /** セッションごとの入場カウント */
  attendance: Record<string, number>;
  announcements: Announcement[];
  inquiries: Inquiry[];
  connections: Record<string, "requested" | "connected">;
  messages: ChatMessage[];
  notices: Notice[];
  /** デモ用の当日時刻（分）。null なら実時刻 */
  clock: number | null;
};

const VERSION = 1;
const KEY = "tedx-app-state";

const uid = () => Math.random().toString(36).slice(2, 10);

function initialState(): State {
  return {
    version: VERSION,
    me: {
      id: "me",
      name: "ゲスト",
      role: "attendee",
      title: "",
      interests: ["AI", "教育"],
      goals: ["アイデアを話したい"],
      bio: "",
      hue: 12,
    },
    ticketCode: "TQX-" + uid().toUpperCase().slice(0, 6),
    ledger: emptyLedger(),
    baseline: { s2: 520, s3: 470, s4: 590, s5: 380, w1: 26, w2: 19, w3: 22, w4: 20, t1: 15, n1: 61, n2: 44 },
    delays: {},
    cancelled: {},
    crowd: { main: 0.55, studioA: 0.2, studioB: 0.1, lounge: 0.35, booths: 0.7, food: 0.8, lobby: 0.45, wc: 0.3, first_aid: 0 },
    checkins: {},
    attendance: { s1: 512, s2: 498 },
    announcements: [
      { id: uid(), at: 575, ja: "ようこそ TEDxQuestgrow 2026 へ！会場Wi-Fi: TEDxQuestgrow-Guest / PW: growbeyond", en: "Welcome! Wi-Fi: TEDxQuestgrow-Guest / PW: growbeyond", level: "info" },
    ],
    inquiries: [],
    connections: {},
    messages: [],
    notices: [],
    clock: 710,
  };
}

function load(): State {
  try {
    const raw = localStorage.getItem(KEY);
    if (raw) {
      const s = JSON.parse(raw) as State;
      if (s.version === VERSION) return s;
    }
  } catch {
    // 破損・非対応環境は初期化
  }
  return initialState();
}

let state: State = typeof localStorage === "undefined" ? initialState() : load();
const listeners = new Set<() => void>();
const channel = typeof BroadcastChannel === "undefined" ? null : new BroadcastChannel(KEY);

channel?.addEventListener("message", (e) => {
  state = e.data as State;
  listeners.forEach((l) => l());
});

function setState(updater: (s: State) => State) {
  state = updater(state);
  try {
    localStorage.setItem(KEY, JSON.stringify(state));
  } catch {
    // 保存できなくてもメモリ上では動作させる
  }
  channel?.postMessage(state);
  listeners.forEach((l) => l());
}

export function useStore<T>(selector: (s: State) => T): T {
  return useSyncExternalStore(
    (l) => {
      listeners.add(l);
      return () => listeners.delete(l);
    },
    () => selector(state),
  );
}

export const getState = () => state;

// ---------- 時刻 ----------

export function nowMinutes(s: State = state): number {
  if (s.clock !== null) return s.clock;
  const d = new Date();
  return d.getHours() * 60 + d.getMinutes();
}

export function effective(session: Session, s: State = state) {
  const d = s.delays[session.id] ?? 0;
  return { start: session.start + d, end: session.end + d, delay: d };
}

export function liveState(session: Session, s: State = state): LiveState {
  if (s.cancelled[session.id]) return "cancelled";
  const { start, end } = effective(session, s);
  const now = nowMinutes(s);
  if (now >= end) return "done";
  if (now >= start) return "live";
  return "scheduled";
}

export function seatsLeft(session: Session, s: State = state): number {
  return session.capacity - (s.baseline[session.id] ?? 0) - (s.ledger.booked[session.id]?.length ?? 0);
}

export function myBookings(s: State = state): Session[] {
  return SESSIONS.filter((x) => s.ledger.booked[x.id]?.includes(s.me.id)).sort((a, b) => a.start - b.start);
}

// ---------- アクション ----------

const notice = (s: State, text: string): Notice[] => [{ id: uid(), at: nowMinutes(s), text, read: false }, ...s.notices];

export const actions = {
  reserve(session: Session) {
    const result = reserveLedger(state.ledger, SESSIONS, session, state.me.id, state.baseline[session.id] ?? 0);
    if (result.ok) {
      setState((s) => ({
        ...s,
        ledger: result.ledger,
        notices: notice(s, result.status === "booked" ? `「${session.title}」を予約しました` : `「${session.title}」のキャンセル待ちに登録しました`),
      }));
    }
    return result;
  },

  cancel(session: Session) {
    const { ledger } = cancelLedger(state.ledger, session, state.me.id, state.baseline[session.id] ?? 0);
    setState((s) => ({ ...s, ledger }));
  },

  /** デモ：他の参加者がキャンセルして1席空く → キャンセル待ち先頭を繰り上げ */
  releaseSeat(session: Session) {
    setState((s) => {
      const baseline = { ...s.baseline, [session.id]: Math.max(0, (s.baseline[session.id] ?? 0) - 1) };
      const { ledger, promoted } = cancelLedger(s.ledger, session, "__nobody__", baseline[session.id]);
      return {
        ...s,
        baseline,
        ledger,
        notices: promoted === s.me.id ? notice(s, `🎉 キャンセル待ちから繰り上がりました：「${session.title}」`) : s.notices,
      };
    });
  },

  updateProfile(p: Partial<Person>) {
    setState((s) => ({ ...s, me: { ...s.me, ...p } }));
  },

  setClock(min: number | null) {
    setState((s) => ({ ...s, clock: min }));
  },

  setDelay(sessionId: string, minutes: number) {
    setState((s) => ({ ...s, delays: { ...s.delays, [sessionId]: Math.max(0, minutes) } }));
  },

  /** 指定セッション以降の同じ部屋のプログラムにも遅延を波及させる */
  cascadeDelay(sessionId: string, minutes: number) {
    const base = SESSIONS.find((x) => x.id === sessionId)!;
    setState((s) => {
      const delays = { ...s.delays };
      for (const x of SESSIONS) if (x.roomId === base.roomId && x.start >= base.start) delays[x.id] = Math.max(0, minutes);
      return { ...s, delays };
    });
  },

  toggleCancelled(sessionId: string) {
    setState((s) => ({ ...s, cancelled: { ...s.cancelled, [sessionId]: !s.cancelled[sessionId] } }));
  },

  setCrowd(zoneId: string, v: number) {
    setState((s) => ({ ...s, crowd: { ...s.crowd, [zoneId]: Math.min(1, Math.max(0, v)) } }));
  },

  checkIn(code: string): "ok" | "dup" | "invalid" {
    const c = code.trim().toUpperCase();
    if (!/^TQX-[A-Z0-9]{6}$/.test(c)) return "invalid";
    if (state.checkins[c]) return "dup";
    setState((s) => ({ ...s, checkins: { ...s.checkins, [c]: nowMinutes(s) } }));
    return "ok";
  },

  countEntry(sessionId: string, delta: number) {
    setState((s) => ({ ...s, attendance: { ...s.attendance, [sessionId]: Math.max(0, (s.attendance[sessionId] ?? 0) + delta) } }));
  },

  announce(a: Omit<Announcement, "id" | "at">) {
    setState((s) => ({
      ...s,
      announcements: [{ ...a, id: uid(), at: nowMinutes(s) }, ...s.announcements],
      notices: notice(s, `📣 ${a.ja}`),
    }));
  },

  submitInquiry(text: string, triage: Triage) {
    const id = uid();
    setState((s) => ({
      ...s,
      inquiries: [{ id, at: nowMinutes(s), fromId: s.me.id, fromName: s.me.name, text, triage, status: "open" }, ...s.inquiries],
    }));
    return id;
  },

  updateInquiryTriage(id: string, triage: Triage) {
    setState((s) => ({ ...s, inquiries: s.inquiries.map((q) => (q.id === id ? { ...q, triage } : q)) }));
  },

  respondInquiry(id: string, reply: string, status: Inquiry["status"]) {
    setState((s) => {
      const q = s.inquiries.find((x) => x.id === id);
      return {
        ...s,
        inquiries: s.inquiries.map((x) => (x.id === id ? { ...x, reply, status } : x)),
        notices: q && q.fromId === s.me.id && reply ? notice(s, `💬 運営からの回答：${reply}`) : s.notices,
      };
    });
  },

  connect(personId: string) {
    setState((s) => ({ ...s, connections: { ...s.connections, [personId]: "requested" } }));
    // デモ：相手が数秒後に承認する
    setTimeout(() => {
      const p = PEOPLE.find((x) => x.id === personId);
      setState((s) => ({
        ...s,
        connections: { ...s.connections, [personId]: "connected" },
        notices: notice(s, `🤝 ${p?.name ?? "相手"}さんとつながりました`),
      }));
    }, 1800);
  },

  sendMessage(to: string, text: string) {
    setState((s) => ({ ...s, messages: [...s.messages, { id: uid(), at: nowMinutes(s), from: s.me.id, to, text }] }));
    const p = PEOPLE.find((x) => x.id === to);
    if (!p) return;
    setTimeout(() => {
      const reply =
        p.role === "speaker"
          ? "メッセージありがとうございます！Q&Aラウンジ（16:25〜）でぜひ続きを話しましょう。"
          : p.role === "staff"
            ? "了解しました！近くのスタッフにも共有しておきますね。"
            : "ありがとうございます！休憩時間にラウンジで話しませんか？";
      setState((s) => ({ ...s, messages: [...s.messages, { id: uid(), at: nowMinutes(s), from: to, to: s.me.id, text: reply }] }));
    }, 1500);
  },

  markNoticesRead() {
    setState((s) => ({ ...s, notices: s.notices.map((n) => ({ ...n, read: true })) }));
  },

  reset() {
    setState(() => initialState());
  },
};
