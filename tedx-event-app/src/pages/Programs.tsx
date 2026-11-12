import { useMemo, useState } from "react";
import { Icon } from "../components/Icon";
import { SessionCard } from "../components/SessionCard";
import { KIND_LABEL, SESSIONS, type SessionKind } from "../data/event";
import { searchSessions } from "../lib/nlp";
import { effective, liveState, nowMinutes, useStore } from "../lib/store";

const KINDS = Object.keys(KIND_LABEL) as SessionKind[];
const EXAMPLES = ["午後のAIのワークショップ", "これから参加できる体験", "教育について話せる交流会", "15時以降のトーク"];

export function ProgramsPage() {
  const s = useStore((x) => x);
  const [q, setQ] = useState("");
  const [kind, setKind] = useState<SessionKind | "all">("all");
  const [hideDone, setHideDone] = useState(true);
  const now = nowMinutes(s);

  const { list, label } = useMemo(() => {
    const { hits, window } = searchSessions(q, { now });
    let list = q.trim() ? hits.map((h) => h.session) : [...SESSIONS].sort((a, b) => a.start - b.start);
    if (kind !== "all") list = list.filter((x) => x.kind === kind);
    if (hideDone) list = list.filter((x) => liveState(x, s) !== "done");
    return { list, label: window?.label };
  }, [q, kind, hideDone, now, s]);

  // 検索していない時は時間帯でグループ化
  const groups = q.trim()
    ? [{ hour: null as number | null, items: list }]
    : Object.entries(
        list.reduce<Record<number, typeof list>>((acc, x) => {
          const h = Math.floor(effective(x, s).start / 60);
          (acc[h] ??= []).push(x);
          return acc;
        }, {}),
      ).map(([h, items]) => ({ hour: Number(h), items }));

  return (
    <>
      <header className="hero compact">
        <div className="brand">プログラム</div>
        <p style={{ marginTop: 4 }}>トーク・ワークショップ・ツアー・交流会を予約しよう</p>
        <div className="search" style={{ marginTop: 14 }}>
          <Icon name="search" size={18} />
          <input
            className="input"
            placeholder="例: 午後のAIのワークショップ"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            aria-label="プログラムを自然文で検索"
          />
        </div>
      </header>

      <div className="page">
        <div className="chips" style={{ marginTop: 12 }}>
          <button className={`filter ${kind === "all" ? "on" : ""}`} onClick={() => setKind("all")}>すべて</button>
          {KINDS.map((k) => (
            <button key={k} className={`filter ${kind === k ? "on" : ""}`} onClick={() => setKind(k)}>
              {KIND_LABEL[k]}
            </button>
          ))}
        </div>
        <div className="row between" style={{ margin: "6px 0" }}>
          <span className="small muted">
            {q.trim() ? `「${q}」の検索結果 ${list.length}件${label ? `（${label}）` : ""}` : `${list.length}件`}
          </span>
          <label className="small muted row" style={{ gap: 4 }}>
            <input type="checkbox" checked={hideDone} onChange={(e) => setHideDone(e.target.checked)} />
            終了したものを隠す
          </label>
        </div>

        {!q && (
          <div className="chips">
            {EXAMPLES.map((e) => (
              <button key={e} className="chip info" style={{ border: 0 }} onClick={() => setQ(e)}>
                <Icon name="sparkle" size={12} /> {e}
              </button>
            ))}
          </div>
        )}

        {groups.map((g) => (
          <div key={g.hour ?? "search"}>
            {g.hour !== null && <div className="hour">{g.hour}:00</div>}
            <div className="stack" style={{ marginTop: g.hour === null ? 12 : 0 }}>
              {g.items.map((x) => (
                <SessionCard key={x.id} session={x} />
              ))}
            </div>
          </div>
        ))}
        {list.length === 0 && <div className="empty">条件に合うプログラムが見つかりませんでした。<br />AIコンシェルジュに相談してみましょう ✨</div>}
      </div>
    </>
  );
}
