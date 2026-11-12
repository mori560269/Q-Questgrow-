---
description: 解説タブに投稿する「AIをどう使ったか」の下書きを作る（With AI 部門の GP30 条件）
---
コンテスト後に解説タブへ投稿する「AI を用いてどのように取り組んだか」の下書きを作ります（投稿は人間が行う）。

材料: `board/ONE_PAGE.md`、`board/decisions.md`、`board/events.jsonl`、`board/REJECTED.md`、`board/lanes/*/notes.md`、`ahc runs --limit 200`、最終提出の README.md。

構成:
1. 結果（順位・スコア）と使った AI モデル・サービス・ハーネスの概要
2. ハーネスの構成（役割・並列数・評価環境・記録）
3. スコアに効いた指示・判断（時刻つき、指示の原文を引用）と、その前後の改善幅
4. 最終解の概要
5. 効かなかったこと・次に直すこと
数字はすべて記録から取り、推測で埋めないこと。`writeup/` に Markdown で保存する。
