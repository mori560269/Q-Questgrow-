"""
phase2/exact.py : 実データの Phase 2 を厳密に解く（上限で枝刈りした列の列挙 + 集合分割 MILP の二分探索）

  考え方
    計画 = 車ごとに「行う飛行の組」を 1 つ選ぶこと. 組を決めれば, その車の最良の停車順と完了時刻 m_c は
    model.truck_schedule で厳密に求まる（停車地点が 7 以下なら全順列）.
    以前の solvers.solve_columns は「1 台 3 飛行まで」に限っていたが, 実データでは 4 飛行する車が最適になりうる.

  1. 上限 UB（ヒューリスティックの解の完了時刻）を決め, 完了時刻が UB 以下の組だけを深さ優先で列挙する.
     飛行を足すと完了時刻は減らない（走行時間は最短経路で三角不等式を満たし, 充電待ちも減らない）ので,
     UB を超えた組から先は調べなくてよい. 同じ拠点・同じ状態の車は同じ組の集合を持つので, 拠点ごとに 1 回だけ列挙する.
  2. T を二分探索し, 「完了時刻 ≤ T の組だけで, 全センサーをちょうど 1 回覆えるか」を集合分割 MILP で判定する.
        Σ_{c ∋ j} x_c = 1                 （各センサー）
        Σ_{c ∈ 拠点 b} x_c ≤ 拠点 b の車の数   （空の組は数えない）
        Σ_{c: 予備が要る組} x_c ≤ 予備バッテリーの数
     判定できる最小の T が最適な完了時刻（列挙が UB で打ち切られていないので厳密）.

  全センサーを回復できない（車と充電回数が足りない）場合は, 回復数の最大化を先に解く（同じ列で, 被覆を ≤ 1 にして数を最大化）.
"""
import time

import numpy as np
from scipy.optimize import milp, LinearConstraint, Bounds
import scipy.sparse as sp

import solvers as S


def truck_classes(I):
    cls = {}
    for tr in I.trucks:
        key = (tr.node, tr.t0, tr.ready, tr.flights_done, tr.spare)
        cls.setdefault(key, []).append(tr)
    return list(cls.values())


def enumerate_columns(I, UB, time_limit=600.0, max_cols=2_000_000):
    """拠点（車の状態）ごとに, 完了時刻 ≤ UB の飛行の組を全部列挙する. 戻り値: [(class, flights, m, needs_spare)], 打ち切ったか"""
    t0 = time.time()
    ev = S.Evaluator(I)
    sets = [frozenset(f["sensors"]) for f in I.flights]
    F = len(I.flights)
    out, truncated = [], False
    for ci, group in enumerate(truck_classes(I)):
        tr = group[0]
        cap = tr.cap(True)
        # 単独でも UB を超える飛行は使わない
        single = [f for f in range(F) if ev.truck(tr.tid, [f])[0] <= UB + 1e-6]
        stack = [((), frozenset(), -1)]
        while stack:
            comb, used, last = stack.pop()
            for pos in range(len(single)):
                f = single[pos]
                if f <= last or sets[f] & used:
                    continue
                nc = comb + (f,)
                if len(nc) > cap:
                    continue
                m = ev.truck(tr.tid, list(nc))[0]
                if m > UB + 1e-6:
                    continue
                out.append((ci, nc, m, len(nc) > tr.cap(False) and not tr.spare))
                stack.append((nc, used | sets[f], f))
            if time.time() - t0 > time_limit or len(out) > max_cols:
                truncated = True
                stack = []
        if truncated:
            break
    return out, truncated


def reduce_columns(I, cols):
    """同じ拠点・同じセンサーの組・同じ予備の要否の列は, 完了時刻が最短のものだけ残す（離陸地点が違うだけの列）.
    判定問題「完了時刻 ≤ T の列で集合分割できるか」の答えは変わらない（最短の列は, 残した列より T に間に合いやすい）"""
    best = {}
    for c in cols:
        k = (c[0], frozenset(j for f in c[1] for j in I.flights[f]["sensors"]), c[3])
        if k not in best or c[2] < best[k][2]:
            best[k] = c
    return list(best.values())


