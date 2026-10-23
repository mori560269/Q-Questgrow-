"""
phase2/solvers.py : Phase 2 の計画を作る 3 つの方法（どれも model.Instance.evaluate で同じように採点する）

  共通の決定変数  y[f,t] = 飛行 f を車 t が行う (0/1)
  目的（辞書式）  ① 回復できるセンサー数を最大  ② 最後の回復時刻（メイクスパン）を最小

  (A) 貪欲法 + 局所探索（古典）
        回復時刻の増え方が小さい (飛行, 車) を順に足す → 飛行の付け替え・交換・統合・分割で改善
  (B) MILP（古典, HiGHS）
        Σ_{f∋j,t} y = 1（各センサーをちょうど 1 回）, 車ごとの飛行回数 ≤ 5（予備で +4）
        D_t ≥ 最も遠い離陸地点までの走行時間, T ≥ D_t + Σ_f y (飛行時間 + 充電 30 分) − 30
        min T   （停車順を無視した近似. 結果は厳密に評価し直す）
  (C) QUBO（Amplify で定式化, neal または Amplify AE で解く）
        E = A Σ_j (Σ_{f∋j,t} y − 1)²             … 各センサーをちょうど 1 回（等式なのでスラック不要）
          + B Σ_t ( Σ_f c_{f,t} y_{f,t} )²         … 車ごとの負荷の 2 乗和（最大値の最小化を 2 次で近似）
        c_{f,t} = 飛行時間 + 充電 30 分 + λ × 車 t から離陸地点までの走行時間
        「最大値の最小化」は QUBO ではスラックが要るので, 負荷の 2 乗和で置き換えた（負荷をならす）
"""
import os
import sys
import time
import numpy as np
from scipy.optimize import milp, LinearConstraint, Bounds
import scipy.sparse as sp

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "placement"))

from model import CHARGE_MIN


def _key(ev):
    return (-ev["recovered"], 0 if ev["feasible"] else 1, round(ev["makespan"], 6),
            round(sum(p["makespan"] for p in ev["per_truck"].values()), 6))


class Evaluator:
    """車ごとの計算結果をキャッシュして, 局所探索を速くする"""

    def __init__(self, inst, mode="makespan"):
        self.I = inst
        self.cache = {}
        self.byid = {t.tid: t for t in inst.trucks}
        self.mode = mode          # "makespan": 最後の回復時刻を最小 / "sum": 回復時刻の合計を最小（早く回復）

    def truck(self, tid, fids):
        k = (tid, tuple(sorted(fids)))
        if k not in self.cache:
            tr = self.byid[tid]
            self.cache[k] = self.I.truck_schedule(tr, list(fids), len(fids) > tr.cap(False))
        return self.cache[k]

    def key(self, plan):
        I = self.I
        rec, ms_sum, spare_need, over = {}, 0.0, 0, False
        for tr in I.trucks:
            f = plan.get(tr.tid, [])
            if len(f) > tr.cap(False) and not tr.spare:
                spare_need += 1
            if len(f) > tr.cap(True):
                over = True
            m, r, _ = self.truck(tr.tid, f)
            ms_sum += m
            for j, t in r.items():
                rec[j] = min(rec.get(j, np.inf), t)
        feas = (spare_need <= I.spares_left) and not over
        ms = max(rec.values(), default=0.0)
        if self.mode == "sum":
            return (-len(rec), 0 if feas else 1, round(sum(rec.values()), 6), round(ms, 6))
        return (-len(rec), 0 if feas else 1, round(ms, 6), round(ms_sum, 6))


def _covered(I, plan):
    s = set()
    for fids in plan.values():
        for f in fids:
            s |= set(I.flights[f]["sensors"])
    return s


