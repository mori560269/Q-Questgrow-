---
description: 指揮役の1周（提出の判定・担当の見直し・人間への要約）
---
conductor の定期作業を 1 周行います。

1. `ahc status` を見る。
2. `board/QUEUE.md` の未判定の提出を古い順に `ahc promote <解> --why "…"` で判定する。判定したら QUEUE.md の行を `- [x]` にして結果を書く。
3. `ahc lane list` で notes の更新が止まっている担当を探し、`.lanes/<名前>/notes.md` の末尾を読む。
   - 尽きている → `ahc lane rm <名前>`、別の切り口で `/assign`。
   - 詰まっている → tmux 窓の状態を見て人間に `ahc notify`。
4. `free` 担当が 1 本もなければ `/assign free-N 自由（BEST の細部改善）` を行う。
5. 昇格が 2 件以上あった、または 3 時間以上昇格がない場合は `critic` サブエージェントを呼ぶ。
6. 人間向けに 5 行で要約: BEST とその改善幅 / 判定した提出 / 担当の入れ替え / 人間に決めてほしいこと / 次の 1 周でやること。要約は `ahc decide` にも残す。
