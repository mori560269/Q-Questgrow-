// イベントのマスターデータ。実運用ではCMSやDBから取得する想定。
// 時刻はすべて当日 0:00 からの経過分（例: 600 = 10:00）で表す。

export const EVENT = {
  name: "TEDxQuestgrow 2026",
  theme: "Grow Beyond — 境界の向こうへ",
  date: "2026-12-12",
  dateLabel: "2026年12月12日（土）",
  venue: "Questgrow ホール",
  doorsOpen: 570,
  closes: 1110,
};

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

export const SPEAKERS: Speaker[] = [
  { id: "sp1", name: "青山 ひかり", title: "海洋ロボティクス研究者", bio: "深海探査ロボットの開発を通じて、人類がまだ知らない世界を可視化している。", hue: 200 },
  { id: "sp2", name: "Daniel Okafor", title: "社会起業家 / 教育NPO代表", bio: "アフリカと日本をつなぐオンライン教室を運営。学びのアクセスを再設計する。", hue: 30 },
  { id: "sp3", name: "佐伯 蓮", title: "AIエシックス研究者", bio: "生成AIと社会の関係を研究。テクノロジーが『誰のためにあるか』を問い続ける。", hue: 270 },
  { id: "sp4", name: "宮下 つむぎ", title: "伝統工芸 × デザイナー", bio: "400年続く染織の技法を現代プロダクトへ。職人と若者の橋渡し役。", hue: 340 },
  { id: "sp5", name: "Lena Fischer", title: "都市農業スタートアップCEO", bio: "ビルの屋上を食料生産拠点に変えるプロジェクトを世界12都市で展開。", hue: 120 },
  { id: "sp6", name: "小田切 健", title: "パラアスリート / 義足エンジニア", bio: "自らの経験から義足を設計。『障害』の定義をテクノロジーで書き換える。", hue: 10 },
  { id: "sp7", name: "藤井 美玲", title: "高校生 起業家", bio: "17歳で地域の空き家を学生の学び場に再生する事業を立ち上げた。", hue: 50 },
  { id: "sp8", name: "Kumi Ensemble", title: "音楽パフォーマンス集団", bio: "和楽器とエレクトロニクスを融合させるパフォーマンスユニット。", hue: 300 },
];

export const SESSIONS: Session[] = [
  { id: "s1", title: "オープニング & パフォーマンス", kind: "performance", start: 600, end: 620, roomId: "main", speakerIds: ["sp8"], capacity: 600, tags: ["音楽", "アート"], description: "和楽器とエレクトロニクスが響き合う、一日の幕開け。", requiresReservation: false },
  { id: "s2", title: "Session 1｜深海は、最後のフロンティア", kind: "talk", start: 620, end: 700, roomId: "main", speakerIds: ["sp1", "sp5"], capacity: 600, tags: ["科学", "環境", "テクノロジー"], description: "深海ロボットと都市農業。地球の『まだ使われていない場所』に眠る可能性を語る2トーク。", requiresReservation: true },
  { id: "s3", title: "Session 2｜学びをひらく", kind: "talk", start: 730, end: 810, roomId: "main", speakerIds: ["sp2", "sp7"], capacity: 600, tags: ["教育", "社会", "起業"], description: "国境と年齢を越えて、学びの場をつくる人たちの挑戦。", requiresReservation: true },
  { id: "s4", title: "Session 3｜テクノロジーと人間らしさ", kind: "talk", start: 900, end: 980, roomId: "main", speakerIds: ["sp3", "sp6"], capacity: 600, tags: ["AI", "テクノロジー", "インクルージョン"], description: "AIと義足。テクノロジーは人間の可能性をどこまで広げるのか。", requiresReservation: true },
  { id: "s5", title: "Session 4｜受け継ぐ、つくりかえる", kind: "talk", start: 1010, end: 1070, roomId: "main", speakerIds: ["sp4"], capacity: 600, tags: ["デザイン", "アート", "地域"], description: "伝統を守ることは、変わり続けること。", requiresReservation: true },
  { id: "w1", title: "AIと一緒にアイデアを育てるワークショップ", kind: "workshop", start: 720, end: 800, roomId: "studioA", speakerIds: ["sp3"], capacity: 30, tags: ["AI", "テクノロジー", "クリエイティブ"], description: "生成AIを“共同発想者”として使い、社会課題のアイデアを形にする実践型ワークショップ。PC不要。", requiresReservation: true },
  { id: "w2", title: "藍染めミニ体験", kind: "workshop", start: 840, end: 900, roomId: "studioB", speakerIds: ["sp4"], capacity: 20, tags: ["アート", "デザイン", "体験"], description: "ハンカチを藍で染める体験。汚れてもよい服装推奨。", requiresReservation: true },
  { id: "w3", title: "屋上ファーム設計ラボ", kind: "workshop", start: 840, end: 900, roomId: "studioA", speakerIds: ["sp5"], capacity: 30, tags: ["環境", "都市", "デザイン"], description: "身近なビルを題材に、屋上農園をチームで設計してみる。", requiresReservation: true },
  { id: "w4", title: "義足に触れてみよう — エンジニアリング体験", kind: "workshop", start: 990, end: 1040, roomId: "studioB", speakerIds: ["sp6"], capacity: 20, tags: ["テクノロジー", "インクルージョン", "体験"], description: "実際の義足パーツに触れ、設計の工夫を学ぶ。", requiresReservation: true },
  { id: "t1", title: "バックステージツアー", kind: "tour", start: 820, end: 845, roomId: "lobby", speakerIds: [], capacity: 15, tags: ["体験"], description: "TEDxの舞台裏をスタッフが案内。集合はロビーのインフォメーション前。", requiresReservation: true },
  { id: "n1", title: "ランチ・ミートアップ「テーマ別テーブル」", kind: "networking", start: 810, end: 880, roomId: "lounge", speakerIds: [], capacity: 80, tags: ["交流", "起業", "教育", "環境"], description: "興味テーマ別のテーブルでランチ。アプリのマッチングで相性の良い人と同席できます。", requiresReservation: true },
  { id: "n2", title: "スピーカーと話そう Q&A ラウンジ", kind: "networking", start: 985, end: 1010, roomId: "lounge", speakerIds: ["sp1", "sp2", "sp7"], capacity: 50, tags: ["交流"], description: "登壇者と少人数で対話できるラウンジセッション。", requiresReservation: true },
  { id: "n3", title: "アフターパーティー", kind: "networking", start: 1075, end: 1110, roomId: "lounge", speakerIds: [], capacity: 120, tags: ["交流"], description: "一日の余韻を語り合うクロージング交流会。", requiresReservation: false },
];

