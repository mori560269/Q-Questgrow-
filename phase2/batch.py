"""
phase2/batch.py : 件数を増やして回す（結論が偶然でないかを確かめる）

  python batch.py equal      → results/batch_equal_time.json      同じ計算時間（32 問 × 予算 2・10 秒 × 種 3）
  python batch.py dynamic    → results/batch_large_dynamic.json   大規模 × 逐次（36 回, 再計画 3 秒）
  python batch.py resilient  → results/batch_resilient.json       回復しやすい配置（評価 100 災害, コスト 0〜10%）
  python batch.py stats      → results/batch_stats.json           信頼区間・勝ち負け・符号検定

  問題はすべて合成（world.py の道路網）. 通信断 15 / 25 / 35 / 45 基, 通行止めは 30〜90 区間をランダムに.
"""
import json
import math
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
from run import trucks_of
from dynamic import run_dynamic, reveal_schedule
import equal_time as ET
import large_dynamic as LD

ROOT = os.path.join(HERE, "..")
RES = os.path.join(ROOT, "results")


def load_world():
    return json.load(open(os.path.join(ROOT, "data", "phase2_world.json")))


def many_instances(w, sizes=(15, 25, 35, 45), per_size=8, seed0=5000):
    out = []
    S_xy = np.array([[s["x"], s["y"]] for s in w["sensors"]])
    for n_fail in sizes:
        for k in range(per_size):
            rng = np.random.default_rng(seed0 + 100 * n_fail + k)
            epi = (S_xy[rng.integers(len(S_xy))] + rng.normal(0, 3000, 2)).tolist()
            sc = make_scenario(w, seed=seed0 + 100 * n_fail + k, epicenter=epi, n_fail=n_fail,
                               n_closed=int(rng.integers(30, 91)), fault_len=25000, fault_angle=None)
            out.append((f"{n_fail}基-{k}", n_fail, sc))
    return out


def _save(path, obj):
    json.dump(obj, open(path, "w"), ensure_ascii=False, indent=1)


# ------------------------------------------------------------------ 同じ計算時間
def run_equal(budgets=(2.0, 10.0), seeds=3):
    w = load_world()
    methods = {k: v for k, v in ET.METHODS.items() if "負荷の 2 乗和" not in k}
    out = os.path.join(RES, "batch_equal_time.json")
    recs = json.load(open(out)) if os.path.exists(out) else []
    done = {(r["問題"], r["予算_秒"], r["手法"], r["種"]) for r in recs}
    for name, n_fail, sc in many_instances(w):
        I = Instance(w, sc["closed_segments"], sc["failed"], trucks_of(w), 2)
        for B in budgets:
            for m, fn in methods.items():
                for s in range(1 if m in ET.DETERMINISTIC else seeds):
                    if (name, B, m, s) in done:
                        continue
                    t0 = time.time()
                    p = fn(I, B, s)
                    used = time.time() - t0
                    e = I.evaluate(p) if p is not None else None
                    recs.append(dict(問題=name, 通信断=n_fail, 回復可能=len(I.recoverable), 予算_秒=B, 手法=m, 種=s,
                                     実際の時間_秒=round(used, 2),
                                     回復数=0 if e is None else e["recovered"],
                                     完了時刻=None if e is None or not e["feasible"] else round(e["makespan"], 1),
                                     平均回復時刻=None if e is None or not e["rec_time"] else
                                     round(float(np.mean(list(e["rec_time"].values()))), 1)))
            _save(out, recs)
            print(name, B, "done", flush=True)


# ------------------------------------------------------------------ 大規模 × 逐次
def run_dynamic_many(sizes=(25, 35, 45), per_size=4, orders=(0, 1, 2)):
    w = load_world()
    out = os.path.join(RES, "batch_large_dynamic.json")
    recs = json.load(open(out)) if os.path.exists(out) else []
    done = {(r["問題"], r["判明の順番"], r["手法"]) for r in recs}
    for name, n_fail, sc in many_instances(w, sizes=sizes, per_size=per_size, seed0=7000):
        for o in orders:
            evs = reveal_schedule(sc, seed=o)
            for m, fn in LD.METHODS.items():
                if (name, o, m) in done:
                    continue
                secs = []

                def method(I, fn=fn, o=o):
                    t = time.time(); p = fn(I, o); secs.append(time.time() - t); return p
                r = run_dynamic(w, sc, method, events=evs)
                recs.append(dict(問題=name, 通信断=n_fail, 判明の順番=o, 手法=m, 回復数=r["recovered"],
                                 平均回復時刻=round(r["mean_time"], 1), 完了時刻=round(r["makespan"], 1),
                                 再計画の最大時間_秒=round(max(secs), 2)))
            _save(out, recs)
            print(name, o, "done", flush=True)


