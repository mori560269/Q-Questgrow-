// content/*.yaml（キャストが編集する掲載情報）を読み込み、チェックして
// src/data/content.generated.json に書き出す。
// エラーはキャストが読んで直せるよう、ファイル名・何件目・直し方を日本語で出す。

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { parseDocument } from "yaml";
import { BOOTH_SLOTS, ZONE_LAYOUT } from "../src/data/venueLayout";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
export const CONTENT_DIR = path.join(ROOT, "content");
export const OUTPUT = path.join(ROOT, "src/data/content.generated.json");

const KINDS: Record<string, string> = {
  トーク: "talk",
  ワークショップ: "workshop",
  ツアー: "tour",
  交流会: "networking",
  パフォーマンス: "performance",
};
const WEEKDAYS = ["日", "月", "火", "水", "木", "金", "土"];

type Rec = Record<string, unknown>;

class Problems {
  list: string[] = [];
  add(where: string, msg: string) {
    this.list.push(`${where}: ${msg}`);
  }
}

function readYaml(dir: string, file: string, p: Problems): Rec | null {
  const full = path.join(dir, file);
  if (!fs.existsSync(full)) {
    p.add(file, "ファイルが見つかりません。消したり名前を変えたりしていないか確認してください。");
    return null;
  }
  const text = fs.readFileSync(full, "utf8");
  if (text.includes("\t")) {
    const line = text.split("\n").findIndex((l) => l.includes("\t")) + 1;
    p.add(`${file} の ${line}行目`, "タブ文字が入っています。行頭はスペースで字下げしてください。");
    return null;
  }
  const doc = parseDocument(text);
  if (doc.errors.length) {
    for (const e of doc.errors.slice(0, 3)) {
      const line = e.linePos?.[0].line;
      p.add(
        `${file}${line ? ` の ${line}行目あたり` : ""}`,
        "書き方が崩れています。字下げのずれ、「:」の後のスペース抜け、カッコやクォートの閉じ忘れがないか見てください。",
      );
    }
    return null;
  }
  const data = doc.toJS();
  if (!data || typeof data !== "object") {
    p.add(file, "中身が空です。");
    return null;
  }
  return data as Rec;
}

const str = (v: unknown) => (typeof v === "string" ? v.trim() : typeof v === "number" ? String(v) : "");

function list(v: unknown): unknown[] {
  if (v === undefined || v === null) return [];
  return Array.isArray(v) ? v : [v];
}

/** "10:20" → 620。YAML 1.1 の60進数（10:20 → 620）として数値で来た場合もそのまま受け付ける */
function parseTime(v: unknown): number | null {
  if (typeof v === "number" && Number.isInteger(v) && v >= 0 && v < 24 * 60) return v;
  const m = str(v).match(/^(\d{1,2}):(\d{2})$/);
  if (!m) return null;
  const h = Number(m[1]);
  const min = Number(m[2]);
  return h < 24 && min < 60 ? h * 60 + min : null;
}

function checkKeys(item: Rec, allowed: string[], where: string, p: Problems) {
  for (const k of Object.keys(item)) {
    if (!allowed.includes(k)) p.add(where, `知らない項目「${k}」があります。使える項目は ${allowed.join("・")} です（打ち間違いかもしれません）。`);
  }
}

function itemLabel(file: string, i: number, item: Rec, key: string) {
  const name = str(item[key]);
  return `${file} の ${i + 1}件目${name ? `（${key}: ${name}）` : ""}`;
}

export type ContentResult = { ok: true; data: unknown } | { ok: false; problems: string[] };

