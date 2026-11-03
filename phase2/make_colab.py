"""
phase2/make_colab.py : Phase 2（配布データ）を Google Colab で動かすノートブックを作る
  python make_colab.py  → notebooks/phase2_real_colab.ipynb
"""
import os
import nbformat as nbf

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "notebooks", "phase2_real_colab.ipynb")

cells = []
md = lambda s: cells.append(nbf.v4.new_markdown_cell(s.strip()))
code = lambda s: cells.append(nbf.v4.new_code_cell(s.strip()))

md("""
# Phase 2（配布データ）: 災害時ドローン臨時通信確保問題を Colab で解く

配布された道路網（道路区間 1,682・ノード 1,597）とサンプル災害で, 通信断センサーをドック搭載車とドローンで回復する計画を求めます。

| 節 | 内容 | 時間の目安 |
|---|---|---|
| 0 | 準備（リポジトリの取得・ライブラリ） | 1〜2 分 |
| 1 | データを見る | 数秒 |
| 2 | 前処理: 対応不能・飛行の候補・下界 | 数秒 |
| 3 | 古典: 貪欲法 / 反復局所探索 / **厳密解法（最適を証明）** | 約 20 秒 |
| 4 | 最適計画の地図と車ごとの行動 | 数秒 |
| 5 | QUBO（CPU の焼きなまし）: 列の集合分割 QUBO・時間枠の判定 QUBO | 約 1 分 |
| 6 | QUBO を **Amplify AE** で解く（任意・トークンが必要） | 約 1 分 |
| 7 | 条件を変えて解き直す（車の台数・速さ・充電・予備バッテリー） | 約 20 秒 |
| 8 | 災害を作って解く（同等〜より複雑な 5 系統） | 約 1 分 |
| 9 | 保存済みの大規模実験（51 問）の結果 | 数秒 |

式は `phase2/FORMULATION_real.md`, 結果のまとめは `phase2/README_real.md`。
""")

md("## 0. 準備")
code(r'''
import os, sys, subprocess, importlib.util

REPO = "https://github.com/mori560269/Q-Questgrow-.git"
BRANCH = "claude/request-5v4fsc"

# リポジトリを取得（このノートブックをリポジトリの中で開いた場合は不要）
if os.path.exists("../phase2/real.py"):
    os.chdir("..")
if not os.path.exists("phase2/real.py"):
    if not os.path.exists("Q-Questgrow-"):
        r = subprocess.run(["git", "clone", "-q", "--depth", "1", "-b", BRANCH, REPO], capture_output=True, text=True)
        if r.returncode != 0:
            # 非公開リポジトリの場合は, GitHub の個人アクセストークン（読み取り権限）を入力する
            from getpass import getpass
            tok = getpass("GitHub のトークン（非公開リポジトリの場合）: ").strip()
            subprocess.run(["git", "clone", "-q", "--depth", "1", "-b", BRANCH,
                            REPO.replace("https://", f"https://{tok}@")], check=True)
            subprocess.run(["git", "-C", "Q-Questgrow-", "remote", "set-url", "origin", REPO], check=True)  # トークンを残さない
    os.chdir("Q-Questgrow-")
print("作業フォルダ:", os.getcwd())

# ライブラリ（足りないものだけ入れる）
need = [p for m, p in [("neal", "dwave-neal"), ("dimod", "dimod"), ("amplify", "amplify"), ("pandas", "pandas")]
        if importlib.util.find_spec(m) is None]
if need:
    subprocess.run([sys.executable, "-m", "pip", "install", "-q"] + need, check=True)

# 日本語フォント（図のラベル用）
import matplotlib, matplotlib.font_manager as fm
if not any("Noto Sans CJK JP" in f.name or "IPAGothic" in f.name for f in fm.fontManager.ttflist):
    subprocess.run("apt-get -qq install -y fonts-noto-cjk > /dev/null 2>&1", shell=True)
    fm.fontManager = fm._load_fontmanager(try_read_cache=False)
print("準備完了")
''')

code(r'''
import sys, os, json, time
sys.path.insert(0, os.path.abspath("phase2"))
sys.path.insert(0, os.path.abspath("placement"))
import numpy as np, pandas as pd
import matplotlib.pyplot as plt
from IPython.display import Image, display

import model
from real import RealWorld, RealInstance, load_sample, slot_lower_bound, make_real_scenario, FAMILIES
from exact import solve_exact, solve_column_qubo
from equal_time import ils, qubo_bisect_timed
from lns import lns
from real_run import schedule_detail, draw
import solvers as S

av = {f.name for f in matplotlib.font_manager.fontManager.ttflist}
plt.rcParams["font.family"] = [f for f in ["Noto Sans CJK JP", "IPAexGothic", "IPAGothic"] if f in av] + ["DejaVu Sans"]
os.makedirs("colab_out", exist_ok=True)
''')