# ------------------------------------------------------------------ 回復しやすい配置
def run_resilient(n_train=100, n_test=100, deltas=(0.0, 0.01, 0.02, 0.03, 0.04, 0.06, 0.08, 0.10)):
    import resilient_placement as RP
    from common import Problem
    from classical import solve_milp
    w = load_world()
    prob = Problem(cell_m=200.0)
    r = RP.recovery_risk(w, prob, RP.disasters(w, n_train, 1000))
    obj = np.repeat(r, prob.K)
    x0 = np.array([q for q in json.load(open(os.path.join(RES, "placement_fine_grid.json")))
                   if q["solve_grid_m"] == 200][0]["x"], float)
    base_cost = float((x0 * prob.cost).sum())
    placements = {"Phase 1 の最適配置": x0}
    for dl in deltas:
        x, info = solve_milp(prob, time_limit=300, obj=obj + 1e-6 * np.tile(prob.cost, prob.P), cost_cap=base_cost * (1 + dl))
        placements[f"回復しやすさ考慮 +{dl:.0%}"] = x
        print("配置", dl, (x * prob.cost).sum(), info["status"], flush=True)
    test = RP.disasters(w, n_test, 0)
    out = {}
    for name, x in placements.items():
        runs = RP.evaluate_placement(w, prob, x, test, budget=1.0)
        ok = Problem(cell_m=1000.0).evaluate(x, cell_m=100.0)["feasible"]
        out[name] = dict(総コスト=float((x * prob.cost).sum()), センサー数=int(x.sum()), 制約_100m=bool(ok), runs=runs)
        print(name, out[name]["総コスト"], out[name]["センサー数"],
              round(float(np.mean([q["完了時刻"] for q in runs])), 1), flush=True)
        _save(os.path.join(RES, "batch_resilient.json"), out)


# ------------------------------------------------------------------ 集計
def boot_ci(x, n=2000, seed=0):
    x = np.asarray(x, float)
    if len(x) == 0:
        return (None, None)
    rng = np.random.default_rng(seed)
    m = rng.choice(x, size=(n, len(x)), replace=True).mean(1)
    return (round(float(np.percentile(m, 2.5)), 2), round(float(np.percentile(m, 97.5)), 2))


def sign_test(wins, losses):
    """引き分けを除いた両側の符号検定の p 値"""
    n = wins + losses
    if n == 0:
        return None
    k = min(wins, losses)
    p = sum(math.comb(n, i) for i in range(0, k + 1)) / 2 ** n * 2
    return round(min(1.0, p), 4)