def _milp_feasible(I, cols, classes, T, J, maximize_cover=False, time_limit=60.0):
    idx = [i for i, c in enumerate(cols) if c[2] <= T + 1e-9]
    n = len(idx)
    if n == 0:
        return None
    jpos = {j: r for r, j in enumerate(J)}
    rows, cc, vals = [], [], []
    for k, i in enumerate(idx):
        for f in cols[i][1]:
            for j in I.flights[f]["sensors"]:
                rows.append(jpos[j]); cc.append(k); vals.append(1)
    nJ = len(J)
    A_cov = sp.csr_matrix((vals, (rows, cc)), shape=(nJ, n))
    A_cls = sp.csr_matrix(([1] * n, ([cols[i][0] for i in idx], list(range(n)))), shape=(len(classes), n))
    A_sp = sp.csr_matrix(([1 if cols[i][3] else 0 for i in idx], ([0] * n, list(range(n)))), shape=(1, n))
    cons = [LinearConstraint(A_cls, 0, [len(g) for g in classes]),
            LinearConstraint(A_sp, 0, I.spares_left)]
    if maximize_cover:
        cons.append(LinearConstraint(A_cov, 0, 1))
        c = -np.asarray(A_cov.sum(0)).ravel() * 1000 + np.array([cols[i][2] for i in idx]) * 1e-3
    else:
        cons.append(LinearConstraint(A_cov, 1, 1))
        c = np.zeros(n)
    r = milp(c, constraints=cons, integrality=np.ones(n), bounds=Bounds(0, 1),
             options=dict(time_limit=time_limit, disp=False))
    if r.x is None or r.status not in (0,):
        return None
    chosen = [idx[k] for k in np.nonzero(np.rint(r.x))[0]]
    return chosen


def solve_exact(I, UB=None, start=None, time_limit=600.0, log=None, reduce=False):
    """戻り値: plan, info（最適か・下界・列の数・時間）"""
    t0 = time.time()
    J = list(I.recoverable)
    if not J:
        return {t.tid: [] for t in I.trucks}, dict(optimal=True, makespan=0.0, cols=0, sec=0.0)
    if start is None:
        from equal_time import ils
        start = ils(I, 5.0, 0)
    e0 = I.evaluate(start)
    full = e0["recovered"] == len(J) and e0["feasible"]
    UB = e0["makespan"] if UB is None else UB
    if not full:
        # 全基は回復できない: 回復数を増やす列は今の完了時刻より遅く終わるかもしれないので, 上限を 1.3 倍にゆるめる
        # （このときは厳密ではない. 結果は optimal=False）
        fin = [v for v in [UB] if np.isfinite(v)]
        UB = (fin[0] if fin else 600.0) * 1.3
    classes = truck_classes(I)
    cols, truncated = enumerate_columns(I, UB, time_limit=time_limit * 0.6)
    cols = [c for c in cols if np.isfinite(c[2])]
    if reduce:
        cols = reduce_columns(I, cols)
    if log:
        log(dict(列=len(cols), 打ち切り=truncated, 秒=round(time.time() - t0, 1)))
    # 空の組（その車は使わない）
    cols = cols + [(ci, (), 0.0, False) for ci in range(len(classes))]

    def to_plan(chosen):
        plan = {t.tid: [] for t in I.trucks}
        free = {ci: [t.tid for t in g] for ci, g in enumerate(classes)}
        for i in chosen:
            ci, comb, m, _ = cols[i]
            if comb:
                plan[free[ci].pop(0)] = list(comb)
        return plan

    if not full:
        # 回復数を先に最大化（UB 以下の列の中で）
        ch = _milp_feasible(I, cols, classes, UB, J, maximize_cover=True, time_limit=max(1.0, time_limit - (time.time() - t0)))
        plan = to_plan(ch) if ch is not None else start
        e = I.evaluate(plan)
        better = (e["recovered"], -e["makespan"]) > (e0["recovered"], -e0["makespan"])
        return (plan if better else start), dict(optimal=False, makespan=I.evaluate(plan if better else start)["makespan"],
                                                 cols=len(cols), sec=round(time.time() - t0, 1), note="全基は回復できない")
    vals = sorted({c[2] for c in cols if c[1]})
    lo, hi = 0, len(vals) - 1
    best = None
    LB = I.lower_bound()
    while lo < hi and time.time() - t0 < time_limit:
        mid = (lo + hi) // 2
        if vals[mid] < LB - 1e-6:
            lo = mid + 1
            continue
        ch = _milp_feasible(I, cols, classes, vals[mid], J, time_limit=max(1.0, time_limit - (time.time() - t0)))
        if ch is not None:
            hi = mid
            best = ch
        else:
            lo = mid + 1
    if best is None or I.evaluate(to_plan(best))["makespan"] > vals[lo] + 1e-6:
        ch = _milp_feasible(I, cols, classes, vals[lo], J, time_limit=max(1.0, time_limit - (time.time() - t0)))
        if ch is not None:
            best = ch
    plan = to_plan(best) if best is not None else start
    e = I.evaluate(plan)
    if e["recovered"] < len(J) or e["makespan"] > e0["makespan"] + 1e-6:
        plan, e = start, e0
    done = time.time() - t0 < time_limit and not truncated
    return plan, dict(optimal=bool(done), makespan=round(e["makespan"], 3), cols=len(cols),
                      sec=round(time.time() - t0, 1), lower=round(LB, 3))


