"""
phase2/real_alloc.py : 8 台のドック搭載車を 3 拠点にどう分けておくと, 災害時の回復が早いか（平常時の計画）

  各拠点に 1 台以上, 合計 8 台の分け方（21 通り）すべてについて, 災害（配布サンプル + A_同等 10 + B_大地震 10）を
  厳密解法（反復局所探索 3 秒の解を上限に, 列挙 + MILP, 最大 60 秒）で解き, 完了時刻の平均・最悪を比べる.
  災害は分け方によらず共通.

  python real_alloc.py   → results/real_alloc.json
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

FAMS = ("A_同等", "B_大地震")
N_PER = 10


def allocations(total=8, n=3):
    return [(a, b, total - a - b) for a in range(1, total) for b in range(1, total - a) if total - a - b >= 1]


def _scen():
    from real import RealWorld, make_real_scenario, load_sample
    rw = RealWorld()
    out = [("サンプル_0", load_sample())]
    for f in FAMS:
        for sd in range(N_PER):
            out.append((f"{f}_{sd}", make_real_scenario(rw, f, sd)))
    return out


_RW = None


def _task(arg):
    global _RW
    alloc, pid, sc = arg
    from real import RealWorld, RealInstance
    from equal_time import ils
    from exact import solve_exact
    if _RW is None:
        _RW = RealWorld()
    sc = json.loads(json.dumps(sc))
    for b, k in zip(sc["drone_bases"], alloc):
        b["num_vehicles"] = k
    I = RealInstance(_RW, sc)
    t0 = time.time()
    st = ils(I, 3.0, 0)
    p, info = solve_exact(I, start=st, time_limit=60.0)
    e = I.evaluate(p)
    rt = list(e["rec_time"].values())
    return dict(配分=list(alloc), 問題=pid, 回復=e["recovered"], 回復可能=len(I.recoverable), 完了時刻=round(e["makespan"], 2),
                平均回復時刻=round(float(np.mean(rt)), 2) if rt else 0.0, 最適=info.get("optimal", False),
                秒=round(time.time() - t0, 1))


def main(procs=4):
    f = os.path.join(RES, "real_alloc.json")
    out = json.load(open(f)) if os.path.exists(f) else []
    done = {(tuple(r["配分"]), r["問題"]) for r in out}
    tasks = [(a, pid, sc) for a in allocations() for pid, sc in _scen() if (a, pid) not in done]
    with Pool(procs) as pool:
        for i, r in enumerate(pool.imap_unordered(_task, tasks)):
            out.append(r)
            if i % 20 == 0:
                json.dump(out, open(f, "w"), ensure_ascii=False, indent=1)
            print(i, r["配分"], r["問題"], r["完了時刻"], r["最適"], r["秒"], flush=True)
    json.dump(out, open(f, "w"), ensure_ascii=False, indent=1)
    summary()


def summary():
    rec = json.load(open(os.path.join(RES, "real_alloc.json")))
    S = []
    names = ["県庁", "西南市役所", "北東町役場"]
    for a in allocations():
        rs = [r for r in rec if tuple(r["配分"]) == a]
        if not rs:
            continue
        S.append(dict(配分=dict(zip(names, a)), 問題=len(rs), 完了時刻_平均=round(float(np.mean([r["完了時刻"] for r in rs])), 2),
                      完了時刻_最悪=round(float(np.max([r["完了時刻"] for r in rs])), 2),
                      平均回復時刻_平均=round(float(np.mean([r["平均回復時刻"] for r in rs])), 2),
                      全問で最適=all(r["最適"] for r in rs)))
    S.sort(key=lambda r: r["完了時刻_平均"])
    base = [r for r in S if list(r["配分"].values()) == [4, 2, 2]]
    json.dump(dict(summary=S, 現状=base[0] if base else None), open(os.path.join(RES, "real_alloc_summary.json"), "w"),
              ensure_ascii=False, indent=1)
    for r in S[:6] + base:
        print(r)


if __name__ == "__main__":
    if "--summary" in sys.argv:
        summary()
    else:
        main()
