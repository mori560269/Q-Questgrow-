// ローカルで動く軽量な日本語NLP。
// - Claude API が使えない時のフォールバック回答
// - 自然文でのプログラム検索（常時利用）
// - 問い合わせの一次振り分け（APIの結果が返るまでの即時表示にも使う）

import { FAQS, SESSIONS, SPEAKERS, ZONES, type Session, type SessionKind, type Zone } from "../data/event";
import { fmt } from "./time";

export function normalize(s: string): string {
  return s
    .normalize("NFKC")
    .toLowerCase()
    // カタカナ → ひらがな（表記ゆれ吸収）
    .replace(/[ァ-ヶ]/g, (c) => String.fromCharCode(c.charCodeAt(0) - 0x60))
    .replace(/[\s、。！？!?・「」（）()]/g, "");
}

function bigrams(s: string): Set<string> {
  const n = normalize(s);
  const out = new Set<string>();
  if (n.length === 1) out.add(n);
  for (let i = 0; i < n.length - 1; i++) out.add(n.slice(i, i + 2));
  return out;
}

/** 文字バイグラムの Dice 係数（0..1） */
export function similarity(a: string, b: string): number {
  const A = bigrams(a);
  const B = bigrams(b);
  if (!A.size || !B.size) return 0;
  let hit = 0;
  for (const g of A) if (B.has(g)) hit++;
  return (2 * hit) / (A.size + B.size);
}

const includesAny = (text: string, words: string[]) => {
  const t = normalize(text);
  return words.some((w) => t.includes(normalize(w)));
};

// ---------- 自然文プログラム検索 ----------

const KIND_WORDS: Record<SessionKind, string[]> = {
  talk: ["トーク", "講演", "スピーチ", "登壇"],
  workshop: ["ワークショップ", "体験", "ws", "手を動かす"],
  tour: ["ツアー", "見学", "舞台裏", "バックステージ"],
  networking: ["交流", "ネットワーキング", "ミートアップ", "パーティー", "話せる"],
  performance: ["パフォーマンス", "ライブ", "音楽", "演奏"],
};

const TAG_SYNONYMS: Record<string, string[]> = {
  AI: ["ai", "人工知能", "生成ai", "機械学習", "chatgpt", "claude"],
  テクノロジー: ["テック", "技術", "ロボット", "エンジニア"],
  環境: ["環境", "気候", "サステナ", "農業", "sdgs", "海"],
  教育: ["教育", "学び", "学校", "先生"],
  起業: ["起業", "スタートアップ", "ビジネス"],
  デザイン: ["デザイン", "ものづくり"],
  アート: ["アート", "芸術", "工芸", "藍染", "染め"],
  インクルージョン: ["インクルージョン", "障害", "バリアフリー", "多様性", "義足"],
  科学: ["科学", "研究", "深海"],
};

export type TimeWindow = { from: number; to: number; label: string };

export function parseTimeWindow(q: string, now?: number): TimeWindow | null {
  const n = normalize(q);
  const m = n.match(/(\d{1,2})(?::(\d{2})|時)/);
  if (m) {
    const t = Number(m[1]) * 60 + Number(m[2] ?? 0);
    if (/以降|から|あと|後/.test(n)) return { from: t, to: 24 * 60, label: `${fmt(t)}以降` };
    if (/まで|前/.test(n)) return { from: 0, to: t, label: `${fmt(t)}まで` };
    return { from: t - 30, to: t + 60, label: `${fmt(t)}ごろ` };
  }
  if (n.includes("午前")) return { from: 0, to: 720, label: "午前" };
  if (n.includes("午後")) return { from: 720, to: 24 * 60, label: "午後" };
  if (n.includes("夕方")) return { from: 960, to: 24 * 60, label: "夕方" };
  if (now !== undefined && /今から|このあと|この後|次|これから|今/.test(n))
    return { from: now, to: now + 120, label: "これから" };
  return null;
}

export type SearchHit = { session: Session; score: number };

