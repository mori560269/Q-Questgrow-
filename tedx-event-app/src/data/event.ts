// イベントのデータ。
// 掲載内容（プログラム・登壇者・会場の名前・FAQなど）はキャストが content/*.yaml で編集し、
// npm run content がチェックして content.generated.json に書き出したものをここで読み込む。
// 時刻はすべて当日 0:00 からの経過分（例: 600 = 10:00）で表す。

import content from "./content.generated.json";
import { BOOTH_SLOTS, ZONE_LAYOUT, type ZoneType } from "./venueLayout";

export { EDGES, NODES, type MapEdge, type MapNode, type ZoneType } from "./venueLayout";

export const EVENT: {
  name: string;
  theme: string;
  date: string;
  dateLabel: string;
  venue: string;
  doorsOpen: number;
  closes: number;
  wifiName: string;
  wifiPassword: string;
  welcomeJa: string;
  welcomeEn: string;
} = content.event;

export type SessionKind = "talk" | "workshop" | "tour" | "networking" | "performance";

export type Speaker = {
  id: string;
  name: string;
  title: string;
  bio: string;
  hue: number; // アバターの色相
};

export type Session = {
  id: string;
  title: string;
  kind: SessionKind;
  start: number;
  end: number;
  roomId: string;
  speakerIds: string[];
  capacity: number;
  tags: string[];
  description: string;
  requiresReservation: boolean;
};

export const KIND_LABEL: Record<SessionKind, string> = {
  talk: "トーク",
  workshop: "ワークショップ",
  tour: "ツアー",
  networking: "交流会",
  performance: "パフォーマンス",
};

export const SPEAKERS: Speaker[] = content.speakers;
export const SESSIONS: Session[] = content.sessions as Session[];

// ---- 会場マップ（形は venueLayout.ts、名前と説明は content/venue.yaml） ----

export type Zone = {
  id: string;
  name: string;
  type: ZoneType;
  x: number;
  y: number;
  w: number;
  h: number;
  nodeId: string; // このゾーンへの入口ノード
  description: string;
};

const zoneText = content.zones as Record<string, { name: string; description: string }>;
export const ZONES: Zone[] = ZONE_LAYOUT.map((z) => ({ ...z, ...zoneText[z.id] }));

export const BOOTHS: { id: string; name: string; y: number }[] = content.booths.map((b) => ({ ...b, y: BOOTH_SLOTS[b.id] }));

// ---- 参加者（ネットワーキング用のデモデータ） ----

export type Role = "attendee" | "speaker" | "staff";

export type Person = {
  id: string;
  name: string;
  role: Role;
  title: string;
  interests: string[];
  goals: string[]; // 「話したい」「仲間を探す」など
  bio: string;
  hue: number;
};

export const INTERESTS: string[] = content.interests;

export const GOALS: string[] = content.goals;

export const PEOPLE: Person[] = [
  { id: "p1", name: "中村 さくら", role: "attendee", title: "UXデザイナー", interests: ["デザイン", "AI", "インクルージョン"], goals: ["アイデアを話したい", "コラボ相手を探す"], bio: "アクセシブルなプロダクトづくりに関心があります。", hue: 330 },
  { id: "p2", name: "Tom Becker", role: "attendee", title: "Climate Tech VC", interests: ["環境", "起業", "都市"], goals: ["投資・支援"], bio: "Seed-stage climate startups in APAC.", hue: 150 },
  { id: "p3", name: "高橋 悠斗", role: "attendee", title: "大学生（工学部）", interests: ["テクノロジー", "科学", "AI"], goals: ["学びたい", "仲間を探したい"], bio: "ロボットサークル所属。海洋ロボットに興味津々。", hue: 210 },
  { id: "p4", name: "林 由美子", role: "attendee", title: "小学校教員", interests: ["教育", "地域", "インクルージョン"], goals: ["学びたい", "アイデアを話したい"], bio: "探究学習の授業づくりをしています。", hue: 40 },
  { id: "p5", name: "Arjun Mehta", role: "attendee", title: "MLエンジニア", interests: ["AI", "テクノロジー", "教育"], goals: ["コラボ相手を探す", "採用・転職"], bio: "EdTechでの機械学習活用を模索中。", hue: 260 },
  { id: "p6", name: "森田 葵", role: "attendee", title: "地域おこし協力隊", interests: ["地域", "起業", "アート"], goals: ["仲間を探したい", "コラボ相手を探す"], bio: "山あいの町で空き家活用に取り組んでいます。", hue: 90 },
  { id: "p7", name: "石井 翔", role: "staff", title: "TEDxQuestgrow 運営（会場）", interests: ["音楽", "デザイン"], goals: ["アイデアを話したい"], bio: "困ったことがあれば何でも声をかけてください！", hue: 0 },
  { id: "p8", name: "青山 ひかり", role: "speaker", title: "海洋ロボティクス研究者", interests: ["科学", "テクノロジー", "環境"], goals: ["アイデアを話したい", "コラボ相手を探す"], bio: "深海の話、なんでも聞いてください。", hue: 200 },
  { id: "p9", name: "藤井 美玲", role: "speaker", title: "高校生 起業家", interests: ["教育", "地域", "起業"], goals: ["仲間を探したい"], bio: "空き家を学生の学び場に。", hue: 50 },
];

// ---- FAQ（AIアシスタントの知識ベース / オフライン時の回答源。content/faq.yaml） ----

export type Faq = { q: string; a: string; keywords: string[] };

export const FAQS: Faq[] = content.faqs;