def stats():
    res = {}
    # 同じ計算時間: 問題ごとの最良（全手法・全種）を基準にした差 %
    f = os.path.join(RES, "batch_equal_time.json")
    if os.path.exists(f):
        rec = json.load(open(f))
        best = {}
        for r in rec:
            if r["完了時刻"] is not None and r["回復数"] == r["回復可能"]:
                best[r["問題"]] = min(best.get(r["問題"], np.inf), r["完了時刻"])
        ref = "古典: 貪欲法 + 反復局所探索"
        out = []
        for B in sorted({r["予算_秒"] for r in rec}):
            for size in sorted({r["通信断"] for r in rec}) + ["全体"]:
                sub = [r for r in rec if r["予算_秒"] == B and (size == "全体" or r["通信断"] == size)]
                for m in sorted({r["手法"] for r in sub}):
                    rs = [r for r in sub if r["手法"] == m]
                    ok = [r for r in rs if r["完了時刻"] is not None and r["回復数"] == r["回復可能"]]
                    gaps = [(r["完了時刻"] - best[r["問題"]]) / best[r["問題"]] * 100 for r in ok]
                    # 古典との対戦（同じ問題・同じ種）
                    w_, l_, t_ = 0, 0, 0
                    if m != ref:
                        for r in rs:
                            c = [q for q in sub if q["手法"] == ref and q["問題"] == r["問題"] and q["種"] == r["種"]]
                            if not c:
                                continue
                            a = r["完了時刻"] if r["完了時刻"] is not None and r["回復数"] == r["回復可能"] else np.inf
                            b = c[0]["完了時刻"] if c[0]["完了時刻"] is not None else np.inf
                            if a < b - 0.05: w_ += 1
                            elif a > b + 0.05: l_ += 1
                            else: t_ += 1
                    out.append(dict(予算_秒=B, 通信断=size, 手法=m, 試行=len(rs),
                                    全基回復の割合=round(len(ok) / len(rs), 3) if rs else None,
                                    最良との差_平均=None if not gaps else round(float(np.mean(gaps)), 2),
                                    最良との差_95CI=boot_ci(gaps), 最良と同じ割合=None if not gaps else
                                    round(float(np.mean([g < 0.05 for g in gaps])), 3),
                                    古典に勝ち=w_, 負け=l_, 引き分け=t_, 符号検定p=sign_test(w_, l_) if m != ref else None))
        res["equal_time"] = out
    f = os.path.join(RES, "batch_large_dynamic.json")
    if os.path.exists(f):
        rec = json.load(open(f))
        ref = list(LD.METHODS)[0]
        out = []
        for size in sorted({r["通信断"] for r in rec}) + ["全体"]:
            sub = [r for r in rec if size == "全体" or r["通信断"] == size]
            base = {(r["問題"], r["判明の順番"]): r for r in sub if r["手法"] == ref}
            for m in LD.METHODS:
                rs = [r for r in sub if r["手法"] == m and (r["問題"], r["判明の順番"]) in base]
                # 勝ち負けは辞書式: 回復できた数が多い方が勝ち, 同じなら平均回復時刻が早い方
                # 時刻の差は回復数が同じ組だけで平均する（回復数が少ない方が平均時刻は早く見えるため）
                def cmp(r):
                    b = base[(r["問題"], r["判明の順番"])]
                    if r["回復数"] != b["回復数"]:
                        return -1 if r["回復数"] > b["回復数"] else 1
                    x = r["平均回復時刻"] - b["平均回復時刻"]
                    return -1 if x < -0.05 else (1 if x > 0.05 else 0)
                same = [r for r in rs if r["回復数"] == base[(r["問題"], r["判明の順番"])]["回復数"]]
                d = [r["平均回復時刻"] - base[(r["問題"], r["判明の順番"])]["平均回復時刻"] for r in same]
                drec = [r["回復数"] - base[(r["問題"], r["判明の順番"])]["回復数"] for r in rs]
                full = [r["回復数"] == r["通信断"] for r in rs]
                c = [cmp(r) for r in rs]
                w_ = sum(x < 0 for x in c); l_ = sum(x > 0 for x in c)
                out.append(dict(通信断=size, 手法=m, 回数=len(rs),
                                平均回復時刻=round(float(np.mean([r["平均回復時刻"] for r in rs])), 2) if rs else None,
                                回復数の差_平均=round(float(np.mean(drec)), 2) if rs else None, 回復数が同じ組=len(same),
                                古典との差_分=round(float(np.mean(d)), 2) if d else None, 差の95CI=boot_ci(d),
                                全基回復の割合=round(float(np.mean(full)), 3) if rs else None,
                                古典に勝ち=int(w_), 負け=int(l_), 符号検定p=sign_test(int(w_), int(l_)) if m != ref else None,
                                再計画の最大時間_秒=max((r["再計画の最大時間_秒"] for r in rs), default=None)))
        res["large_dynamic"] = out
    f = os.path.join(RES, "batch_resilient.json")
    if os.path.exists(f):
        rec = json.load(open(f))
        base = list(rec.values())[0]["runs"]
        out = []
        for name, v in rec.items():
            runs = v["runs"]
            dm = [a["完了時刻"] - b["完了時刻"] for a, b in zip(runs, base)]
            dr = [a["平均回復時刻"] - b["平均回復時刻"] for a, b in zip(runs, base)
                  if a["平均回復時刻"] is not None and b["平均回復時刻"] is not None]
            out.append(dict(配置=name, 総コスト=v["総コスト"], センサー数=v["センサー数"], 制約_100m=v["制約_100m"],
                            通信断_平均=round(float(np.mean([q["通信断"] for q in runs])), 2),
                            対応不能_合計=int(sum(q["対応不能"] for q in runs)),
                            完了時刻_平均=round(float(np.mean([q["完了時刻"] for q in runs])), 2),
                            完了時刻の差_95CI=boot_ci(dm),
                            平均回復時刻_平均=round(float(np.mean([q["平均回復時刻"] for q in runs if q["平均回復時刻"] is not None])), 2),
                            平均回復時刻の差_95CI=boot_ci(dr),
                            完了時刻が早くなった災害=int(sum(x < -0.05 for x in dm)),
                            遅くなった災害=int(sum(x > 0.05 for x in dm)),
                            符号検定p=sign_test(int(sum(x < -0.05 for x in dm)), int(sum(x > 0.05 for x in dm)))))
        res["resilient"] = out
    _save(os.path.join(RES, "batch_stats.json"), res)
    for k, v in res.items():
        print("==", k)
        for r in v:
            print(r)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "stats"
    dict(equal=run_equal, dynamic=run_dynamic_many, resilient=run_resilient, stats=stats)[cmd]()
