"""
phase2/lns.py : 大近傍探索（LNS）. 計画の一部（数台の車）を壊して, その部分問題を解き直す

  同じ枠組みで, 部分問題の解き方だけを入れ替えて比べる（公平な比較のため）
    "qubo" : 二分探索の判定 QUBO（qubo_bisect.build_decision_qubo）を焼きなましで解く
    "milp" : 列挙 + 集合分割 MILP（solvers.solve_columns, 1 台 3 飛行までで厳密）
    "ils"  : 古典の反復局所探索（equal_time.ils）

  壊し方: 最も遅く終わる車（確率 0.7）か無作為な 1 台を選び, 残り k−1 台を「次に近い車」か「無作為な車」（半々）で足す.
          その k 台に割り当てたセンサーを, その k 台だけで解き直す（他の車はそのまま）.
  受け入れ: 車ごとの完了時刻を遅い順に並べたものが辞書式で良くなれば（最大値が同じでも 2 番目が縮めば）採用.
           部分問題の QUBO は小さい（数十〜数百変数）ので, 焼きなましでも最適に近い解が出やすい.
"""
import copy
import time

import numpy as np

import solvers as S
from qubo_bisect import build_decision_qubo, decode
from model import Instance


def sub_instance(I, tids, plan):
    """車 tids と, その車に割り当てたセンサーだけの部分問題（センサー番号・飛行の中身は元のまま）"""
    J = copy.copy(I)
    J.trucks = [t for t in I.trucks if t.tid in tids]
    sens = set()
    for t in tids:
        for f in plan.get(t, []):
            sens |= set(I.flights[f]["sensors"])
    J.recoverable = sorted(sens)
    J.unreachable = []
    fmap = [fi for fi, f in enumerate(I.flights) if set(f["sensors"]) <= sens]
    J.flights = [I.flights[fi] for fi in fmap]
    others = [t for t in I.trucks if t.tid not in tids]
    J.spares_left = I.spares_left - sum(1 for t in others if len(plan.get(t.tid, [])) > t.cap(False) and not t.spare)
    J._lb = None
    return J, fmap


def profile(I, ev, plan):
    """(回復数の符号反転, 実行不可, 車ごとの完了時刻を遅い順に)"""
    k = ev.key(plan)
    ms = sorted((ev.truck(t.tid, plan.get(t.tid, []))[0] for t in I.trucks), reverse=True)
    return (k[0], k[1]) + tuple(round(m, 6) for m in ms)


def repair_qubo(J, budget, seed, cur_ms, chunk=(8, 1000)):
    """部分問題を, 上限 T を「今の完了時刻」から下界へ向けて二分探索する判定 QUBO で解く"""
    from qubo_amplify import solve_inner
    t_end = time.time() + budget
    ev = S.Evaluator(J)
    lo, hi = J.lower_bound(), cur_ms
    best, bms = None, np.inf
    it = 0
    while time.time() < t_end and hi - lo > 0.5:
        T = (lo + hi) / 2
        m = build_decision_qubo(J, T)
        if m is None:
            lo = T
            continue
        sols, _ = solve_inner(m["lin"], m["Q"], "neal", None, 1000, chunk[0], chunk[1], (seed * 7919 + it) % (1 << 31))
        it += 1
        found = None
        for s in sols:
            p, exact = decode(J, m["var"], s)
            if not exact:
                continue
            e = ev.key(p)
            if e[1] == 0 and e[0] == -len(J.recoverable) and (found is None or e[2] < found[1]):
                found = (p, e[2])
        if found is not None and found[1] < bms:
            best, bms = found
        if found is not None and found[1] <= T + 1e-6:
            hi = found[1]
        else:
            lo = T          # 焼きなましが見つけられなかった（真に不可能とは限らない）
    return best


def max_flights_for(J, limit=200000):
    """列挙する組の数が limit 以下になる範囲で, 1 台あたりの飛行の上限をできるだけ大きくする"""
    from math import comb
    F = len(J.flights)
    k = 1
    while k < 9 and comb(F, k + 1) * len(J.trucks) <= limit:
        k += 1
    return k


