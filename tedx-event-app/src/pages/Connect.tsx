import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Avatar } from "../components/Avatar";
import { Icon } from "../components/Icon";
import { toast } from "../components/Toast";
import { GOALS, INTERESTS, PEOPLE, type Role } from "../data/event";
import { rankMatches } from "../lib/matching";
import { actions, useStore } from "../lib/store";

const ROLE_LABEL: Record<Role, string> = { attendee: "来場者", speaker: "登壇者", staff: "スタッフ" };
const ROLE_CHIP: Record<Role, string> = { attendee: "", speaker: "red", staff: "dark" };

export function ConnectPage() {
  const s = useStore((x) => x);
  const [tab, setTab] = useState<"match" | "friends">("match");
  const [editing, setEditing] = useState(false);
  const [roleFilter, setRoleFilter] = useState<Role | "all">("all");
  const matches = useMemo(() => rankMatches(s.me, PEOPLE), [s.me]);
  const friends = PEOPLE.filter((p) => s.connections[p.id] === "connected");

  const toggle = (key: "interests" | "goals", v: string) => {
    const cur = s.me[key];
    actions.updateProfile({ [key]: cur.includes(v) ? cur.filter((x) => x !== v) : [...cur, v] });
  };

  return (
    <>
      <header className="hero compact">
        <div className="brand">つながる</div>
        <p style={{ marginTop: 4 }}>関心の近い来場者・登壇者・スタッフと出会おう</p>
      </header>

      <div className="page" style={{ marginTop: 12 }}>
        <div className="card">
          <div className="row between">
            <div>
              <b>あなたの関心と目的</b>
              <div className="small muted">マッチングに使われます</div>
            </div>
            <button className="link" onClick={() => setEditing(!editing)}>{editing ? "完了" : "編集"}</button>
          </div>
          <div className="row wrap" style={{ gap: 6, marginTop: 10 }}>
            {(editing ? INTERESTS : s.me.interests).map((i) => (
              <button key={i} className={`filter ${s.me.interests.includes(i) ? "on" : ""}`} style={{ padding: "5px 12px", fontSize: 12 }} onClick={() => editing && toggle("interests", i)}>
                #{i}
              </button>
            ))}
          </div>
          <div className="row wrap" style={{ gap: 6, marginTop: 8 }}>
            {(editing ? GOALS : s.me.goals).map((g) => (
              <button key={g} className={`chip ${s.me.goals.includes(g) ? "info" : ""}`} style={{ border: 0 }} onClick={() => editing && toggle("goals", g)}>
                {g}
              </button>
            ))}
          </div>
        </div>

        <div className="seg" style={{ marginTop: 14 }}>
          <button className={tab === "match" ? "on" : ""} onClick={() => setTab("match")}>おすすめ</button>
          <button className={tab === "friends" ? "on" : ""} onClick={() => setTab("friends")}>つながり（{friends.length}）</button>
        </div>

        {tab === "match" && (
          <>
            <div className="chips" style={{ marginTop: 10 }}>
              {(["all", "attendee", "speaker", "staff"] as const).map((r) => (
                <button key={r} className={`filter ${roleFilter === r ? "on" : ""}`} onClick={() => setRoleFilter(r)}>
                  {r === "all" ? "すべて" : ROLE_LABEL[r]}
                </button>
              ))}
            </div>
            <div className="stack" style={{ marginTop: 6 }}>
              {matches
                .filter((m) => roleFilter === "all" || m.person.role === roleFilter)
                .map((m) => {
                  const st = s.connections[m.person.id];
                  return (
                    <div key={m.person.id} className="card">
                      <div className="row" style={{ alignItems: "flex-start" }}>
                        <Avatar name={m.person.name} hue={m.person.hue} size={50} />
                        <div className="grow">
                          <div className="row" style={{ gap: 6 }}>
                            <b>{m.person.name}</b>
                            <span className={`chip ${ROLE_CHIP[m.person.role]}`}>{ROLE_LABEL[m.person.role]}</span>
                          </div>
                          <div className="small muted">{m.person.title}</div>
                          <p className="small" style={{ margin: "6px 0", lineHeight: 1.5 }}>{m.person.bio}</p>
                          {m.reasons.map((r) => (
                            <div key={r} className="small" style={{ color: "var(--info)" }}>✓ {r}</div>
                          ))}
                        </div>
                        <div className="center">
                          <div style={{ fontWeight: 900, fontSize: 18, color: "var(--red)" }}>{Math.round(m.score * 100)}%</div>
                          <div className="small muted">相性</div>
                        </div>
                      </div>
                      <div className="row" style={{ marginTop: 10, justifyContent: "flex-end" }}>
                        {st === "connected" ? (
                          <Link to={`/connect/${m.person.id}`} className="btn sm dark">
                            <Icon name="chat" size={14} /> メッセージ
                          </Link>
                        ) : st === "requested" ? (
                          <button className="btn sm secondary" disabled>リクエスト送信済み</button>
                        ) : (
                          <button className="btn sm" onClick={() => { actions.connect(m.person.id); toast(`${m.person.name}さんにつながりリクエストを送りました`); }}>
                            つながる
                          </button>
                        )}
                      </div>
                    </div>
                  );
                })}
            </div>
          </>
        )}

        {tab === "friends" && (
          <div className="stack" style={{ marginTop: 12 }}>
            {friends.length === 0 && <div className="empty">まだつながりがありません。<br />おすすめから気になる人に声をかけてみましょう。</div>}
            {friends.map((p) => {
              const last = [...s.messages].reverse().find((m) => m.from === p.id || m.to === p.id);
              return (
                <Link key={p.id} to={`/connect/${p.id}`} className="card row">
                  <Avatar name={p.name} hue={p.hue} size={44} />
                  <div className="grow">
                    <b>{p.name}</b>
                    <div className="small muted ellipsis">{last ? last.text : p.title}</div>
                  </div>
                  <span className="muted">›</span>
                </Link>
              );
            })}
          </div>
        )}
      </div>
    </>
  );
}