# ---------------------------------------------------------------- (A) 貪欲法
def greedy(I, ev=None, deadline=None):
    """deadline (time.time() の値) を過ぎたら, その時点までの計画を返す（全部は回復しないこともある）"""
    ev = ev or Evaluator(I)
    plan = {t.tid: [] for t in I.trucks}
    todo = set(I.recoverable)
    while todo:
        if deadline is not None and time.time() > deadline:
            break
        best = None
        cur = ev.key(plan)
        for fi, f in enumerate(I.flights):
            S = set(f["sensors"])
            if not S <= todo:
                continue
            for tr in I.trucks:
                cand = plan[tr.tid] + [fi]
                if len(cand) > tr.cap(True):
                    continue
                p2 = dict(plan); p2[tr.tid] = cand
                k = ev.key(p2)
                if k[1] and not cur[1]:
                    continue
                m = ev.truck(tr.tid, cand)[0]
                score = (k[2], m / len(S))
                if best is None or score < best[0]:
                    best = (score, tr.tid, fi)
        if best is None:
            break
        plan[best[1]].append(best[2])
        todo -= set(I.flights[best[2]]["sensors"])
    return plan


def local_search(I, plan, time_limit=10.0, ev=None):
    ev = ev or Evaluator(I)
    plan = {k: list(v) for k, v in plan.items()}
    best = ev.key(plan)
    t0 = time.time()
    by_set = {}
    for fi, f in enumerate(I.flights):
        by_set.setdefault(f["sensors"], []).append(fi)
    tids = [t.tid for t in I.trucks]
    improved = True
    while improved and time.time() - t0 < time_limit:
        improved = False
        moves = []
        for a in tids:
            for i, f in enumerate(plan[a]):
                for b in tids:                                   # 付け替え
                    if b != a:
                        moves.append(("move", a, i, b))
                for alt in by_set[I.flights[f]["sensors"]]:      # 別の離陸地点に変える
                    if alt != f:
                        moves.append(("alt", a, i, alt))
                if len(I.flights[f]["sensors"]) > 1:              # 分割
                    moves.append(("split", a, i))
        for a in tids:                                           # 交換
            for b in tids:
                if a < b:
                    for i in range(len(plan[a])):
                        for j in range(len(plan[b])):
                            moves.append(("swap", a, i, b, j))
        flat = [(a, i) for a in tids for i in range(len(plan[a]))]
        for x in range(len(flat)):                               # 統合
            for y in range(x + 1, len(flat)):
                moves.append(("merge", flat[x], flat[y]))
        for mv in moves:
            if time.time() - t0 > time_limit:
                break
            p2 = {k: list(v) for k, v in plan.items()}
            try:
                if mv[0] == "move":
                    _, a, i, b = mv; p2[b].append(p2[a].pop(i))
                elif mv[0] == "alt":
                    _, a, i, alt = mv; p2[a][i] = alt
                elif mv[0] == "swap":
                    _, a, i, b, j = mv; p2[a][i], p2[b][j] = p2[b][j], p2[a][i]
                elif mv[0] == "merge":
                    (a, i), (b, j) = mv[1], mv[2]
                    U = tuple(sorted(set(I.flights[p2[a][i]]["sensors"]) | set(I.flights[p2[b][j]]["sensors"])))
                    if U not in by_set:
                        continue
                    fa, fb = p2[a][i], p2[b][j]
                    p2[a].remove(fa); p2[b].remove(fb)
                    alts = by_set[U]
                    cands = []
                    for t in tids:
                        for alt in alts:
                            p3 = {k: list(v) for k, v in p2.items()}; p3[t].append(alt)
                            cands.append((ev.key(p3), p3))
                    p2 = min(cands, key=lambda c: c[0])[1]
                elif mv[0] == "split":
                    _, a, i = mv
                    f = p2[a].pop(i)
                    for j in I.flights[f]["sensors"]:
                        singles = by_set.get((j,), [])
                        if not singles:
                            raise ValueError
                        cands = []
                        for t in tids:
                            for alt in singles:
                                p3 = {k: list(v) for k, v in p2.items()}; p3[t].append(alt)
                                cands.append((ev.key(p3), p3))
                        p2 = min(cands, key=lambda c: c[0])[1]
            except (ValueError, IndexError):
                continue
            k = ev.key(p2)
            if k < best:
                plan, best, improved = p2, k, True
                break
    return plan


