"""
phase2/real_batch.py : 実データの道路網で, サンプルと同等〜より複雑な災害を多数作り, 古典と QUBO を同じ計算時間で比べる

  災害の系統（real.FAMILIES）: A_同等 / B_大地震 / C_複合（震源 2・車が減る・予備 0〜2）/ D_広域 / E_連続大地震
  各系統 10 問 + 配布サンプル

  1. 基準: 厳密解法（exact.solve_exact. 反復局所探索 10 秒の解を上限に, 列挙 + MILP の二分探索, 最大 300 秒）
           と 枠割当の下界（real.slot_lower_bound）
  2. 同じ計算時間（5 秒は乱数の種 2 つ, 30 秒は 1 つ）で 7 手法
       古典: 貪欲法 + 局所探索 / 反復局所探索 / 厳密解法（時間内）/ LNS（予算の 30% の反復局所探索から, 部分問題を列の MILP で）
       QUBO: 時間枠の判定 QUBO 二分探索（生の解）/ 列の集合分割 QUBO（列の列挙は古典）/ LNS（同じ初期解から, 部分問題を列の QUBO で）

  python real_batch.py ref       → results/real_batch_ref.json
  python real_batch.py equal     → results/real_batch_equal.json   （途中から再開できる）
  python real_batch.py stats     → results/real_batch_stats.json
"""
import json
import os
import sys
import time
from multiprocessing import Pool

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "placement"))
RES = os.path.join(HERE, "..", "results")

N_PER = 10
BUDGETS = (5.0, 30.0)
SEEDS = (0, 1)


def scenarios():
    from real import RealWorld, FAMILIES, make_real_scenario, load_sample
    rw = RealWorld()
    out = [("サンプル", load_sample())]
    for fam in FAMILIES:
        for sd in range(N_PER):
            out.append((fam, make_real_scenario(rw, fam, sd)))
    return out


_RW = None


def _inst(sc):
    global _RW
    from real import RealWorld, RealInstance
    if _RW is None:
        _RW = RealWorld()
    return RealInstance(_RW, sc)


def m_greedy(I, budget, seed):
    import solvers as S
    return S.solve_greedy_ls(I, min(budget, 1.0))[0]


def m_ils(I, budget, seed):
    from equal_time import ils
    return ils(I, budget, seed)


def m_exact(I, budget, seed):
    from equal_time import ils
    from exact import solve_exact
    t0 = time.time()
    st = ils(I, min(2.0, budget * 0.2), seed)
    p, info = solve_exact(I, start=st, time_limit=max(0.5, budget - (time.time() - t0)))
    return p


def m_lns_milp(I, budget, seed):
    from lns import lns
    from equal_time import ils
    t0 = time.time()
    st = ils(I, budget * 0.3, seed)                                    # 予算の 30% で初期解（QUBO 版と同じ）
    return lns(I, max(0.1, budget - (time.time() - t0)), seed, "colmilp", k_trucks=4, start=st)


def m_qubo_slot(I, budget, seed):
    from equal_time import qubo_bisect_timed
    return qubo_bisect_timed(I, budget, seed)


def m_qubo_col(I, budget, seed):
    import solvers as S
    from exact import solve_column_qubo
    t0 = time.time()
    st = S.local_search(I, S.greedy(I), min(1.0, budget * 0.1))       # 上限 UB は貪欲法 + 局所探索の解から
    p, info = solve_column_qubo(I, max(0.1, budget - (time.time() - t0)), seed, start=st)
    return p


def m_lns_qubo(I, budget, seed):
    from lns import lns
    from equal_time import ils
    t0 = time.time()
    st = ils(I, budget * 0.3, seed)
    return lns(I, max(0.1, budget - (time.time() - t0)), seed, "colqubo", k_trucks=4, start=st)


METHODS = {
    "古典: 貪欲法 + 局所探索": m_greedy,
    "古典: 反復局所探索": m_ils,
    "古典: 厳密解法（列挙 + MILP, 時間内）": m_exact,
    "古典: LNS（部分問題を列の MILP）": m_lns_milp,
    "QUBO: 時間枠の判定 QUBO（生の解）": m_qubo_slot,
    "QUBO: 列の集合分割 QUBO（生の解, 列挙は古典）": m_qubo_col,
    "QUBO: LNS（部分問題を列の QUBO）": m_lns_qubo,
}
DETERMINISTIC = {"古典: 貪欲法 + 局所探索"}


