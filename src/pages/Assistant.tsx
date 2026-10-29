import { useEffect, useRef, useState } from "react";
import { Icon } from "../components/Icon";
import { RichText } from "../components/RichText";
import { SubHeader } from "../components/SubHeader";
import { toast } from "../components/Toast";
import { SESSIONS, ZONES } from "../data/event";
import { askConcierge, checkAi, triage, type ChatTurn } from "../lib/api";
import { CATEGORY_LABEL, triageLocally } from "../lib/nlp";
import { actions, effective, getState, myBookings, nowMinutes, seatsLeft, useStore, type State } from "../lib/store";
import { fmt, fmtRange } from "../lib/time";

const SUGGESTIONS = ["次に何を見ればいい？", "AIに興味があります。おすすめは？", "トイレはどこ？", "ランチはどうすればいい？", "遅延情報はある？", "車椅子で移動しやすいルートは？"];

/** Claude に渡す「現在の状況」。ユーザーごと・時刻ごとに変わる情報だけをまとめる。 */
function liveContext(s: State): string {
  const now = nowMinutes(s);
  const lines = [
    `現在時刻: ${fmt(now)}`,
    `来場者: ${s.me.name}（関心: ${s.me.interests.join("、") || "未設定"}）`,
    `予約済み: ${myBookings(s).map((x) => `${x.id}（${fmtRange(effective(x, s).start, effective(x, s).end)}）`).join(", ") || "なし"}`,
    `キャンセル待ち: ${SESSIONS.filter((x) => s.ledger.waitlist[x.id]?.includes(s.me.id)).map((x) => x.id).join(", ") || "なし"}`,
    `遅延: ${Object.entries(s.delays).filter(([, d]) => d > 0).map(([id, d]) => `${id}が${d}分遅れ`).join(", ") || "なし"}`,
    `中止: ${Object.keys(s.cancelled).filter((id) => s.cancelled[id]).join(", ") || "なし"}`,
    `残席: ${SESSIONS.filter((x) => x.requiresReservation).map((x) => `${x.id}=${Math.max(0, seatsLeft(x, s))}`).join(", ")}`,
    `混雑度(0-1): ${ZONES.map((z) => `${z.id}=${(s.crowd[z.id] ?? 0).toFixed(1)}`).join(", ")}`,
    `最新のお知らせ: ${s.announcements.slice(0, 3).map((a) => `${fmt(a.at)} ${a.ja}`).join(" / ") || "なし"}`,
  ];
  return lines.join("\n");
}

type Turn = ChatTurn & { source?: "ai" | "local" };

