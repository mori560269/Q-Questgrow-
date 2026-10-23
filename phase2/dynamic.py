"""
phase2/dynamic.py : 情報が少しずつ分かる状況での逐次再計画

  実際の災害では, どのセンサーが止まったか・どの道路が通れないかは時間とともに分かる.
  例: 0 分に通信断の 6 割と通行止めの半分が分かり, 残りが 20 分後・40 分後に分かる.
  情報が入るたびに, その時点の車の状態（位置・時刻・使った飛行回数・充電の残り時間）から計画を作り直す.

  計画の実行のしかた
    - 飛行中の飛行は最後まで行う（そのセンサーは回復）
    - 移動中の車は, 次の停車地点まで行ってから新しい計画に従う
    - 新しい計画は, まだ回復していない既知の通信断センサーだけを対象にする
"""
import time
import numpy as np

from model import Instance, Truck, CHARGE_MIN


def replay(I, tr, order, fids):
    """車 1 台の計画を時刻つきの行動に展開する（model.truck_schedule と同じ規則）"""
    stops = {}
    for f in fids:
        stops.setdefault(I.flights[f]["node"], []).append(f)
    for v in stops:
        stops[v].sort(key=lambda f: I.flights[f]["dur"])
    t, ready, pos = tr.t0, tr.ready, tr.node
    out = []
    for v in order:
        dep = t
        t += I.drive(pos, v) if pos != v else 0.0
        leg = dict(node=v, depart=dep, arrive=t, flights=[])
        pos = v
        for f in stops[v]:
            fl = I.flights[f]
            start = max(t, ready)
            recs = {I.targets[j]: start + o for j, o in zip(fl["order"], fl["offset"])}
            t = start + fl["dur"]
            ready = t + CHARGE_MIN
            leg["flights"].append(dict(start=start, end=t, recs=recs))
        out.append(leg)
    return out


def advance(I, ev_plan, tau, recovered):
    """時刻 tau までの計画を実行して, 車の新しい状態を返す"""
    new = []
    for tr in I.trucks:
        info = ev_plan["per_truck"][tr.tid]
        legs = replay(I, tr, info["order"], info["flights"])
        node, avail, used, ready = tr.node, max(tr.t0, tau), tr.flights_done, tr.ready
        for leg in legs:
            if leg["depart"] > tau:
                break
            node = leg["node"]
            avail = max(tau, leg["arrive"])
            for fl in leg["flights"]:
                if fl["start"] <= tau:
                    used += 1
                    for s, t in fl["recs"].items():
                        recovered[s] = min(recovered.get(s, np.inf), t)
                    avail = max(tau, fl["end"])
                    ready = fl["end"] + CHARGE_MIN
        new.append(Truck(tr.tid, tr.depot, node, t0=avail, flights_done=used, ready=ready, spare=tr.spare))
    return new


def reveal_schedule(sc, times=(0.0, 20.0, 40.0), first_frac=0.6, seed=0):
    rng = np.random.default_rng(seed)
    f = list(sc["failed"]); c = list(sc["closed_segments"])
    rng.shuffle(f); rng.shuffle(c)
    nf0 = int(round(len(f) * first_frac)); nc0 = int(round(len(c) * 0.5))
    rest_f = np.array_split(f[nf0:], len(times) - 1)
    rest_c = np.array_split(c[nc0:], len(times) - 1)
    ev = [dict(t=times[0], failed=f[:nf0], closed=c[:nc0])]
    for k, t in enumerate(times[1:]):
        ev.append(dict(t=t, failed=[int(x) for x in rest_f[k]], closed=[int(x) for x in rest_c[k]]))
    return ev


def run_dynamic(world, sc, method, spares=2, events=None, log=None):
    """method(I) -> plan. 戻り値: 回復数, 完了時刻, 再計画の計算時間"""
    events = events or reveal_schedule(sc)
    trucks, k = [], 0
    for d in world["depots"]:
        for _ in range(d["trucks"]):
            trucks.append(Truck(k, d["name"], d["node"])); k += 1
    known_f, known_c = set(), set()
    recovered, solve_sec, spares_left = {}, [], spares
    ev_plan, I = None, None
    for e in events:
        if ev_plan is not None:
            trucks = advance(I, ev_plan, e["t"], recovered)
            for tr in trucks:
                if tr.flights_done > 5 and not tr.spare:
                    tr.spare = True; spares_left -= 1
        known_f |= set(e["failed"]); known_c |= set(e["closed"])
        targets = sorted(s for s in known_f if s not in recovered)
        I = Instance(world, sorted(known_c), targets, trucks, max(0, spares_left))
        t0 = time.time()
        plan = method(I)
        solve_sec.append(time.time() - t0)
        ev_plan = I.evaluate(plan)
        if log:
            log(f"  t={e['t']:.0f} 分: 既知の通信断 {len(known_f)}, 未回復 {len(targets)}, "
                f"計画の完了 {ev_plan['makespan']:.1f} 分, 計算 {solve_sec[-1]:.2f} 秒")
    advance(I, ev_plan, 1e9, recovered)
    allf = set(sc["failed"])
    rec = {s: t for s, t in recovered.items() if s in allf}
    return dict(recovered=len(rec), makespan=float(max(rec.values(), default=0.0)),
                mean_time=float(np.mean(list(rec.values()))) if rec else 0.0, solve_sec=solve_sec, rec_time=rec)
