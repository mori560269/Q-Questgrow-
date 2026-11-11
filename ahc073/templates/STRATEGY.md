# STRATEGY: {name}

作成 {created} ／ 役割 **{role}**

| 項目 | 内容 |
|---|---|
| 観点 | {angle} |
| 起点 | `{origin}` |
| 仮説 | {hypothesis} |
| 最小の実験 | {experiment} |
| 続ける条件 | {continue_if} |

## 守ること
- 作業はこの worktree の中だけ。解は `solutions/{name}/` で育てる（main.cpp と README.md）。
- 測定は `ahc compare BEST solutions/{name} --set select` → 良ければ `--set dev --fresh`。
- 改善が出たら README.md に「起点からの差分」を書き、`ahc handoff solutions/{name} -m "要約"`。
- 棄却した案は `ahc reject "案" --reason "根拠" --reopen-if "条件"`。思いついた別の案は `ahc idea add "..."`。
- 実験ごとに notes.md へ: 何を変えたか / 測定コマンド / 結果 / 結論。
- 共有の方針は ホームの `board/BRIEF.md` と `board/CONSTRAINTS.md`、閉じた問いは `board/REJECTED.md` を先に読む。
- この観点が尽きたら、notes.md に「尽きた理由」と「次に試すなら」を書いて止まる（無理に続けない）。
