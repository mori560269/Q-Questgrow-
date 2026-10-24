"""
phase2/resilient_placement.py : 災害時の回復しやすさも考えたセンサー配置（Phase 1 と Phase 2 をつなぐ）

  1. 回復しにくさの見積もり（候補地ごと, 学習用の災害シナリオ 100 通りの平均）
       r_p = 平均 [ 通信断になる確率_p × 最も早く回復できる時刻_p ]
       最も早く回復できる時刻 = 通行止めを除いた道路で, どれかの車が 4 km 以内の離陸地点まで行き, 飛んで滞空を終える時刻
       （どの離陸地点にも行けなければ 300 分として数える）
  2. 配置の MILP（Phase 1 の制約はすべてそのまま, 200 m マス）
       総コスト ≤ (1 + δ) × 6,160 の中で, Σ r_p x_{p,k} を最小にする（δ = 0, 3%, 6%）
       δ = 0 は「コストは最適のまま, 最適解の中で最も回復しやすい配置」を選ぶことに当たる
  3. 評価（学習とは別の災害シナリオ 30 通り）
       各配置で Phase 2 を解き（古典の反復局所探索, 早く回復するほど良い, 2 秒）, 対応不能の数・平均回復時刻・完了時刻を比べる
       災害は配置によらず共通（震源・断層・通行止め・各地点が通信断になる乱数）

  python resilient_placement.py   → results/phase2_resilient_placement.json, results/phase2_resilient_map.png
"""
import copy
import json
import os
import sys
import time
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "placement"))
from common import Problem
from classical import solve_milp
from model import Instance, FLIGHT_MIN, HOVER_MIN, DRONE_M_PER_MIN
from world import make_scenario
import solvers as S
from equal_time import ils
from run import trucks_of

ROOT = os.path.join(HERE, "..")
FAIL_R = 25000.0         # 通信断の起きやすさ: 0.9 exp(−(震源からの距離 / 25 km)²)
UNREACH_MIN = 300.0


def disasters(w, n, seed0):
    """配置によらない災害: 震源, 断層沿いの通行止め, 各候補地の乱数（通信断の判定に使う）"""
    out = []
    pts = np.array(Problem(cell_m=1000.0).pts)
    pref = np.array(w["pref"])
    from matplotlib.path import Path
    path = Path(pref)
    for k in range(n):
        rng = np.random.default_rng(seed0 + k)
        while True:
            e = pref.min(0) + rng.random(2) * (pref.max(0) - pref.min(0))
            if path.contains_point(e):
                break
        sc = make_scenario(w, seed=seed0 + k, epicenter=e.tolist(), n_fail=1, n_closed=int(rng.integers(34, 81)),
                           fault_len=25000, fault_angle=None)
        d = np.hypot(*(pts - e).T)
        p_fail = 0.9 * np.exp(-(d / FAIL_R) ** 2)
        out.append(dict(epicenter=e.tolist(), closed=sc["closed_segments"], fails=rng.random(len(pts)) < p_fail,
                        p_fail=p_fail))
    return out


def world_with(w, prob, x):
    w2 = copy.copy(w)
    S_ = []
    for p in range(prob.P):
        ks = np.nonzero(x[p])[0]
        if len(ks):
            S_.append(dict(id=prob.pid[p], muni=prob.names[prob.preg[p]], x=float(prob.pts[p, 0]),
                           y=float(prob.pts[p, 1]), kind=prob.kname[ks[0]], p=p))
    w2["sensors"] = S_
    return w2


def recovery_risk(w, prob, scenarios):
    """候補地ごとの r_p = 平均 [ 通信断の確率 × 最も早く回復できる時刻 ]"""
    # 通行止めを除いた道路で拠点からの走行時間を求め, 候補地ごとに
    #   min over 4 km 以内の交差点 v [ 走行時間(v) + 直線距離(v, p) / ドローンの速さ + 滞空 3 分 ]
    R1 = (FLIGHT_MIN - HOVER_MIN) * DRONE_M_PER_MIN / 2
    nodes = np.array(w["nodes"])
    dist = np.hypot(nodes[:, None, 0] - prob.pts[None, :, 0], nodes[:, None, 1] - prob.pts[None, :, 1])
    near = dist <= R1
    r = np.zeros(prob.P)
    for sc in scenarios:
        I = Instance(w, sc["closed"], [], trucks_of(w), 2)       # 走行時間だけ使う（目標なし）
        drive = np.min(np.array([I.drive_from[s] for s in I.drive_from]), axis=0)
        t = np.where(near, drive[:, None] + dist / DRONE_M_PER_MIN + HOVER_MIN, np.inf).min(0)
        best = np.where(np.isfinite(t), t, UNREACH_MIN)
        r += sc["p_fail"] * best
    return r / len(scenarios)


