"""
phase2/qubo_bisect.py : 「最後の回復時刻を最小」を, 上限 T の二分探索 + 判定 QUBO で解く

  以前の QUBO（solvers.solve_qubo）は, 最大値の最小化を「車ごとの負荷の 2 乗和」で近似していたため,
  生の解が最良より 30〜50% 悪かった. ここでは最大値をそのまま扱う.

  1. 上限 T を決めて, 「全センサーを T 分以内に回復できる計画があるか」を判定する QUBO を解く
  2. あれば T を縮め, なければ広げる（二分探索）. 見つかった計画は model.evaluate で厳密に確かめる

  判定 QUBO（スラック変数なし. 制約はすべて 1 次の「候補から外す」か 2 次の罰金）
    変数  y[f,t,k] = 飛行 f を, 車 t の k 番目の飛行として行う
          → T に間に合わない (f,t,k) は, 最初から変数にしない（1 次の条件）
    E =   Σ_j ( Σ_{f∋j,t,k} y − 1 )²                     … 各センサーをちょうど 1 回
        + Σ_{t,k} Σ_{f<g} y[f,t,k] y[g,t,k]               … 1 つの枠に飛行は 1 つまで
        + Σ_{t,k≥2} ( u[t,k] − u[t,k−1] u[t,k] )          … 枠は前から詰めて使う（u = その枠の使用）
        + Σ  y[f,t,k] y[g,t,k+1]   （f の次に g だと T に間に合わない組）  … 連続する 2 つの飛行の時間
        + ε Σ (回復時刻の見積もり) y                       … 同点なら早く回復する方（罰金より必ず小さい）
    E = ε の項だけ  ⇔  （見積もりの上で）T 以内に終わる計画

  枠 k の開始時刻は「その車の最初の飛行 + (k−1) × (最短の飛行時間 + 充電 30 分)」以上という下界で見積もる.
  3 つ以上続く飛行の時間の積み重ねは 2 次の項では表せないので, 最後に厳密な評価で確かめる.
"""
import os
import sys
import time
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "placement"))
from model import CHARGE_MIN
import solvers as S


def _rec_last(f):
    return max(f["offset"])


