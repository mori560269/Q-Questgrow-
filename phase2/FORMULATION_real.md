# Phase 2（実データ）の定式化

配布データ（`data/phase2_real/`: 道路区間 1,682・道路ノード 1,597・サンプル災害）で使っている式をまとめる。
コードとの対応は各節の見出しに書いた。

## 0. 記号

| 記号 | 意味 | サンプルの値 |
|---|---|---|
| $J$ | 回復できる通信断センサー（前処理で対応不能を除いたもの） | 14 基（通信断 18 − 対応不能 4） |
| $K$ | ドック搭載車. 車 $k$ は拠点 $b(k)$ から時刻 0 に出発 | 8 台（県庁 4・西南 2・北東 2） |
| $V$ | 離陸地点の候補 = 一般道（trunk / primary / secondary）の, 通行できる区間の端点 | — |
| $\tau(u,v)$ | 通行止めを除いた道路網での最短走行時間（区間ごとに 長さ / 道路種別の速さ） | motorway 60, link 30, trunk 40, primary 30, secondary 20 km/h |
| $s$ | 停車するたびの離陸準備 | 10 分 |
| $c$ | ドックでの 1 回の充電 | 30 分 |
| $h$ | センサー上空の滞空 | 3 分 / 基 |
| $F_{\max}$ | 最大飛行時間 | 15 分 |
| $v_d$ | ドローンの速さ | 40 km/h |
| $n_0,\ n_+$ | 1 台の飛行回数の上限（予備なし / あり） | $1+4=5$, $5+4=9$ |
| $B$ | 予備バッテリーの総数（1 台に 0〜1 個） | 1 |

## 1. 前処理（`real.RealInstance`）

**飛行.** 離陸地点 $v$ から, センサーの列 $(j_1,\dots,j_m)$（$m\le 3$）を回って $v$ に戻る飛行 $f$ の所要時間は

$$
d_f=\frac{\lVert v-j_1\rVert+\sum_{i=1}^{m-1}\lVert j_i-j_{i+1}\rVert+\lVert j_m-v\rVert}{v_d}+h\,m\ \le F_{\max}.
$$

通信半径は 0 m なので, センサーの真上まで飛ぶ. センサー $j_i$ の回復時刻は飛行開始から $o_{f,j_i}=\big(\text{そこまでの飛行距離}\big)/v_d+h\,i$.
1 基だけなら届く半径は $(F_{\max}-h)\,v_d/2=4.0$ km（往復距離の上限 20 km は飛行時間の制約より緩いので効かない）.

**対応不能.** 4 km 以内に, 拠点から通行できる道でたどり着ける離陸地点がないセンサー.
サンプルでは P07_1・P07_5・P07_7・P07_9 の 4 基で, 課題資料の「4 基は対応不能」と一致する（4 基とも, 地形的には 4 km 以内に一般道があるが, 通行止めでそこへ行けない）.
センサーどうしは最も近くて 2,978 m 離れているので, サンプルでは 2 基以上を回る飛行は 15 分に収まらず, 飛行はすべて 1 基ずつになる.

**候補の絞り込み.** センサーの組ごとに, 各拠点から「走行 + 飛行」が最短の離陸地点と, 飛行時間が最短の離陸地点だけを残す（サンプル: 離陸地点 136 → 27, 飛行 28）.

## 2. 目的（辞書式）

1. 回復できたセンサー数を最大化
2. 最後のセンサーの回復時刻（メイクスパン）$C_{\max}=\max_{j} t_j$ を最小化

## 3. 計画の厳密な評価（`model.Instance.truck_schedule`）

車 $k$ に飛行の集合 $S_k$ を割り当てると, 停車地点の順番 $(v_1,\dots,v_r)$ を全順列（7 か所以下）で調べ, 次の漸化式で時刻を計算する.
車の時刻 $T$, ドローンが次に飛べる時刻 $R$（初め $T=R=0$）, 現在地 $p=b(k)$ として, 停車地点 $v_i$ ごとに

$$
T \leftarrow T+\tau(p,v_i)+s,\qquad p\leftarrow v_i,
$$

その地点で行う飛行 $f$ ごとに（短い順）