def solve_greedy_ls(I, time_limit=10.0, mode="makespan"):
    t = time.time()
    ev = Evaluator(I, mode)
    p = greedy(I, ev)
    p = local_search(I, p, time_limit, ev)
    return p, time.time() - t


# ---------------------------------------------------------------- (B) MILP
def solve_milp(I, time_limit=60.0):
    t0 = time.time()
    F, T = len(I.flights), len(I.trucks)
    if F == 0:
        return {t.tid: [] for t in I.trucks}, 0.0, dict(status=-1)
    nY = F * T
    iz, iD, iT = nY, nY + T, nY + 2 * T
    n = iT + 1
    c = np.zeros(n); c[iT] = 1.0
    rows = []
    # 各センサーをちょうど 1 回
    for j in I.recoverable:
        r = np.zeros(n)
        for fi, f in enumerate(I.flights):
            if j in f["sensors"]:
                r[fi * T:(fi + 1) * T] = 1
        rows.append((r, 1, 1))
    for ti, tr in enumerate(I.trucks):
        r = np.zeros(n)
        r[[fi * T + ti for fi in range(F)]] = 1
        if not tr.spare:
            r[iz + ti] = -4
        rows.append((r, -np.inf, tr.cap(False) if not tr.spare else tr.cap(True)))
        for fi, f in enumerate(I.flights):                   # D_t ≥ 走行時間 × y
            d = I.drive_from[tr.node][f["node"]]
            if not np.isfinite(d):                                  # 行けない組み合わせは y = 0
                r = np.zeros(n); r[fi * T + ti] = 1; rows.append((r, 0, 0)); continue
            r = np.zeros(n); r[iD + ti] = 1; r[fi * T + ti] = -(d + tr.t0)
            rows.append((r, 0, np.inf))
        r = np.zeros(n); r[iT] = 1; r[iD + ti] = -1                # T ≥ D_t + Σ y (dur + 30) − 30
        for fi, f in enumerate(I.flights):
            r[fi * T + ti] = -(f["dur"] + CHARGE_MIN)
        rows.append((r, -CHARGE_MIN, np.inf))
    r = np.zeros(n); r[iz:iz + T] = 1
    rows.append((r, -np.inf, I.spares_left))
    A = sp.csr_matrix(np.array([x[0] for x in rows]))
    lo = np.array([x[1] for x in rows], float); hi = np.array([x[2] for x in rows], float)
    integ = np.r_[np.ones(nY + T), np.zeros(T + 1)]
    ub = np.r_[np.ones(nY + T), np.full(T + 1, np.inf)]
    res = milp(c, constraints=LinearConstraint(A, lo, hi), integrality=integ, bounds=Bounds(0, ub),
               options=dict(time_limit=time_limit, disp=False))
    plan = {t.tid: [] for t in I.trucks}
    if res.x is not None:
        y = np.rint(res.x[:nY]).reshape(F, T)
        for fi, ti in zip(*np.nonzero(y)):
            plan[I.trucks[ti].tid].append(int(fi))
    return plan, time.time() - t0, dict(status=int(res.status), proxy_T=None if res.x is None else float(res.x[iT]))