def evaluate_placement(w, prob, x, scenarios, budget=2.0):
    w2 = world_with(w, prob, x)
    loc = [s["p"] for s in w2["sensors"]]
    out = []
    for k, sc in enumerate(scenarios):
        failed = [i for i, p in enumerate(loc) if sc["fails"][p]]
        if not failed:
            out.append(dict(通信断=0, 対応不能=0, 回復数=0, 平均回復時刻=None, 完了時刻=0.0)); continue
        I = Instance(w2, sc["closed"], failed, trucks_of(w), 2)
        plan = ils(I, budget, k, ev=S.Evaluator(I, "sum"))
        e = I.evaluate(plan)
        rt = list(e["rec_time"].values())
        out.append(dict(通信断=len(failed), 対応不能=len(I.unreachable), 回復数=e["recovered"],
                        平均回復時刻=None if not rt else round(float(np.mean(rt)), 1), 完了時刻=round(e["makespan"], 1)))
    return out


def main(n_train=100, n_test=30, deltas=(0.0, 0.03, 0.06)):
    w = json.load(open(os.path.join(ROOT, "data", "phase2_world.json")))
    prob = Problem(cell_m=200.0)
    t0 = time.time()
    train = disasters(w, n_train, 1000)
    r = recovery_risk(w, prob, train)
    print("回復しにくさの見積もり", round(time.time() - t0, 1), "秒. 最大", round(r.max(), 1), "最小", round(r.min(), 1), flush=True)
    obj = np.repeat(r, prob.K)                              # 種類によらず, その候補地に置くと r_p
    placements = {}
    x0 = np.array([q for q in json.load(open(os.path.join(ROOT, "results", "placement_fine_grid.json")))
                   if q["solve_grid_m"] == 200][0]["x"], float)
    placements["Phase 1 の最適配置（コスト最小のみ）"] = x0
    base_cost = float((x0 * prob.cost).sum())
    for dl in deltas:
        x, info = solve_milp(prob, time_limit=300, obj=obj + 1e-6 * np.tile(prob.cost, prob.P),
                             cost_cap=base_cost * (1 + dl))
        placements[f"回復しやすさ考慮（コスト +{dl:.0%} まで）"] = x
        print(dl, "status", info["status"], "cost", (x * prob.cost).sum(), round(info["sec"], 1), "秒", flush=True)
    test = disasters(w, n_test, 0)
    res = {}
    for name, x in placements.items():
        ev100 = Problem(cell_m=1000.0).evaluate(x, cell_m=100.0)
        runs = evaluate_placement(w, prob, x, test)
        mt = [q["平均回復時刻"] for q in runs if q["平均回復時刻"] is not None]
        res[name] = dict(
            総コスト=float((x * prob.cost).sum()), 台数=dict(zip(prob.kname, x.sum(0).astype(int).tolist())),
            Phase1の制約_100mマスで判定=bool(ev100["feasible"]),
            回復しにくさの合計=round(float((x.sum(1) * r).sum()), 1),
            通信断_平均=round(float(np.mean([q["通信断"] for q in runs])), 1),
            対応不能_合計=int(sum(q["対応不能"] for q in runs)),
            平均回復時刻_平均=round(float(np.mean(mt)), 1),
            完了時刻_平均=round(float(np.mean([q["完了時刻"] for q in runs])), 1),
            runs=runs, x=x.astype(int).tolist())
        print(name, {k: v for k, v in res[name].items() if k not in ("runs", "x")}, flush=True)
    json.dump(dict(r=r.round(2).tolist(), results=res), open(os.path.join(ROOT, "results", "phase2_resilient_placement.json"), "w"),
              ensure_ascii=False, indent=1)
    draw(w, prob, r, placements)


def draw(w, prob, r, placements):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager as fm
    from matplotlib.patches import Polygon as Poly
    av = {f.name for f in fm.fontManager.ttflist}
    plt.rcParams["font.family"] = [f for f in ["Noto Sans CJK JP", "IPAexGothic", "IPAGothic"] if f in av] + ["DejaVu Sans"]
    names = list(placements)
    show = [names[0], names[1], names[-1]]
    fig, axes = plt.subplots(1, 3, figsize=(16, 5.8))
    for ax, nm in zip(axes, show):
        x = placements[nm]
        for P in w["polys"]:
            ax.add_patch(Poly(np.array(P) / 1000, closed=True, fc="#f4f1e8", ec="#999", lw=0.6))
        sc = ax.scatter(prob.pts[:, 0] / 1000, prob.pts[:, 1] / 1000, c=r, cmap="Oranges", s=22, vmin=0, edgecolors="none")
        on = x.sum(1) > 0
        ax.scatter(prob.pts[on, 0] / 1000, prob.pts[on, 1] / 1000, facecolors="none", edgecolors="#14213D", s=70, lw=1.2)
        for d in w["depots"]:
            ax.plot(*(np.array(w["nodes"][d["node"]]) / 1000), "s", color="#6f42c1", ms=9)
        ax.set_aspect("equal"); ax.set_xticks([]); ax.set_yticks([])
        ax.set_title(f"{nm}\nコスト {(x * prob.cost).sum():.0f} / {int(on.sum())} 基", fontsize=11)
    fig.colorbar(sc, ax=axes, shrink=0.7, label="回復しにくさ r_p（通信断の確率 × 回復までの時間, 分）")
    fig.text(0.01, 0.02, "点の色 = その候補地の回復しにくさ（濃いほど回復しにくい）, 黒丸 = センサーを置いた候補地, 紫の四角 = 拠点", fontsize=10)
    fig.savefig(os.path.join(ROOT, "results", "phase2_resilient_map.png"), dpi=90, bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    main()