def repair_milp(J, budget, seed, cur_ms):
    p, t, info = S.solve_columns(J, max_flights_for(J), max(0.5, budget))
    return p if info.get("status") == 0 else None


def repair_ils(J, budget, seed, cur_ms):
    from equal_time import ils
    return ils(J, budget, seed)


def repair_colqubo(J, budget, seed, cur_ms, start=None):
    """部分問題の列（完了時刻 ≤ 今の値）を列挙し, 集合分割 QUBO の二分探索で選ぶ"""
    from exact import solve_column_qubo
    p, info = solve_column_qubo(J, budget, seed, UB=cur_ms + 1e-6, start=start, chunk=(8, 1000))
    return p


def repair_colmilp(J, budget, seed, cur_ms, start=None):
    """同じ列を, 集合分割 MILP の二分探索で選ぶ（部分問題の厳密解）"""
    from exact import solve_exact
    p, info = solve_exact(J, UB=cur_ms + 1e-6, start=start, time_limit=budget)
    return p


REPAIRS = dict(qubo=repair_qubo, milp=repair_milp, ils=repair_ils, colqubo=repair_colqubo, colmilp=repair_colmilp)
STARTS = {"colqubo", "colmilp"}


def lns(I, budget, seed=0, repair="qubo", k_trucks=3, slice_sec=None, start=None, log=None):
    t_end = time.time() + budget
    rng = np.random.default_rng(seed)
    ev = S.Evaluator(I)
    if start is None:
        start = S.greedy(I, ev, deadline=time.time() + budget * 0.1)
        start = S.local_search(I, start, min(budget * 0.1, max(0.0, t_end - time.time())), ev)
    cur = {t.tid: list(start.get(t.tid, [])) for t in I.trucks}
    ckey = profile(I, ev, cur)
    tids = [t.tid for t in I.trucks]
    node_of = {t.tid: t.node for t in I.trucks}
    slice_sec = slice_sec or max(0.3, min(2.0, budget / 15))
    n_try = n_acc = 0
    while time.time() < t_end - 0.05:
        per = {t: ev.truck(t, cur[t])[0] for t in tids}
        if rng.random() < 0.7:
            c = max(tids, key=lambda t: per[t])
        else:
            c = tids[rng.integers(len(tids))]
        stops = [I.flights[f]["node"] for f in cur[c]] or [node_of[c]]
        # 近い車: その車の今の停車地点（なければ拠点）から c の停車地点までの走行時間
        def near(t):
            pts = [I.flights[f]["node"] for f in cur[t]] or [node_of[t]]
            return min(I.drive(a, b) if a != b else 0.0 for a in pts for b in stops) + rng.random() * 20
        others = sorted((t for t in tids if t != c), key=near)
        # 残りの k−1 台: 1 台ずつ, 半分の確率で「次に近い車」, 半分で「無作為な車」
        # （近い車だけだと, 遠い拠点で余っている車を使えない）
        group = [c]
        while len(group) < min(k_trucks, len(tids)):
            rest = [t for t in others if t not in group]
            group.append(rest[0] if rng.random() < 0.5 else rest[rng.integers(len(rest))])
        J, fmap = sub_instance(I, group, cur)
        if not J.recoverable:
            continue
        inv = {f: i for i, f in enumerate(fmap)}
        sub_cur = {t: [inv[f] for f in cur[t]] for t in group}
        cur_ms = max(per[t] for t in group)
        args = (J, min(slice_sec, max(0.05, t_end - time.time())), int(rng.integers(1 << 30)), cur_ms)
        sp = REPAIRS[repair](*args, start=sub_cur) if repair in STARTS else REPAIRS[repair](*args)
        n_try += 1
        if sp is None:
            continue
        new = dict(cur)
        for t in group:
            new[t] = [fmap[f] for f in sp.get(t, [])]
        nk = profile(I, ev, new)
        if nk < ckey:
            cur, ckey = new, nk
            n_acc += 1
            if log:
                log(dict(t=round(budget - (t_end - time.time()), 1), 完了=round(nk[2], 1)))
    return cur