# ---------------------------------------------------------------------- 同じ列を QUBO で選ぶ（集合分割 QUBO）
def _slack_bits(n):
    """0..n を表す 2 進の重み（最後の桁で上限をちょうど n にそろえる）"""
    w, s = [], 0
    b = 1
    while s + b <= n:
        w.append(b); s += b; b *= 2
    if s < n:
        w.append(n - s)
    return w


def build_column_qubo(I, cols, classes, T, J, eps_total=0.3, per_truck=False):
    """完了時刻 ≤ T の列だけを変数にした集合分割 QUBO（MILP の判定問題と同じ制約）
        E = Σ_j (Σ_{c∋j} x_c − 1)²                                   … 各センサーをちょうど 1 回
          + Σ_b (Σ_{c∈b} x_c + Σ_i w_i s_{b,i} − 車の数_b)²          … 拠点ごとの車の数（s はスラック）
          + (Σ_{予備が要る c} x_c + Σ_i w_i s_i − 予備の数)²           … 予備バッテリー
          + ε Σ_c m_c x_c / Σ m                                         … 同点なら各車が早く終わる方
       E = ε の項だけ ⇔ T 以内に全センサーを回復する計画"""
    if per_truck:
        return _build_column_qubo_per_truck(I, cols, classes, T, J, eps_total)
    idx = [i for i, c in enumerate(cols) if c[1] and c[2] <= T + 1e-9]
    nX = len(idx)
    jpos = {j: r for r, j in enumerate(J)}
    cover = [[] for _ in J]
    for k, i in enumerate(idx):
        for f in cols[i][1]:
            for j in I.flights[f]["sensors"]:
                cover[jpos[j]].append(k)
    if any(not c for c in cover):
        return None
    groups = []                                   # (変数の並び, 係数, 右辺)
    var_n = nX
    for b, g in enumerate(classes):
        mem = [k for k, i in enumerate(idx) if cols[i][0] == b]
        if len(mem) == 0:
            continue
        w = _slack_bits(len(g))
        sl = list(range(var_n, var_n + len(w))); var_n += len(w)
        groups.append((mem + sl, [1.0] * len(mem) + [float(x) for x in w], float(len(g))))
    spm = [k for k, i in enumerate(idx) if cols[i][3]]
    if spm:
        w = _slack_bits(I.spares_left)
        sl = list(range(var_n, var_n + len(w))); var_n += len(w)
        groups.append((spm + sl, [1.0] * len(spm) + [float(x) for x in w], float(I.spares_left)))
    lin = np.zeros(var_n)
    Q = np.zeros((var_n, var_n))
    for mem in cover:                                         # (Σ x − 1)²
        for a in mem:
            lin[a] -= 1.0
        for x in range(len(mem)):
            for y in range(x + 1, len(mem)):
                Q[mem[x], mem[y]] += 2.0
    for mem, co, rhs in groups:                               # (Σ a_i z_i − rhs)²
        for x in range(len(mem)):
            lin[mem[x]] += co[x] * co[x] - 2.0 * rhs * co[x]
            for y in range(x + 1, len(mem)):
                a, b_ = min(mem[x], mem[y]), max(mem[x], mem[y])
                Q[a, b_] += 2.0 * co[x] * co[y]
    m = np.array([cols[i][2] for i in idx])
    lin[:nX] += eps_total * m / max(m.sum(), 1e-9)
    return dict(lin=lin, Q=Q, idx=idx, nX=nX, n=var_n)


