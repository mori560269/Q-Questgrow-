// npm run content : 掲載情報をチェックしてアプリに反映する
import fs from "node:fs";
import { buildContent, formatProblems } from "./content";

const result = buildContent();
if (result.ok) {
  console.log("✅ 掲載情報（content フォルダ）に問題はありません。");
} else {
  console.error(formatProblems(result.problems));
  // GitHub Actions では、結果ページの一番上と、変更ファイルの画面にもエラーを出す
  if (process.env.GITHUB_ACTIONS) {
    for (const p of result.problems) {
      const file = p.match(/^(\w+\.yaml)/)?.[1];
      console.log(`::error${file ? ` file=tedx-event-app/content/${file}` : ""},title=掲載情報の書き方::${p}`);
    }
    if (process.env.GITHUB_STEP_SUMMARY) {
      const md = [
        `## ❌ 掲載情報に ${result.problems.length} か所、直してほしいところがあります`,
        "",
        ...result.problems.map((p) => `- ${p}`),
        "",
        "直し方は `tedx-event-app/content/README.md` の「書き方のルール」を見てください。",
        "",
      ].join("\n");
      fs.appendFileSync(process.env.GITHUB_STEP_SUMMARY, md);
    }
  }
  process.exit(1);
}
