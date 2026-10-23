"""
phase2/run.py : Phase 2（災害時ドローン臨時通信確保）の比較実験

  python run.py            → results/phase2_compare.json, results/phase2_map.png, results/phase2_gantt.png
  python run.py --scale    → results/phase2_scale.json（シナリオを変えた比較）
  python run.py --dynamic  → results/phase2_dynamic.json（情報が少しずつ分かる場合の逐次再計画）
"""
import argparse
import json
import os
import sys
import time
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from model import Instance, Truck
from world import make_scenario
import solvers as S
from dynamic import run_dynamic, reveal_schedule
from qubo_bisect import solve_qubo_bisect

ROOT = os.path.join(HERE, "..")
RES = os.path.join(ROOT, "results")


def load():
    w = json.load(open(os.path.join(ROOT, "data", "phase2_world.json")))
    sc = json.load(open(os.path.join(ROOT, "data", "phase2_scenario_sample.json")))
    return w, sc


def trucks_of(w):
    out, k = [], 0
    for d in w["depots"]:
        for _ in range(d["trucks"]):
            out.append(Truck(k, d["name"], d["node"])); k += 1
    return out


def row(I, name, plan, sec, **extra):
    e = I.evaluate(plan)
    return dict(手法=name, 回復数=e["recovered"], 回復可能=e["recoverable"], 対応不能=e["unreachable"],
                完了時刻_分=round(e["makespan"], 1), 実行可能=e["feasible"], 予備バッテリー=e["spares_used"],
                計算時間_秒=round(sec, 2), **extra), e


def compare(I, seeds=3, qubo_reads=20, qubo_sweeps=2000, backend="neal", token=None, col_limit=120, log=print):
    rows, evs = [], {}
    p, t = S.solve_greedy_ls(I, 10); r, e = row(I, "貪欲法 + 局所探索", p, t); rows.append(r); evs["greedy"] = e; log(r)
    p, t, info = S.solve_milp(I, 30); r, e = row(I, "MILP（近似モデル）", p, t, 備考=f"status {info['status']}")
    rows.append(r); log(r)
    p, t, info = S.solve_columns(I, 3, col_limit)
    r, e = row(I, "列挙 + MILP（厳密, 1 台 3 飛行まで）", p, t, 備考=f"列 {info['columns']}, status {info['status']}")
    rows.append(r); evs["exact"] = e; log(r)
    best_raw, best_ls, secs, exact_cnt = None, None, [], 0
    for s in range(seeds):
        p, t, info = S.solve_qubo(I, backend=backend, token=token, num_reads=qubo_reads, num_sweeps=qubo_sweeps, seed=s)
        secs.append(t); exact_cnt += int(info.get("raw_exact_cover", False))
        e = I.evaluate(p)
        if best_raw is None or S._key(e) < S._key(best_raw[1]):
            best_raw = (p, e, info)
        t2 = time.time()
        q = S.local_search(I, S.repair(I, p), 10)
        e2 = I.evaluate(q)
        if best_ls is None or S._key(e2) < S._key(best_ls[1]):
            best_ls = (q, e2, time.time() - t2)
    r, e = row(I, "QUBO（生の解）", best_raw[0], float(np.mean(secs)),
               備考=f"変数 {best_raw[2].get('n')}, {seeds} 回中 各センサーちょうど 1 回 {exact_cnt} 回")
    rows.append(r); evs["qubo_raw"] = e; log(r)
    r, e = row(I, "QUBO + 修復 + 局所探索", best_ls[0], float(np.mean(secs)) + best_ls[2]); rows.append(r)
    evs["qubo_ls"] = e; log(r)
    # 上限 T の二分探索 + 判定 QUBO（qubo_bisect.py）
    best_b, best_bls, secs = None, None, []
    for s in range(seeds):
        p, t, info = solve_qubo_bisect(I, backend=backend, token=token, num_reads=qubo_reads,
                                       num_sweeps=qubo_sweeps, seed=s)
        secs.append(t)
        e = I.evaluate(p)
        if best_b is None or S._key(e) < S._key(best_b[1]):
            best_b = (p, e, info)
        t2 = time.time()
        q = S.local_search(I, p, 10)
        e2 = I.evaluate(q)
        if best_bls is None or S._key(e2) < S._key(best_bls[1]):
            best_bls = (q, e2, time.time() - t2)
    r, e = row(I, "QUBO 二分探索（生の解）", best_b[0], float(np.mean(secs)),
               備考=f"QUBO を解いた回数 {best_b[2]['iters'] + 1}")
    rows.append(r); evs["qubo_bisect"] = e; log(r)
    r, e = row(I, "QUBO 二分探索 + 局所探索", best_bls[0], float(np.mean(secs)) + best_bls[2]); rows.append(r)
    evs["qubo_bisect_ls"] = e; log(r)
    lb = I.lower_bound()
    opt = evs["exact"]["makespan"] if evs["exact"]["recovered"] == evs["exact"]["recoverable"] else None
    for r in rows:
        r["厳密解との差"] = f"{(r['完了時刻_分'] - opt) / opt:+.1%}" if opt else None
    return rows, evs, lb


