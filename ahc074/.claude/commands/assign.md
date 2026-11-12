---
description: 担当を1本追加する（割り当て表の1行から worktree と tmux 窓を作って起動）
argument-hint: <名前> <観点> [claude|codex]
---
担当「$1」（観点: $2）を追加します。

1. `board/IDEA_STOCK.md` と `board/REJECTED.md` を見て、この観点に関係する案・閉じた問いを確認する。
2. 仮説・最小の実験・続ける条件を 1 行ずつ決める（既存の担当と重ならないこと）。
3. `ahc lane new $1 --angle "$2" --hypothesis "…" --experiment "…" --continue-if "…"`
4. `ahc lane start $1 --agent ${3:-claude}`
5. 使った案があれば `ahc idea take <ID> --lane $1`。`ahc decide` に割り当ての理由を残す。
