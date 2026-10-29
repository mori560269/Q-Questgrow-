import { Link, useNavigate } from "react-router-dom";
import { Avatar } from "../components/Avatar";
import { Icon } from "../components/Icon";
import { KIND_COLOR, SessionCard } from "../components/SessionCard";
import { EVENT, KIND_LABEL, SESSIONS, SPEAKERS, ZONES } from "../data/event";
import { effective, liveState, myBookings, nowMinutes, useStore } from "../lib/store";
import { fmt } from "../lib/time";

export function HomePage() {
  const s = useStore((x) => x);
  const nav = useNavigate();
  const now = nowMinutes(s);
  const unread = s.notices.filter((n) => !n.read).length;

  const live = SESSIONS.filter((x) => liveState(x, s) === "live");
  const upcoming = SESSIONS.filter((x) => liveState(x, s) === "scheduled").sort((a, b) => effective(a, s).start - effective(b, s).start);
  const nextMine = myBookings(s).find((x) => ["scheduled", "live"].includes(liveState(x, s)));
  const latest = s.announcements[0];

  const greeting = now < 720 ? "おはようございます" : now < 1020 ? "こんにちは" : "こんばんは";

  return (
    <>
      <header className="hero">
        <div className="hero-top">
          <Link to="/me" className="row" style={{ gap: 8 }}>
            <Avatar name={s.me.name} hue={s.me.hue} size={36} />
            <div className="brand">
              TED<b>x</b> Questgrow
            </div>
          </Link>
          <button className="icon-btn" onClick={() => nav("/notices")} aria-label="通知">
            <Icon name="bell" />
            {unread > 0 && <span className="dot" />}
          </button>
        </div>
        <h1>
          {greeting}、<br />
          {s.me.name}さん
        </h1>
        <p>
          {EVENT.dateLabel} ・ {EVENT.venue} ・ 現在 {fmt(now)}
        </p>
      </header>

      <div className="page">
        <div className="lift card">
          {nextMine ? (
            <NextUp id={nextMine.id} />
          ) : (
            <div className="row">
              <div className="grow">
                <div className="small muted">あなたの次の予定</div>
                <div style={{ fontWeight: 700, marginTop: 4 }}>まだ予約がありません</div>
              </div>
              <Link className="btn sm" to="/programs">
                探す
              </Link>
            </div>
          )}
          <div className="divider" />
          <div className="quick">
            <Link to="/plan">
              <span className="q-ic"><Icon name="ticket" /></span>チケット
            </Link>
            <Link to="/map">
              <span className="q-ic"><Icon name="route" /></span>ルート案内
            </Link>
            <Link to="/assistant">
              <span className="q-ic" style={{ color: "var(--red)" }}><Icon name="sparkle" /></span>AIに聞く
            </Link>
            <Link to="/connect">
              <span className="q-ic"><Icon name="heart" /></span>マッチング
            </Link>
          </div>
        </div>

        {latest && (
          <Link to="/notices" className={`banner ${latest.level}`} style={{ marginTop: 14 }}>
            <Icon name="megaphone" size={18} />
            <div className="grow">
              <b>{fmt(latest.at)}</b> {latest.ja}
            </div>
          </Link>
        )}

        {live.length > 0 && (
          <>
            <div className="section">
              <h2>いま開催中</h2>
            </div>
            <div className="stack">
              {live.map((x) => (
                <SessionCard key={x.id} session={x} compact />
              ))}
            </div>
          </>
        )}

        <div className="section">
          <h2>このあと</h2>
          <Link to="/programs">すべて見る</Link>
        </div>
        <div className="carousel">
          {upcoming.slice(0, 6).map((x) => (
            <Link key={x.id} to={`/programs/${x.id}`} className="poster" style={{ background: posterBg(KIND_COLOR[x.kind], x.id) }}>
              <span className="chip dark tl">
                {fmt(effective(x, s).start)} ・ {ZONES.find((z) => z.id === x.roomId)?.name}
              </span>
              <span className="small" style={{ opacity: 0.9 }}>{KIND_LABEL[x.kind]}</span>
              <h3>{x.title}</h3>
            </Link>
          ))}
          {upcoming.length === 0 && <div className="empty">本日のプログラムはすべて終了しました</div>}
        </div>

        <div className="section">
          <h2>会場の混雑状況</h2>
          <Link to="/map">マップ</Link>
        </div>
        <div className="card">
          {ZONES.filter((z) => z.type !== "service").map((z) => (
            <div key={z.id} className="row" style={{ marginBottom: 8 }}>
              <div style={{ width: 96 }} className="small">{z.name}</div>
              <div className="meter grow">
                <i style={{ width: `${(s.crowd[z.id] ?? 0) * 100}%`, background: crowdColor(s.crowd[z.id] ?? 0) }} />
              </div>
              <div style={{ width: 64, whiteSpace: "nowrap", textAlign: "right" }} className="small muted">{crowdLabel(s.crowd[z.id] ?? 0)}</div>
            </div>
          ))}
        </div>

        <div className="section">
          <h2>スピーカー</h2>
        </div>
        <div className="carousel">
          {SPEAKERS.map((sp) => (
            <div key={sp.id} className="card center" style={{ width: 132 }}>
              <div className="row" style={{ justifyContent: "center" }}>
                <Avatar name={sp.name} hue={sp.hue} size={64} />
              </div>
              <div style={{ fontWeight: 700, fontSize: 13, marginTop: 8 }} className="ellipsis">{sp.name}</div>
              <div className="small muted" style={{ lineHeight: 1.4, marginTop: 2 }}>{sp.title}</div>
            </div>
          ))}
        </div>

        {s.me.role === "staff" && (
          <Link to="/ops" className="card row" style={{ marginTop: 16, background: "var(--navy)", color: "#fff" }}>
            <Icon name="shield" />
            <div className="grow">
              <b>運営ダッシュボード</b>
              <div className="small" style={{ opacity: 0.7 }}>進行管理・受付・問い合わせ・配信</div>
            </div>
          </Link>
        )}
      </div>
    </>
  );
}