def _build_column_qubo_per_truck(I, cols, classes, T, J, eps_total=0.3):
    """スラック変数を使わない形: 変数 x[c, t] = 車 t が組 c を行う（t は c の拠点の車）
        E = Σ_j (Σ_{c∋j, t} x − 1)²                    … 各センサーをちょうど 1 回
          + Σ_t Σ_{c<c'} x[c,t] x[c',t]                 … 1 台が選ぶ組は 1 つまで（2 次の罰金だけ）
          + Σ_{(c,t)<(c',t'), 予備が要る} x x            … 予備バッテリーが 1 個なら, 予備が要る組は 1 つまで
          + ε Σ m_c x[c,t]
       予備が 2 個以上のときは, 予備が要る組の数にスラックを使う（ここでは予備 ≤ 1 個以外は数の罰金に切り替え）"""
    idx = [i for i, c in enumerate(cols) if c[1] and c[2] <= T + 1e-9]
    var = []                                        # (列, 車の番号)
    for i in idx:
        for tr in classes[cols[i][0]]:
            var.append((i, tr.tid))
    n = len(var)
    jpos = {j: r for r, j in enumerate(J)}
    cover = [[] for _ in J]
    by_truck = {}
    spare = []
    for k, (i, tid) in enumerate(var):
        for f in cols[i][1]:
            for j in I.flights[f]["sensors"]:
                cover[jpos[j]].append(k)
        by_truck.setdefault(tid, []).append(k)
        if cols[i][3]:
            spare.append(k)
    if any(not c for c in cover):
        return None
    extra = []
    if spare and I.spares_left >= 1:
        w = _slack_bits(I.spares_left)
        extra = w if I.spares_left > 1 else []
    nn = n + len(extra)
    lin = np.zeros(nn)
    Q = np.zeros((nn, nn))
    for mem in cover:
        for a in mem:
            lin[a] -= 1.0
        for x in range(len(mem)):
            for y in range(x + 1, len(mem)):
                Q[mem[x], mem[y]] += 2.0
    for mem in by_truck.values():
        for x in range(len(mem)):
            for y in range(x + 1, len(mem)):
                Q[mem[x], mem[y]] += 1.0
    if spare:
        if I.spares_left == 0:
            for a in spare:
                lin[a] += 1.0
        elif I.spares_left == 1:
            for x in range(len(spare)):
                for y in range(x + 1, len(spare)):
                    Q[min(spare[x], spare[y]), max(spare[x], spare[y])] += 1.0
        else:
            mem = spare + list(range(n, nn))
            co = [1.0] * len(spare) + [float(v) for v in extra]
            rhs = float(I.spares_left)
            for x in range(len(mem)):
                lin[mem[x]] += co[x] * co[x] - 2.0 * rhs * co[x]
                for y in range(x + 1, len(mem)):
                    Q[min(mem[x], mem[y]), max(mem[x], mem[y])] += 2.0 * co[x] * co[y]
    m = np.array([cols[i][2] for i, _ in var])
    lin[:n] += eps_total * m / max(m.sum(), 1e-9)
    return dict(lin=lin, Q=Q, var=var, nX=n, n=nn, per_truck=True)


