import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Icon } from "../components/Icon";
import { BOOTHS, EDGES, NODES, SESSIONS, ZONES, type ZoneType } from "../data/event";
import { shortestPath, walkMinutes } from "../lib/route";
import { effective, liveState, useStore } from "../lib/store";
import { fmt } from "../lib/time";
import { crowdColor, crowdLabel } from "./Home";

const TYPE_FILL: Record<ZoneType, string> = {
  hall: "#ffe3e0",
  room: "#e3ebff",
  booth: "#fff1d6",
  food: "#ffe9d2",
  service: "#eceef5",
  lounge: "#e0f5ea",
};

export function MapPage() {
  const s = useStore((x) => x);
  const [params, setParams] = useSearchParams();
  const to = params.get("to");
  const [from, setFrom] = useState("lobby");
  const [avoidStairs, setAvoidStairs] = useState(false);
  const [heat, setHeat] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);

  const dest = ZONES.find((z) => z.id === to);
  const origin = ZONES.find((z) => z.id === from)!;
  const route = useMemo(
    () => (dest ? shortestPath(NODES, EDGES, origin.nodeId, dest.nodeId, { avoidStairs }) : null),
    [dest, origin, avoidStairs],
  );
  const points = route?.path.map((id) => NODES.find((n) => n.id === id)!).map((n) => `${n.x},${n.y}`).join(" ");
  const usesStairs = route?.path.some((id, i) => {
    const nxt = route.path[i + 1];
    return EDGES.some((e) => e.stairs && ((e.a === id && e.b === nxt) || (e.b === id && e.a === nxt)));
  });

  const sel = ZONES.find((z) => z.id === selected);
  const selSessions = sel ? SESSIONS.filter((x) => x.roomId === sel.id && liveState(x, s) !== "done") : [];

  const go = (id: string) => {
    setParams({ to: id });
    setSelected(null);
  };

  return (
    <>
      <header className="hero compact">
        <div className="brand">会場マップ</div>
        <p style={{ marginTop: 4 }}>エリアをタップして詳細・ルートを確認</p>
      </header>

      <div className="page" style={{ marginTop: 12 }}>
        <div className="card" style={{ padding: 12 }}>
          <div className="row">
            <Icon name="pin" size={18} />
            <select className="input" style={{ padding: "8px 10px" }} value={from} onChange={(e) => setFrom(e.target.value)} aria-label="現在地">
              {ZONES.map((z) => (
                <option key={z.id} value={z.id}>現在地: {z.name}</option>
              ))}
            </select>
          </div>
          <div className="row" style={{ marginTop: 8 }}>
            <Icon name="route" size={18} />
            <select className="input" style={{ padding: "8px 10px" }} value={to ?? ""} onChange={(e) => go(e.target.value)} aria-label="目的地">
              <option value="">目的地を選択</option>
              {ZONES.map((z) => (
                <option key={z.id} value={z.id}>{z.name}</option>
              ))}
            </select>
          </div>
          <div className="row wrap" style={{ marginTop: 10, gap: 8 }}>
            <button className={`filter ${avoidStairs ? "on" : ""}`} onClick={() => setAvoidStairs(!avoidStairs)}>
              ♿ 段差を避ける
            </button>
            <button className={`filter ${heat ? "on" : ""}`} onClick={() => setHeat(!heat)}>
              🔥 混雑ヒートマップ
            </button>
          </div>
          {dest && route && (
            <div className="banner info" style={{ marginTop: 10 }}>
              <Icon name="route" size={18} />
              <div>
                <b>{origin.name} → {dest.name}</b>：徒歩 約{walkMinutes(route.distance)}分
                {usesStairs ? "（階段あり・最短）" : avoidStairs ? "（段差なしルート）" : ""}
              </div>
            </div>
          )}
        </div>

        <div className="map-wrap" style={{ marginTop: 12 }}>
          <svg viewBox="0 0 360 520" role="img" aria-label="会場マップ">
            <rect x="5" y="5" width="350" height="510" rx="18" fill="#f7f8fc" stroke="#d9dce8" />
            {/* 通路 */}
            {EDGES.map((e, i) => {
              const a = NODES.find((n) => n.id === e.a)!;
              const b = NODES.find((n) => n.id === e.b)!;
              return <line key={i} x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke={e.stairs ? "#c9a227" : "#e1e4ef"} strokeWidth={e.stairs ? 3 : 8} strokeDasharray={e.stairs ? "3 4" : undefined} strokeLinecap="round" />;
            })}
            {ZONES.map((z) => {
              const c = s.crowd[z.id] ?? 0;
              const active = z.id === to || z.id === selected;
              return (
                <g key={z.id} className="zone" onClick={() => setSelected(z.id)}>
                  <rect
                    x={z.x}
                    y={z.y}
                    width={z.w}
                    height={z.h}
                    rx={12}
                    fill={heat ? heatFill(c) : TYPE_FILL[z.type]}
                    stroke={active ? "#e62b1e" : "#c9cde0"}
                    strokeWidth={active ? 3 : 1}
                  />
                  <text x={z.x + z.w / 2} y={z.y + (z.id === "booths" ? 14 : z.h / 2)} textAnchor="middle" dominantBaseline="middle" className="zone-label" fill="#2a2f4a">
                    {z.name.split("（")[0]}
                  </text>
                  {heat && (
                    <text x={z.x + z.w / 2} y={z.y + z.h / 2 + 15} textAnchor="middle" className="zone-label" fill="#555" style={{ fontSize: 10 }}>
                      {crowdLabel(c)}
                    </text>
                  )}
                </g>
              );
            })}
            {BOOTHS.map((b) => (
              <g key={b.id} style={{ pointerEvents: "none" }}>
                <rect x={156} y={b.y + 10} width={48} height={18} rx={5} fill="#fff" stroke="#f0c674" />
                <text x={180} y={b.y + 20} textAnchor="middle" dominantBaseline="middle" style={{ fontSize: 9, fontWeight: 700 }} fill="#8a6200">
                  {b.id}
                </text>
              </g>
            ))}
            <text x={180} y={190} textAnchor="middle" style={{ fontSize: 9 }} fill="#888">▲ 入口</text>
            {points && <polyline points={points} className="route-line" />}
            {route && (() => {
              const a = NODES.find((n) => n.id === route.path[0])!;
              const b = NODES.find((n) => n.id === route.path[route.path.length - 1])!;
              return (
                <>
                  <circle cx={a.x} cy={a.y} r={8} fill="#3a6df0" stroke="#fff" strokeWidth={3} />
                  <circle cx={b.x} cy={b.y} r={9} fill="#e62b1e" stroke="#fff" strokeWidth={3} />
                </>
              );
            })()}
          </svg>
          <div className="legend" style={{ padding: "6px 6px 2px" }}>
            <span><i style={{ background: "#3a6df0" }} />現在地</span>
            <span><i style={{ background: "#e62b1e" }} />目的地</span>
            <span><i style={{ background: "#c9a227" }} />階段の近道</span>
          </div>
        </div>

        <div className="section"><h2>展示ブース</h2></div>
        <div className="card">
          {BOOTHS.map((b) => (
            <div key={b.id} className="row" style={{ padding: "6px 0" }}>
              <span className="chip warn">{b.id}</span>
              <span className="small">{b.name}</span>
            </div>
          ))}
        </div>
      </div>

      {sel && (
        <div className="sheet" role="dialog" aria-label={sel.name}>
          <div className="grip" />
          <div className="row between">
            <h3 style={{ margin: 0 }}>{sel.name}</h3>
            <button className="icon-btn" style={{ background: "#f1f2f8", color: "var(--text)" }} onClick={() => setSelected(null)} aria-label="閉じる">
              <Icon name="x" size={18} />
            </button>
          </div>
          <p className="small muted" style={{ margin: "6px 0 10px", lineHeight: 1.6 }}>{sel.description}</p>
          <div className="row small" style={{ marginBottom: 10 }}>
            混雑度
            <div className="meter grow">
              <i style={{ width: `${(s.crowd[sel.id] ?? 0) * 100}%`, background: crowdColor(s.crowd[sel.id] ?? 0) }} />
            </div>
            {crowdLabel(s.crowd[sel.id] ?? 0)}
          </div>
          {selSessions.slice(0, 2).map((x) => (
            <Link key={x.id} to={`/programs/${x.id}`} className="row small" style={{ padding: "6px 0" }}>
              <b>{fmt(effective(x, s).start)}</b>
              <span className="ellipsis grow">{x.title}</span>
              {liveState(x, s) === "live" && <span className="chip live">LIVE</span>}
            </Link>
          ))}
          <div className="row" style={{ marginTop: 10 }}>
            <button className="btn grow" onClick={() => go(sel.id)}>ここへ行く</button>
            <button className="btn secondary" onClick={() => { setFrom(sel.id); setSelected(null); }}>現在地にする</button>
          </div>
        </div>
      )}
    </>
  );
}

function heatFill(c: number) {
  const base = c >= 0.8 ? "#e2412f" : c >= 0.55 ? "#f2a516" : "#12a46b";
  return `color-mix(in srgb, ${base} ${Math.round(20 + c * 50)}%, white)`;
}
