# Q-Questgrow-

災害救助ドローンの観測計画を **QUBO（Fixstars Amplify / 焼きなまし）** と **MILP（厳密解法）** で解いて比べるコード集です。

## ファイル構成

| ファイル | 問題 | 解き方 |
|---|---|---|
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

Colab で動かす場合は `rolling_geo_amplify.ipynb` を開き、指示に従って5つのファイルをアップロードしてください。
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
