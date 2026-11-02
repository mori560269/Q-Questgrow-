"""
phase2/real_qubo_improve.py : 列の集合分割 QUBO の改良（離陸地点が違うだけの列をまとめる）を, 同じ列の MILP と比べる

  各問題で, 反復局所探索 5 秒の解を上限に列を列挙し（古典の前処理, 全手法で共通・時間に含めない）,
    MILP（全部の列） / MILP（まとめた列） / QUBO（全部の列, 30 秒） / QUBO（まとめた列, 30 秒）
  で, 最適値（MILP で証明）にどこまで届くかを比べる. QUBO は CPU の焼きなまし（neal）.

  python real_qubo_improve.py   → results/real_qubo_improve.json
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
BUDGET = 30.0
_RW = None


def _task(arg):
    global _RW
    pid, sc = arg
    from real import RealWorld, RealInstance
    from equal_time import ils
    from exact import enumerate_columns, reduce_columns, solve_exact, solve_column_qubo
    if _RW is None:
        _RW = RealWorld()
    I = RealInstance(_RW, sc)
    st = ils(I, 5.0, 0)
    e0 = I.evaluate(st)
    if e0["recovered"] < len(I.recoverable):
        return dict(問題=pid, 省略="全基を回復できない問題")
    UB = e0["makespan"]
    t0 = time.time()
    cols, trunc = enumerate_columns(I, UB, time_limit=300)
    t_enum = time.time() - t0
    red = reduce_columns(I, cols)
    out = dict(問題=pid, 回復可能=len(I.recoverable), 上限=round(UB, 3), 列=len(cols), まとめた列=len(red),
               列挙_秒=round(t_enum, 1), 打ち切り=trunc)
    for name, cs in (("全部", cols), ("まとめ", red)):
        t = time.time()
        p, info = solve_exact(I, start=st, UB=UB, time_limit=300, reduce=(name == "まとめ"))   # 列挙込みの時間
        out[f"MILP_{name}_完了"] = info["makespan"]
        out[f"MILP_{name}_最適"] = info["optimal"]
        out[f"MILP_{name}_秒"] = round(time.time() - t, 2)
        for sd in (0,):
            t = time.time()
            q, qi = solve_column_qubo(I, BUDGET, sd, UB=UB, start=st, cols=cs)
            out[f"QUBO_{name}_完了"] = qi["makespan"]
            out[f"QUBO_{name}_秒"] = round(time.time() - t, 2)
            out[f"QUBO_{name}_最大変数"] = max((h["変数"] or 0) for h in qi["history"]) if qi["history"] else 0
    return out


def main(procs=4):
    from real_batch import scenarios
    f = os.path.join(RES, "real_qubo_improve.json")
    out = json.load(open(f)) if os.path.exists(f) else []
    done = {r["問題"] for r in out}
    cnt, tasks = {}, []
    for name, sc in scenarios():
        k = cnt.get(name, 0); cnt[name] = k + 1
        if f"{name}_{k}" not in done:
            tasks.append((f"{name}_{k}", sc))
    with Pool(procs) as pool:
        for r in pool.imap_unordered(_task, tasks):
            out.append(r)
            json.dump(out, open(f, "w"), ensure_ascii=False, indent=1)
            print(r, flush=True)
    summary()


def summary():
    rec = [r for r in json.load(open(os.path.join(RES, "real_qubo_improve.json"))) if "省略" not in r]
    S = {}
    for name in ("全部", "まとめ"):
        ok = [r for r in rec if r[f"QUBO_{name}_完了"] is not None]
        opt = [r for r in ok if abs(r[f"QUBO_{name}_完了"] - r["MILP_全部_完了"]) < 0.05]
        gaps = [(r[f"QUBO_{name}_完了"] - r["MILP_全部_完了"]) / r["MILP_全部_完了"] * 100 for r in ok]
        S[name] = dict(問題=len(rec), 解が出た=len(ok), 最適と同じ=len(opt),
                       最適との差_平均=round(float(np.mean(gaps)), 2) if gaps else None,
                       列_中央値=int(np.median([r["列" if name == "全部" else "まとめた列"] for r in rec])),
                       最大変数_中央値=int(np.median([r[f"QUBO_{name}_最大変数"] for r in rec])),
                       MILP_秒_中央値=round(float(np.median([r[f"MILP_{name}_秒"] for r in rec])), 2))
    # 列の数ごとの成功率
    bins = [(0, 100), (100, 300), (300, 1000), (1000, 10 ** 9)]
    by = []
    for lo, hi in bins:
        for name in ("全部", "まとめ"):
            key = "列" if name == "全部" else "まとめた列"
            rs = [r for r in rec if lo <= r[key] < hi]
            if rs:
                by.append(dict(列の数=f"{lo}〜{hi if hi < 10 ** 9 else ''}", 列=name, 問題=len(rs),
                               解が出た=sum(r[f"QUBO_{name}_完了"] is not None for r in rs),
                               最適と同じ=sum(r[f"QUBO_{name}_完了"] is not None and abs(r[f"QUBO_{name}_完了"] - r["MILP_全部_完了"]) < 0.05 for r in rs)))
    json.dump(dict(summary=S, by_size=by), open(os.path.join(RES, "real_qubo_improve_summary.json"), "w"), ensure_ascii=False, indent=1)
    print(S)
    for b in by:
        print(b)


if __name__ == "__main__":
    if "--summary" in sys.argv:
        summary()
    else:
        main()