export function AssistantPage() {
  const [mode, setMode] = useState<"ai" | "staff">("ai");
  const [turns, setTurns] = useState<Turn[]>([
    { role: "assistant", content: "こんにちは！TEDxQuestgrow の AI コンシェルジュです ✨\nプログラム選び、会場の場所、当日の疑問など、なんでも聞いてください。" },
  ]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [ai, setAi] = useState<boolean | null>(null);
  const end = useRef<HTMLDivElement>(null);

  useEffect(() => {
    checkAi().then(setAi);
  }, []);
  useEffect(() => {
    end.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns]);

  async function ask(q: string) {
    if (!q.trim() || busy) return;
    setInput("");
    setBusy(true);
    const history: Turn[] = [...turns, { role: "user", content: q.trim() }];
    setTurns([...history, { role: "assistant", content: "" }]);
    const s = getState();
    const result = await askConcierge(
      // 先頭の挨拶（assistant）は API に送らない
      history.slice(1).map(({ role, content }) => ({ role, content })),
      liveContext(s),
      { now: nowMinutes(s), myBookings: myBookings(s), delays: s.delays, announcements: s.announcements.map((a) => a.ja) },
      (text) => setTurns([...history, { role: "assistant", content: text }]),
    );
    setTurns([...history, { role: "assistant", content: result.text, source: result.source }]);
    setBusy(false);
  }

  return (
    <>
      <SubHeader
        title="AIコンシェルジュ"
        right={ai !== null && <span className={`chip ${ai ? "ok" : ""}`}>{ai ? "Claude 接続中" : "オフライン応答"}</span>}
      />
      <div className="page">
        <div className="seg">
          <button className={mode === "ai" ? "on" : ""} onClick={() => setMode("ai")}>✨ AIに質問</button>
          <button className={mode === "staff" ? "on" : ""} onClick={() => setMode("staff")}>🙋 スタッフに問い合わせ</button>
        </div>
      </div>

      {mode === "ai" ? (
        <>
          <div className="chat">
            {turns.map((t, i) => (
              <div key={i} className={`bubble ${t.role === "user" ? "me" : "them"}`}>
                {t.role === "assistant" && !t.content ? (
                  <span className="typing"><span /><span /><span /></span>
                ) : t.role === "assistant" ? (
                  <RichText text={t.content} />
                ) : (
                  t.content
                )}
              </div>
            ))}
            {turns.length <= 1 && (
              <div className="row wrap" style={{ gap: 8 }}>
                {SUGGESTIONS.map((q) => (
                  <button key={q} className="chip info" style={{ border: 0, padding: "8px 12px", fontSize: 12 }} onClick={() => ask(q)}>
                    {q}
                  </button>
                ))}
              </div>
            )}
            <div ref={end} />
          </div>
          <div className="composer">
            <form onSubmit={(e) => { e.preventDefault(); ask(input); }}>
              <input className="input" value={input} onChange={(e) => setInput(e.target.value)} placeholder="質問を入力（例: 15時に空いてるワークショップは？）" aria-label="質問" disabled={busy} />
              <button className="btn" disabled={busy || !input.trim()} aria-label="送信"><Icon name="send" size={18} /></button>
            </form>
          </div>
        </>
      ) : (
        <StaffInquiry />
      )}
    </>
  );
}

function StaffInquiry() {
  const s = useStore((x) => x);
  const [text, setText] = useState("");
  const mine = s.inquiries.filter((q) => q.fromId === s.me.id);
  const preview = text.trim() ? triageLocally(text) : null;

  async function submit() {
    const body = text.trim();
    if (!body) return;
    // まずローカル判定で即時登録し、AIの振り分け結果が返ってきたら上書きする
    const id = actions.submitInquiry(body, triageLocally(body));
    setText("");
    toast("運営スタッフに送信しました");
    const t = await triage(body);
    if (t.source === "ai") actions.updateInquiryTriage(id, t);
  }

  return (
    <div className="page" style={{ marginTop: 12 }}>
      <div className="card">
        <label className="field" htmlFor="inq">困っていること・質問</label>
        <textarea id="inq" className="input" rows={4} value={text} onChange={(e) => setText(e.target.value)} placeholder="例: スタジオAの近くで黒い財布を落としました" />
        {preview && (
          <div className="small muted" style={{ marginTop: 8 }}>
            自動分類: <b>{CATEGORY_LABEL[preview.category]}</b>
            {preview.urgency === "high" && <span className="chip red" style={{ marginLeft: 6 }}>緊急</span>}
          </div>
        )}
        {preview?.category === "medical" && (
          <div className="banner urgent" style={{ marginTop: 8 }}>緊急の場合は、近くのスタッフに直接声をかけるか、ロビー右手の救護室へお越しください。</div>
        )}
        <button className="btn block" style={{ marginTop: 12 }} disabled={!text.trim()} onClick={submit}>送信する</button>
      </div>

      <div className="section"><h2>送信した問い合わせ</h2></div>
      {mine.length === 0 && <div className="empty">まだ問い合わせはありません</div>}
      <div className="stack">
        {mine.map((q) => (
          <div key={q.id} className="card">
            <div className="row between">
              <span className="chip">{CATEGORY_LABEL[q.triage.category]}</span>
              <span className={`chip ${q.status === "resolved" ? "ok" : q.status === "in_progress" ? "info" : "warn"}`}>
                {q.status === "resolved" ? "解決済み" : q.status === "in_progress" ? "対応中" : "受付済み"}
              </span>
            </div>
            <p className="small" style={{ margin: "8px 0 0" }}>{q.text}</p>
            {q.reply && <div className="banner info" style={{ marginTop: 8 }}>💬 {q.reply}</div>}
          </div>
        ))}
      </div>
    </div>
  );
}