def _ref_task(arg):
    name, k, sc = arg
    from real import slot_lower_bound
    from equal_time import ils
    from exact import solve_exact
    I = _inst(sc)
    t0 = time.time()
    lb = slot_lower_bound(I) if I.recoverable else 0.0
    st = ils(I, 10.0, 0)
    p, info = solve_exact(I, start=st, time_limit=300.0)
    e = I.evaluate(p)
    return dict(問題=f"{name}_{k}", 系統=name, 通信断=len(I.targets), 回復可能=len(I.recoverable), 対応不能=len(I.unreachable),
                通行止め=len(sc["closed_segments"]), 車=len(I.trucks), 予備=I.spares_left, 飛行=len(I.flights),
                下界=round(lb, 3), 最良=round(e["makespan"], 3), 回復数=e["recovered"], 最適=info.get("optimal", False),
                列=info.get("cols"), 秒=round(time.time() - t0, 1), plan={str(a): b for a, b in p.items()})


def _equal_task(arg):
    pid, sc, m, B, sd = arg
    I = _inst(sc)
    t0 = time.time()
    try:
        p = METHODS[m](I, B, sd)
        err = None
    except Exception as ex:          # 1 問の失敗で全体を止めない（記録して続ける）
        p, err = None, repr(ex)[:200]
    sec = time.time() - t0
    if p is None:
        return dict(問題=pid, 手法=m, 予算_秒=B, 種=sd, 回復数=None, 完了時刻=None, 実時間_秒=round(sec, 2), 誤り=err)
    e = I.evaluate(p)
    return dict(問題=pid, 手法=m, 予算_秒=B, 種=sd, 回復数=e["recovered"], 回復可能=e["recoverable"],
                完了時刻=round(e["makespan"], 3) if e["feasible"] else None, 実行可能=e["feasible"],
                実時間_秒=round(sec, 2), 誤り=err)


def _load(f):
    return json.load(open(f)) if os.path.exists(f) else []


def _save(f, obj):
    tmp = f + ".tmp"
    json.dump(obj, open(tmp, "w"), ensure_ascii=False, indent=1)
    os.replace(tmp, f)


def run_ref(procs=1):
    f = os.path.join(RES, "real_batch_ref.json")
    done = {r["問題"] for r in _load(f)}
    cnt = {}
    tasks = []
    for name, sc in scenarios():
        k = cnt.get(name, 0); cnt[name] = k + 1
        if f"{name}_{k}" not in done:
            tasks.append((name, k, sc))
    out = _load(f)
    with Pool(procs) as pool:
        for r in pool.imap_unordered(_ref_task, tasks):
            out.append(r)
            _save(f, out)
            print(r["問題"], r["回復可能"], r["下界"], r["最良"], r["最適"], r["秒"], flush=True)


def run_equal(procs=3):
    f = os.path.join(RES, "real_batch_equal.json")
    out = _load(f)
    done = {(r["問題"], r["手法"], r["予算_秒"], r["種"]) for r in out}
    cnt = {}
    tasks = []
    for name, sc in scenarios():
        k = cnt.get(name, 0); cnt[name] = k + 1
        pid = f"{name}_{k}"
        for B in BUDGETS:
            for m in METHODS:
                # 30 秒の予算は乱数の種 1 つだけ（計算時間の都合. 5 秒は 2 つ）
                for sd in (SEEDS[:1] if m in DETERMINISTIC or B >= 30 else SEEDS):
                    if (pid, m, B, sd) not in done:
                        tasks.append((pid, sc, m, B, sd))
    print(len(tasks), "件", flush=True)
    with Pool(procs) as pool:
        for i, r in enumerate(pool.imap_unordered(_equal_task, tasks)):
            out.append(r)
            if i % 10 == 0 or i == len(tasks) - 1:
                _save(f, out)
            print(i, r["問題"], r["手法"][:12], r["予算_秒"], r["完了時刻"], r["実時間_秒"], r.get("誤り") or "", flush=True)
    _save(f, out)


