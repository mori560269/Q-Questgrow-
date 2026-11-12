import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { Icon } from "../components/Icon";
import { SubHeader } from "../components/SubHeader";
import { PEOPLE } from "../data/event";
import { actions, useStore } from "../lib/store";

export function ChatPage() {
  const { id } = useParams();
  const person = PEOPLE.find((p) => p.id === id);
  const all = useStore((s) => s.messages);
  const meId = useStore((s) => s.me.id);
  const [text, setText] = useState("");
  const end = useRef<HTMLDivElement>(null);
  const msgs = all.filter((m) => m.from === id || m.to === id);
  useEffect(() => {
    end.current?.scrollIntoView({ behavior: "smooth" });
  }, [msgs.length]);
  if (!person) return <div className="empty">ユーザーが見つかりません</div>;

  const icebreakers = [`はじめまして！${person.interests[0]}に興味があります`, "休憩時間に少しお話しできませんか？", "今日いちばん印象に残ったトークは？"];

  return (
    <>
      <SubHeader title={person.name} />
      <div className="chat">
        <div className="center small muted" style={{ margin: "8px 0" }}>{person.title} ・ {person.interests.map((i) => `#${i}`).join(" ")}</div>
        {msgs.length === 0 && (
          <div className="stack">
            <div className="small muted center">会話のきっかけ</div>
            {icebreakers.map((t) => (
              <button key={t} className="chip info" style={{ border: 0, alignSelf: "center", padding: "8px 14px", fontSize: 12 }} onClick={() => setText(t)}>
                {t}
              </button>
            ))}
          </div>
        )}
        {msgs.map((m) => (
          <div key={m.id} className={`bubble ${m.from === meId ? "me" : "them"}`}>{m.text}</div>
        ))}
        <div ref={end} />
      </div>
      <div className="composer">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (!text.trim()) return;
            actions.sendMessage(person.id, text.trim());
            setText("");
          }}
        >
          <input className="input" value={text} onChange={(e) => setText(e.target.value)} placeholder="メッセージを入力" aria-label="メッセージ" />
          <button className="btn" aria-label="送信"><Icon name="send" size={18} /></button>
        </form>
      </div>
    </>
  );
}
