# ahc-harness — AHC（長期）With AI 部門向けハーネス

Claude Code / Codex CLI を複数の「担当」として並べ、**測定に基づいて解を育てる**ための作業場です。
AHC074 With AI 部門の上位勢の公開記事（設計の根拠は `docs/DESIGN.md`）を参考に、効いたと報告されている仕組みを最小構成で実装しています。

- 標準ライブラリだけの Python 1 ファイル（`harness/ahc.py`、Python 3.11+）
- 必要なもの: git、g++、tmux（担当を並べる場合）、Claude Code / Codex CLI、公式ローカルツール

> **ルールの確認を必ず。** With AI 部門では「自分だけで開発したハーネス」と「誰でも使えるサービス」は使えますが、
> 他人が開発に関わった非公開のハーネスは禁止です。このハーネスは**提出を自動化しません**（提出は人間が手で行う設計）。
> 参加前に最新の「長期 AtCoder Heuristic Contest 生成AI利用ルール」を読み、自分の使い方が収まるか確認してください。

## 構成

```
ahc.toml            問題ごとの設定（目的の向き・ツール・テスト集合・昇格の線・エージェント起動コマンド）
AGENTS.md           エージェントの作業ルール（CLAUDE.md から @import）
bin/ahc             CLI（どの worktree からでもホームを見つける）
harness/ahc.py      本体
templates/          timer.hpp（実時間＋仮想時計）、main.cpp ひな形、STRATEGY.md、担当の初回指示
.claude/agents/     analyst / critic / advisor / framer（実行しない役のサブエージェント）
.claude/commands/   /kickoff /framing /assign /review /premise /writeup
board/              共有黒板（BEST, BRIEF, IDEA_STOCK, REJECTED, decisions, ONE_PAGE, QUEUE, events.jsonl）
solutions/<name>/   解（main.cpp と README.md が必須）
.lanes/<name>/      担当ごとの git worktree（STRATEGY.md と notes.md）
.ahc/               評価記録 db.sqlite、ビルド物、出力、report.html
```

## 流れ

```
            人間（方針・昇格の線・提出）
               │  ahc notify / ONE_PAGE.md
        ┌──────┴──────┐
        │ conductor    │  ホームの Claude Code（/review を回す）
        └──┬───┬───┬──┘
   lane new/start  promote ← QUEUE.md ← handoff
     ┌─────┼─────┐
  worker  free  merger …  各 worktree の Claude Code / Codex（pump が続行を送る）
     └─────┴─────┘
           ahc eval / compare（交互測定・仮想時計・SQLite）
```

## はじめかた

```bash
export PATH=$PWD/bin:$PATH
ahc init                                  # board/ を作り git init
# 1) 公式ツールを problem/tools/ に展開して cargo build -r、問題文を problem/statement.md に
# 2) ahc.toml を問題に合わせる（Claude Code で /kickoff を使えば一緒に直してくれる）
ahc gen 3000                              # 入力を増やす（dev=1000, full=3000 を想定）
git add -A && git commit -m init          # worktree の起点になるので一度コミット

claude                                    # ホームで起動 → /kickoff → /framing
```

担当を手で足すとき:

```bash
ahc lane new gap1 --angle gap --hypothesis "…" --experiment "…" --continue-if "select で +0.3%"
ahc lane start gap1 --agent claude        # tmux セッション ahc に窓を作って起動
ahc pump --interval 90                    # 別窓で。止まった担当に続行を送り、長く止まれば通知
```

日々の確認: `ahc status`、`.ahc/report.html`、`board/ONE_PAGE.md`。提出前に `ahc pack BEST --minify --check`。

## 測定の考え方

| 仕組み | コマンド | 目的 |
|---|---|---|
| 結果の再利用 | `eval` | ソース＋ローカルヘッダ＋ビルドコマンドのハッシュが同じなら測り直さない |
| 交互測定 | `compare --fresh` / `promote` | 基準と候補を seed ごとに交互に流し、同じ回の中だけで比べる（負荷の揺れを相殺） |
| 対応のある統計 | `compare` | log 比の平均（gain）、標準誤差、z 値、勝ち/負け/引き分け |
| 事前登録した線 | `promote` | `ahc.toml [promote]` の線をすべて満たしたときだけ BEST を更新 |
| 仮想時計 | `--virtual` + `timer.hpp` | 処理の料金で打ち切るので、機械や負荷が違っても出力が同じ |
| AI 向けの観察 | `cases` / `stats` | ケースごと・特徴量の層ごとの表をテキストで出す |

手元とジャッジの速さが違うと時間で打ち切る解の点が変わります。本番相当の測定はジャッジに近い CPU のマシンで行うのが理想です（`AHC_HOME` を同じ構成にして `ahc eval` を流す）。

## 設定のポイント（ahc.toml）

- `objective` を間違えると比較がすべて逆になります。最初に確認。
- `score_regex` は公式ツールの出力に合わせる（既定は `Score = 123`）。
- `[eval.sets]` は入力ファイルのソート順のインデックス範囲。
- `[agents]` の起動コマンドは手元の CLI に合わせて変えてください（権限モードなど）。`{prompt_file}` に初回指示が入ります。
- `[notify] cmd` に ntfy や Slack の webhook を入れると、昇格・停止を手元に通知できます。
