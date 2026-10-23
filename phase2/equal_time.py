"""
phase2/equal_time.py : 同じ計算時間で, 古典と QUBO を比べる

  1 問あたりの時間の予算（例: 0.5 秒・2 秒・10 秒）を決め, どの手法もその時間内で一番良い解を出す.
  時間切れの時点で持っている解を, model.evaluate で同じように採点する.
  （問題の前処理 = 道路の最短路・飛行の列挙 は全手法で共通なので, 予算に含めない）

  手法
    古典      貪欲法 → 反復局所探索（局所探索で行き詰まったら, 飛行をいくつか別の車に移して崩し, 局所探索し直す）
    古典      列挙 + MILP（厳密. 1 台 3 飛行まで）: 予算内に終わらなければ「解なし」
    QUBO      負荷の 2 乗和 QUBO を, 予算いっぱい乱数の種を変えて解き直す（生の解）
    QUBO      上限 T の二分探索 QUBO を, 予算いっぱい続ける（生の解）
    QUBO+古典 二分探索 QUBO に予算の半分, 残りで反復局所探索

  python equal_time.py   → results/phase2_equal_time.json
"""
import json
import os
import sys
import time
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "placement"))
from model import Instance
from world import make_scenario
import solvers as S
from qubo_bisect import build_decision_qubo, decode
from qubo_amplify import solve_inner

ROOT = os.path.join(HERE, "..")
CHUNK = dict(num_reads=4, num_sweeps=500)          # 1 回の焼きなましの大きさ（短く区切って何度も呼ぶ）


def trucks_of(w):
    from run import trucks_of as f
    return f(w)


def _better(ev_a, ev_b):
    return ev_b is None or S._key(ev_a) < S._key(ev_b)


# ------------------------------------------------------------------ 古典: 反復局所探索
def ils(I, budget, seed=0, start=None, ev=None):
    t_end = time.time() + budget
    rng = np.random.default_rng(seed)
    ev = ev or S.Evaluator(I)
    plan = start if start is not None else S.greedy(I, ev, deadline=t_end)
    if time.time() < t_end:
        plan = S.local_search(I, plan, max(0.0, t_end - time.time()), ev)
    best, bkey = plan, ev.key(plan)
    tids = [t.tid for t in I.trucks]
    while time.time() < t_end:
        p = {k: list(v) for k, v in best.items()}
        flat = [(a, i) for a in tids for i in range(len(p[a]))]
        if not flat:
            break
        for _ in range(min(3, len(flat))):                        # 飛行を 3 つまで別の車へ
            a = tids[rng.integers(len(tids))]
            if not p[a]:
                continue
            f = p[a].pop(rng.integers(len(p[a])))
            p[tids[rng.integers(len(tids))]].append(f)
        p = S.local_search(I, p, max(0.0, t_end - time.time()), ev)
        k = ev.key(p)
        if k < bkey:
            best, bkey = p, k
    return best


# ------------------------------------------------------------------ QUBO: 負荷の 2 乗和を繰り返し解く
def qubo_load_timed(I, budget, seed=0):
    t_end = time.time() + budget
    F, T = len(I.flights), len(I.trucks)
    lin, Q, _ = S.build_qubo(I)
    ev = S.Evaluator(I)
    best, bev, it = None, None, 0
    while time.time() < t_end or best is None:
        sols, _ = solve_inner(lin, Q, "neal", None, 1000, CHUNK["num_reads"], CHUNK["num_sweeps"], seed * 1000 + it)
        it += 1
        for s in sols:
            y = np.rint(s).reshape(F, T)
            plan = {t.tid: [] for t in I.trucks}
            for fi, ti in zip(*np.nonzero(y)):
                plan[I.trucks[ti].tid].append(int(fi))
            # 生の解: 各センサーをちょうど 1 回覆うものだけを採用（修復はしない）
            cnt = {}
            for fids in plan.values():
                for f in fids:
                    for j in I.flights[f]["sensors"]:
                        cnt[j] = cnt.get(j, 0) + 1
            if not all(cnt.get(j, 0) == 1 for j in I.recoverable):
                continue
            e = I.evaluate(plan)
            if _better(e, bev):
                best, bev = plan, e
        if time.time() >= t_end:
            break
    return best


# ------------------------------------------------------------------ QUBO: 上限 T の二分探索（時間制限つき）
def qubo_bisect_timed(I, budget, seed=0):
    t_end = time.time() + budget
    best = qubo_load_timed(I, min(budget * 0.15, 1.0), seed)        # 上限の初期値（予算の一部を使う）
    bev = I.evaluate(best) if best is not None else None
    hi = bev["makespan"] if bev is not None and bev["recovered"] == bev["recoverable"] else None
    lo = I.lower_bound()
    it = 0
    while time.time() < t_end:
        T_lim = (lo + hi) / 2 if hi is not None else lo * 1.6
        if hi is not None and hi - lo < 0.5:
            break
        model = build_decision_qubo(I, T_lim)
        if model is None:
            lo = T_lim
            continue
        found = None
        slice_end = min(t_end, time.time() + max(0.2, budget / 6))  # 1 つの T に使う時間
        while time.time() < slice_end:
            sols, _ = solve_inner(model["lin"], model["Q"], "neal", None, 1000, CHUNK["num_reads"],
                                  CHUNK["num_sweeps"], seed * 1000 + it)
            it += 1
            for s in sols:
                plan, exact = decode(I, model["var"], s)
                if not exact:
                    continue
                e = I.evaluate(plan)
                if e["recovered"] == e["recoverable"] and e["feasible"] and _better(e, bev):
                    best, bev = plan, e
                    hi = e["makespan"]
                if e["makespan"] <= T_lim + 1e-6:
                    found = True
            if found:
                break
        if not found:
            lo = T_lim
    return best