md("""
## 1. データを見る

- 道路: motorway（高速）/ motorway_link / trunk（国道）/ primary / secondary
- 拠点: 県庁 4 台・西南市役所 2 台・北東町役場 2 台
- センサーの位置は Phase 1 の候補地 86 か所（`data/candidate_locations.geojson`）
""")
code(r'''
rw = RealWorld()
sc = load_sample()
print("道路区間", len(rw.seg), "/ 道路ノード", len(rw.nodes), "/ センサー候補地", len(rw.sensor_ids))
print("通信断", len(sc["disconnected_sensors"]), "基 / 通行止め", len(sc["closed_segments"]), "区間")
print("拠点:", [(b["name"], b["num_vehicles"]) for b in sc["drone_bases"]])
print("車の速さ [km/h]:", sc["vehicle"]["speed_kmh"], "/ 離陸準備", sc["vehicle"]["launch_setup_time_min"], "分")
print("ドローン:", sc["drone"], "\nドック:", sc["dock"], "\n予備バッテリー:", sc["fleet"]["total_spare_batteries"], "個")

fig, ax = plt.subplots(figsize=(7, 7))
closed = set(sc["closed_segments"])
for sid, s in zip(rw.seg_ids, rw.seg):
    g = np.array(s["geom"]) / 1000
    ax.plot(g[:, 0], g[:, 1], color="#d62728" if sid in closed else ("#555" if s["hw"].startswith("motorway") else "#aaa"),
            lw=2.5 if sid in closed else (1.6 if s["hw"].startswith("motorway") else 0.6))
fail = set(sc["disconnected_sensors"])
for sid, (x, y) in zip(rw.sensor_ids, rw.sensor_xy / 1000):
    ax.plot(x, y, "o", color="#14213D" if sid in fail else "#ccc", ms=6 if sid in fail else 3)
for nid, nm in rw.base_nodes.items():
    p = rw.nodes[rw.nid[nid]] / 1000
    ax.plot(*p, "s", color="#6f42c1", ms=10); ax.annotate(nm[:5], p, xytext=(5, 5), textcoords="offset points")
ax.set_aspect("equal"); ax.set_title("道路網（赤 = 通行止め）と通信断センサー（濃い点）")
plt.show()
''')

md("""
## 2. 前処理

通行止めを除いた道路網で最短走行時間を求め, 一般道の離陸地点から 15 分以内（滞空 3 分/基込み）で回れる飛行を列挙します。
1 基を往復するなら半径 4.0 km。**下界** はセンサーを「車 × 何番目の飛行」の枠に割り当てる最大流で求めます（`FORMULATION_real.md` 4 節）。
""")
code(r'''
I = RealInstance(rw, sc)
print("回復可能", len(I.recoverable), "基 / 対応不能", len(I.unreachable), "基")
for k, v in I.unreach_reason.items():
    print("  ", k, ":", v)
print("飛行の候補", len(I.flights), "/ 2 基以上を回る飛行", sum(len(f["sensors"]) > 1 for f in I.flights))
print("下界: 単純", round(model.Instance.lower_bound(I), 1), "分 / 枠割当の最大流", round(slot_lower_bound(I), 1), "分")
''')

md("""
## 3. 古典の手法

- 貪欲法 + 局所探索（一瞬）
- 反復局所探索（ILS, 10 秒）
- **厳密解法**: 上限を超える「車ごとの飛行の組」を枝刈りしながら列挙し, 集合分割 MILP を二分探索して最適を証明（`FORMULATION_real.md` 5 節）
""")
code(r'''
rows, plans = [], {}
t = time.time(); p = S.solve_greedy_ls(I, 1.0)[0]; plans["貪欲法 + 局所探索"] = (p, time.time() - t)
t = time.time(); p = ils(I, 10.0, 0); plans["反復局所探索（10 秒）"] = (p, time.time() - t)
t = time.time(); p, info = solve_exact(I, start=plans["反復局所探索（10 秒）"][0], time_limit=120)
plans["厳密解法"] = (p, time.time() - t)
for name, (p, sec) in plans.items():
    e = I.evaluate(p)
    rows.append(dict(手法=name, 回復数=e["recovered"], 完了時刻_分=round(e["makespan"], 2),
                     平均回復時刻_分=round(np.mean(list(e["rec_time"].values())), 2), 時間_秒=round(sec, 2)))
print("厳密解法:", info)
best_plan = plans["厳密解法"][0]
pd.DataFrame(rows)
''')

