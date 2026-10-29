import { Fragment } from "react";
import { Link } from "react-router-dom";
import { SESSIONS, ZONES } from "../data/event";
import { SessionCard } from "./SessionCard";

/** AIの回答中の [[sessionId]] / [[map:zoneId]] をカード・リンクに置き換えて描画する */
export function RichText({ text }: { text: string }) {
  const parts = text.split(/(\[\[[^\]]+\]\])/g);
  return (
    <>
      {parts.map((p, i) => {
        const m = p.match(/^\[\[(map:)?([^\]]+)\]\]$/);
        if (!m) return <Fragment key={i}>{p}</Fragment>;
        if (m[1]) {
          const z = ZONES.find((x) => x.id === m[2]);
          return z ? (
            <Link key={i} to={`/map?to=${z.id}`} className="chip info" style={{ margin: "0 2px" }}>
              📍 {z.name}
            </Link>
          ) : null;
        }
        const s = SESSIONS.find((x) => x.id === m[2]);
        return s ? (
          <span key={i} className="ref">
            <SessionCard session={s} />
          </span>
        ) : null;
      })}
    </>
  );
}
