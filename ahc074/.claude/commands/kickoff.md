---
description: 問題公開直後の立ち上げ（設定・ツール確認・最初の解・BEST 初期化）
---
問題が公開された直後の立ち上げを行います。あなたは conductor です。

1. `problem/statement.md` を読み、目的（最大化/最小化）、インタラクティブか、時間制限、入力の1行目の項目を確認する。
2. `ahc.toml` の `[problem]` `[tools]` `[features]` を問題に合わせて直す（変更点を人間に1画面で示す）。
3. `problem/tools/` で `cargo build -r` が済んでいるか確認し、入力が足りなければ `ahc gen 3000` を提案する（実行は人間の了承後）。
4. `templates/main.cpp` を元に、**必ず正しい出力を出す最小の解**を `solutions/baseline/` に作り、README.md を書く。
5. `ahc eval baseline --set smoke` でエラーが 0 件であることを確認し、`ahc promote baseline --init`。
6. `board/BRIEF.md` に問題の要点・スコアの式・効きそうな自由度を書く。
7. 最後に `/framing` へ進むことを提案する。
