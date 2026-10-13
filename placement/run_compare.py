"""
placement/run_compare.py : 元の課題 (固定センサーの最適配置) を, 古典的手法と Amplify の QUBO で解いて比べる

  python run_compare.py                          # QUBO はローカルの焼きなまし (neal) で解く
  AMPLIFY_TOKEN=xxxx python run_compare.py --backend amplify   # QUBO を Fixstars Amplify AE で解く

  出力: results/placement_compare.json, results/placement_maps.png
  判定は全手法共通: 1 km マスで面的充足率を数える (参考に 200 m マスでも数え直す)
"""
import argparse
import json
import os
import sys
import time
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import Problem, save_map
from classical import solve_milp, solve_greedy, repair
from qubo_amplify import build_model, solve_model, solve_lagrangian

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")


def summarize(prob, x, extra):
    ev = prob.evaluate(x, cell_m=1000.0)
    ev200 = prob.evaluate(x, cell_m=200.0)
    ev["feasible_200m"] = ev200["feasible"]
    ev["cov_200m"] = ev200["cov"]
    ev.update(extra)
    return ev


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", choices=["neal", "amplify"], default="neal")
    ap.add_argument("--token", default=None)
    ap.add_argument("--seeds", type=int, default=5)
    ap.add_argument("--iters", type=int, default=100)
    a = ap.parse_args()
    be = a.backend
    solver_name = "Amplify AE" if be == "amplify" else "焼きなまし neal (Amplify のモデルを変換)"

    prob = Problem(cell_m=1000.0)
    out, maps = {}, {}

    # ---- 古典 (A) MILP
    x, info = solve_milp(prob)
    out["MILP"] = summarize(prob, x, dict(method="MILP (HiGHS)", sec=info["sec"], detail=info))
    print("MILP", out["MILP"]["cost"], out["MILP"]["feasible"], round(info["sec"], 1), "s", flush=True)
    maps["MILP (最適解)"] = out["MILP"]

    # ---- 古典 (B) 貪欲法
    x, info = solve_greedy(prob)
    out["greedy"] = summarize(prob, x, dict(method="貪欲法", sec=info["sec"]))
    print("greedy", out["greedy"]["cost"], out["greedy"]["feasible"], round(info["sec"], 1), "s", flush=True)
    maps["貪欲法"] = out["greedy"]

    # ---- QUBO 1: マスの被覆変数 + Amplify の制約 (スラック付き)
    pq = Problem(cell_m=2000.0)
    model, xv, binfo = build_model(pq)
    runs = []
    for s in range(a.seeds):
        sols, sinfo = solve_model(model, xv, backend=be, token=a.token, num_reads=4, num_sweeps=8000,
                                  seed=s, time_limit_ms=10000)
        raw = [prob.evaluate(x_, cell_m=1000.0) for x_ in sols]
        rawbest = min(raw, key=lambda r: (not r["feasible"], r["cost"]))
        rep = repair(prob, np.array(rawbest["x"], float))
        runs.append(dict(seed=s, sec=sinfo["sec"], raw_cost=rawbest["cost"], raw_feasible=rawbest["feasible"],
                         raw_checks=rawbest["checks"], repaired=rep, info=sinfo))
        print("QUBO1 seed", s, rawbest["cost"], rawbest["feasible"], "→ 修復", (rep * prob.cost).sum(), flush=True)
    bestrep = min(runs, key=lambda r: (r["repaired"] * prob.cost).sum())
    out["QUBO1"] = summarize(prob, bestrep["repaired"], dict(
        method=f"QUBO 1 (被覆マス + スラック) + 修復 / {solver_name}", sec=float(np.mean([r["sec"] for r in runs])),
        build=binfo, runs=[{k: v for k, v in r.items() if k != "repaired"} for r in runs],
        raw_feasible_runs=sum(r["raw_feasible"] for r in runs),
        repaired_costs=[float((r["repaired"] * prob.cost).sum()) for r in runs]))
    maps["QUBO 1 + 修復"] = out["QUBO1"]

    # ---- QUBO 2: ラグランジュ緩和 (スラックなし) + 乗数の外側ループ
    runs = []
    for s in range(a.seeds):
        best, linfo = solve_lagrangian(prob, iters=a.iters, backend=be, token=a.token, seed=1000 * s)
        hist = linfo.pop("history")
        # 各反復の解を修復したもの (QUBO + 修復) も記録するため, 最良の生の解から修復
        runs.append(dict(seed=s, raw_best_cost=None if best is None else best[0],
                         raw_x=None if best is None else best[1], info=linfo, history=hist))
        print("QUBO2 seed", s, None if best is None else best[0], "実行可能な反復", linfo["feasible_iters"],
              "/", a.iters, round(linfo["sec"], 1), "s", flush=True)
    ok = [r for r in runs if r["raw_x"] is not None]
    bestraw = min(ok, key=lambda r: r["raw_best_cost"])
    out["QUBO2"] = summarize(prob, bestraw["raw_x"], dict(
        method=f"QUBO 2 (ラグランジュ緩和) / {solver_name}", sec=float(np.mean([r["info"]["sec"] for r in runs])),
        raw_costs=[r["raw_best_cost"] for r in runs],
        feasible_iters=[r["info"]["feasible_iters"] for r in runs], iters=a.iters,
        info=bestraw["info"], history=bestraw["history"]))
    maps["QUBO 2 (ラグランジュ)"] = out["QUBO2"]
    # QUBO 2 の解をさらに 要らないセンサーを外す修復で磨く
    pol = repair(prob, np.array(bestraw["raw_x"], float))
    out["QUBO2_polished"] = summarize(prob, pol, dict(method=f"QUBO 2 + 修復 / {solver_name}"))
    maps["QUBO 2 + 修復"] = out["QUBO2_polished"]

    opt = out["MILP"]["cost"]
    for k, r in out.items():
        r["gap_to_opt"] = round((r["cost"] - opt) / opt, 4)
    os.makedirs(os.path.join(ROOT, "results"), exist_ok=True)
    json.dump(dict(backend=be, problem=dict(points=prob.P, types=prob.K, cells_1km=int(prob.N)), results=out),
              open(os.path.join(ROOT, "results", "placement_compare.json"), "w"), ensure_ascii=False, indent=1,
              default=lambda o: o.tolist() if hasattr(o, "tolist") else str(o))
    save_map(prob, maps, os.path.join(ROOT, "results", "placement_maps.png"))
    print("\n手法, コスト, 最適との差, 実行可能(1km), 実行可能(200m), 時間")
    for k, r in out.items():
        print(f"{r['method']}, {r['cost']:.0f}, {r['gap_to_opt']:+.1%}, {r['feasible']}, {r['feasible_200m']}, "
              f"{r.get('sec', 0):.1f}s")


if __name__ == "__main__":
    main()
