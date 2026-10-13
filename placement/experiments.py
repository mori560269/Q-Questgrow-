"""
placement/experiments.py : Colab (placement_amplify.ipynb) から呼ぶ比較実験

  run_all(...)        古典 (MILP, 貪欲法) と QUBO 1 / QUBO 2 を同じ物差しで比べる
  equal_time(...)     同じ計算時間でどこまで良い解が出るか (MILP の時間制限も変える)
  scaling(...)        候補地を増やしながら MILP と QUBO 2 を比べる

  backend="amplify" なら QUBO を Fixstars Amplify AE で, "neal" ならローカルの焼きなましで解く.
  解はすべて 1 km マスで判定し, 「QUBO + 修復」は貪欲法の手で不足を補い 要らないセンサーを外したもの.
"""
import time
import numpy as np

from common import Problem
from classical import solve_milp, solve_greedy, repair
from qubo_amplify import build_model, solve_model, solve_lagrangian


def _row(prob, name, x, sec, opt=None, **extra):
    ev = prob.evaluate(x, cell_m=1000.0)
    r = dict(手法=name, コスト=ev["cost"], 実行可能=ev["feasible"], 時間_秒=round(sec, 2), **ev["n_sensors"], **extra)
    if opt:
        r["最適との差"] = f"{(ev['cost'] - opt) / opt:+.1%}"
    r["_x"] = ev["x"]
    return r


def run_all(backend="neal", token=None, seeds=3, q1_sweeps=8000, q1_time_ms=10000,
            q2_iters=100, q2_sweeps=200, q2_time_ms=500, log=print):
    prob = Problem(cell_m=1000.0)
    rows = []
    x, info = solve_milp(prob)
    opt = float((x * prob.cost).sum())
    rows.append(_row(prob, "MILP (HiGHS)", x, info["sec"], opt, 備考="最適 (gap 0)"))
    log(rows[-1]["手法"], rows[-1]["コスト"], rows[-1]["時間_秒"])
    x, info = solve_greedy(prob)
    rows.append(_row(prob, "貪欲法", x, info["sec"], opt))
    log(rows[-1]["手法"], rows[-1]["コスト"], rows[-1]["時間_秒"])

    # QUBO 1
    pq = Problem(cell_m=2000.0)
    model, xv, binfo = build_model(pq)
    raw_best, rep_best, secs, raw_ok = None, None, [], 0
    for s in range(seeds):
        sols, sinfo = solve_model(model, xv, backend=backend, token=token, num_reads=4,
                                  num_sweeps=q1_sweeps, seed=s, time_limit_ms=q1_time_ms)
        secs.append(sinfo["sec"])
        evs = [prob.evaluate(x_, cell_m=1000.0) for x_ in sols]
        b = min(evs, key=lambda r: (not r["feasible"], r["cost"]))
        raw_ok += int(b["feasible"])
        if raw_best is None or (not b["feasible"], b["cost"]) < (not raw_best["feasible"], raw_best["cost"]):
            raw_best = b
        t = time.time()
        rx = repair(prob, np.array(b["x"], float))
        rc = float((rx * prob.cost).sum())
        if rep_best is None or rc < rep_best[0]:
            rep_best = (rc, rx, time.time() - t)
        log("QUBO1 seed", s, b["cost"], b["feasible"], "→ 修復", rc)
    q1note = f"変数 {binfo['n_x'] + binfo['n_y']}+スラック / {seeds} 回中 修復なしで実行可能 {raw_ok} 回"
    rows.append(_row(prob, "QUBO 1 (生の解)", np.array(raw_best["x"]), float(np.mean(secs)), opt, 備考=q1note))
    rows.append(_row(prob, "QUBO 1 + 修復", rep_best[1], float(np.mean(secs)) + rep_best[2], opt))

    # QUBO 2
    best_raw, best_rep, secs, feas_it = None, None, [], []
    for s in range(seeds):
        best, li = solve_lagrangian(prob, iters=q2_iters, backend=backend, token=token, num_sweeps=q2_sweeps,
                                    time_limit_ms=q2_time_ms, seed=1000 * s)
        secs.append(li["sec"]); feas_it.append(li["feasible_iters"])
        start = best[1] if best else li["least_violating_x"]
        if best and (best_raw is None or best[0] < best_raw[0]):
            best_raw = best
        t = time.time()
        rx = repair(prob, start)
        rc = float((rx * prob.cost).sum())
        if best_rep is None or rc < best_rep[0]:
            best_rep = (rc, rx, time.time() - t)
        log("QUBO2 seed", s, None if best is None else best[0], "実行可能な反復", li["feasible_iters"], "→ 修復", rc)
    note = f"変数 {prob.P * prob.K} / 反復 {q2_iters} 回のうち実行可能 {feas_it}"
    if best_raw:
        rows.append(_row(prob, "QUBO 2 (生の解)", best_raw[1], float(np.mean(secs)), opt, 備考=note))
    else:
        rows.append(dict(手法="QUBO 2 (生の解)", コスト=None, 実行可能=False, 時間_秒=round(float(np.mean(secs)), 2),
                         備考=note + " / 実行可能な解なし"))
    rows.append(_row(prob, "QUBO 2 + 修復", best_rep[1], float(np.mean(secs)) + best_rep[2], opt))
    return prob, rows