# ---------------------------------------------------------------- (B') 列挙 + MILP（古典, ほぼ厳密）
def solve_columns(I, max_flights=3, time_limit=120.0):
    """車ごとに「行う飛行の組（最大 max_flights 個, センサーが重ならない）」を列挙して, その組の厳密な完了時刻を計算.
    各車から組を 1 つずつ選び, 全センサーをちょうど 1 回覆う中で, 最大の完了時刻を最小化する (集合分割 MILP).
    1 台の飛行が max_flights 個以下という範囲では厳密な最適解."""
    t0 = time.time()
    F = len(I.flights)
    ev = Evaluator(I)
    cols = []           # (truck index, flights, makespan)
    sets = [set(f["sensors"]) for f in I.flights]
    import itertools
    for ti, tr in enumerate(I.trucks):
        cols.append((ti, (), 0.0))
        for k in range(1, max_flights + 1):
            if k > tr.cap(True):
                break
            for comb in itertools.combinations(range(F), k):
                u = set()
                ok = True
                for f in comb:
                    if sets[f] & u:
                        ok = False; break
                    u |= sets[f]
                if not ok:
                    continue
                m = ev.truck(tr.tid, list(comb))[0]
                cols.append((ti, comb, m))
            if time.time() - t0 > time_limit / 2:
                break
    nC = len(cols)
    n = nC + 1
    c = np.zeros(n); c[-1] = 1.0
    A_rows, lo, hi = [], [], []
    rows_s = {j: np.zeros(n) for j in I.recoverable}
    rows_t = [np.zeros(n) for _ in I.trucks]
    spare_row = np.zeros(n)
    ms_rows = []
    for ci, (ti, comb, m) in enumerate(cols):
        for f in comb:
            for j in I.flights[f]["sensors"]:
                rows_s[j][ci] = 1
        rows_t[ti][ci] = 1
        if len(comb) > I.trucks[ti].cap(False) and not I.trucks[ti].spare:
            spare_row[ci] = 1
    for j in I.recoverable:
        A_rows.append(rows_s[j]); lo.append(1); hi.append(1)
    for r in rows_t:
        A_rows.append(r); lo.append(1); hi.append(1)
    A_rows.append(spare_row); lo.append(-np.inf); hi.append(I.spares_left)
    # 各車はちょうど 1 つの組を選ぶので, T ≥ Σ_c (その車の組の完了時刻) x_c で最大値を表せる
    for ti in range(len(I.trucks)):
        r = np.zeros(n); r[-1] = 1
        for ci, (tj, _, m) in enumerate(cols):
            if tj == ti:
                r[ci] = -m
        A_rows.append(r); lo.append(0); hi.append(np.inf)
    A = sp.csr_matrix(np.array(A_rows))
    integ = np.r_[np.ones(nC), 0]
    ub = np.r_[np.ones(nC), np.inf]
    res = milp(c, constraints=LinearConstraint(A, lo, hi), integrality=integ, bounds=Bounds(0, ub),
               options=dict(time_limit=max(0.1, time_limit - (time.time() - t0)), disp=False))
    plan = {t.tid: [] for t in I.trucks}
    if res.x is not None:
        for ci in np.nonzero(np.rint(res.x[:nC]))[0]:
            ti, comb, _ = cols[ci]
            plan[I.trucks[ti].tid] = list(comb)
    return plan, time.time() - t0, dict(status=int(res.status), columns=nC,
                                         gap=float(getattr(res, "mip_gap", np.nan) or 0.0))