md("## 4. 最適計画の地図と車ごとの行動")
code(r'''
detail = schedule_detail(I, best_plan)
draw(rw, I, best_plan, detail, "colab_out/sample_map.png", "colab_out/sample_gantt.png")
display(Image("colab_out/sample_map.png", width=700))
display(Image("colab_out/sample_gantt.png", width=850))
pd.DataFrame([dict(センサー=rw.sensor_ids[k], 回復時刻_分=round(v, 1)) for k, v in sorted(I.evaluate(best_plan)["rec_time"].items(), key=lambda kv: kv[1])])
''')

md("""
## 5. QUBO（CPU の焼きなまし）

- **列の集合分割 QUBO**（`FORMULATION_real.md` 7 節）: 厳密解法と同じ列（車ごとの飛行の組）と同じ制約を QUBO にしたもの。
  `reduce=True` で離陸地点が違うだけの列をまとめ, 変数を減らします（最適値は変わらない）。
- **時間枠の判定 QUBO**（6 節）: 「車 k の q 番目の飛行」を変数にし, 上限 T を二分探索。
- **LNS-QUBO**: 4 台ずつ壊し, 部分問題を列の集合分割 QUBO で解き直す。

上限 T（完了時刻）を二分探索し, 各 T で「T 以内に全センサーを回復できるか」を QUBO で判定します。
""")
code(r'''
opt = I.evaluate(best_plan)["makespan"]
res = []
st = S.local_search(I, S.greedy(I), 1.0)          # 列の列挙の上限には貪欲法 + 局所探索の解を使う
for name, fn in [
    ("列の集合分割 QUBO（30 秒）", lambda: solve_column_qubo(I, 30, 0, start=st)[0]),
    ("列の集合分割 QUBO, 列をまとめる（30 秒）", lambda: solve_column_qubo(I, 30, 0, start=st, reduce=True)[0]),
    ("時間枠の判定 QUBO（30 秒）", lambda: qubo_bisect_timed(I, 30, 0)),
    ("LNS-QUBO（30 秒）", lambda: lns(I, 30, 0, "colqubo", k_trucks=4)),
]:
    t = time.time(); p = fn(); sec = time.time() - t
    if p is None:
        res.append(dict(手法=name, 完了時刻_分=None, 最適との差="解が出ない", 時間_秒=round(sec, 1))); continue
    e = I.evaluate(p)
    res.append(dict(手法=name, 回復数=e["recovered"], 完了時刻_分=round(e["makespan"], 2),
                    最適との差=f'+{(e["makespan"] - opt) / opt * 100:.1f}%', 時間_秒=round(sec, 1)))
pd.DataFrame(res)
''')

md("""
## 6. QUBO を Amplify AE で解く（任意）

Amplify AE のトークンが必要です（https://amplify.fixstars.com で取得）。トークンはノートブックに書かず, 実行時に入力してください。
`USE_AMPLIFY = True` にして実行します。各判定で AE を `AE_MS` ミリ秒使います。
""")
code(r'''
USE_AMPLIFY = False
AE_MS = 3000

if USE_AMPLIFY:
    from getpass import getpass
    token = os.environ.get("AMPLIFY_TOKEN") or getpass("Amplify AE のトークン: ").strip()
    t = time.time()
    p, qi = solve_column_qubo(I, 120, 0, start=st, reduce=True, backend="amplify", token=token, ae_ms=AE_MS)
    print("時間", round(time.time() - t, 1), "秒 / 二分探索の履歴:", qi["history"])
    if p is not None:
        e = I.evaluate(p)
        print("Amplify AE: 完了時刻", round(e["makespan"], 2), "分（最適", round(opt, 2), "分）")
    else:
        print("Amplify AE: 制約を満たす解が出ませんでした")
else:
    print("USE_AMPLIFY = True にすると実行します")
''')

md("""
## 7. 条件を変えて解き直す

下の値を変えて実行すると, 厳密解法でその条件の最適値を求めます。
""")
code(r'''
VEHICLES = {"新緑県庁（災害対策本部）": 4, "西南市役所": 2, "北東町役場": 2}   # 拠点ごとの車の台数
SPEED_FACTOR = 1.0       # 車の速さ（倍）
SETUP_MIN = 10           # 離陸準備 [分]
CHARGE_MIN = 30          # 充電 [分]
SPARES = 1               # 予備バッテリーの数

sc2 = json.loads(json.dumps(sc))
for b in sc2["drone_bases"]:
    b["num_vehicles"] = VEHICLES[b["name"]]
sc2["vehicle"]["speed_kmh"] = {k: v * SPEED_FACTOR for k, v in sc["vehicle"]["speed_kmh"].items()}
sc2["vehicle"]["launch_setup_time_min"] = SETUP_MIN
sc2["fleet"]["total_spare_batteries"] = SPARES
model.CHARGE_MIN = float(CHARGE_MIN)
try:
    I2 = RealInstance(rw, sc2)
    p2, info2 = solve_exact(I2, start=ils(I2, 5.0, 0), time_limit=120)
    e2 = I2.evaluate(p2)
    print(f'最適な完了時刻 {e2["makespan"]:.1f} 分（配布サンプルの条件では {opt:.1f} 分）, 最適を証明: {info2["optimal"]}')
    print("平均回復時刻", round(np.mean(list(e2["rec_time"].values())), 1), "分 / 下界", round(I2.lower_bound(), 1), "分")
finally:
    model.CHARGE_MIN = 30.0
''')

