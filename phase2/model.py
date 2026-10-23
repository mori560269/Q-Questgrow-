"""
phase2/model.py : Phase 2 の問題を作り, 計画を厳密に評価する（全手法で共通の物差し）

  ドローン（課題資料の値）
    最大飛行 15 分, センサー上空の滞空 3 分/基, 速度 40 km/h（= 666.7 m/分）
    → 1 基だけ往復するなら半径 4.0 km まで届く
  ドック搭載車
    最初は満充電. ドックでの充電は 1 回 30 分（内蔵で 4 回まで）. 予備バッテリー 1 個で +4 回
    → 1 台あたりの飛行回数の上限は 5 回（予備ありで 9 回）
    充電は車の移動中も進む（ドックは車に積まれている）. 飛行中は車は止まる.
  道路
    高速道路 80 / 国道 50 / 主要地方道 40 / 一般道 30 km/h. 通行止めの区間を含む道路は通れない.
    離陸地点は一般道側の交差点（高速道路上には止められない）.

  計画 = 各車に「飛行（離陸地点 + 回るセンサーの順）」を割り当てたもの.
  evaluate() が車ごとに停車順を最適化し, 各センサーの回復時刻・完了時刻（メイクスパン）を厳密に計算する.
"""
import itertools
import numpy as np
import scipy.sparse as sp
from scipy.sparse.csgraph import dijkstra

from world import SPEED_KMH

FLIGHT_MIN = 15.0
HOVER_MIN = 3.0
DRONE_M_PER_MIN = 40000.0 / 60.0
CHARGE_MIN = 30.0
BASE_CHARGES = 4
SPARE_CHARGES = 4
MAX_PER_FLIGHT = 3


class Truck:
    def __init__(self, tid, depot, node, t0=0.0, flights_done=0, ready=0.0, spare=False):
        self.tid, self.depot, self.node, self.t0 = tid, depot, node, t0
        self.flights_done, self.ready, self.spare = flights_done, ready, spare

    def cap(self, spare=None):
        s = self.spare if spare is None else spare
        return 1 + BASE_CHARGES + (SPARE_CHARGES if s else 0) - self.flights_done