export function searchSessions(query: string, opts: { now?: number; sessions?: Session[] } = {}): {
  hits: SearchHit[];
  window: TimeWindow | null;
} {
  const sessions = opts.sessions ?? SESSIONS;
  const q = query.trim();
  if (!q) return { hits: sessions.map((s) => ({ session: s, score: 0 })), window: null };
  const window = parseTimeWindow(q, opts.now);
  const kinds = (Object.keys(KIND_WORDS) as SessionKind[]).filter((k) => includesAny(q, KIND_WORDS[k]));
  const tags = Object.keys(TAG_SYNONYMS).filter((t) => includesAny(q, [t, ...TAG_SYNONYMS[t]]));

  const hits = sessions
    .map((s) => {
      let score = 0;
      if (kinds.includes(s.kind)) score += 2;
      score += s.tags.filter((t) => tags.includes(t)).length * 2;
      const speakers = SPEAKERS.filter((sp) => s.speakerIds.includes(sp.id));
      const haystack = [s.title, s.description, ...s.tags, ...speakers.map((sp) => sp.name + sp.title)].join(" ");
      score += similarity(q, haystack) * 3;
      if (includesAny(haystack, [q])) score += 3;
      if (window) {
        const inWindow = s.start >= window.from && s.start < window.to;
        if (!inWindow) score = kinds.length || tags.length ? -1 : score - 5;
        else if (!kinds.length && !tags.length) score += 1;
      }
      return { session: s, score };
    })
    .filter((h) => h.score > 0.6)
    .sort((a, b) => b.score - a.score || a.session.start - b.session.start);
  return { hits, window };
}

// ---------- 場所の検出 ----------

const ZONE_WORDS: Record<string, string[]> = {
  main: ["メインホール", "ホール", "メイン", "大ホール"],
  studioA: ["スタジオa", "スタジオエー"],
  studioB: ["スタジオb", "スタジオビー"],
  lounge: ["ラウンジ", "交流"],
  booths: ["ブース", "展示"],
  food: ["フード", "食べ", "飲み物", "ドリンク", "カフェ", "軽食", "コーヒー"],
  lobby: ["ロビー", "受付", "インフォメーション", "クローク", "入口"],
  wc: ["トイレ", "お手洗い", "化粧室", "授乳"],
  first_aid: ["救護", "医務", "看護"],
};

export function detectZone(q: string): Zone | undefined {
  return ZONES.find((z) => includesAny(q, ZONE_WORDS[z.id] ?? [z.name]));
}

// ---------- フォールバック回答 ----------

export type LocalContext = {
  now: number;
  myBookings: Session[];
  delays: Record<string, number>;
  announcements: string[];
};

/** API不使用時のルールベース回答。返り値の [[id]] はセッションカードとして描画される。 */
export function answerLocally(question: string, ctx: LocalContext): string {
  const q = question;
  const zone = detectZone(q);
  const wantsPlace = includesAny(q, ["どこ", "場所", "行き方", "道", "迷", "近く", "where"]);

  if (zone && (wantsPlace || q.length < 12)) {
    return `「${zone.name}」は${zone.description}\nマップで現在地からのルートを確認できます → [[map:${zone.id}]]`;
  }

  if (includesAny(q, ["私の予定", "マイプラン", "予約した", "予約一覧", "自分の"])) {
    if (!ctx.myBookings.length) return "まだ予約がありません。気になるプログラムを探してみましょう。";
    return "あなたの予約はこちらです。" + ctx.myBookings.map((s) => `[[${s.id}]]`).join("");
  }

  if (includesAny(q, ["遅延", "遅れて", "押して", "お知らせ", "最新"])) {
    const delayed = Object.entries(ctx.delays).filter(([, d]) => d > 0);
    const lines = delayed.map(([id, d]) => `・[[${id}]] 約${d}分遅れ`);
    if (ctx.announcements.length) lines.unshift(`最新のお知らせ: ${ctx.announcements[0]}`);
    return lines.length ? lines.join("\n") : "現在、遅延やお知らせはありません。予定通り進行中です。";
  }

  const { hits, window } = searchSessions(q, { now: ctx.now });
  const asksProgram = includesAny(q, ["おすすめ", "セッション", "プログラム", "ワークショップ", "トーク", "次", "何が", "見たい", "参加したい", "興味"]);
  if (hits.length && (asksProgram || window)) {
    const top = hits.slice(0, 3).map((h) => h.session);
    const head = window ? `${window.label}のプログラムで、ご希望に合いそうなもの` : "ご希望に合いそうなプログラム";
    return `${head}です。\n${top.map((s) => `[[${s.id}]]`).join("")}`;
  }

  const ranked = FAQS.map((f) => ({
    f,
    score: similarity(q, f.q) + (includesAny(q, f.keywords) ? 0.6 : 0),
  })).sort((a, b) => b.score - a.score);
  if (ranked[0].score > 0.35) return ranked[0].f.a;

  if (hits.length) return `関連しそうなプログラムです。\n${hits.slice(0, 3).map((h) => `[[${h.session.id}]]`).join("")}`;

  return "すみません、うまくお答えできませんでした。「スタッフに問い合わせ」から質問を送ると、運営スタッフが回答します。";
}