def equal_time(backend="neal", token=None, budgets=(1, 3, 10), seed=0, log=print):
    """同じ時間 (秒) でどこまで良い解が出るか. MILP は時間制限, QUBO 2 は反復回数と 1 回の時間で調整"""
    prob = Problem(cell_m=1000.0)
    x, _ = solve_milp(prob)
    opt = float((x * prob.cost).sum())
    rows = []
    for b in budgets:
        x, info = solve_milp(prob, time_limit=b)
        ev = prob.evaluate(x, cell_m=1000.0)
        rows.append(dict(時間の予算_秒=b, 手法="MILP", コスト=ev["cost"] if ev["feasible"] else None,
                         実行可能=ev["feasible"], 実際の時間=round(info["sec"], 2)))
        if backend == "amplify":
            iters, kw = max(3, int(b / 0.6)), dict(time_limit_ms=500)       # AE: 1 回 0.5 秒 + 通信
        else:
            iters, kw = max(3, int(b / 0.04)), dict(num_sweeps=200)         # neal: 1 回 約 0.04 秒
        best, li = solve_lagrangian(prob, iters=iters, backend=backend, token=token, seed=seed, **kw)
        rows.append(dict(時間の予算_秒=b, 手法=f"QUBO 2 ({iters} 反復)", コスト=None if best is None else best[0],
                         実行可能=best is not None, 実際の時間=round(li["sec"], 2)))
        log(rows[-2]); log(rows[-1])
    for r in rows:
        r["最適との差"] = None if r["コスト"] is None else f"{(r['コスト'] - opt) / opt:+.1%}"
    return rows


def scaling(backend="neal", token=None, grids=(None, 8000, 5000), milp_limit=120, q2_iters=100,
            q2_sweeps=200, q2_time_ms=500, log=print):
    """候補地を増やしながら比べる. grids は候補地に足す格子の間隔 [m] (None = 元の 86 か所)"""
    rows = []
    for g in grids:
        prob = Problem(cell_m=1000.0, extra_grid_m=g)
        x, info = solve_milp(prob, time_limit=milp_limit)
        opt = float((x * prob.cost).sum())
        best, li = solve_lagrangian(prob, iters=q2_iters, backend=backend, token=token, num_sweeps=q2_sweeps,
                                    time_limit_ms=q2_time_ms)
        t = time.time()
        rx = repair(prob, best[1] if best else li["least_violating_x"])
        rc = float((rx * prob.cost).sum())
        r = dict(候補地=prob.P, 変数=prob.P * prob.K, MILP_コスト=opt, MILP_秒=round(info["sec"], 1),
                 MILP_状態="最適" if info["status"] == 0 else "時間切れ",
                 QUBO2_コスト=None if best is None else best[0], QUBO2_秒=round(li["sec"], 1),
                 QUBO2_実行可能な反復=f"{li['feasible_iters']}/{q2_iters}",
                 QUBO2修復_コスト=rc, QUBO2修復_秒=round(li["sec"] + time.time() - t, 1))
        r["QUBO2修復_最適との差"] = f"{(rc - opt) / opt:+.1%}"
        rows.append(r)
        log(r)
    return rows