md("""
## 8. 災害を作って解く

配布の道路網の上で, サンプルの傾向（震源から 20 km 以内が通信断・橋やトンネルほど通行止め）に合わせて災害を作ります。

| 系統 | 内容 |
|---|---|
| A_同等 | サンプルと同じ規模 |
| B_大地震 | 半径 30 km, 通行止め約 80 |
| C_複合 | 震源 2 つ, 1 拠点の車が半分, 予備 0〜2 個 |
| D_広域 | 半径 42 km, 通行止め約 130 |
| E_連続大地震 | 震源 2 つ（半径 32 km）, 通行止め約 180, 車が減る |
""")
code(r'''
FAMILY = "B_大地震"      # A_同等 / B_大地震 / C_複合 / D_広域 / E_連続大地震
SEED = 3
BUDGET = 20              # 各手法の計算時間 [秒]

sc3 = make_real_scenario(rw, FAMILY, SEED)
I3 = RealInstance(rw, sc3)
print(sc3["description"])
print("通信断", len(I3.targets), "/ 回復可能", len(I3.recoverable), "/ 対応不能", len(I3.unreachable),
      "/ 通行止め", len(sc3["closed_segments"]), "/ 車", len(I3.trucks), "/ 予備", I3.spares_left, "/ 下界", round(I3.lower_bound(), 1))
out = []
for name, fn in [("反復局所探索", lambda: ils(I3, BUDGET, 0)),
                 ("厳密解法（時間内）", lambda: solve_exact(I3, start=ils(I3, 2, 0), time_limit=BUDGET)[0]),
                 ("LNS-MILP", lambda: lns(I3, BUDGET, 0, "colmilp", k_trucks=4)),
                 ("LNS-QUBO", lambda: lns(I3, BUDGET, 0, "colqubo", k_trucks=4))]:
    t = time.time(); p = fn(); e = I3.evaluate(p)
    out.append(dict(手法=name, 回復数=e["recovered"], 完了時刻_分=round(e["makespan"], 2), 時間_秒=round(time.time() - t, 1), plan=p))
best3 = min(out, key=lambda r: (-r["回復数"], r["完了時刻_分"]))
draw(rw, I3, best3["plan"], schedule_detail(I3, best3["plan"]), "colab_out/gen_map.png", "colab_out/gen_gantt.png")
display(Image("colab_out/gen_map.png", width=650))
pd.DataFrame([{k: v for k, v in r.items() if k != "plan"} for r in out])
''')

md("""
## 9. 保存済みの大規模実験（51 問）の結果

`real_batch.py`（同じ計算時間の比較）, `real_qubo_improve.py`（列をまとめた QUBO）, `real_alloc.py`（8 台の分け方）の結果です。
""")
code(r'''
S_ = json.load(open("results/real_batch_stats.json"))
print("基準（厳密解法 最大 300 秒）")
display(pd.DataFrame(S_["reference"]))
print("同じ計算時間 30 秒, 全 51 問")
df = pd.DataFrame([r for r in S_["equal_time"] if r["系統"] == "全体" and r["予算_秒"] == 30])
display(df[["手法", "試行", "最大回復数に届いた割合", "最良との差_平均", "最良との差_95CI", "古典ILSに勝ち", "負け", "引き分け", "符号検定p"]])
print("列の集合分割 QUBO: 列をまとめる前と後")
display(pd.DataFrame(json.load(open("results/real_qubo_improve_summary.json"))["summary"]).T)
print("8 台の分け方（完了時刻の平均が早い順, 上位 8）")
A = json.load(open("results/real_alloc_summary.json"))["summary"]
display(pd.DataFrame([dict(県庁=r["配分"]["県庁"], 西南市役所=r["配分"]["西南市役所"], 北東町役場=r["配分"]["北東町役場"],
                           完了時刻_平均=r["完了時刻_平均"], 完了時刻_最悪=r["完了時刻_最悪"]) for r in A[:8]]))
''')

nb = nbf.v4.new_notebook()
nb["cells"] = cells
nb["metadata"] = {"colab": {"provenance": [], "toc_visible": True},
                  "kernelspec": {"name": "python3", "display_name": "Python 3"},
                  "language_info": {"name": "python"}}
nbf.write(nb, OUT)
print("written", OUT)