def qubo_bisect_then_ils(I, budget, seed=0):
    t0 = time.time()
    p = qubo_bisect_timed(I, budget / 2, seed)
    rest = budget - (time.time() - t0)
    return ils(I, max(0.0, rest), seed, start=p if p is not None else None)


def exact_timed(I, budget, seed=0):
    p, t, info = S.solve_columns(I, 3, budget)
    if info["status"] != 0 or t > budget * 1.05:
        return None
    return p


METHODS = {
    "古典: 貪欲法 + 反復局所探索": ils,
    "古典: 列挙 + MILP（厳密）": exact_timed,
    "QUBO: 負荷の 2 乗和（生の解）": qubo_load_timed,
    "QUBO: 二分探索（生の解）": qubo_bisect_timed,
    "QUBO 二分探索 → 古典の反復局所探索": qubo_bisect_then_ils,
}
DETERMINISTIC = {"古典: 列挙 + MILP（厳密）"}


def instances(w):
    out = []
    sc = json.load(open(os.path.join(ROOT, "data", "phase2_scenario_sample.json")))
    out.append(("サンプル 18 / 34", sc))
    rng = np.random.default_rng(0)
    S_xy = np.array([[s["x"], s["y"]] for s in w["sensors"]])
    for n_fail in (15, 25, 35):
        for n_closed in (34, 80):
            epi = (S_xy[rng.integers(len(S_xy))] + rng.normal(0, 3000, 2)).tolist()   # run.py --scale と同じ
            out.append((f"{n_fail} / {n_closed}", make_scenario(w, seed=11, epicenter=epi, n_fail=n_fail,
                                                                n_closed=n_closed, fault_len=25000, fault_angle=None)))
    return out


def main(budgets=(0.5, 2.0, 10.0), seeds=3):
    w = json.load(open(os.path.join(ROOT, "data", "phase2_world.json")))
    records = []
    for name, sc in instances(w):
        I = Instance(w, sc["closed_segments"], sc["failed"], trucks_of(w), 2)
        for B in budgets:
            for m, fn in METHODS.items():
                for s in range(1 if m in DETERMINISTIC else seeds):
                    t0 = time.time()
                    p = fn(I, B, s)
                    used = time.time() - t0
                    if p is None:
                        rec = dict(回復数=0, 完了時刻=None)
                    else:
                        e = I.evaluate(p)
                        rec = dict(回復数=e["recovered"], 完了時刻=round(e["makespan"], 1) if e["feasible"] else None)
                    records.append(dict(シナリオ=name, 回復可能=len(I.recoverable), 予算_秒=B, 手法=m, 種=s,
                                        実際の時間_秒=round(used, 2), **rec))
                    print(records[-1], flush=True)
    json.dump(records, open(os.path.join(ROOT, "results", "phase2_equal_time.json"), "w"), ensure_ascii=False, indent=1)


def summarize():
    """シナリオごとに「これまでに見つかった最良の完了時刻」を基準に, 手法 × 予算の成績をまとめる"""
    rec = json.load(open(os.path.join(ROOT, "results", "phase2_equal_time.json")))
    best = {}
    for r in rec:
        if r["完了時刻"] is not None and r["回復数"] == r["回復可能"]:
            best[r["シナリオ"]] = min(best.get(r["シナリオ"], np.inf), r["完了時刻"])
    # 以前の実験（時間制限なし）で見つかった値も基準に含める
    for r in json.load(open(os.path.join(ROOT, "results", "phase2_scale.json"))):
        name = f"{r['通信断']} / {r['通行止め']}"
        for k, v in r.items():
            if k.endswith("_分") and k != "下界_分" and v is not None:
                best[name] = min(best.get(name, np.inf), v)
    for r in json.load(open(os.path.join(ROOT, "results", "phase2_compare.json")))["results"]:
        best["サンプル 18 / 34"] = min(best.get("サンプル 18 / 34", np.inf), r["完了時刻_分"])
    out = {}
    for r in rec:
        key = (r["予算_秒"], r["手法"])
        d = out.setdefault(key, dict(gaps=[], fail=0, n=0, over=[]))
        d["n"] += 1
        d["over"].append(r["実際の時間_秒"] / r["予算_秒"])
        if r["完了時刻"] is None or r["回復数"] < r["回復可能"]:
            d["fail"] += 1
        else:
            d["gaps"].append((r["完了時刻"] - best[r["シナリオ"]]) / best[r["シナリオ"]] * 100)
    rows = []
    for (B, m), d in sorted(out.items()):
        g = d["gaps"]
        rows.append(dict(予算_秒=B, 手法=m, 試行=d["n"], 全基回復できた割合=round(1 - d["fail"] / d["n"], 3),
                         最良との差_平均=None if not g else round(float(np.mean(g)), 1),
                         最良との差_最悪=None if not g else round(float(np.max(g)), 1),
                         最良と同じだった割合=None if not g else round(float(np.mean([x < 0.05 for x in g])), 2),
                         時間の超過_最大倍=round(float(np.max(d["over"])), 2)))
    json.dump(dict(best_known=best, summary=rows), open(os.path.join(ROOT, "results", "phase2_equal_time_summary.json"), "w"),
              ensure_ascii=False, indent=1)
    for r in rows:
        print(r)
    return best, rows


if __name__ == "__main__":
    if "--summary" in sys.argv:
        summarize()
    else:
        main()
