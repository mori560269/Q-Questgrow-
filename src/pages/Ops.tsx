import { useState } from "react";
import { Link } from "react-router-dom";
import { Icon } from "../components/Icon";
import { StatusChip } from "../components/SessionCard";
import { toast } from "../components/Toast";
import { SESSIONS, ZONES } from "../data/event";
import { draftAnnouncement } from "../lib/api";
import { CATEGORY_LABEL } from "../lib/nlp";
import { actions, effective, liveState, nowMinutes, seatsLeft, useStore, type Announcement, type Inquiry } from "../lib/store";
import { fmt, fmtRange } from "../lib/time";
import { crowdColor, crowdLabel } from "./Home";

type Tab = "flow" | "checkin" | "inbox" | "broadcast" | "venue";
const TABS: [Tab, string][] = [
  ["flow", "進行"],
  ["checkin", "受付"],
  ["inbox", "問い合わせ"],
  ["broadcast", "配信"],
  ["venue", "会場"],
];

// 事前にチェックイン済みとみなす人数（デモ）
const PRE_CHECKED_IN = 486;
const TOTAL_TICKETS = 640;

export function OpsPage() {
  const s = useStore((x) => x);
  const [tab, setTab] = useState<Tab>("flow");
  const open = s.inquiries.filter((q) => q.status !== "resolved");
  const urgent = open.filter((q) => q.triage.urgency === "high");
  const delayed = SESSIONS.filter((x) => (s.delays[x.id] ?? 0) > 0 && liveState(x, s) !== "done");
  const checkedIn = PRE_CHECKED_IN + Object.keys(s.checkins).length;

  if (s.me.role !== "staff") {
    return (
      <div className="page empty" style={{ paddingTop: 80 }}>
        運営ダッシュボードはスタッフ専用です。<br />
        <Link to="/me" className="link">プロフィールでスタッフモードに切り替え →</Link>
      </div>
    );
  }

  return (
    <>
      <header className="hero compact">
        <div className="hero-top">
          <div className="brand">運営ダッシュボード</div>
          <span className="chip dark">STAFF</span>
        </div>
        <ClockControl />
      </header>

      <div className="page" style={{ marginTop: 12 }}>
        {urgent.length > 0 && (
          <button className="banner urgent" style={{ width: "100%", border: 0, textAlign: "left", marginBottom: 10 }} onClick={() => setTab("inbox")}>
            🚨 緊急の問い合わせが {urgent.length} 件あります：{urgent[0].triage.summary}
          </button>
        )}
        <div className="kpis">
          <div className="kpi"><span>チェックイン</span><b>{checkedIn}<small className="muted" style={{ fontSize: 12 }}> / {TOTAL_TICKETS}</small></b></div>
          <div className="kpi"><span>未対応の問い合わせ</span><b style={{ color: open.length ? "var(--danger)" : undefined }}>{open.length}</b></div>
          <div className="kpi"><span>遅延中のプログラム</span><b style={{ color: delayed.length ? "var(--warn)" : undefined }}>{delayed.length}</b></div>
          <div className="kpi"><span>配信済みお知らせ</span><b>{s.announcements.length}</b></div>
        </div>

        <div className="seg" style={{ marginTop: 14 }}>
          {TABS.map(([k, label]) => (
            <button key={k} className={tab === k ? "on" : ""} onClick={() => setTab(k)}>
              {label}
              {k === "inbox" && open.length > 0 && ` (${open.length})`}
            </button>
          ))}
        </div>

        <div style={{ marginTop: 12 }}>
          {tab === "flow" && <FlowTab />}
          {tab === "checkin" && <CheckinTab checkedIn={checkedIn} />}
          {tab === "inbox" && <InboxTab />}
          {tab === "broadcast" && <BroadcastTab />}
          {tab === "venue" && <VenueTab />}
        </div>
      </div>
    </>
  );
}