def build_decision_qubo(I, T_lim, eps_total=0.3, sum_weight=0.0):
    """sum_weight > 0 なら「回復時刻の合計を最小（早く回復するほど良い）」を目的に足す:
         Σ (枠の開始の下界 + 各センサーまでの時間) y          … 1 次
       + Σ (前の飛行のせいで遅れる分 × 回るセンサー数) y y'   … 連続する 2 つの飛行の 2 次
       係数は, 1 変数あたりの最大値が sum_weight（< 被覆の罰金 2）になるようにそろえる"""
    F = len(I.flights)

    var = []                                   # (f, ti, k, 開始の下界)
    S1 = {}
    for ti, tr in enumerate(I.trucks):
        for fi, f in enumerate(I.flights):
            d = I.drive_from[tr.node][f["node"]]
            if np.isfinite(d):
                S1[fi, ti] = max(tr.t0 + d, tr.ready)
    for ti, tr in enumerate(I.trucks):
        fl = [fi for fi in range(F) if (fi, ti) in S1]
        if not fl:
            continue
        # 枠 k で飛行 f を始められる最も早い時刻の下界を, 前の枠から積み上げて求める（動的計画法）
        #   LB_1(f) = 車がその離陸地点に着く時刻
        #   LB_k(f) = max( LB_1(f), min_g [ LB_{k-1}(g) + 飛行時間_g + max(g→f の走行時間, 充電 30 分) ] )
        LB = {fi: S1[fi, ti] for fi in fl}
        for k in range(1, tr.cap(True) + 1):
            if k > 1:
                new = {}
                for fi in fl:
                    best = np.inf
                    for gi in fl:
                        if gi == fi or not np.isfinite(LB[gi]):
                            continue
                        vg, vf = I.flights[gi]["node"], I.flights[fi]["node"]
                        dv = I.drive(vg, vf) if vg != vf else 0.0
                        best = min(best, LB[gi] + I.flights[gi]["dur"] + max(dv, CHARGE_MIN))
                    new[fi] = max(S1[fi, ti], best)
                LB = new
            for fi in fl:
                st = LB[fi]
                if np.isfinite(st) and st + _rec_last(I.flights[fi]) <= T_lim + 1e-9:
                    var.append((fi, ti, k, st))
    n = len(var)
    pos = {(fi, ti, k): i for i, (fi, ti, k, _) in enumerate(var)}
    # T に間に合う候補が 1 つもないセンサーがあれば, その時点で「T では無理」
    cov = {j: [] for j in I.recoverable}
    for i, (fi, ti, k, st) in enumerate(var):
        for j in I.flights[fi]["sensors"]:
            if j in cov:
                cov[j].append(i)
    if any(len(v) == 0 for v in cov.values()) or n == 0:
        return None
    lin = np.zeros(n)
    Q = np.zeros((n, n))

    def q(a, b, w):
        if a == b:
            lin[a] += w
        else:
            Q[min(a, b), max(a, b)] += w

    # 重み: 被覆 W_COV, 1 枠 1 つ W_ONE, 詰める 1, 時間 W_TIME.
    # 「詰める」の −u[k−1]u[k] は, 1 枠に複数入ると際限なく負になる. W_ONE ≥ 3 なら
    # 各枠の W_ONE·a(a−1)/2 が隣の枠との −a·b を上回り, エネルギーが下に抜けない.
    W_COV, W_ONE, W_TIME = 2.0, 3.0, 2.0
    delays = []
    for j, mem in cov.items():                                        # ちょうど 1 回
        for a in mem:
            lin[a] += -W_COV
        for x in range(len(mem)):
            for y in range(x + 1, len(mem)):
                q(mem[x], mem[y], 2.0 * W_COV)
    slots = {}
    for i, (fi, ti, k, st) in enumerate(var):
        slots.setdefault((ti, k), []).append(i)
    for (ti, k), mem in slots.items():                                # 1 枠に 1 つまで
        for x in range(len(mem)):
            for y in range(x + 1, len(mem)):
                q(mem[x], mem[y], W_ONE)
        if k >= 2:                                                    # 前から詰める
            prev = slots.get((ti, k - 1), [])
            for g in mem:
                lin[g] += 1.0
                for f in prev:
                    q(f, g, -1.0)
            # 連続する 2 つの飛行が T に間に合わない組に罰金（目的が「合計」なら遅れの分も足す）
            for f in prev:
                fi, _, _, stf = var[f]
                Ff = I.flights[fi]
                end_f = stf + Ff["dur"]
                for g in mem:
                    gi, _, _, stg = var[g]
                    Fg = I.flights[gi]
                    dv = I.drive(Ff["node"], Fg["node"]) if Ff["node"] != Fg["node"] else 0.0
                    if not np.isfinite(dv):
                        q(f, g, W_TIME); continue
                    start_g = max(end_f + dv, end_f + CHARGE_MIN, stg)
                    if start_g + _rec_last(Fg) > T_lim + 1e-9:
                        q(f, g, W_TIME)
                    elif sum_weight > 0:
                        delays.append((f, g, (start_g - stg) * len(Fg["sensors"])))
    est = np.array([st + _rec_last(I.flights[fi]) for (fi, ti, k, st) in var])
    if sum_weight > 0:
        cost = np.array([sum(st + o for o in I.flights[fi]["offset"]) for (fi, ti, k, st) in var])
        scale = sum_weight / max(cost.max(), max((d for _, _, d in delays), default=0.0), 1e-9)
        lin += scale * cost
        for f, g, d in delays:
            if d > 0:
                q(f, g, scale * d)
    else:
        lin += eps_total * est / (est.sum() + 1e-9)                   # 同点なら早い方（罰金 1 より十分小さい）
    return dict(lin=lin, Q=Q, var=var, n=n)


def decode(I, var, s):
    plan = {t.tid: [] for t in I.trucks}
    for i in np.nonzero(np.rint(s))[0]:
        fi, ti, k, _ = var[i]
        plan[I.trucks[ti].tid].append(fi)
    cnt = {}
    for fids in plan.values():
        for f in fids:
            for j in I.flights[f]["sensors"]:
                cnt[j] = cnt.get(j, 0) + 1
    exact = all(cnt.get(j, 0) == 1 for j in I.recoverable)
    return plan, exact