export function loadContent(dir: string = CONTENT_DIR): ContentResult {
  const p = new Problems();

  // ---- event.yaml ----
  const ev = readYaml(dir, "event.yaml", p) ?? {};
  checkKeys(ev, ["イベント名", "テーマ", "開催日", "会場名", "開場", "閉場", "WiFi名", "WiFiパスワード", "最初のお知らせ", "最初のお知らせ英語"], "event.yaml", p);
  for (const k of ["イベント名", "会場名"]) if (!str(ev[k])) p.add("event.yaml", `「${k}」が空です。`);
  const dateRaw = ev["開催日"] instanceof Date ? (ev["開催日"] as Date).toISOString().slice(0, 10) : str(ev["開催日"]);
  const dm = dateRaw.match(/^(\d{4})-(\d{1,2})-(\d{1,2})$/);
  if (!dm) p.add("event.yaml", `「開催日」は 2026-12-12 のように 年-月-日 で書いてください（今は「${dateRaw}」）。`);
  const doorsOpen = parseTime(ev["開場"]);
  const closes = parseTime(ev["閉場"]);
  if (doorsOpen === null) p.add("event.yaml", `「開場」は "9:30" のように書いてください（今は「${str(ev["開場"])}」）。`);
  if (closes === null) p.add("event.yaml", `「閉場」は "18:30" のように書いてください（今は「${str(ev["閉場"])}」）。`);
  let dateLabel = "";
  if (dm) {
    const d = new Date(Date.UTC(Number(dm[1]), Number(dm[2]) - 1, Number(dm[3])));
    dateLabel = `${dm[1]}年${Number(dm[2])}月${Number(dm[3])}日（${WEEKDAYS[d.getUTCDay()]}）`;
  }

  // ---- venue.yaml ----
  const venue = readYaml(dir, "venue.yaml", p) ?? {};
  checkKeys(venue, ["エリア", "ブース"], "venue.yaml", p);
  const zones: Record<string, { name: string; description: string }> = {};
  list(venue["エリア"]).forEach((raw, i) => {
    const item = (raw ?? {}) as Rec;
    const where = itemLabel("venue.yaml のエリア", i, item, "ID");
    checkKeys(item, ["ID", "名前", "説明"], where, p);
    const id = str(item.ID);
    if (!ZONE_LAYOUT.some((z) => z.id === id)) {
      p.add(where, `ID「${id}」は地図にありません。ID は変えずに、名前と説明だけを編集してください。`);
      return;
    }
    if (zones[id]) p.add(where, `ID「${id}」が2回出てきます。`);
    if (!str(item["名前"])) p.add(where, "「名前」が空です。");
    zones[id] = { name: str(item["名前"]), description: str(item["説明"]) };
  });
  for (const z of ZONE_LAYOUT) if (!zones[z.id]) p.add("venue.yaml", `エリア「${z.id}」が見つかりません。消さずに残してください。`);
  const booths: { id: string; name: string }[] = [];
  list(venue["ブース"]).forEach((raw, i) => {
    const item = (raw ?? {}) as Rec;
    const where = itemLabel("venue.yaml のブース", i, item, "番号");
    checkKeys(item, ["番号", "名前"], where, p);
    const id = str(item["番号"]).toUpperCase();
    if (!(id in BOOTH_SLOTS)) p.add(where, `「番号」は ${Object.keys(BOOTH_SLOTS).join("・")} のどれかにしてください（今は「${id}」）。`);
    else if (booths.some((b) => b.id === id)) p.add(where, `番号「${id}」が2回出てきます。`);
    else booths.push({ id, name: str(item["名前"]) });
  });
  const zoneByName = new Map(Object.entries(zones).map(([id, z]) => [z.name, id]));

  // ---- speakers.yaml ----
  const spDoc = readYaml(dir, "speakers.yaml", p) ?? {};
  checkKeys(spDoc, ["登壇者"], "speakers.yaml", p);
  const speakers = list(spDoc["登壇者"]).map((raw, i) => {
    const item = (raw ?? {}) as Rec;
    const where = itemLabel("speakers.yaml", i, item, "名前");
    checkKeys(item, ["名前", "肩書き", "紹介", "色"], where, p);
    const name = str(item["名前"]);
    if (!name) p.add(where, "「名前」が空です。");
    let hue = item["色"] === undefined ? [...name].reduce((a, c) => a + c.charCodeAt(0), 0) % 360 : Number(item["色"]);
    if (!Number.isFinite(hue) || hue < 0 || hue >= 360) {
      p.add(where, `「色」は 0〜359 の数字にしてください（今は「${str(item["色"])}」）。`);
      hue = 0;
    }
    return { id: `sp${i + 1}`, name, title: str(item["肩書き"]), bio: str(item["紹介"]), hue };
  });
  const names = new Set<string>();
  speakers.forEach((s, i) => {
    if (s.name && names.has(s.name)) p.add(`speakers.yaml の ${i + 1}件目`, `名前「${s.name}」が2回出てきます。`);
    names.add(s.name);
  });

  // ---- programs.yaml ----
  const prDoc = readYaml(dir, "programs.yaml", p) ?? {};
  checkKeys(prDoc, ["プログラム"], "programs.yaml", p);
  const ids = new Set<string>();
  const sessions = list(prDoc["プログラム"]).map((raw, i) => {
    const item = (raw ?? {}) as Rec;
    const where = itemLabel("programs.yaml", i, item, "ID");
    checkKeys(item, ["ID", "タイトル", "種類", "開始", "終了", "会場", "登壇者", "定員", "予約", "タグ", "説明"], where, p);

    const id = str(item.ID);
    if (!/^[A-Za-z0-9_-]+$/.test(id)) p.add(where, `「ID」は英数字で書いてください（今は「${id}」）。`);
    else if (ids.has(id)) p.add(where, `ID「${id}」がほかのプログラムと重なっています。`);
    ids.add(id);
    if (!str(item["タイトル"])) p.add(where, "「タイトル」が空です。");

    const kind = KINDS[str(item["種類"])];
    if (!kind) p.add(where, `「種類」は ${Object.keys(KINDS).join(" / ")} のどれかにしてください（今は「${str(item["種類"])}」）。`);

    const start = parseTime(item["開始"]);
    const end = parseTime(item["終了"]);
    if (start === null) p.add(where, `「開始」は "10:20" のように書いてください（今は「${str(item["開始"])}」）。`);
    if (end === null) p.add(where, `「終了」は "11:40" のように書いてください（今は「${str(item["終了"])}」）。`);
    if (start !== null && end !== null && end <= start) p.add(where, "「終了」が「開始」より前になっています。");

    const roomId = zoneByName.get(str(item["会場"]));
    if (!roomId) p.add(where, `会場「${str(item["会場"])}」が venue.yaml にありません。使える会場: ${[...zoneByName.keys()].join("、")}`);

    const speakerIds = list(item["登壇者"]).map((n) => {
      const sp = speakers.find((s) => s.name === str(n));
      if (!sp) p.add(where, `登壇者「${str(n)}」が speakers.yaml にいません。名前の表記（スペースなど）をそろえてください。`);
      return sp?.id ?? "";
    });

    const capacity = Number(item["定員"]);
    if (!Number.isInteger(capacity) || capacity <= 0) p.add(where, `「定員」は 1 以上の数字にしてください（今は「${str(item["定員"])}」）。`);

    const reserve = str(item["予約"]);
    if (reserve !== "必要" && reserve !== "不要") p.add(where, `「予約」は 必要 か 不要 にしてください（今は「${reserve}」）。`);

    return {
      id,
      title: str(item["タイトル"]),
      kind,
      start,
      end,
      roomId,
      speakerIds: speakerIds.filter(Boolean),
      capacity,
      tags: list(item["タグ"]).map(str).filter(Boolean),
      description: str(item["説明"]),
      requiresReservation: reserve === "必要",
    };
  });
  if (!sessions.length) p.add("programs.yaml", "プログラムが1件もありません。");

  // ---- faq.yaml ----
  const faqDoc = readYaml(dir, "faq.yaml", p) ?? {};
  checkKeys(faqDoc, ["よくある質問"], "faq.yaml", p);
  const faqs = list(faqDoc["よくある質問"]).map((raw, i) => {
    const item = (raw ?? {}) as Rec;
    const where = itemLabel("faq.yaml", i, item, "質問");
    checkKeys(item, ["質問", "答え", "キーワード"], where, p);
    if (!str(item["質問"])) p.add(where, "「質問」が空です。");
    if (!str(item["答え"])) p.add(where, "「答え」が空です。");
    return { q: str(item["質問"]), a: str(item["答え"]), keywords: list(item["キーワード"]).map(str).filter(Boolean) };
  });

  // ---- networking.yaml ----
  const net = readYaml(dir, "networking.yaml", p) ?? {};
  checkKeys(net, ["関心タグ", "目的"], "networking.yaml", p);
  const interests = list(net["関心タグ"]).map(str).filter(Boolean);
  const goals = list(net["目的"]).map(str).filter(Boolean);
  if (!interests.length) p.add("networking.yaml", "「関心タグ」が1つもありません。");
  if (!goals.length) p.add("networking.yaml", "「目的」が1つもありません。");

  if (p.list.length) return { ok: false, problems: p.list };

  return {
    ok: true,
    data: {
      event: {
        name: str(ev["イベント名"]),
        theme: str(ev["テーマ"]),
        date: dateRaw,
        dateLabel,
        venue: str(ev["会場名"]),
        doorsOpen,
        closes,
        wifiName: str(ev["WiFi名"]),
        wifiPassword: str(ev["WiFiパスワード"]),
        welcomeJa: str(ev["最初のお知らせ"]),
        welcomeEn: str(ev["最初のお知らせ英語"]),
      },
      speakers,
      sessions,
      zones,
      booths,
      faqs,
      interests,
      goals,
    },
  };
}

/** チェックして JSON を書き出す。内容が変わらなければ書き込まない（開発サーバーの無駄な再読み込みを防ぐ） */
export function buildContent(): ContentResult {
  const result = loadContent();
  if (result.ok) {
    const json = JSON.stringify(result.data, null, 2) + "\n";
    const prev = fs.existsSync(OUTPUT) ? fs.readFileSync(OUTPUT, "utf8") : "";
    if (prev !== json) fs.writeFileSync(OUTPUT, json);
  }
  return result;
}

export function formatProblems(problems: string[]): string {
  return [`❌ 掲載情報（content フォルダ）に ${problems.length} か所、直してほしいところがあります：`, "", ...problems.map((x) => `  ・${x}`), ""].join("\n");
}