$$
\text{start}_f=\max(T,R),\quad t_j=\text{start}_f+o_{f,j}\ (j\in f),\quad T\leftarrow \text{start}_f+d_f,\quad R\leftarrow T+c .
$$

充電は走行中も進む（$R$ は走行で止まらない）. $|S_k|>n_0$ ならその車は予備バッテリーを積む. 全手法の解をこの式で評価する.

## 4. 下界: 枠の割当 + 最大流（`real.slot_lower_bound`）

車 $k$ の $q$ 番目の飛行として飛行 $f$ を始められる最も早い時刻の下界 $L_{k,q}(f)$ を, 前の枠から積み上げる.

$$
L_{k,1}(f)=\tau(b(k),v_f)+s,\qquad
L_{k,q}(f)=\max\Big(L_{k,1}(f),\ \min_{g\ne f}\big[L_{k,q-1}(g)+d_g+\max(\tau'(v_g,v_f),\,c)\big]\Big),
$$

$\tau'(u,v)=\tau(u,v)+s$（$u\ne v$）, $\tau'(v,v)=0$. センサー $j$ を車 $k$ の $q$ 番目で回復する最早時刻の下界は $e_{k,q,j}=\min_{f\ni j}\big[L_{k,q}(f)+o_{f,j}\big]$.

上限 $T$ に対し, 二部グラフ「センサー $j$ ― 枠 $(k,q)$」（$e_{k,q,j}\le T$ のとき辺）で, 全センサーを異なる枠に割り当てられるかを最大流で判定する.
予備バッテリーで増える枠 $q=6,\dots,9$ は全車合わせて $4B$ 個までなので, それらはいったんハブに集めて容量 $4B$ で終点につなぐ.
判定が通る最小の $T$ が下界. サンプルで **126.3 分**（単純な下界「各センサーに最も早く行ける時刻の最大」は 87.2 分）. 最適値 130.1 分との差は 3%.

## 5. 厳密解法: 上限で枝刈りした列の列挙 + 集合分割 MILP（`exact.solve_exact`）

**列.** 車の状態（拠点）ごとに, 飛行の組 $S$ と, その完了時刻 $m_S$（3 節の評価）を「列」とする.
同じ拠点の車は同じ列を持つので, 列挙は拠点ごとに 1 回.

**枝刈り.** 飛行を足しても完了時刻は減らない:

$$
S\subseteq S'\ \Rightarrow\ m_S\le m_{S'} .
$$

（$S'$ の最適な順番から $S'\setminus S$ の飛行を抜いた順番は $S$ の実行可能な順番で, 走行時間は最短経路なので三角不等式 $\tau'(u,w)\le\tau'(u,v)+\tau'(v,w)$ を満たし, 充電待ちも増えない.）
そこで反復局所探索の解の完了時刻を上限 $UB$ とし, $m_S\le UB$ の組だけを深さ優先で列挙する. 超えた組から先は調べない.

**判定 MILP.** 上限 $T$ のもとで, $m_S\le T$ の列 $x_S\in\{0,1\}$ だけを使って

$$
\sum_{S\ni j}x_S=1\ (\forall j\in J),\qquad
\sum_{S\in\mathcal S_b}x_S\le |K_b|\ (\forall\text{拠点 }b),\qquad
\sum_{S:\,|S|>n_0}x_S\le B .
$$

**二分探索.** 列の完了時刻の値を並べて $T$ を二分探索し, 判定が通る最小の $T$ が最適なメイクスパン（列挙が $UB$ で打ち切られていなければ厳密）.
サンプルは列 343 個, **0.2 秒で最適値 130.08 分を証明**.

全センサーを回復できない（車と充電回数が足りない）ときは, 被覆を $\le 1$ にして $\max\sum_j\sum_{S\ni j}x_S$ を先に解く.

## 6. QUBO-1: 時間枠の判定 QUBO（`qubo_bisect.build_decision_qubo`）

変数 $y_{f,k,q}=1$: 飛行 $f$ を車 $k$ の $q$ 番目に行う. $L_{k,q}(f)+\max_j o_{f,j}>T$ の組は最初から変数にしない.

$$
\begin{aligned}
E(y)=\;&2\sum_{j}\Big(\sum_{f\ni j,k,q}y_{f,k,q}-1\Big)^2
+3\sum_{k,q}\sum_{f<g}y_{f,k,q}\,y_{g,k,q}
+\sum_{k,q\ge2}\big(u_{k,q}-u_{k,q-1}u_{k,q}\big)\\
&+2\sum_{k,q}\ \sum_{(f,g)\in\mathcal B_{k,q}(T)}y_{f,k,q-1}\,y_{g,k,q}
+\varepsilon\sum (\text{回復時刻の見積もり})\,y ,
\end{aligned}
$$

$u_{k,q}=\sum_f y_{f,k,q}$, $\mathcal B_{k,q}(T)$ は「$f$ の次に $g$ を行うと $T$ に間に合わない組」.
上限 $T$ は $[\,\text{4 節の下界},\ \text{解の完了時刻}\,]$ で二分探索する.

## 7. QUBO-2: 列の集合分割 QUBO（`exact.build_column_qubo`）

5 節と同じ列・同じ制約を QUBO で書く（MILP との違いは解き方だけ）. $m_S\le T$ の列 $x_S$ と, 不等式のためのスラック $z$:

$$
\begin{aligned}
E(x,z)=\;&\sum_{j\in J}\Big(\sum_{S\ni j}x_S-1\Big)^2
+\sum_{b}\Big(\sum_{S\in\mathcal S_b}x_S+\sum_i w_i z_{b,i}-|K_b|\Big)^2\\
&+\Big(\sum_{S:\,|S|>n_0}x_S+\sum_i w_i z_{i}-B\Big)^2
+\varepsilon\,\frac{\sum_S m_S x_S}{\sum_S m_S},
\end{aligned}
$$

$w=(1,2,4,\dots)$ は $0..$右辺を表す 2 進の重み（最後の桁で上限をちょうどにそろえる）. $\varepsilon=0.3<1$ なので, 制約を 1 つでも破る解は必ず損をする.
$E=\varepsilon$ の項だけ $\Leftrightarrow$ $T$ 以内に全センサーを回復する計画. $T$ は 5 節と同じく列の完了時刻の値で二分探索する.

変形（`per_truck=True`）: 変数を $x_{S,k}$（車ごと）にし, 「1 台が選ぶ列は 1 つまで」を $\sum_{S<S'}x_{S,k}x_{S',k}$ の 2 次の罰金で書く（スラックなし）. 変数が拠点の車の数倍に増え, 焼きなましでは悪化した.

## 8. LNS（大近傍探索, `lns.lns`）

1. 最も遅く終わる車（確率 0.7）か無作為な 1 台を選び, 残りを「次に近い車」か「無作為な車」で足して 4 台にする.
2. その 4 台に割り当てたセンサーだけの部分問題を作る（他の車は固定, 予備バッテリーは残りの数）.
3. 部分問題を, 上限 = 今の 4 台の完了時刻の最大 として 5 節の MILP（古典）か 7 節の QUBO で解き直す.
4. 車ごとの完了時刻を遅い順に並べたものが辞書式で良くなれば採用.

部分問題は列が数十〜数百個なので, QUBO でも焼きなましが扱える大きさになる.

## 9. Amplify での書き方（7 節の QUBO）

```python
from amplify import VariableGenerator, Model, FixstarsClient, solve, one_hot, less_equal
gen = VariableGenerator()
x = gen.array("Binary", n_columns)                      # m_S <= T の列だけ
cover = sum(((sum(x[c] for c in cols_with[j]) - 1) ** 2) for j in J)
fleet = sum(less_equal(sum(x[c] for c in cols_of_base[b]), n_trucks[b]) for b in bases)
spare = less_equal(sum(x[c] for c in cols_need_spare), n_spare)
obj = eps * sum(m[c] * x[c] for c in range(n_columns)) / sum(m)
model = Model(obj + cover, fleet + spare)                # Amplify が不等式をスラックつきの罰金に変換
client = FixstarsClient(); client.parameters.timeout = 1000
result = solve(model, client)
```

この環境からは amplify.fixstars.com に接続できないため, 結果は CPU の焼きなまし（neal）で得た.