// ---------- 問い合わせの一次振り分け ----------

export type InquiryCategory = "medical" | "lost" | "facility" | "program" | "accessibility" | "other";
export type Urgency = "high" | "medium" | "low";

export const CATEGORY_LABEL: Record<InquiryCategory, string> = {
  medical: "救護・安全",
  lost: "落とし物・迷子",
  facility: "設備・会場",
  program: "プログラム・予約",
  accessibility: "アクセシビリティ",
  other: "その他",
};

export type Triage = { category: InquiryCategory; urgency: Urgency; summary: string; suggestedReply: string; source: "local" | "ai" };

const CATEGORY_RULES: [InquiryCategory, string[]][] = [
  ["medical", ["体調", "気分", "倒れ", "けが", "怪我", "血", "救急", "痛", "熱", "めまい", "火事", "煙", "危ない", "地震"]],
  ["lost", ["落とし", "忘れ", "なくし", "紛失", "失くし", "迷子", "はぐれ", "財布", "スマホ"]],
  ["accessibility", ["車椅子", "段差", "ベビーカー", "手話", "字幕", "聴覚", "視覚", "多目的"]],
  ["facility", ["トイレ", "暑", "寒", "空調", "wifi", "wi-fi", "電源", "充電", "音が", "マイク", "席", "うるさ", "汚れ"]],
  ["program", ["予約", "キャンセル", "セッション", "ワークショップ", "時間", "遅延", "チケット", "qr", "受付"]],
];

const HIGH_WORDS = ["倒れ", "救急", "血", "火事", "煙", "迷子", "地震", "息", "意識", "危ない", "至急", "急ぎ"];

const REPLIES: Record<InquiryCategory, string> = {
  medical: "すぐにスタッフが向かいます。可能であればその場で安静にしてお待ちください。救護室はロビー右手です。",
  lost: "お問い合わせありがとうございます。インフォメーションで確認し、見つかり次第アプリでお知らせします。特徴（色・形など）を教えてください。",
  facility: "ご不便をおかけしています。担当スタッフが確認に向かいます。",
  program: "お問い合わせありがとうございます。担当スタッフが確認してご連絡します。",
  accessibility: "サポートスタッフがお手伝いに伺います。現在の場所を教えていただけますか？",
  other: "お問い合わせありがとうございます。担当スタッフより折り返しご連絡します。",
};

export function triageLocally(text: string): Triage {
  const category = CATEGORY_RULES.find(([, words]) => includesAny(text, words))?.[0] ?? "other";
  const urgency: Urgency = includesAny(text, HIGH_WORDS)
    ? "high"
    : category === "medical" || category === "accessibility"
      ? "medium"
      : "low";
  const summary = text.length > 40 ? text.slice(0, 40) + "…" : text;
  return { category, urgency, summary, suggestedReply: REPLIES[category], source: "local" };
}

/** 運営向け：アナウンス文のテンプレート生成（AI不使用時） */
export function draftAnnouncementLocally(note: string): { ja: string; en: string } {
  return {
    ja: `【お知らせ】${note.trim()}。ご不便をおかけしますが、ご理解とご協力をお願いいたします。`,
    en: `[Notice] ${note.trim()} — We apologize for any inconvenience and appreciate your understanding.`,
  };
}