// ---- 会場マップ ----
// SVG座標系 (0..360 x 0..520)。zone は描画用の矩形、node はルート検索用のグラフ頂点。

export type ZoneType = "hall" | "room" | "booth" | "food" | "service" | "lounge";

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

export const ZONES: Zone[] = [
  { id: "main", name: "メインホール", type: "hall", x: 20, y: 20, w: 320, h: 150, nodeId: "n_main", description: "トークセッション会場。座席は自由席（予約者優先エリアあり）。" },
  { id: "studioA", name: "スタジオA", type: "room", x: 20, y: 200, w: 110, h: 80, nodeId: "n_studioA", description: "ワークショップ会場（定員30名）。" },
  { id: "studioB", name: "スタジオB", type: "room", x: 20, y: 290, w: 110, h: 70, nodeId: "n_studioB", description: "ワークショップ会場（定員20名）。" },
  { id: "lounge", name: "ラウンジ", type: "lounge", x: 230, y: 200, w: 110, h: 110, nodeId: "n_lounge", description: "交流会・ランチ・Q&Aラウンジ。" },
  { id: "booths", name: "展示ブース", type: "booth", x: 150, y: 200, w: 60, h: 160, nodeId: "n_booths", description: "パートナー企業・団体の展示（B1〜B6）。" },
  { id: "food", name: "フードコート", type: "food", x: 230, y: 320, w: 110, h: 60, nodeId: "n_food", description: "軽食・ドリンク。キャッシュレスのみ。" },
  { id: "lobby", name: "ロビー / 受付", type: "service", x: 100, y: 410, w: 160, h: 90, nodeId: "n_lobby", description: "受付・チェックイン・インフォメーション・クローク。" },
  { id: "wc", name: "トイレ（多目的あり）", type: "service", x: 20, y: 380, w: 60, h: 50, nodeId: "n_wc", description: "多目的トイレ・授乳室あり。" },
  { id: "first_aid", name: "救護室", type: "service", x: 290, y: 410, w: 50, h: 50, nodeId: "n_aid", description: "体調不良の際はこちらへ。看護師常駐。" },
];

export const BOOTHS = [
  { id: "B1", name: "海洋ロボット展示", y: 215 },
  { id: "B2", name: "アップサイクル雑貨", y: 240 },
  { id: "B3", name: "AI 似顔絵ブース", y: 265 },
  { id: "B4", name: "地域の空き家マップ", y: 290 },
  { id: "B5", name: "屋上ファームの野菜", y: 315 },
  { id: "B6", name: "TEDx メッセージウォール", y: 340 },
];

export type MapNode = { id: string; x: number; y: number };
export type MapEdge = { a: string; b: string; stairs?: boolean };