function ClockControl() {
  const s = useStore((x) => x);
  const now = nowMinutes(s);
  return (
    <div style={{ marginTop: 12, position: "relative", zIndex: 1 }}>
      <div className="row between small">
        <span>当日時刻（デモ）: <b style={{ fontSize: 16 }}>{fmt(now)}</b></span>
        <button className="chip" style={{ border: 0 }} onClick={() => actions.setClock(s.clock === null ? 710 : null)}>
          {s.clock === null ? "デモ時刻に切替" : "実時刻に切替"}
        </button>
      </div>
      {s.clock !== null && (
        <input type="range" min={570} max={1110} step={5} value={s.clock} onChange={(e) => actions.setClock(Number(e.target.value))} aria-label="デモ時刻" />
      )}
    </div>
  );
}

function FlowTab() {
  const s = useStore((x) => x);
  const sessions = [...SESSIONS].sort((a, b) => a.start - b.start);
  return (
    <div className="stack">
      <div className="small muted">遅延を設定すると、来場者アプリの時刻表示・AIの案内に即時反映されます。「以降も」で同じ会場の後続プログラムにも波及します。</div>
      {sessions.map((x) => {
        const { start, end, delay } = effective(x, s);
        const st = liveState(x, s);
        const room = ZONES.find((z) => z.id === x.roomId)!;
        const booked = x.capacity - Math.max(0, seatsLeft(x, s));
        const present = s.attendance[x.id] ?? 0;
        return (
          <div key={x.id} className="card" style={{ opacity: st === "done" ? 0.6 : 1 }}>
            <div className="row between">
              <div className="row" style={{ gap: 6 }}>
                <b className="small">{fmtRange(start, end)}</b>
                <StatusChip session={x} />
                {delay > 0 && <span className="chip warn">+{delay}分</span>}
              </div>
              <span className="small muted">{room.name}</span>
            </div>
            <div style={{ fontWeight: 700, fontSize: 14, margin: "6px 0" }}>{x.title}</div>
            <div className="row wrap between" style={{ gap: 8 }}>
              <div className="stepper">
                <span className="small muted">遅延</span>
                <button onClick={() => actions.setDelay(x.id, delay - 5)} aria-label="遅延を5分減らす">−</button>
                <b className="small" style={{ width: 34, textAlign: "center" }}>{delay}分</b>
                <button onClick={() => actions.setDelay(x.id, delay + 5)} aria-label="遅延を5分増やす">＋</button>
                <button className="chip" style={{ width: "auto", border: 0, borderRadius: 999, padding: "4px 8px" }} onClick={() => { actions.cascadeDelay(x.id, delay); toast(`${room.name}の後続プログラムにも${delay}分を反映しました`); }}>
                  以降も
                </button>
              </div>
              <div className="stepper">
                <span className="small muted">入場</span>
                <button onClick={() => actions.countEntry(x.id, -1)} aria-label="入場数を減らす">−</button>
                <b className="small" style={{ minWidth: 34, textAlign: "center" }}>{present}</b>
                <button onClick={() => actions.countEntry(x.id, 1)} aria-label="入場数を増やす">＋</button>
              </div>
            </div>
            <div className="row between small muted" style={{ marginTop: 8 }}>
              <span>{x.requiresReservation ? `予約 ${booked}/${x.capacity}` : `定員 ${x.capacity}`}・待ち {s.ledger.waitlist[x.id]?.length ?? 0}</span>
              <button className="link" style={{ color: "var(--danger)" }} onClick={() => { if (confirm(s.cancelled[x.id] ? "中止を取り消しますか？" : "このプログラムを中止にしますか？")) actions.toggleCancelled(x.id); }}>
                {s.cancelled[x.id] ? "中止を取り消す" : "中止にする"}
              </button>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function CheckinTab({ checkedIn }: { checkedIn: number }) {
  const s = useStore((x) => x);
  const [code, setCode] = useState("");
  const recent = Object.entries(s.checkins).sort((a, b) => b[1] - a[1]).slice(0, 8);

  const submit = (c: string) => {
    const r = actions.checkIn(c);
    toast(r === "ok" ? `✅ ${c.toUpperCase()} チェックイン完了` : r === "dup" ? "⚠️ すでにチェックイン済みのチケットです" : "❌ 無効なチケット番号です");
    if (r === "ok") setCode("");
  };

  return (
    <div className="stack">
      <div className="card">
        <b>チケット照合</b>
        <div className="small muted" style={{ margin: "4px 0 10px" }}>QRリーダーの読み取り結果、またはチケット番号を入力</div>
        <form className="row" onSubmit={(e) => { e.preventDefault(); submit(code); }}>
          <input className="input" value={code} onChange={(e) => setCode(e.target.value)} placeholder="TQX-XXXXXX" aria-label="チケット番号" />
          <button className="btn">照合</button>
        </form>
        <button className="link" style={{ marginTop: 10 }} onClick={() => submit(s.ticketCode)}>
          デモ：自分のチケット（{s.ticketCode}）を読み取る
        </button>
      </div>
      <div className="card">
        <div className="row between"><b>来場状況</b><span className="small muted">{Math.round((checkedIn / TOTAL_TICKETS) * 100)}%</span></div>
        <div className="meter" style={{ margin: "10px 0" }}><i style={{ width: `${(checkedIn / TOTAL_TICKETS) * 100}%`, background: "var(--ok)" }} /></div>
        <div className="small muted">直近のチェックイン</div>
        {recent.length === 0 && <div className="small muted" style={{ marginTop: 6 }}>このアプリからのチェックインはまだありません</div>}
        {recent.map(([c, at]) => (
          <div key={c} className="row between small" style={{ marginTop: 6 }}>
            <code>{c}</code>
            <span className="muted">{fmt(at)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

const URG_ORDER = { high: 0, medium: 1, low: 2 };

function InboxTab() {
  const s = useStore((x) => x);
  const list = [...s.inquiries].sort(
    (a, b) => Number(a.status === "resolved") - Number(b.status === "resolved") || URG_ORDER[a.triage.urgency] - URG_ORDER[b.triage.urgency] || b.at - a.at,
  );
  if (!list.length)
    return (
      <div className="empty">
        問い合わせはまだありません。<br />
        来場者画面の「AIコンシェルジュ → スタッフに問い合わせ」から送信すると、ここに自動分類されて届きます。
      </div>
    );
  return (
    <div className="stack">
      {list.map((q) => (
        <InquiryCard key={q.id} q={q} />
      ))}
    </div>
  );
}

function InquiryCard({ q }: { q: Inquiry }) {
  const [reply, setReply] = useState(q.reply ?? q.triage.suggestedReply);
  const urgLabel = { high: "緊急", medium: "要対応", low: "通常" }[q.triage.urgency];
  return (
    <div className={`card urg-${q.triage.urgency}`} style={{ opacity: q.status === "resolved" ? 0.6 : 1 }}>
      <div className="row between">
        <div className="row" style={{ gap: 6 }}>
          <span className={`chip ${q.triage.urgency === "high" ? "red" : q.triage.urgency === "medium" ? "warn" : ""}`}>{urgLabel}</span>
          <span className="chip">{CATEGORY_LABEL[q.triage.category]}</span>
          <span className="chip info" title="振り分け方法">{q.triage.source === "ai" ? "✨ AI分類" : "ルール分類"}</span>
        </div>
        <span className="small muted">{fmt(q.at)}</span>
      </div>
      <div style={{ fontWeight: 700, fontSize: 14, margin: "8px 0 2px" }}>{q.triage.summary}</div>
      <div className="small muted">{q.fromName}：「{q.text}」</div>
      <label className="field" style={{ marginTop: 10 }}>返信（AIの返信案を編集できます）</label>
      <textarea className="input" rows={3} value={reply} onChange={(e) => setReply(e.target.value)} />
      <div className="row" style={{ marginTop: 8, justifyContent: "flex-end" }}>
        {q.status === "open" && (
          <button className="btn sm secondary" onClick={() => { actions.respondInquiry(q.id, reply, "in_progress"); toast("対応中にしました"); }}>
            対応中にして返信
          </button>
        )}
        {q.status !== "resolved" && (
          <button className="btn sm ok" onClick={() => { actions.respondInquiry(q.id, reply, "resolved"); toast("解決済みにしました"); }}>
            <Icon name="check" size={14} /> 返信して解決
          </button>
        )}
      </div>
    </div>
  );
}

function BroadcastTab() {
  const s = useStore((x) => x);
  const [note, setNote] = useState("");
  const [draft, setDraft] = useState<{ ja: string; en: string; source: "ai" | "local" } | null>(null);
  const [level, setLevel] = useState<Announcement["level"]>("info");
  const [busy, setBusy] = useState(false);
  const delayed = SESSIONS.filter((x) => (s.delays[x.id] ?? 0) > 0 && liveState(x, s) === "scheduled");

  async function generate(text = note) {
    if (!text.trim()) return;
    setNote(text);
    setBusy(true);
    setDraft(await draftAnnouncement(text));
    setBusy(false);
  }

  return (
    <div className="stack">
      <div className="card">
        <b>お知らせを作成</b>
        <div className="small muted" style={{ margin: "4px 0 10px" }}>メモを書くと、AIが日本語・英語のお知らせ文に整えます</div>
        <textarea className="input" rows={3} value={note} onChange={(e) => setNote(e.target.value)} placeholder="例: セッション3 機材トラブルで15分押し 15:20開始" />
        {delayed.length > 0 && (
          <div className="row wrap" style={{ gap: 6, marginTop: 8 }}>
            {delayed.map((x) => (
              <button key={x.id} className="chip warn" style={{ border: 0 }} onClick={() => generate(`「${x.title}」は${s.delays[x.id]}分遅れて${fmt(effective(x, s).start)}開始`)}>
                遅延を通知: {x.title.slice(0, 14)}…
              </button>
            ))}
          </div>
        )}
        <button className="btn dark block" style={{ marginTop: 10 }} disabled={busy || !note.trim()} onClick={() => generate()}>
          <Icon name="sparkle" size={16} /> {busy ? "作成中…" : "文面を作成"}
        </button>
      </div>

      {draft && (
        <div className="card">
          <div className="row between">
            <b>プレビュー</b>
            <span className="chip info">{draft.source === "ai" ? "✨ Claude 生成" : "テンプレート"}</span>
          </div>
          <label className="field" style={{ marginTop: 10 }}>日本語</label>
          <textarea className="input" rows={3} value={draft.ja} onChange={(e) => setDraft({ ...draft, ja: e.target.value })} />
          <label className="field" style={{ marginTop: 10 }}>English</label>
          <textarea className="input" rows={3} value={draft.en} onChange={(e) => setDraft({ ...draft, en: e.target.value })} />
          <div className="seg" style={{ marginTop: 10 }}>
            {(["info", "warn", "urgent"] as const).map((l) => (
              <button key={l} className={level === l ? "on" : ""} onClick={() => setLevel(l)}>
                {{ info: "通常", warn: "注意", urgent: "重要" }[l]}
              </button>
            ))}
          </div>
          <button
            className="btn block"
            style={{ marginTop: 10 }}
            onClick={() => {
              actions.announce({ ja: draft.ja, en: draft.en, level });
              setDraft(null);
              setNote("");
              toast("📣 全来場者に配信しました");
            }}
          >
            <Icon name="megaphone" size={16} /> 全来場者に配信
          </button>
        </div>
      )}

      <div className="section"><h2>配信履歴</h2></div>
      {s.announcements.map((a) => (
        <div key={a.id} className={`banner ${a.level}`} style={{ display: "block" }}>
          <b className="small">{fmt(a.at)}</b> {a.ja}
        </div>
      ))}
    </div>
  );
}

function VenueTab() {
  const s = useStore((x) => x);
  return (
    <div className="card">
      <b>エリアの混雑度</b>
      <div className="small muted" style={{ margin: "4px 0 12px" }}>巡回スタッフの目視で更新（将来は人流センサーと連携）。来場者のマップとAI案内に反映されます。</div>
      {ZONES.map((z) => {
        const v = s.crowd[z.id] ?? 0;
        return (
          <div key={z.id} style={{ marginBottom: 12 }}>
            <div className="row between small">
              <span>{z.name}</span>
              <b style={{ color: crowdColor(v) }}>{crowdLabel(v)} {Math.round(v * 100)}%</b>
            </div>
            <input type="range" min={0} max={1} step={0.05} value={v} onChange={(e) => actions.setCrowd(z.id, Number(e.target.value))} aria-label={`${z.name}の混雑度`} />
          </div>
        );
      })}
    </div>
  );
}
