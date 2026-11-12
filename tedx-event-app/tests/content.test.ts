import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { CONTENT_DIR, loadContent } from "../scripts/content";

/** content フォルダを一時ディレクトリにコピーし、1ファイルだけ書き換えて読み込む */
function withEdit(file: string, edit: (text: string) => string) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "content-"));
  for (const f of fs.readdirSync(CONTENT_DIR)) fs.copyFileSync(path.join(CONTENT_DIR, f), path.join(dir, f));
  fs.writeFileSync(path.join(dir, file), edit(fs.readFileSync(path.join(dir, file), "utf8")));
  const result = loadContent(dir);
  fs.rmSync(dir, { recursive: true });
  return result.ok ? [] : result.problems;
}

describe("content（掲載情報）", () => {
  it("同梱の content はそのまま通る", () => {
    expect(loadContent().ok).toBe(true);
  });

  it("時刻の書き間違いを、何件目のどのプログラムかと一緒に指摘する", () => {
    const problems = withEdit("programs.yaml", (t) => t.replace('開始: "10:20"', '開始: "25:00"'));
    expect(problems.join("\n")).toMatch(/programs\.yaml の 2件目（ID: s2）: 「開始」は "10:20" のように/);
  });

  it("speakers.yaml にいない登壇者・存在しない会場・種類の打ち間違いを指摘する", () => {
    const problems = withEdit("programs.yaml", (t) =>
      t.replace("[青山 ひかり, Lena Fischer]", "[青山ひかり]").replace("会場: スタジオA", "会場: スタジオC").replace("種類: ツアー", "種類: 見学"),
    ).join("\n");
    expect(problems).toContain("登壇者「青山ひかり」が speakers.yaml にいません");
    expect(problems).toContain("会場「スタジオC」が venue.yaml にありません");
    expect(problems).toContain("「種類」は トーク / ワークショップ");
  });

  it("字下げが崩れたら行番号つきで知らせる", () => {
    const problems = withEdit("faq.yaml", (t) => t.replace("    答え: 受付", "  答え: 受付"));
    expect(problems.join("\n")).toMatch(/faq\.yaml の \d+行目あたり: 書き方が崩れています/);
  });

  it("項目名の打ち間違いを知らせる", () => {
    const problems = withEdit("speakers.yaml", (t) => t.replace("肩書き:", "肩書:"));
    expect(problems.join("\n")).toContain("知らない項目「肩書」");
  });
});