def stats():
    from batch import boot_ci, sign_test
    ref = {r["問題"]: r for r in _load(os.path.join(RES, "real_batch_ref.json"))}
    rec = _load(os.path.join(RES, "real_batch_equal.json"))
    # 問題ごとの最良: 基準（厳密解法 300 秒）と, 全手法・全予算で見つかった最良の小さい方
    best = {p: r["最良"] for p, r in ref.items() if r["回復数"] == r["回復可能"]}
    for r in rec:
        if r["完了時刻"] is not None and r["回復数"] == r["回復可能"]:
            best[r["問題"]] = min(best.get(r["問題"], np.inf), r["完了時刻"])
    fams = sorted({r["系統"] for r in ref.values()})
    ref_name = "古典: 反復局所探索"
    out = []
    for B in BUDGETS:
        for fam in fams + ["全体"]:
            sub = [r for r in rec if r["予算_秒"] == B and (fam == "全体" or ref.get(r["問題"], {}).get("系統") == fam)]
            for m in METHODS:
                rs = [r for r in sub if r["手法"] == m]
                if not rs:
                    continue
                ok = [r for r in rs if r["完了時刻"] is not None and r["回復数"] == r["回復可能"] and r["問題"] in best]
                gaps = [(r["完了時刻"] - best[r["問題"]]) / best[r["問題"]] * 100 for r in ok]
                lbg = [(r["完了時刻"] - ref[r["問題"]]["下界"]) / ref[r["問題"]]["下界"] * 100 for r in ok
                       if ref.get(r["問題"], {}).get("下界", 0) > 0]
                w = l = t = 0
                if m != ref_name:
                    for r in rs:
                        c = [q for q in sub if q["手法"] == ref_name and q["問題"] == r["問題"] and q["種"] == r["種"]]
                        if not c:
                            c = [q for q in sub if q["手法"] == ref_name and q["問題"] == r["問題"]]
                        if not c:
                            continue
                        a = (-(r["回復数"] or 0), r["完了時刻"] if r["完了時刻"] is not None else np.inf)
                        b = (-(c[0]["回復数"] or 0), c[0]["完了時刻"] if c[0]["完了時刻"] is not None else np.inf)
                        if a[0] < b[0] or (a[0] == b[0] and a[1] < b[1] - 0.05): w += 1
                        elif a[0] > b[0] or (a[0] == b[0] and a[1] > b[1] + 0.05): l += 1
                        else: t += 1
                out.append(dict(予算_秒=B, 系統=fam, 手法=m, 試行=len(rs),
                                全基回復の割合=round(len(ok) / len(rs), 3),
                                最良との差_平均=None if not gaps else round(float(np.mean(gaps)), 2),
                                最良との差_95CI=boot_ci(gaps),
                                最良と同じ割合=None if not gaps else round(float(np.mean([g < 0.05 for g in gaps])), 3),
                                下界との差_平均=None if not lbg else round(float(np.mean(lbg)), 2),
                                実時間_最大=round(max(r["実時間_秒"] for r in rs), 1),
                                古典ILSに勝ち=w, 負け=l, 引き分け=t, 符号検定p=sign_test(w, l) if m != ref_name else None))
    refsum = []
    for fam in fams + ["全体"]:
        rs = [r for r in ref.values() if fam == "全体" or r["系統"] == fam]
        refsum.append(dict(系統=fam, 問題=len(rs), 通信断_平均=round(float(np.mean([r["通信断"] for r in rs])), 1),
                           回復可能_平均=round(float(np.mean([r["回復可能"] for r in rs])), 1),
                           対応不能_平均=round(float(np.mean([r["対応不能"] for r in rs])), 1),
                           通行止め_平均=round(float(np.mean([r["通行止め"] for r in rs])), 1),
                           最適を証明=sum(bool(r["最適"]) for r in rs),
                           下界との差_平均=round(float(np.mean([(r["最良"] - r["下界"]) / r["下界"] * 100 for r in rs if r["下界"] > 0])), 2),
                           厳密解法の時間_中央値=round(float(np.median([r["秒"] for r in rs])), 1)))
    _save(os.path.join(RES, "real_batch_stats.json"), dict(reference=refsum, equal_time=out))
    for r in refsum:
        print(r)
    for r in out:
        if r["系統"] == "全体":
            print(r)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "stats"
    dict(ref=run_ref, equal=run_equal, stats=stats)[cmd]()
