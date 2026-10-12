# Q-Questgrow-

災害救助ドローンの観測計画を **QUBO（Fixstars Amplify / 焼きなまし）** と **MILP（厳密解法）** で解いて比べるコード集です。

## まず見るところ: 毎秒最適化 + トラブル対応（`realtime_drone.py`）

任意の地域データ（JSON）で、20 機のドローンの動きを **1 秒ごとに QUBO で最適化し直し**、
飛行中に **トラブルを見つけたらその場で QUBO を組み直す** シミュレーションです。

[Colab で開く](https://colab.research.google.com/github/mori560269/Q-Questgrow-/blob/claude/request-5v4fsc/realtime_drone.ipynb)
（上から順に実行すると、動画とトラブル・最適化の記録が表示されます）

```bash
python realtime_drone.py --data data/data_transformed.json --scenario data/scenario_example.json \
                         --out realtime_run.json --video realtime_run.mp4
python realtime_drone.py --data 任意の地域.json                 # シナリオを省略すると既定値
AMPLIFY_TOKEN=xxxx python realtime_drone.py ... --backend amplify --realtime   # AE で実時間 1 秒ごと
```

### 現実に寄せた設定（すべてシナリオ JSON で変更可）

| 項目 | 以前（`*_geo.py`） | 今回の既定値 |
|---|---|---|
| 見える範囲 | 18 / 10 / 4.5 km | **500 / 300 / 150 m**（ALPHA / BETA / GAMMA、高度 100〜150 m の搭載センサー想定） |
| 機体数 | 5 機 | **20 機**（ALPHA 4・BETA 8・GAMMA 8） |
| 速度 | 1 ステップで 2 マス（最大 20 km） | **12〜15 m/s** |
| バッテリー | 残量 8 に対し 1 ステップで +4 回復 | **15 分飛行・満充電 45 分**（充電は飛行の 3 倍遅い） |
| 地図 | 10 km マス | **100 m マス**（新緑県で約 64 万マス） |
| 時間 | 10 ステップ | **1 秒刻み・60 分**（`duration_sec`） |

充電が遅いので、例では 20 機を 3 組に分け、15 分ずつずらして出発させています（`launch_waves`）。

### 毎秒の処理

1. **トラブルの検知**
   - `hazard`（火災・土砂崩れなど）と `survivor`（要救助者）は、**ドローンの見える範囲に入るまで隠れています**。
   - 見つかった危険区域は、以後飛行禁止になります。見つかった要救助者には、最寄りの 1 機が向かって `observe_sec` 秒見守ります。
   - `drone_failure`（故障）と `battery_fault`（バッテリー異常）は、指定した時刻に起きます。電池切れの不時着もトラブルとして扱います。
2. **QUBO を組んで解く**: 毎秒（`replan_sec`）実行し、トラブルが起きたときはその場で、新しい制約と報酬で組み直します。
3. **全機を 1 秒ぶん動かす**: 観測、alpha/beta の加算、バッテリーの消費と充電、帰還の判断を行います。

### QUBO（飛行中の機体だけが対象。1 回あたり変数 約 700、2 次項 約 2 万）

- 変数 `x[d,h,k]`: 機体 `d` が先読みステップ `h` で候補地点 `k` に向かうかどうか。
  候補地点は、現在地を中心に「速度 × 30 秒」間隔で並べた格子（3×3、5×5）です。
- 地域外・飛行禁止区域・バッテリー不足で戻れなくなる地点は、**最初から候補に入れません**（どの解を選んでも安全）。
- 報酬: 新たに見えるマス、alpha/beta の残り要求、要救助者の見守り
- ペナルティ: 2 機が同じマスを重ねて見ること、同じ市町村の alpha/beta の取り合い、同じ要救助者への重複、one-hot、移動
- 解き方: neal（または Amplify AE）の解を出発点に、one-hot を保ったまま局所探索で磨きます。
  また、毎秒の解き直しでジグザグしないよう、「今の方向を続ける」候補にボーナスを付けています。

### 入力 JSON

`data_transformed.json` と同じ形式なら、どの地域でも動きます。必要な項目は次のとおりです。

- `municipalities[]`: `name`、`polygon_vertices`（m）、`required_coverage_rate`、`required_alpha_response`、`required_beta_resolution`
- `sensor_specifications[]`: `sensor_type_id`、`alpha_field_response`、`beta_density_resolution`
- `prefecture_outer_boundary.vertices`（省略可。動画の外枠に使います）

シナリオは `--scenario` で渡します（入力 JSON の `"scenario"` キーに書いても構いません）。書き方は `data/scenario_example.json` を参照してください。

### 結果（新緑県・`data/scenario_example.json`・60 分）

動画: `videos/realtime_run.mp4` / 記録: `results/realtime_run.json`

| 時刻 | トラブル（すべてその秒のうちに QUBO を組み直し） |
|---|---|
| 05:11 | 機体7 が 火災 を発見 |
| 10:58 | 機体10 が 土砂崩れ を発見 |
| 20:00 | 機体5 のバッテリー異常 (残量 35%) |
| 21:26 | 機体11 が 要救助者A を発見 |
| 22:56 | 要救助者A の見守り完了 |
| 35:00 | 機体12 が故障して離脱 |

- 最適化: 60 分で **3451 回**（うちトラブル起因 6 回）。
  1 回あたり 組み立て 44 ms ＋ 求解 10 ms（最大 197 ms）で、毎秒の更新に十分間に合います。
  60 分ぶんの計算にかかった実時間は 225 秒です。
- 総合スコア 0.674（要求達成 16/24）。
  alpha/beta の要求はほぼ満たせますが、被覆率は市町村ごとに 1.0〜2.3% にとどまります。
  見える範囲を半径 150〜500 m にしたため、1 時間で県全体（約 6,400 km²）を見て回るのは不可能、というのが現実的な結論です。
- 充電が遅いため、同時に飛べるのは平均 5〜10 機です。50 分前後には全機が充電中になる時間帯もあります。
  機体数（`fleet`）や充電時間（`full_charge_sec`）、組数（`launch_waves`）を変えると、この差がどう変わるかを試せます。


## ファイル構成

| ファイル | 問題 | 解き方 |
|---|---|---|
| `realtime_drone.py` | 任意の地域（毎秒・トラブル対応） | 毎秒 QUBO（neal / Amplify AE）＋局所探索 |
| `realtime_world.py` / `realtime_video.py` | 同上 | 地図・シナリオ・評価 / 動画 |
| `realtime_drone.ipynb` | 同上 | Colab 用ノートブック |
| `qubo_sa.py` | グリッド版（危険領域あり） | QUBO を一括で解く（neal） |
| `milp_classical.py` | グリッド版 | MILP（`scipy.optimize.milp` / HiGHS） |
| `rolling_grid.py` | グリッド版 | **ローリングホライズン** QUBO（neal / Amplify AE） |
| `qubo_geo.py` | 新緑県版（充電つき） | QUBO を一括で解く（neal） |
| `milp_geo.py` | 新緑県版 | MILP（HiGHS） |
| `rolling_geo.py` | 新緑県版 | **ローリングホライズン** QUBO（自前で QUBO 行列を組む） |
| `rolling_geo_amplify.py` | 新緑県版 | **ローリングホライズン**、Amplify の書き方で定式化（Amplify AE / neal） |
| `rolling_geo_amplify.ipynb` | 新緑県版 | 上の Colab 用ノートブック |
| `solver_backend.py` | 共通 | QUBO 行列を neal / Amplify AE で解く窓口 |
| `common.py` / `geo_common.py` | 共通 | シナリオ・評価関数・動画 |
| `data/` | | 新緑県のデータ（`data_transformed.json` ほか） |
| `results/*.json` / `videos/*.mp4` | | 実行結果と動画 |

## 実行方法

```bash
pip install numpy scipy matplotlib dimod dwave-neal amplify

# 一括で解く版
python qubo_sa.py ; python milp_classical.py ; python qubo_geo.py ; python milp_geo.py

# ローリングホライズン版 (neal, トークン不要)
python rolling_grid.py --unit 1 --horizon 2 --video rolling_grid.mp4
python rolling_geo.py  --unit 2 --horizon 3 --video rolling_geo.mp4

# Fixstars Amplify AE で解く (トークンは https://amplify.fixstars.com で発行)
AMPLIFY_TOKEN=xxxx python rolling_geo_amplify.py --unit 2 --horizon 3 --time-limit-ms 1000
# 同じ Amplify のモデルをローカルの焼きなましで解く (定式化の確認用)
python rolling_geo_amplify.py --backend neal
```

Colab で動かす場合は、次のリンクから開いて上から順に実行してください（コードとデータは `git clone` で自動取得します）。
動画・窓ごとの記録・他の手法との比較表もノートブック内で表示されます。

[Colab で開く](https://colab.research.google.com/github/mori560269/Q-Questgrow-/blob/claude/request-5v4fsc/rolling_geo_amplify.ipynb)
データの場所は `GEO_DATA_PATH` で変えられます（既定では `data/` → カレントディレクトリの順に探します）。

## ローリングホライズン（単位時間ごとの再最適化）

全ステップを1つの QUBO にすると、観測の重複を表す2次項が (機体数 × ステップ数)² に比例して増え、
求解に時間がかかります（新緑県版で2次項 約119万、140秒）。そこで次の手順を繰り返します。

1. 状態（各機の位置・バッテリー残量・観測済みセル・市町村ごとの alpha/beta 累計）を持つ
2. 先読み `--horizon` ステップぶんだけの小さな QUBO を作って解く
3. そのうち先頭の `--unit` ステップ（単位時間）だけを確定して実行する
4. 状態を更新して 2 に戻る

窓ごとの QUBO では、次の点を一括版から変えています。

- 観測済みのセルや、被覆率の要求をすでに満たした市町村には報酬を付けない
- alpha/beta は「残りの要求量」だけを目標にする
- バッテリーの初期値は満タンではなく、その時点の残量にする
- ペナルティ係数は、被覆の報酬だけでなく alpha/beta の報酬も含めた最大値に合わせて決める

各窓では、ソルバーが返した解をすべて厳密な評価関数で採点し、いちばん良い実行可能解を採用します。
制約違反の解は修復してから候補に加えます。

### Amplify 版（`rolling_geo_amplify.py`）の定式化

Q-Quest GROW ハンズオンのノートブックと同じ書き方です。

- 変数: `x = gen.array("Binary", shape=(D, H, C))`（機体 × ステップ × セル）
- コスト関数: 被覆の報酬と重複ペナルティ、alpha/beta 不足 `W (A - R - s)²`（`s` は整数スラック）
- 罰金項: 到達できないセルへの移動
- 制約: `one_hot(x, axis=2)`、バッテリーの `greater_equal(...)`
- 求解: `AmplifyAEClient`、`time_limit_ms = 1000`、`solve(model, client, filter_solution=False)`

バッテリーを状態変数で表さず、窓内の累積残量に対する不等式制約で表すため、
`rolling_geo.py` にあった「モードと位置の整合」の変数と項がいりません。
ただし、満タン（`BATT_MAX`）で頭打ちになる効果は式に入れていません。
そのため、最終的な実行可能性は厳密なシミュレーションで判定しています。

## 結果: 新緑県版（実データ, 66セル・5機・10ステップ）

| 手法 | score | 要求達成 | 時間 | 備考 |
|---|---|---|---|---|
| MILP（`milp_geo.py`） | **0.906** | 18 / 24 | 150 s | 時間切れ、gap 0.43% |
| QUBO 一括（`qubo_geo.py`） | 0.835 | 14 / 24 | 141 s | 2次項 約119万、修復なしで制約OKの解は 0/30 |
| ローリング QUBO（単位1, 先読み2） | 0.841 | 15 / 24 | 11 s | |
| ローリング QUBO（単位1, 先読み3） | 0.881 | 13 / 24 | 20 s | |
| **ローリング QUBO（単位2, 先読み3）** | **0.884** | 16 / 24 | **11 s** | 1窓の2次項 約16万 |
| Amplify 版を neal で（単位2, 先読み3） | 0.869 | 16 / 24 | 17 s | Amplify AE では未実行（下記） |

ローリング版（単位2・先読み3）は、一括 QUBO より約13倍速く、score も 0.835 から 0.884 に上がりました。
MILP の最適値（0.906）との差は約2.5%です。

Amplify AE では、1窓あたり約1秒（`time_limit_ms`）＋通信時間で、5窓ぶん解く想定です。
この開発環境からは Fixstars のサーバーに接続できないため、AE での実行結果はまだありません。

## 結果: グリッド版（10×10, 3機, 6ステップ）

| 手法 | J | 観測率 | 時間 |
|---|---|---|---|
| MILP（最適） | **0.868** | **96.8%** | 14 s |
| QUBO 一括（`qubo_sa.py`） | 0.708 | 80.8% | 143 s |
| ローリング QUBO（単位1, 先読み2） | 0.795 | 89.5% | 8〜11 s |

## 2つの解き方の違い

- **QUBO 版**
  - 「観測できた範囲の和集合」は2次式では正確に書けません。そのため包除原理を2次で打ち切った近似（重複ペナルティ `λ_ov`）を使っています。
  - 制約はペナルティ項になるので、係数の調整が必要です。
- **MILP 版**
  - 和集合は `y[s]`、`min(1,·)` のキャップは `u[m] ≤ 1` で表すので、近似なしに書けます。
  - 制約も不等式のまま扱えます。

どちらの解も、最終的には共通の評価関数（厳密な和集合・キャップつき）で採点します。

なお、衝突回避（同じ時刻に同じセルに複数機を置かない）は、新緑県版には QUBO・MILP とも入っていません（グリッド版には入っています）。