function NextUp({ id }: { id: string }) {
  const s = useStore((x) => x);
  const session = SESSIONS.find((x) => x.id === id)!;
  const { start, delay } = effective(session, s);
  const mins = start - nowMinutes(s);
  const room = ZONES.find((z) => z.id === session.roomId)!;
  return (
    <div>
      <div className="row between">
        <div className="small muted">あなたの次の予定</div>
        {liveState(session, s) === "live" ? (
          <span className="chip live">開催中</span>
        ) : (
          <span className={`chip ${mins <= 15 ? "red" : "info"}`}>
            <Icon name="clock" size={12} /> {mins >= 60 ? `${Math.floor(mins / 60)}時間${mins % 60}分後` : `あと${mins}分`}
          </span>
        )}
      </div>
      <Link to={`/programs/${session.id}`}>
        <div style={{ fontWeight: 900, fontSize: 17, margin: "6px 0 2px", lineHeight: 1.4 }}>{session.title}</div>
      </Link>
      <div className="row between">
        <div className="small muted">
          {fmt(start)}〜 ・ {room.name}
          {delay > 0 && <span style={{ color: "var(--danger)", fontWeight: 700 }}> （{delay}分遅れ）</span>}
        </div>
        <Link to={`/map?to=${room.id}`} className="link">
          道順 →
        </Link>
      </div>
    </div>
  );
}

export function crowdColor(v: number) {
  return v >= 0.8 ? "var(--danger)" : v >= 0.55 ? "var(--warn)" : "var(--ok)";
}
export function crowdLabel(v: number) {
  return v >= 0.8 ? "混雑" : v >= 0.55 ? "やや混雑" : "空いてる";
}

function posterBg(color: string, seed: string) {
  const h = [...seed].reduce((a, c) => a + c.charCodeAt(0), 0) % 360;
  return `radial-gradient(120% 90% at 100% 0%, ${color}, transparent 60%), radial-gradient(100% 100% at 0% 100%, hsl(${h} 70% 45%), transparent 70%), #141a3a`;
}
