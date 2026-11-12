# free3（起点: pflip-1112135529 からの差分）

1. 列の長さの配分: 重み 1+SLOPE·p（SLOPE 5）→ 1+SLOPE·p^EXPO（SLOPE 1, EXPO 1.5）、さらに丸めでできた凸凹を昇順に並べ直す（PPSORT）。
   p の小さい列は 2 枚（最小）のまま、後ろの列をより長く。期待値評価（seed0-47）で約 -0.4%。
2. 実行時間の削減（出力は同じ部分 + 模擬計算の間引き）:
   - portFlip は列の先頭と末尾の位置だけ探す。fixPorts の portStack(c) は先頭 2 枚だけの走査に。
   - 模擬計算中は mv の出力文字列と visible() の assert を省く（SIMM）。
   - SIMEVERY 2→4（groundCostAll の呼び出しが半分。期待値評価で損なし）。
   - 保険: 模擬計算の経過が SIMTL=0.9 秒を超えたら打ち切る（標本 100 未満ならその回の設計に戻す）。
   1 ケース（単独）約 0.33 → 0.19 秒。
3. 手元専用の計測: -DEXPECT（各注文の時点で全商品を serve した手数の平均の和 = 期待得点。揺れが実得点の 1/10 以下）、-DTIMING。

## 測定
- `ahc compare BEST solutions/free3 --set select`: 15167.9 → 15110.5, gain=+0.38% ±0.16% z=+2.35 30勝20敗, time max 1401→318ms
- `ahc compare BEST solutions/free3 --set dev --fresh`: 15208.7 → 15130.3, gain=+0.5172% ±0.0898% z=+5.75 100勝50敗, 誤り 0, time mean/max 450/858 → 294/618ms
