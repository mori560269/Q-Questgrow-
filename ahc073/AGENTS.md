# AGENTS.md — AHC（長期）With AI 部門ハーネスの作業ルール

このリポジトリは、1つの AHC 問題を複数の AI エージェント（Claude Code / Codex CLI）で並列に解くための作業場です。
人間が方針と提出を握り、エージェントは測定に基づいて解を改善します。

## 0. 絶対に守ること
- **AtCoder への提出はしない。** 提出は人間が手で行う。`ahc pack` で提出用ファイルを作るところまで。
- **測っていない改善を主張しない。** 「速くなったはず」「良くなるはず」は notes.md に仮説として書き、結果は `ahc` の出力を貼る。
- **昇格の線（ahc.toml の `[promote]`）を結果を見てから動かさない。** 動かす必要があれば人間に提案し、理由を `ahc decide` で残す。
- **自分の worktree の外を編集しない。** ホームの共有物（board/）は `ahc idea / reject / decide / handoff` 経由でだけ書く。
- 大きなファイル（数百 MB 超）を作らない。出力やログは `.ahc/` 以下に任せる。
- 問題文とローカルツールの外の情報（他の参加者の解法、コンテスト中の公開情報）を探しに行かない。

## 1. ディレクトリ
| パス | 中身 |
|---|---|
| `problem/statement.md` | 問題文（人間が置く） |
| `problem/tools/` | 公式ローカルツール（gen / vis / tester）。`cargo build -r` 済み |
| `solutions/<name>/` | 解。`main.cpp`（提出するソース）と `README.md`（内容、または起点との差分）を必ず置く |
| `templates/` | `timer.hpp`（実時間 + 仮想時計）、`main.cpp` ひな形、担当用テンプレ |
| `board/` | 共有黒板: `BEST`, `BRIEF.md`, `CONSTRAINTS.md`, `IDEA_STOCK.md`, `REJECTED.md`, `decisions.md`, `ONE_PAGE.md`, `QUEUE.md`, `events.jsonl` |
| `.lanes/<name>/` | 担当ごとの git worktree（`STRATEGY.md` と `notes.md` を持つ） |
| `.ahc/` | 評価の記録（`db.sqlite`）、ビルド物、出力、`report.html`（git 管理外） |

## 2. コマンド早見表（`bin/ahc`、PATH に通すか `$AHC_HOME/bin/ahc`）
```
ahc eval <解> --set smoke|select|dev|full     # 評価して記録（同一ソースの結果は再利用）
ahc compare <基準> <候補...> --set dev [--fresh] # ケースごとに交互に測る。gain / z / 勝ち負け
ahc promote <候補> [--why "..."]              # 登録済みの線で BEST への昇格を判定
ahc handoff solutions/<name> -m "要約"         # 担当の改善版をホームへ提出（README.md 必須）
ahc cases <run|解> [--vs <run|解>] --sort diff  # ケースごとの表（悪いケースを探す）
ahc stats <run|解> [--vs ...] [--by N]          # 入力の特徴量ごとの成績
ahc idea add "案" / ahc idea list               # 案の在庫
ahc reject "案" --reason "根拠" --reopen-if "条件" # 否定のカード
ahc decide "判断と理由"                          # 判断の記録
ahc notify "人間に知らせたいこと"
ahc status                                     # 全体の状況
ahc pack <解> --minify --check                  # 提出用1ファイル（ヘッダ展開・縮小・サイズ確認）
```
`<解>` は `solutions/` の名前、ディレクトリ、`BEST` のどれでもよい。

## 3. 測定のルール
- 集合の使い分け: `smoke`（動くか）→ `select`（見込みがあるか）→ `dev`（昇格の判定）→ `full`（最終確認、人間の指示があるとき）。
- 時間で打ち切る解を比べるときは `--fresh`（同じ回の中で基準と候補を交互に測る）。過去の記録と比べない。
- 可能なら仮想時計（`templates/timer.hpp`、`--virtual`）で比べる。負荷や機械の差でスコアが揺れない。
- 改善幅が小さい（< 0.1%）ときは z 値と勝ち負けの数を必ず見る。`dev` で z ≥ 2 に届かなければ「差なし」と書く。
- TLE・RE・スコア 0 が 1 件でも出たら、改善より先に直す。

## 4. 役割
### conductor（指揮役 — ホームのセッション）
- 担当の割り当て（`ahc lane new ... --angle --hypothesis --experiment --continue-if` → `ahc lane start`）。
- `board/QUEUE.md` の提出を順に `ahc promote` で判定し、結果を `ahc decide` に残す。
- 担当が尽きたら止め（`ahc lane rm`）、新しいセッションで**別の切り口**を渡す。最良版を自由に改善する `free` 担当を常に 1 本以上動かす。
- 担当の捉え方が同じものに集まっていないか見る。重なっていたら出し直させる（`/framing`）。
- 人間への窓口。人間の判断が要ることは `ahc notify` で知らせ、返事を待つ間も止まらず他を進める（その判断は保留のまま）。
- 昇格のたびに `board/ONE_PAGE.md` が更新される。人間が 1 画面で状況を掴めるよう、`board/BRIEF.md` を最新に保つ。

### worker（改善担当）
- STRATEGY.md の観点だけを掘る。最小の実験 → 測定 → notes.md → 次、の繰り返し。
- 改善が出たら README.md に差分を書いて `ahc handoff`。その後は handoff した版を起点に続けてよい。
- 観点が尽きたら、尽きた理由と次の案を notes.md と `ahc idea add` に残して止まる。

### free（自由担当）
- BEST から出発し、観点を縛らずに細部（定数・近傍の選び方・高速化・無駄な手）を改善する。

### merger（統合役）
- 複数の handoff を部品ごとに分け、1 部品ずつ BEST に入れて `ahc compare --fresh` で採否を測り、1 本にまとめる。
- 部品の採否は表にして README.md に残す。

### analyst / critic / advisor（実行しない役）
- analyst: `ahc cases / stats` を読み、悪いケースの共通点と伸びしろを報告する。
- critic: 直近の判断と notes を読み、前提の誤り・測定の穴・見落とした方向を指摘する。
- advisor: コードを走らせずに案だけ出す。案は `ahc idea add` で登録する。

## 5. 書き方
- notes.md は実験 1 回 = 1 節: **変更 / コマンド / 結果（ahc の出力を貼る）/ 結論**。
- 否定した案は必ず `ahc reject` に。理由と「どうなったら再開するか」を書く。同じ問いを繰り返さないため。
- コードのコメントは最小限。提出サイズに効くので、長い説明は README.md に書く。
