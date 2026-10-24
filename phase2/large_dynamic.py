"""
phase2/large_dynamic.py : 大規模 × 逐次の場面で, 「早く回復するほど良い」の QUBO と古典を同じ時間で比べる

  問題   通信断 25 / 35 基 × 通行止め 34 / 80 区間（run.py --scale と同じ 4 問）
  逐次   0 分に通信断の 6 割・通行止めの半分が分かり, 残りが 20 分後・40 分後に分かる（判明の順番 2 通り）
  時間   再計画 1 回あたり 3 秒（どの手法も同じ）
  目的   平均回復時刻（早く回復するほど良い）. 参考に最後の回復時刻も記録

  python large_dynamic.py   → results/phase2_large_dynamic.json
"""
import json
import os
import sys
import time
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import solvers as S
from dynamic import run_dynamic, reveal_schedule
from equal_time import ils, instances
from qubo_bisect import solve_qubo_sum_timed

ROOT = os.path.join(HERE, "..")
BUDGET = 3.0


def m_ils_sum(I, seed):
    return ils(I, BUDGET, seed, ev=S.Evaluator(I, "sum"))


def m_ils_ms(I, seed):
    return ils(I, BUDGET, seed)


def m_qubo_sum(I, seed):
    p = solve_qubo_sum_timed(I, BUDGET, seed)
    return p if p is not None else {t.tid: [] for t in I.trucks}


def m_qubo_sum_then_ils(I, seed):
    t0 = time.time()
    p = solve_qubo_sum_timed(I, BUDGET / 2, seed)
    rest = max(0.0, BUDGET - (time.time() - t0))
    return ils(I, rest, seed, start=p, ev=S.Evaluator(I, "sum")) if p is not None else m_ils_sum(I, seed)


METHODS = {
    "古典: 反復局所探索（早く回復するほど良い）": m_ils_sum,
    "QUBO: 早く回復するほど良い（生の解）": m_qubo_sum,
    "QUBO（早く回復）→ 古典の反復局所探索": m_qubo_sum_then_ils,
    "参考 古典: 反復局所探索（最後の回復時刻を最小）": m_ils_ms,
}


def main(orders=(0, 1)):
    w = json.load(open(os.path.join(ROOT, "data", "phase2_world.json")))
    recs = []
    for name, sc in instances(w)[3:]:                      # 通信断 25 / 35 基の 4 問
        for o in orders:
            evs = reveal_schedule(sc, seed=o)
            for m, fn in METHODS.items():
                secs = []

                def method(I, fn=fn, o=o):
                    t = time.time()
                    p = fn(I, o)
                    secs.append(time.time() - t)
                    return p
                r = run_dynamic(w, sc, method, events=evs)
                recs.append(dict(シナリオ=name, 判明の順番=o, 手法=m, 回復数=r["recovered"], 通信断=len(sc["failed"]),
                                 平均回復時刻=round(r["mean_time"], 1), 完了時刻=round(r["makespan"], 1),
                                 再計画の最大時間_秒=round(max(secs), 2)))
                print(recs[-1], flush=True)
    summary = {}
    for m in METHODS:
        rs = [r for r in recs if r["手法"] == m]
        summary[m] = dict(平均回復時刻_平均=round(float(np.mean([r["平均回復時刻"] for r in rs])), 1),
                          完了時刻_平均=round(float(np.mean([r["完了時刻"] for r in rs])), 1),
                          回復数_合計=int(sum(r["回復数"] for r in rs)),
                          再計画の最大時間_秒=round(float(max(r["再計画の最大時間_秒"] for r in rs)), 2))
    # 1 問ずつ, 古典（早く回復）を基準にした差
    base = {(r["シナリオ"], r["判明の順番"]): r["平均回復時刻"] for r in recs if r["手法"] == list(METHODS)[0]}
    for m in METHODS:
        d = [(r["平均回復時刻"] - base[(r["シナリオ"], r["判明の順番"])]) for r in recs if r["手法"] == m]
        summary[m]["古典との差_分_平均"] = round(float(np.mean(d)), 1)
        summary[m]["古典より良かった回数"] = int(sum(x < -0.05 for x in d))
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    json.dump(dict(budget_sec=BUDGET, runs=recs, summary=summary),
              open(os.path.join(ROOT, "results", "phase2_large_dynamic.json"), "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