class Instance:
    """world + その時点で分かっている通行止め・通信断 + 車の状態 から, 解くべき問題を作る"""

    def __init__(self, world, closed_segments, targets, trucks, spares_left):
        self.world = world
        nodes = np.array(world["nodes"])
        self.nodes = nodes
        n = len(nodes)
        closed_edges = {world["segments"][s]["edge"] for s in closed_segments}
        rows, cols, w = [], [], []
        for i, e in enumerate(world["edges"]):
            if i in closed_edges:
                continue
            t = e["length_m"] / 1000.0 / SPEED_KMH[e["cls"]] * 60.0
            rows += [e["a"], e["b"]]; cols += [e["b"], e["a"]]; w += [t, t]
        # 高速道路は別の層 (n 以降の番号). IC・JCT でだけ一般道とつながる
        ic = world["expressway"]["ic_node"]
        names = list(ic)
        for k, nm in enumerate(names):
            rows += [n + k, ic[nm]]; cols += [ic[nm], n + k]; w += [1.0, 1.0]
        for a, b, L in world["expressway"]["edges"]:
            t = L / 1000.0 / SPEED_KMH["expressway"] * 60.0
            ia, ib = n + names.index(a), n + names.index(b)
            rows += [ia, ib]; cols += [ib, ia]; w += [t, t]
        self.G = sp.coo_matrix((w, (rows, cols)), shape=(n + len(names), n + len(names))).tocsr()
        self.n_road = n

        S = world["sensors"]
        self.targets = list(targets)
        self.sxy = np.array([[S[i]["x"], S[i]["y"]] for i in self.targets]).reshape(-1, 2)
        self.trucks = trucks
        self.spares_left = spares_left

        # 車の出発点からの走行時間
        starts = sorted({t.node for t in trucks})
        D0 = dijkstra(self.G, indices=starts)
        self.drive_from = {s: D0[i][:n] for i, s in enumerate(starts)}
        reach = np.min(np.array([self.drive_from[s] for s in starts]), axis=0) < np.inf

        # 離陸地点の候補: 車が行ける一般道の交差点で, どれかの目標センサーから 4 km 以内
        R1 = (FLIGHT_MIN - HOVER_MIN) * DRONE_M_PER_MIN / 2
        dist = np.hypot(nodes[:, None, 0] - self.sxy[None, :, 0], nodes[:, None, 1] - self.sxy[None, :, 1]) \
            if len(self.targets) else np.zeros((n, 0))
        near = (dist <= R1) & reach[:, None]
        self.launch = [int(v) for v in np.nonzero(near.any(1))[0]]
        self.recoverable = [j for j in range(len(self.targets)) if near[:, j].any()]
        self.unreachable = [j for j in range(len(self.targets)) if not near[:, j].any()]

        # 離陸地点どうしの走行時間
        if self.launch:
            DL = dijkstra(self.G, indices=self.launch)
            self.drive_ll = {v: DL[i][:n] for i, v in enumerate(self.launch)}
        else:
            self.drive_ll = {}

        # ---- 飛行の列挙: 離陸地点 v から, 目標センサー 1〜3 基を最短の順で回って戻る
        flights = {}
        for v in self.launch:
            cand = [j for j in self.recoverable if dist[v, j] <= FLIGHT_MIN * DRONE_M_PER_MIN / 2]
            for k in range(1, MAX_PER_FLIGHT + 1):
                for comb in itertools.combinations(cand, k):
                    best = None
                    for perm in itertools.permutations(comb):
                        P = [nodes[v]] + [self.sxy[j] for j in perm] + [nodes[v]]
                        legs = [float(np.hypot(*(P[i + 1] - P[i]))) for i in range(len(P) - 1)]
                        tt = sum(legs) / DRONE_M_PER_MIN + HOVER_MIN * k
                        if tt <= FLIGHT_MIN and (best is None or tt < best[0]):
                            off, acc = [], 0.0
                            for i, j in enumerate(perm):
                                acc += legs[i] / DRONE_M_PER_MIN + HOVER_MIN
                                off.append(acc)
                            best = (tt, perm, off)
                    if best is not None:
                        key = tuple(sorted(comb))
                        flights.setdefault(key, []).append(dict(node=v, dur=best[0], order=list(best[1]),
                                                                offset=best[2]))
        # 同じセンサーの組の飛行は, 各出発点から近い離陸地点だけを残す（候補を絞る）
        self.flights = []
        for key, lst in flights.items():
            keep = set()
            for s in starts:
                keep.add(min(range(len(lst)), key=lambda i: self.drive_from[s][lst[i]["node"]] + lst[i]["dur"]))
            for i in sorted(keep):
                f = dict(lst[i]); f["sensors"] = key
                self.flights.append(f)

    def drive(self, a, b):
        if a in self.drive_ll:
            return float(self.drive_ll[a][b])
        if b in self.drive_ll:
            return float(self.drive_ll[b][a])
        return float(self.drive_from[a][b])

    # ------------------------------------------------------------------ 厳密な評価
    def truck_schedule(self, truck, fids, spare):
        """車 1 台に割り当てた飛行を, 停車順を最適化して実行したときの各センサーの回復時刻"""
        if not fids:
            return 0.0, {}, []
        stops = {}
        for f in fids:
            stops.setdefault(self.flights[f]["node"], []).append(f)
        for v in stops:
            stops[v].sort(key=lambda f: self.flights[f]["dur"])
        nodes = list(stops)

        def run(order):
            t, ready, pos, used, rec = truck.t0, truck.ready, truck.node, 0, {}
            for v in order:
                t += self.drive(pos, v) if pos != v else 0.0
                pos = v
                for f in stops[v]:
                    fl = self.flights[f]
                    start = max(t, ready)
                    for j, o in zip(fl["order"], fl["offset"]):
                        rec[j] = start + o
                    t = start + fl["dur"]
                    ready = t + CHARGE_MIN
                    used += 1
            return max(rec.values()), rec

        if len(nodes) <= 7:
            best = min((run(p) + (p,) for p in itertools.permutations(nodes)), key=lambda r: r[0])
        else:   # 近い順 + 2-opt
            order, pos, rest = [], truck.node, set(nodes)
            while rest:
                v = min(rest, key=lambda u: self.drive(pos, u)); order.append(v); rest.remove(v); pos = v
            best = run(order) + (tuple(order),)
            improved = True
            while improved:
                improved = False
                for i in range(len(order) - 1):
                    for j in range(i + 1, len(order)):
                        o = order[:i] + order[i:j + 1][::-1] + order[j + 1:]
                        r = run(o)
                        if r[0] < best[0] - 1e-9:
                            best, order, improved = r + (tuple(o),), o, True
        return best[0], best[1], list(best[2])

    def evaluate(self, plan):
        """plan: {tid: [flight index...]}. 戻り値: 回復数, メイクスパン, 予備バッテリーの割当, 実行可能か"""
        need = {}
        for tr in self.trucks:
            k = len(plan.get(tr.tid, []))
            if k > tr.cap(False):
                need[tr.tid] = k
        spare_ok = len([t for t in need if not next(x for x in self.trucks if x.tid == t).spare]) <= self.spares_left
        over = any(len(plan.get(tr.tid, [])) > tr.cap(True) for tr in self.trucks)
        rec, ms, per = {}, 0.0, {}
        for tr in self.trucks:
            fids = plan.get(tr.tid, [])
            m, r, order = self.truck_schedule(tr, fids, tr.tid in need)
            per[tr.tid] = dict(makespan=m, order=order, flights=list(fids), spare=tr.tid in need)
            for j, t in r.items():
                rec[j] = min(rec.get(j, np.inf), t)
            ms = max(ms, m)
        covered = [j for j in self.recoverable if j in rec]
        return dict(recovered=len(covered), recoverable=len(self.recoverable), unreachable=len(self.unreachable),
                    makespan=float(max([rec[j] for j in covered], default=0.0)), feasible=spare_ok and not over,
                    spares_used=len(need), per_truck=per, rec_time={self.targets[j]: rec[j] for j in covered})

    def lower_bound(self):
        """各センサーを, どれかの車が真っ先に回復しに行った場合の最短時刻. その最大値はメイクスパンの下界"""
        best = {}
        for f in self.flights:
            for tr in self.trucks:
                d = self.drive_from[tr.node][f["node"]]
                st = max(tr.t0 + d, tr.ready)
                for j, o in zip(f["order"], f["offset"]):
                    best[j] = min(best.get(j, np.inf), st + o)
        return float(max(best.values(), default=0.0))
