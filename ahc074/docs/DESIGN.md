# 設計の根拠 — AHC074 With AI 部門の上位勢から取り入れたもの

AHC074（HACK TO THE FUTURE 2027 予選、2026/10/30〜11/9）は、長期 AHC に Human Only / With AI の 2 部門制が初めて適用された回です。
このハーネスは主に次の 2 つの公開記事を読んで作りました（2026/11/11 時点、システムテスト前）。

- thun-c「AHC074 With AI部門のAIの使い方（暫定10位）」Qiita — Claude Code と Codex CLI を最大 21 本並べる自作ハーネス
- hitonanode/ahc074（GitHub）と参加記 — 解ごとの README、pahcer による全ケース評価、交互比較、AI 向けテキストビジュアライザ

AtCoder の解説タブ（With AI 部門は投稿が GP30 の条件）はこの環境から読めなかったため、1〜3 位の記事はまだ反映していません。読めたら追記してください。

## 取り入れたもの

| 上位勢の工夫 | このハーネスでの実装 |
|---|---|
| 担当 = 1 セッション + git worktree + STRATEGY.md + notes.md | `ahc lane new/start`、`templates/STRATEGY.md` |
| 配送係（pump）が返答の終わった担当に続行を送る／進まなければ停止と判定 | `ahc pump`（画面の変化で判定、`idle_cycles` / `stall_cycles`） |
| 指揮役・担当・統合役・相談役・批評役の分担 | AGENTS.md の役割、`.claude/agents/`、`/review` |
| 評価器が共有の枠で測って SQLite に記録、同一ソースは再利用 | `ahc eval`、`.ahc/db.sqlite` |
| 動作確認 50 / 選別 200 / 手元比較 1000 / 本番相当 3000 の段階 | `[eval.sets]` smoke / select / dev / full |
| 候補と基準をケースごとに交互に走らせ、昇格はその回だけで比べる | `ahc compare --fresh`、`ahc promote`（既定で再測定） |
| 仮想時計（処理ごとの料金）で判断し、実時間は非常時の打ち切りだけ | `templates/timer.hpp`（`-DAHC_VIRTUAL_CLOCK`） |
| 昇格の線は測定前に登録し、結果を見て動かさない | `ahc.toml [promote]`、AGENTS.md §0 |
| 提出はすべて人間が手で | ハーネスは提出しない。`ahc pack` まで |
| 解ごとに main.cpp と README.md（改良元との差分）を必ず置く | `ahc handoff` は README.md がないと拒否 |
| 否定のカード（再開条件つき）、案の在庫、閉じた問いの一覧 | `ahc reject`、`ahc idea`、`board/REJECTED.md` |
| 人間向けの 1 画面の要約、判断の記録、通知 | `board/ONE_PAGE.md`、`ahc decide`、`ahc notify` |
| 最良版を改善する自由な担当を常に 1 本以上／尽きた担当は新しいセッションで別の切り口 | `--role free`、`/review` 手順 4 |
| 実装の前に捉え方を出させ、重なりを見て仲間分け・出し直し | `/framing`、`framer` サブエージェント |
| 「1 位は大きな見落としがあるはず」という作った目標・前提を疑う問い | `/premise`、`critic` サブエージェント |
| 提出上限に収める機械的な縮小 | `ahc pack --minify --check` |
| AI 向けのビジュアライザ（テキストで cases / stats / state） | `ahc cases`、`ahc stats` |
| 評価のたびに作り直す HTML レポート | `.ahc/report.html` |
| GP30 のための「AI をどう使ったか」の解説投稿 | `/writeup`（記録から下書き） |

## 上位勢が報告した「効かなかった・限界があった」点への対処

- **全担当が同じ捉え方に収束した** → `/framing` で捉え方の段階を挟み、critic に収束を見張らせる。
- **同じ依頼文では毎回同じ捉え方になった** → 担当ごとに観点・仮説・最小の実験を変えた STRATEGY.md を渡す。
- **担当の試作が巨大なファイルを作って PC が止まった** → AGENTS.md で禁止、出力は `.ahc/out/` に集約し stderr は末尾 200KB だけ残す。
- **確認待ちで止まった担当に長く気づかなかった** → `ahc pump` が `stall_cycles` で通知。
- **負荷で探索量が減り、昇格判定が揺れた** → 交互測定と仮想時計。並列数は `eval.parallel` で絞れる。
- **手元の速さがジャッジと違った** → 本番相当の測定はジャッジに近い CPU で（README 参照）。

## まだ入れていないもの（必要になったら）

- 担当の上限数・ラウンド制の自動化（いまは conductor が `/review` で判断）
- 2 台目のマシンでの分散評価（`AHC_HOME` を共有ストレージに置けば `ahc eval` を別機で流せる）
- ChatGPT Pro など外部サービスに渡す相談用 zip の作成（`ahc pack` の出力と問題文・ツールをまとめるだけで作れる）
- 入力の層別サンプリング（入力分布が一様でない問題向け）