export const NODES: MapNode[] = [
  { id: "n_lobby", x: 180, y: 420 },
  { id: "n_hub", x: 180, y: 390 },
  { id: "n_west", x: 140, y: 390 },
  { id: "n_east", x: 220, y: 390 },
  { id: "n_corrW", x: 140, y: 245 },
  { id: "n_corrE", x: 220, y: 245 },
  { id: "n_top", x: 180, y: 185 },
  { id: "n_main", x: 180, y: 170 },
  { id: "n_studioA", x: 130, y: 240 },
  { id: "n_studioB", x: 130, y: 325 },
  { id: "n_booths", x: 180, y: 360 },
  { id: "n_lounge", x: 230, y: 255 },
  { id: "n_food", x: 230, y: 350 },
  { id: "n_wc", x: 80, y: 405 },
  { id: "n_aid", x: 290, y: 435 },
];

export const EDGES: MapEdge[] = [
  { a: "n_lobby", b: "n_hub" },
  { a: "n_hub", b: "n_west" },
  { a: "n_hub", b: "n_east" },
  { a: "n_hub", b: "n_booths" },
  { a: "n_west", b: "n_studioB" },
  { a: "n_west", b: "n_corrW" },
  { a: "n_west", b: "n_wc" },
  { a: "n_studioB", b: "n_corrW" },
  { a: "n_corrW", b: "n_studioA" },
  { a: "n_corrW", b: "n_top" },
  { a: "n_east", b: "n_food" },
  { a: "n_east", b: "n_corrE" },
  { a: "n_food", b: "n_corrE" },
  { a: "n_corrE", b: "n_lounge" },
  { a: "n_corrE", b: "n_top" },
  { a: "n_top", b: "n_main" },
  { a: "n_lobby", b: "n_aid" },
  // 展示ブース中央を抜ける近道（階段あり）
  { a: "n_booths", b: "n_top", stairs: true },
];

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

export const INTERESTS = [
  "AI", "テクノロジー", "教育", "環境", "起業", "デザイン", "アート", "地域", "インクルージョン", "科学", "都市", "音楽",
];

export const GOALS = ["仲間を探したい", "アイデアを話したい", "採用・転職", "投資・支援", "学びたい", "コラボ相手を探す"];

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

// ---- FAQ（AIアシスタントの知識ベース / オフライン時の回答源） ----

export type Faq = { q: string; a: string; keywords: string[] };

export const FAQS: Faq[] = [
  { q: "受付は何時からですか？", a: "受付（ロビー）は9:30開始です。チケットのQRコードを受付スタッフに提示してください。", keywords: ["受付", "開場", "何時", "チェックイン", "入場"] },
  { q: "Wi-Fiはありますか？", a: "会場Wi-Fi「TEDxQuestgrow-Guest」が利用できます。パスワードはロビーの掲示とアプリのお知らせに記載しています。", keywords: ["wifi", "wi-fi", "ワイファイ", "インターネット", "ネット"] },
  { q: "昼食はどうすればいいですか？", a: "フードコートで軽食・ドリンクを販売しています（キャッシュレスのみ）。13:30〜14:40はラウンジでランチ・ミートアップもあります（要予約）。", keywords: ["昼食", "ランチ", "ご飯", "食事", "フード", "お腹"] },
  { q: "荷物を預けられますか？", a: "ロビーのクロークで手荷物をお預かりします（無料・18:45まで）。貴重品はご自身で管理してください。", keywords: ["荷物", "クローク", "預け", "コート", "ロッカー"] },
  { q: "途中入退場はできますか？", a: "メインホールはトークの合間（拍手の後）に入退場できます。トーク中の入場はスタッフがご案内します。", keywords: ["途中", "入退場", "遅刻", "遅れ", "退場"] },
  { q: "車椅子でも参加できますか？", a: "全エリア段差なしで移動できるルートがあります。マップの「段差を避ける」をオンにすると車椅子対応ルートを表示します。多目的トイレはトイレエリアにあります。", keywords: ["車椅子", "バリアフリー", "段差", "エレベーター", "多目的"] },
  { q: "撮影してもいいですか？", a: "トーク中のフラッシュ撮影・動画撮影はご遠慮ください。写真撮影（フラッシュなし）は可能です。トークは後日TEDxの公式チャンネルで公開されます。", keywords: ["撮影", "写真", "動画", "カメラ", "録画"] },
  { q: "体調が悪くなったら？", a: "ロビー右手の救護室（看護師常駐）へお越しください。近くのスタッフに声をかけていただいても対応します。", keywords: ["体調", "気分", "救護", "具合", "けが", "怪我", "医務"] },
  { q: "落とし物をしました", a: "ロビーのインフォメーションで落とし物をお預かりしています。アプリの「スタッフに問い合わせ」からも連絡できます。", keywords: ["落とし物", "忘れ物", "なくした", "紛失", "失くし"] },
  { q: "予約していないセッションに参加できますか？", a: "空席があれば参加できます。満席の場合はキャンセル待ちに登録すると、空きが出た時に自動で繰り上がります。", keywords: ["予約", "当日", "空き", "キャンセル待ち", "満席", "参加"] },
];