# ---------------------------------------------------------------- (C) QUBO
def build_qubo(I, lam=0.5):
    F, T = len(I.flights), len(I.trucks)
    n = F * T
    cft = np.zeros((F, T))
    for fi, f in enumerate(I.flights):
        for ti, tr in enumerate(I.trucks):
            d = I.drive_from[tr.node][f["node"]]
            cft[fi, ti] = f["dur"] + CHARGE_MIN + lam * ((d if np.isfinite(d) else 1e3) + max(0.0, tr.ready - tr.t0))
    base = np.array([tr.t0 - min(t.t0 for t in I.trucks) for tr in I.trucks])
    # 重み: 1 つの飛行を外して得をする量より, 被覆の罰金が必ず大きくなるように
    est_load = cft.min(1).sum() / T + base.max()
    B = 1.0
    A = 2.0 * B * (2 * (est_load + cft.max()) * cft.max() + cft.max() ** 2)
    lin = np.zeros(n)
    Q = np.zeros((n, n))
    idx = lambda fi, ti: fi * T + ti
    for j in I.recoverable:
        mem = [idx(fi, ti) for fi, f in enumerate(I.flights) if j in f["sensors"] for ti in range(T)]
        for a in mem:
            lin[a] += -A
        for x in range(len(mem)):
            for y in range(x + 1, len(mem)):
                Q[min(mem[x], mem[y]), max(mem[x], mem[y])] += 2 * A
    for fi, f in enumerate(I.flights):                 # 車がその離陸地点へ行けない組み合わせは選ばせない
        for ti, tr in enumerate(I.trucks):
            if not np.isfinite(I.drive_from[tr.node][f["node"]]):
                lin[idx(fi, ti)] += 10 * A
    for ti in range(T):
        ids = [idx(fi, ti) for fi in range(F)]
        cs = cft[:, ti]
        for a, ca in zip(ids, cs):
            lin[a] += B * (ca ** 2 + 2 * base[ti] * ca)
        for x in range(F):
            for y in range(x + 1, F):
                Q[ids[x], ids[y]] += 2 * B * cs[x] * cs[y]
    return lin, Q, dict(A=A, B=B, n=n, nnz=int((Q != 0).sum() + (lin != 0).sum()))


def repair(I, plan, ev=None):
    """各センサーをちょうど 1 回にそろえる: 重複した飛行を外し, 足りないセンサーは貪欲法で足す"""
    ev = ev or Evaluator(I)
    plan = {k: list(v) for k, v in plan.items()}
    seen = set()
    allf = sorted([(a, f) for a in plan for f in plan[a]], key=lambda x: -len(I.flights[x[1]]["sensors"]))
    keep = {a: [] for a in plan}
    for a, f in allf:
        S = set(I.flights[f]["sensors"])
        if S & seen:
            continue
        keep[a].append(f); seen |= S
    todo = set(I.recoverable) - seen
    by_set = {}
    for fi, f in enumerate(I.flights):
        by_set.setdefault(f["sensors"], []).append(fi)
    for j in sorted(todo):
        cands = []
        for fi in by_set.get((j,), []):
            for tr in I.trucks:
                p3 = {k: list(v) for k, v in keep.items()}; p3[tr.tid].append(fi)
                cands.append((ev.key(p3), p3))
        if cands:
            keep = min(cands, key=lambda c: c[0])[1]
    return keep


def solve_qubo(I, backend="neal", token=None, num_reads=20, num_sweeps=2000, time_limit_ms=2000, seed=0, lam=0.5):
    from qubo_amplify import solve_inner
    t0 = time.time()
    F, T = len(I.flights), len(I.trucks)
    if F == 0:
        return {t.tid: [] for t in I.trucks}, 0.0, {}
    lin, Q, info = build_qubo(I, lam)
    sols, timed_out = solve_inner(lin, Q, backend, token, time_limit_ms, num_reads, num_sweeps, seed)
    ev = Evaluator(I)
    best = None
    for s in sols[:num_reads]:
        y = np.rint(s).reshape(F, T)
        plan = {t.tid: [] for t in I.trucks}
        for fi, ti in zip(*np.nonzero(y)):
            plan[I.trucks[ti].tid].append(int(fi))
        cnt = {}
        for fids in plan.values():
            for f in fids:
                for j in I.flights[f]["sensors"]:
                    cnt[j] = cnt.get(j, 0) + 1
        exact = all(cnt.get(j, 0) == 1 for j in I.recoverable)
        k = (0 if exact else 1,) + ev.key(plan)
        if best is None or k < best[0]:
            best = (k, plan, exact)
    info.update(raw_exact_cover=best[2], ae_timed_out=timed_out)
    return best[1], time.time() - t0, info