def draw(w, sc, I, ev, path_map, path_gantt):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager as fm
    from matplotlib.patches import Polygon as Poly
    av = {f.name for f in fm.fontManager.ttflist}
    plt.rcParams["font.family"] = [f for f in ["Noto Sans CJK JP", "IPAexGothic", "IPAGothic"] if f in av] + ["DejaVu Sans"]
    N = np.array(w["nodes"]) / 1000
    fig, ax = plt.subplots(figsize=(10, 10))
    for P in w["polys"]:
        ax.add_patch(Poly(np.array(P) / 1000, closed=True, fc="#f4f1e8", ec="#999", lw=0.6))
    ax.plot(*(np.array(w["pref"]) / 1000).T, "k-", lw=1.2)
    style = {"local": ("#e3b26b", 0.6), "major": ("#3a8f5c", 1.0), "national": ("#c0504d", 1.4)}
    closed_edges = {w["segments"][s]["edge"] for s in sc["closed_segments"]}
    for i, e in enumerate(w["edges"]):
        c, lw = style[e["cls"]]
        ax.plot(*N[[e["a"], e["b"]]].T, color=c, lw=lw, alpha=0.8, zorder=1)
    for s in sc["closed_segments"]:
        g = w["segments"][s]
        ax.plot(g["x"] / 1000, g["y"] / 1000, "kx", ms=6, mew=1.6, zorder=4)
    ic = w["expressway"]["ic_node"]
    for a, b, _ in w["expressway"]["edges"]:
        ax.plot(*N[[ic[a], ic[b]]].T, color="#1f5fbf", lw=3, zorder=2)
    for k, v in ic.items():
        ax.plot(*N[v], "s", color="#1f5fbf", ms=6, zorder=5); ax.annotate(k, N[v], fontsize=8, color="#1f5fbf")
    Sxy = np.array([[s["x"], s["y"]] for s in w["sensors"]]) / 1000
    failed = set(sc["failed"])
    unreach = {I.targets[j] for j in I.unreachable}
    ok = [i for i in range(len(Sxy)) if i not in failed]
    ax.plot(*Sxy[ok].T, "^", color="#9a9a9a", ms=5, zorder=3, label="通信正常")
    fr = [i for i in failed if i not in unreach]
    ax.plot(*Sxy[fr].T, "^", color="#e8590c", ms=9, mec="k", zorder=6, label="通信断（回復対象）")
    if unreach:
        ax.plot(*Sxy[list(unreach)].T, "o", mfc="none", mec="#d6336c", ms=14, mew=2, zorder=6, label="対応不能")
    cols = plt.cm.tab10(np.arange(10))
    for tid, info in ev["per_truck"].items():
        for f in info["flights"]:
            fl = I.flights[f]
            pts = [N[fl["node"]]] + [I.sxy[j] / 1000 for j in fl["order"]] + [N[fl["node"]]]
            ax.plot(*np.array(pts).T, "--", color=cols[tid % 10], lw=1.3, zorder=7)
            ax.plot(*N[fl["node"]], "D", color=cols[tid % 10], ms=6, mec="k", zorder=8)
    for d in w["depots"]:
        ax.plot(*N[d["node"]], "o", color="#6f42c1", ms=12, mec="k", zorder=9)
        ax.annotate(f"{d['name']}（{d['trucks']} 台）", N[d["node"]] + 1.2, fontsize=10, color="#6f42c1", weight="bold")
    E = np.array(sc["epicenter"]) / 1000
    ax.plot(*E, "*", color="#d6336c", ms=18, mec="k", zorder=9, label="震源")
    ax.plot([], [], "kx", label="通行止め区間"); ax.plot([], [], "D", color="#555", label="離陸地点（色 = 車）")
    ax.set_aspect("equal"); ax.legend(loc="lower right", fontsize=9)
    ax.set_title(f"Phase 2 サンプル: 通信断 {len(failed)} 基・通行止め {len(sc['closed_segments'])} 区間 → "
                 f"回復 {ev['recovered']} 基, 完了 {ev['makespan']:.1f} 分")
    fig.tight_layout(); fig.savefig(path_map, dpi=90); plt.close(fig)

    # 車ごとの行動（ガントチャート）
    from dynamic import replay
    fig, ax = plt.subplots(figsize=(11, 4.5))
    for tr in I.trucks:
        info = ev["per_truck"][tr.tid]
        legs = replay(I, tr, info["order"], info["flights"])
        y = tr.tid
        for leg in legs:
            ax.barh(y, leg["arrive"] - leg["depart"], left=leg["depart"], color="#adb5bd", height=0.5)
            for fl in leg["flights"]:
                ax.barh(y, fl["end"] - fl["start"], left=fl["start"], color=cols[tr.tid % 10], height=0.5)
                for t in fl["recs"].values():
                    ax.plot(t, y, "k|", ms=12)
    ax.set_yticks(range(len(I.trucks)))
    ax.set_yticklabels([f"車{t.tid}（{t.depot}）" for t in I.trucks])
    ax.axvline(ev["makespan"], color="#d6336c", ls="--"); ax.text(ev["makespan"], -0.8, f" 完了 {ev['makespan']:.1f} 分", color="#d6336c")
    ax.set_xlabel("経過時間 [分]（灰色 = 移動, 色 = 飛行, 縦線 = センサー回復）")
    ax.invert_yaxis(); fig.tight_layout(); fig.savefig(path_gantt, dpi=90); plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scale", action="store_true")
    ap.add_argument("--dynamic", action="store_true")
    ap.add_argument("--backend", default="neal")
    a = ap.parse_args()
    w, sc = load()
    os.makedirs(RES, exist_ok=True)
    if a.dynamic:
        # 判明する順番を 8 通り変えて, 方法ごとの平均と最悪を比べる
        qubo = lambda I: S.solve_qubo(I, backend=a.backend, num_reads=10, num_sweeps=1000)[0]
        methods = {
            "貪欲法 + 局所探索（最後の回復時刻を最小）": lambda I: S.solve_greedy_ls(I, 3, "makespan")[0],
            "貪欲法 + 局所探索（回復時刻の合計を最小）": lambda I: S.solve_greedy_ls(I, 3, "sum")[0],
            "列挙 + MILP（各時点で厳密）": lambda I: S.solve_columns(I, 3, 60)[0],
            "QUBO + 局所探索（最後の回復時刻を最小）": lambda I: S.local_search(I, S.repair(I, qubo(I)), 3),
            "QUBO + 局所探索（回復時刻の合計を最小）":
                lambda I: S.local_search(I, S.repair(I, qubo(I)), 3, S.Evaluator(I, "sum")),
        }
        runs = {k: [] for k in methods}
        for rs in range(8):
            evs = reveal_schedule(sc, seed=rs)
            for name, m in methods.items():
                r = run_dynamic(w, sc, m, events=evs)
                runs[name].append(dict(回復数=r["recovered"], 完了時刻_分=round(r["makespan"], 1),
                                       平均回復時刻_分=round(r["mean_time"], 1),
                                       再計画の最大計算時間_秒=round(max(r["solve_sec"]), 2)))
            print("判明の順番", rs, {k: v[-1]["完了時刻_分"] for k, v in runs.items()}, flush=True)
        summary = {}
        for k, v in runs.items():
            summary[k] = dict(回復数_平均=round(float(np.mean([x["回復数"] for x in v])), 2),
                              完了時刻_平均=round(float(np.mean([x["完了時刻_分"] for x in v])), 1),
                              完了時刻_最悪=round(float(np.max([x["完了時刻_分"] for x in v])), 1),
                              平均回復時刻=round(float(np.mean([x["平均回復時刻_分"] for x in v])), 1),
                              再計画の最大計算時間_秒=round(float(np.max([x["再計画の最大計算時間_秒"] for x in v])), 2))
        I = Instance(w, sc["closed_segments"], sc["failed"], trucks_of(w), 2)
        p, t, _ = S.solve_columns(I, 3, 120)
        e = I.evaluate(p)
        summary["参考: 最初から全部分かっていた場合（厳密）"] = dict(
            回復数_平均=e["recovered"], 完了時刻_平均=round(e["makespan"], 1),
            平均回復時刻=round(float(np.mean(list(e["rec_time"].values()))), 1))
        print(json.dumps(summary, ensure_ascii=False, indent=1))
        ev0 = reveal_schedule(sc, seed=0)
        json.dump(dict(events=[dict(t=x["t"], 判明した通信断=len(x["failed"]), 判明した通行止め=len(x["closed"])) for x in ev0],
                       summary=summary, runs=runs), open(os.path.join(RES, "phase2_dynamic.json"), "w"),
                  ensure_ascii=False, indent=1)
        return
    if a.scale:
        rows = []
        cases = [(n_fail, n_closed, seed) for n_fail in (15, 25, 35) for n_closed in (34, 80) for seed in (11,)]
        rng = np.random.default_rng(0)
        S_xy = np.array([[s["x"], s["y"]] for s in w["sensors"]])
        for n_fail, n_closed, seed in cases:
            epi = (S_xy[rng.integers(len(S_xy))] + rng.normal(0, 3000, 2)).tolist()
            scx = make_scenario(w, seed=seed, epicenter=epi, n_fail=n_fail, n_closed=n_closed,
                                fault_len=25000, fault_angle=None)
            I = Instance(w, scx["closed_segments"], scx["failed"], trucks_of(w), 2)
            res, evs, lb = compare(I, seeds=2, col_limit=150, log=lambda r: None)
            d = {r["手法"]: r for r in res}
            rows.append(dict(通信断=n_fail, 通行止め=n_closed, seed=seed, 回復可能=I.recoverable.__len__(),
                             対応不能=len(I.unreachable), 飛行候補=len(I.flights), 下界_分=round(lb, 1),
                             **{f"{k}_分": v["完了時刻_分"] for k, v in d.items()},
                             **{f"{k}_秒": v["計算時間_秒"] for k, v in d.items()}))
            print(rows[-1], flush=True)
        json.dump(rows, open(os.path.join(RES, "phase2_scale.json"), "w"), ensure_ascii=False, indent=1)
        return
    I = Instance(w, sc["closed_segments"], sc["failed"], trucks_of(w), 2)
    rows, evs, lb = compare(I)
    print("メイクスパンの下界", round(lb, 1))
    json.dump(dict(scenario=dict(通信断=len(sc["failed"]), 通行止め区間=len(sc["closed_segments"]),
                                 回復可能=len(I.recoverable), 対応不能=len(I.unreachable),
                                 離陸地点候補=len(I.launch), 飛行候補=len(I.flights), 下界_分=round(lb, 1)),
                   results=rows), open(os.path.join(RES, "phase2_compare.json"), "w"), ensure_ascii=False, indent=1)
    draw(w, sc, I, evs["exact"], os.path.join(RES, "phase2_map.png"), os.path.join(RES, "phase2_gantt.png"))


if __name__ == "__main__":
    main()