def solve_qubo_bisect(I, backend="neal", token=None, num_reads=20, num_sweeps=2000, time_limit_ms=2000,
                      seed=0, max_iter=8, tol=1.0, use_repair=False, log=None):
    """戻り値: (最良の計画, 計算時間, 情報). use_repair=False なら, QUBO がそのまま出した正しい形の解だけを使う"""
    from qubo_amplify import solve_inner
    t0 = time.time()
    ev = S.Evaluator(I)
    # 上限の初期値: 以前の QUBO（負荷の 2 乗和）の生の解
    p0, _, _ = S.solve_qubo(I, backend=backend, token=token, num_reads=num_reads, num_sweeps=num_sweeps,
                            time_limit_ms=time_limit_ms, seed=seed)
    if use_repair:
        p0 = S.repair(I, p0, ev)
    e0 = I.evaluate(p0)
    best_plan, hi = p0, (e0["makespan"] if e0["recovered"] == e0["recoverable"] and e0["feasible"] else np.inf)
    lo = I.lower_bound()
    hist = [dict(T=None, 判定="初期値（負荷の 2 乗和 QUBO）", 完了時刻=round(e0["makespan"], 1))]
    it = 0
    while it < max_iter and (not np.isfinite(hi) or hi - lo > tol):
        T_lim = (lo + hi) / 2 if np.isfinite(hi) else lo * 1.5
        it += 1
        model = build_decision_qubo(I, T_lim)
        if model is None:
            lo = T_lim
            hist.append(dict(T=round(T_lim, 1), 判定="候補なし（間に合わないセンサーあり）"))
            continue
        sols, _ = solve_inner(model["lin"], model["Q"], backend, token, time_limit_ms, num_reads, num_sweeps,
                              seed + it)
        found = None
        for s in sols[:num_reads]:
            plan, exact = decode(I, model["var"], s)
            if not exact:
                if not use_repair:
                    continue
                plan = S.repair(I, plan, ev)
            e = I.evaluate(plan)
            if e["recovered"] == e["recoverable"] and e["feasible"]:
                if found is None or e["makespan"] < found[1]:
                    found = (plan, e["makespan"])
        if found and found[1] < hi:
            best_plan, hi = found
        if found and found[1] <= T_lim + 1e-6:
            hist.append(dict(T=round(T_lim, 1), 判定="あり", 完了時刻=round(found[1], 1), 変数=model["n"]))
        else:
            lo = T_lim
            hist.append(dict(T=round(T_lim, 1), 判定="見つからず", 変数=model["n"],
                             最良=None if not found else round(found[1], 1)))
        if log:
            log(hist[-1])
    return best_plan, time.time() - t0, dict(history=hist, iters=it, lower=round(lo, 1), upper=round(hi, 1))


def solve_qubo_sum_timed(I, budget, seed=0, chunk=(8, 2000), sum_weight=1.8, start_factor=1.35):
    """「早く回復するほど良い」の QUBO を, 時間の予算いっぱい解く.
    上限 T は下界の 1.35 倍から始め, 解が見つからなければ 25% ずつゆるめ, 見つかればその完了時刻まで締める.
    （T がゆるいと変数が増えて解の質が落ちる: サンプルで T=230 → 1,242 変数, T=140 → 594 変数）
    sum_weight = 目的の係数の最大値. 被覆の罰金 2 より小さければ, センサーを外して得をすることはない"""
    from qubo_amplify import solve_inner
    t_end = time.time() + budget
    ev = S.Evaluator(I, "sum")
    T_lim = I.lower_bound() * start_factor
    best, bkey, it, miss = None, None, 0, 0
    model, model_T = None, None
    while True:
        if time.time() >= t_end and (best is not None or time.time() >= t_end + budget):
            break
        if model is None or model_T != T_lim:
            model = build_decision_qubo(I, T_lim, sum_weight=sum_weight)
            model_T = T_lim
            if model is None:
                T_lim *= 1.25
                continue
        sols, _ = solve_inner(model["lin"], model["Q"], "neal", None, 1000, chunk[0], chunk[1], seed * 1000 + it)
        it += 1
        got = False
        for s_ in sols:
            plan, exact = decode(I, model["var"], s_)
            if not exact:
                continue
            got = True
            k = ev.key(plan)
            if bkey is None or k < bkey:
                best, bkey = plan, k
        if best is not None:
            e = I.evaluate(best)
            if e["feasible"] and e["makespan"] < T_lim - 1e-6:
                T_lim = e["makespan"] + 1e-6
        if not got and best is None:
            T_lim *= 1.25
    return best