def solve_column_qubo(I, budget, seed=0, UB=None, start=None, cols=None, chunk=(16, 2000), log=None, reduce=False):
    """列の列挙（古典の前処理, MILP と共通）+ 集合分割 QUBO の二分探索（焼きなまし）.
    戻り値: plan, info"""
    from qubo_amplify import solve_inner
    t0 = time.time()
    t_end = t0 + budget
    J = list(I.recoverable)
    classes = truck_classes(I)
    if start is None:
        from equal_time import ils
        start = ils(I, min(2.0, budget * 0.2), seed)
    e0 = I.evaluate(start)
    UB = e0["makespan"] if UB is None else UB
    if cols is None:
        cols, truncated = enumerate_columns(I, UB, time_limit=budget * 0.5)
    if reduce:
        cols = reduce_columns(I, cols)
    t_enum = time.time() - t0
    vals = sorted({c[2] for c in cols if c[1]})
    LB = I.lower_bound()
    lo = int(np.searchsorted(vals, LB - 1e-6))
    hi = len(vals) - 1
    best, bms, it, hist, rate = None, np.inf, 0, [], None
    free0 = {ci: [t.tid for t in g] for ci, g in enumerate(classes)}

    def to_plan(chosen):
        plan = {t.tid: [] for t in I.trucks}
        free = {k: list(v) for k, v in free0.items()}
        for i in chosen:
            ci, comb, m, _ = cols[i]
            if not free[ci]:
                return None
            plan[free[ci].pop(0)] = list(comb)
        return plan

    while lo <= hi and time.time() < t_end:
        mid = (lo + hi) // 2
        T = vals[mid]
        mdl = build_column_qubo(I, cols, classes, T, J)
        found = None
        if mdl is not None:
            # 残り時間に収まるよう掃引回数を決める（1 回目の実測から 1 掃引あたりの時間を見積もる）
            nnz = max(1, int(np.count_nonzero(mdl["Q"])) + mdl["n"])
            left = max(0.05, t_end - time.time())
            sweeps = int(min(chunk[1], max(50, left / (rate * nnz * chunk[0])))) if rate else min(chunk[1], 200)
            ts = time.time()
            sols, _ = solve_inner(mdl["lin"], mdl["Q"], "neal", None, 1000, chunk[0], sweeps, (seed * 7919 + it) % (1 << 31))
            rate = (time.time() - ts) / (nnz * chunk[0] * sweeps)
            it += 1
            for s in sols:
                if mdl.get("per_truck"):
                    on = [mdl["var"][k] for k in np.nonzero(np.rint(s[:mdl["nX"]]))[0]]
                    p = {t.tid: [] for t in I.trucks}
                    bad = False
                    for i, tid in on:
                        if p[tid]:
                            bad = True
                        p[tid] = list(cols[i][1])
                    if bad:
                        continue
                    e = I.evaluate(p)
                    if e["feasible"] and e["recovered"] == len(J) and (found is None or e["makespan"] < found[1]):
                        found = (p, e["makespan"])
                    continue
                ch = [mdl["idx"][k] for k in np.nonzero(np.rint(s[:mdl["nX"]]))[0]]
                cnt = {}
                for i in ch:
                    for f in cols[i][1]:
                        for j in I.flights[f]["sensors"]:
                            cnt[j] = cnt.get(j, 0) + 1
                if any(cnt.get(j, 0) != 1 for j in J):
                    continue
                p = to_plan(ch)
                if p is None:
                    continue
                e = I.evaluate(p)
                if e["feasible"] and e["recovered"] == len(J) and (found is None or e["makespan"] < found[1]):
                    found = (p, e["makespan"])
        hist.append(dict(T=round(T, 1), 変数=None if mdl is None else mdl["n"], 判定="あり" if found else "見つからず"))
        if found and found[1] < bms:
            best, bms = found
        if found:
            hi = int(np.searchsorted(vals, found[1] - 1e-6)) - 1
        else:
            lo = mid + 1
    return best, dict(makespan=None if best is None else round(bms, 3), cols=len(cols), sec=round(time.time() - t0, 2),
                      enum_sec=round(t_enum, 2), iters=it, history=hist)
