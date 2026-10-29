import { answerLocally, draftAnnouncementLocally, triageLocally, type LocalContext, type Triage } from "./nlp";

export type ChatTurn = { role: "user" | "assistant"; content: string };

let aiAvailable: Promise<boolean> | null = null;

export function checkAi(): Promise<boolean> {
  aiAvailable ??= fetch("/api/health")
    .then((r) => (r.ok ? r.json() : { ai: false }))
    .then((j: { ai?: boolean }) => Boolean(j.ai))
    .catch(() => false);
  return aiAvailable;
}

/**
 * AIコンシェルジュに質問する。Claude が使えない／失敗した場合はローカルNLPで回答する。
 * onDelta にはストリーミング中の累積テキストが渡される。
 */
export async function askConcierge(
  history: ChatTurn[],
  liveContext: string,
  local: LocalContext,
  onDelta: (text: string) => void,
): Promise<{ text: string; source: "ai" | "local" }> {
  const fallback = () => {
    const text = answerLocally(history[history.length - 1].content, local);
    onDelta(text);
    return { text, source: "local" as const };
  };
  if (!(await checkAi())) return fallback();

  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages: history.slice(-20), context: liveContext }),
    });
    if (!res.ok || !res.body) return fallback();

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    let text = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const events = buf.split("\n\n");
      buf = events.pop() ?? "";
      for (const ev of events) {
        if (!ev.startsWith("data: ")) continue;
        const data = JSON.parse(ev.slice(6)) as { type: string; text?: string };
        if (data.type === "text" && data.text) {
          text += data.text;
          onDelta(text);
        } else if (data.type === "error" || data.type === "refusal") {
          if (!text) return fallback();
        }
      }
    }
    return text ? { text, source: "ai" } : fallback();
  } catch {
    return fallback();
  }
}

export async function triage(text: string): Promise<Triage> {
  if (await checkAi()) {
    try {
      const res = await fetch("/api/triage", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      });
      if (res.ok) return (await res.json()) as Triage;
    } catch {
      // ローカルへフォールバック
    }
  }
  return triageLocally(text);
}

export async function draftAnnouncement(note: string): Promise<{ ja: string; en: string; source: "ai" | "local" }> {
  if (await checkAi()) {
    try {
      const res = await fetch("/api/announce", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ note }),
      });
      if (res.ok) return { ...((await res.json()) as { ja: string; en: string }), source: "ai" };
    } catch {
      // ローカルへフォールバック
    }
  }
  return { ...draftAnnouncementLocally(note), source: "local" };
}
