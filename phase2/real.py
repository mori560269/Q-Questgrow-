"""
phase2/real.py : 課題で配布された Phase 2 の実データ（道路網・道路ノード・災害シナリオ）を読み, 解くべき問題を作る

  データ（data/phase2_real/）
    roads.geojson       道路区間 1,682（1 km 以下）. highway = motorway / motorway_link / trunk / primary / secondary
    road_nodes.geojson  道路ノード 1,597（区間の端点. 拠点・IC・JCT・交差点・形状点）
    scenario_sample.json  サンプル災害（通信断 18 基, 通行止め 34 区間, 拠点 3 か所・車 8 台, 予備バッテリー 1 個）
    センサーの位置は Phase 1 の候補地 86 か所（data/candidate_locations.geojson, P01_1 など）

  シナリオの値をそのまま使う
    車の速さ   motorway 60 / motorway_link 30 / trunk 40 / primary 30 / secondary 20 km/h（区間ごとの走行時間 = 長さ / 速さ）
    離陸準備   停車するたびに 10 分（launch_setup_time_min）
    離陸地点   trunk / primary / secondary（一般道）の, 通行できる区間の端点（道路ノード）. 高速道路上には止まれない
    ドローン   最大飛行 15 分, 滞空 3 分/基, 40 km/h, 通信半径 0 m（センサーの真上まで飛ぶ）
               → 1 基を往復するなら半径 (15 − 3) × 40/60 / 2 = 4.0 km. 往復距離の上限 20 km は飛行時間より緩いので効かない
    ドック     充電 30 分/回, 内蔵 4 回, 予備バッテリー 1 個で +4 回（1 台に 0〜1 個）, 走行中も充電できる
               → 1 台あたりの飛行は最大 5 回（予備ありで 9 回）

  model.Instance（合成データで作った厳密な評価器・全ソルバー）をそのまま使えるよう, 同じ形のデータを作る.
  drive(a, b) と drive_from は「走行時間 + 離陸準備 10 分」を返す（停車先が変わるたびに準備がかかるため）.
"""
import itertools
import json
import os

import numpy as np
import scipy.sparse as sp
from scipy.sparse.csgraph import dijkstra

import model
from model import Truck, FLIGHT_MIN, HOVER_MIN, DRONE_M_PER_MIN, MAX_PER_FLIGHT

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data")
LAUNCHABLE = ("trunk", "primary", "secondary")


class RealWorld:
    """道路網とセンサー位置（シナリオによらない部分）"""

    def __init__(self, data_dir=os.path.join(DATA, "phase2_real")):
        R = json.load(open(os.path.join(data_dir, "roads.geojson")))["features"]
        N = json.load(open(os.path.join(data_dir, "road_nodes.geojson")))["features"]
        C = json.load(open(os.path.join(DATA, "candidate_locations.geojson")))["features"]
        self.node_ids = [f["properties"]["node_id"] for f in N]
        self.nid = {v: i for i, v in enumerate(self.node_ids)}
        self.node_props = [f["properties"] for f in N]
        self.nodes = np.array([f["geometry"]["coordinates"] for f in N], float)
        self.seg_ids = [f["properties"]["segment_id"] for f in R]
        self.sid = {v: i for i, v in enumerate(self.seg_ids)}
        self.seg = [dict(a=self.nid[f["properties"]["from_node"]], b=self.nid[f["properties"]["to_node"]],
                         L=f["properties"]["length_m"], hw=f["properties"]["highway"],
                         structure=f["properties"]["structure"], muni=f["properties"]["municipality_id"],
                         name=f["properties"]["name"], geom=f["geometry"]["coordinates"]) for f in R]
        self.sensor_ids = [f["properties"]["candidate_id"] for f in C]
        self.sensor_xy = np.array([f["geometry"]["coordinates"] for f in C], float)
        self.sensor_muni = [f["properties"]["municipality_id"] for f in C]
        self.base_nodes = {p["node_id"]: p["name"] for p in self.node_props if p["drone_base"]}
        # model.Instance が参照する world["sensors"]（x, y）
        self.world = dict(sensors=[dict(id=s, x=float(x), y=float(y)) for s, (x, y) in zip(self.sensor_ids, self.sensor_xy)])


class RealInstance(model.Instance):
    """シナリオ（通行止め・通信断・車・予備バッテリー）から, model.Instance と同じ形の問題を作る"""

    def __init__(self, rw, sc, trucks=None, spares_left=None, closed=None, targets=None):
        self.rw, self.sc = rw, sc
        self.world = rw.world
        speed = sc["vehicle"]["speed_kmh"]
        self.setup = float(sc["vehicle"].get("launch_setup_time_min", 0.0))
        launchable = tuple(sc["vehicle"].get("launchable_highways", LAUNCHABLE))
        closed = set(sc["closed_segments"] if closed is None else closed)
        n = len(rw.nodes)
        self.nodes = rw.nodes
        rows, cols, w = [], [], []
        can_launch = np.zeros(n, bool)
        for sid, s in zip(rw.seg_ids, rw.seg):
            if sid in closed:
                continue
            t = s["L"] / 1000.0 / speed[s["hw"]] * 60.0
            rows += [s["a"], s["b"]]; cols += [s["b"], s["a"]]; w += [t, t]
            if s["hw"] in launchable:
                can_launch[s["a"]] = can_launch[s["b"]] = True
        self.G = sp.coo_matrix((w, (rows, cols)), shape=(n, n)).tocsr()
        self.n_road = n

        if trucks is None:
            trucks, k = [], 0
            for b in sc["drone_bases"]:
                for _ in range(b["num_vehicles"]):
                    trucks.append(Truck(k, b["name"], rw.nid[b["node_id"]])); k += 1
        self.trucks = trucks
        self.spares_left = sc["fleet"]["total_spare_batteries"] if spares_left is None else spares_left
        tg = sc["disconnected_sensors"] if targets is None else targets
        self.targets = [rw.sensor_ids.index(s) for s in tg]
        self.target_ids = list(tg)
        self.sxy = rw.sensor_xy[self.targets].reshape(-1, 2)

        starts = sorted({t.node for t in trucks})
        D0 = dijkstra(self.G, indices=starts)
        self.drive_raw = {s: D0[i] for i, s in enumerate(starts)}
        self.drive_from = {s: D0[i] + self.setup for i, s in enumerate(starts)}     # 走行 + 離陸準備
        reach = np.min(np.array([D0[i] for i in range(len(starts))]), axis=0) < np.inf

        R1 = (FLIGHT_MIN - HOVER_MIN) * DRONE_M_PER_MIN / 2
        dist = np.hypot(rw.nodes[:, None, 0] - self.sxy[None, :, 0], rw.nodes[:, None, 1] - self.sxy[None, :, 1]) \
            if len(self.targets) else np.zeros((n, 0))
        self.dist = dist
        ok = reach & can_launch
        near = (dist <= R1) & ok[:, None]
        self.launch_all = [int(v) for v in np.nonzero(near.any(1))[0]]
        self.recoverable = [j for j in range(len(self.targets)) if near[:, j].any()]
        self.unreachable = [j for j in range(len(self.targets)) if not near[:, j].any()]
        # 対応不能の理由: 道路から 4 km を超える（地形） / 通行止めで行けない
        self.unreach_reason = {}
        for j in self.unreachable:
            geo = ((dist[:, j] <= R1) & can_launch).any()
            self.unreach_reason[self.target_ids[j]] = "通行止めで届く離陸地点に行けない" if geo else "一般道から 4 km を超える"

        self._enumerate_flights(dist, R1, starts)
        self.launch = sorted({f["node"] for f in self.flights})
        if self.launch:
            DL = dijkstra(self.G, indices=self.launch)
            self.drive_ll = {v: DL[i] for i, v in enumerate(self.launch)}
        else:
            self.drive_ll = {}

    def _enumerate_flights(self, dist, R1, starts):
        """離陸地点 v から, 通信断センサー 1〜3 基を最短の順で回って v に戻る飛行（15 分以内）"""
        nodes = self.nodes
        flights = {}
        for v in self.launch_all:
            cand = [j for j in self.recoverable if dist[v, j] <= FLIGHT_MIN * DRONE_M_PER_MIN / 2]
            for k in range(1, MAX_PER_FLIGHT + 1):
                for comb in itertools.combinations(cand, k):
                    best = None
                    for perm in itertools.permutations(comb):
                        P = [nodes[v]] + [self.sxy[j] for j in perm] + [nodes[v]]
                        legs = [float(np.hypot(*(P[i + 1] - P[i]))) for i in range(len(P) - 1)]
                        tt = sum(legs) / DRONE_M_PER_MIN + HOVER_MIN * k
                        if tt <= FLIGHT_MIN + 1e-9 and (best is None or tt < best[0]):
                            off, acc = [], 0.0
                            for i, j in enumerate(perm):
                                acc += legs[i] / DRONE_M_PER_MIN + HOVER_MIN
                                off.append(acc)
                            best = (tt, perm, off)
                    if best is not None:
                        flights.setdefault(tuple(sorted(comb)), []).append(
                            dict(node=v, dur=best[0], order=list(best[1]), offset=best[2]))
        # センサーの組ごとに, 各拠点から「走行 + 飛行」が最短の離陸地点だけを残す
        # （+ 飛行時間が最短の地点も残す: 同じ地点にとどまって続けて飛ぶ計画のため）
        self.flights = []
        for key, lst in flights.items():
            keep = {min(range(len(lst)), key=lambda i: lst[i]["dur"])}
            for s in starts:
                keep.add(min(range(len(lst)), key=lambda i: self.drive_from[s][lst[i]["node"]] + lst[i]["dur"]))
            for i in sorted(keep):
                f = dict(lst[i]); f["sensors"] = key
                self.flights.append(f)

    def lower_bound(self):
        """枠割当の最大流による下界（slot_lower_bound）. 元の下界 model.Instance.lower_bound 以上"""
        if getattr(self, "_lb", None) is None or self._lb[0] is not self.trucks or self._lb[1] != len(self.recoverable):
            self._lb = (self.trucks, len(self.recoverable), slot_lower_bound(self))
        return self._lb[2]

    def drive(self, a, b):
        """a → b の走行時間 + 離陸準備（a ≠ b のとき）"""
        if a == b:
            return 0.0
        if a in self.drive_ll:
            return float(self.drive_ll[a][b]) + self.setup
        if b in self.drive_ll:
            return float(self.drive_ll[b][a]) + self.setup
        return float(self.drive_from[a][b])


# ---------------------------------------------------------------------- 下界（スロット割当の最大流）
def slot_lower_bound(I, return_detail=False):
    """メイクスパンの下界. 「センサー j を車 t の k 番目の飛行で回復する最も早い時刻 e[t,k,j]」を
    動的計画法で下から見積もり（qubo_bisect と同じ枠の下界）, 上限 T のもとで
      全センサーを, 異なる (車, 枠) に e ≤ T で割り当てられるか
    を最大流で判定し, T を二分探索する. 予備バッテリーで増える枠 6〜9 は, 全車合わせて 4 × 予備の数まで.
    （1 つの枠で回るセンサーは 1 基という前提. 2 基以上を回る飛行があるときは使わない）"""
    from scipy.sparse.csgraph import maximum_flow
    from model import CHARGE_MIN
    if any(len(f["sensors"]) > 1 for f in I.flights):
        return model.Instance.lower_bound(I)
    J = list(I.recoverable)
    if not J:
        return 0.0
    jpos = {j: i for i, j in enumerate(J)}
    F = len(I.flights)
    E = []          # (j, t, k, e)
    for ti, tr in enumerate(I.trucks):
        S1 = {}
        for fi, f in enumerate(I.flights):
            d = I.drive_from[tr.node][f["node"]]
            if np.isfinite(d):
                S1[fi] = max(tr.t0 + d, tr.ready)
        fl = list(S1)
        LB = dict(S1)
        for k in range(1, tr.cap(True) + 1):
            if k > 1:
                new = {}
                for fi in fl:
                    best = np.inf
                    for gi in fl:
                        if gi == fi:
                            continue
                        vg, vf = I.flights[gi]["node"], I.flights[fi]["node"]
                        dv = I.drive(vg, vf) if vg != vf else 0.0
                        best = min(best, LB[gi] + I.flights[gi]["dur"] + max(dv, CHARGE_MIN))
                    new[fi] = max(S1[fi], best)
                LB = new
            ej = {}
            for fi in fl:
                f = I.flights[fi]
                for j, o in zip(f["order"], f["offset"]):
                    ej[j] = min(ej.get(j, np.inf), LB[fi] + o)
            for j, e in ej.items():
                if j in jpos and np.isfinite(e):
                    E.append((jpos[j], ti, k, e))
    nT = len(I.trucks)
    K = max(tr.cap(True) for tr in I.trucks)
    base_cap = [tr.cap(False) for tr in I.trucks]
    extra = 4 * I.spares_left
    nJ = len(J)
    # 頂点: 0 = 始点, 1..nJ = センサー, 次に (t,k) の枠, ハブ, 終点
    slot0 = 1 + nJ
    hub = slot0 + nT * K
    sink = hub + 1

    def feasible(T):
        r, c, w = [], [], []
        for i in range(nJ):
            r.append(0); c.append(1 + i); w.append(1)
        used = set()
        for (i, ti, k, e) in E:
            if e <= T + 1e-9:
                r.append(1 + i); c.append(slot0 + ti * K + k - 1); w.append(1); used.add((ti, k))
        for (ti, k) in used:
            v = slot0 + ti * K + k - 1
            if k <= base_cap[ti]:
                r.append(v); c.append(sink); w.append(1)
            else:
                r.append(v); c.append(hub); w.append(1)
        r.append(hub); c.append(sink); w.append(max(extra, 0))
        M = sp.csr_matrix((np.array(w, np.int32), (r, c)), shape=(sink + 1, sink + 1))
        return maximum_flow(M, 0, sink).flow_value == nJ

    vals = sorted({e for *_, e in E})
    lo, hi = 0, len(vals) - 1
    if not feasible(vals[hi]):
        return float("inf")
    while lo < hi:
        mid = (lo + hi) // 2
        if feasible(vals[mid]):
            hi = mid
        else:
            lo = mid + 1
    return float(vals[lo])


# ---------------------------------------------------------------------- 災害シナリオの生成
def prefecture_paths():
    from matplotlib.path import Path
    M = json.load(open(os.path.join(DATA, "municipalities.geojson")))["features"]
    return [Path(np.array(f["geometry"]["coordinates"][0])) for f in M]


FAMILIES = {
    # 名前: (震源の数, 通信断の半径 km, 通行止めの数（震源 1 つあたり）, 通信断の確率, 高速道路の閉鎖を強める, 車の減少, 予備バッテリーの数)
    "A_同等":   dict(n_epi=1, R_fail=20.0, n_closed=34, p_fail=0.92, motorway_mult=1.0, fleet_cut=0, spares=(1, 1)),
    "B_大地震": dict(n_epi=1, R_fail=30.0, n_closed=80, p_fail=0.92, motorway_mult=2.0, fleet_cut=0, spares=(1, 1)),
    "C_複合":   dict(n_epi=2, R_fail=18.0, n_closed=35, p_fail=0.92, motorway_mult=1.0, fleet_cut=1, spares=(0, 2)),
    "D_広域":   dict(n_epi=1, R_fail=42.0, n_closed=130, p_fail=0.92, motorway_mult=2.0, fleet_cut=0, spares=(2, 2)),
    "E_連続大地震": dict(n_epi=2, R_fail=32.0, n_closed=90, p_fail=0.92, motorway_mult=2.0, fleet_cut=1, spares=(1, 2)),
}


def make_real_scenario(rw, family, seed, base=None):
    """サンプルの傾向に合わせた災害を作る
       通信断   震源から R_fail 以内の候補地が確率 p_fail で通信断（サンプル: 20 km 以内の 19 基中 18 基）
       通行止め 区間の中点が震源に近いほど, また橋・トンネルほど閉じやすい（サンプル: 20 km 以内の
                橋・トンネル 35 区間中 10, それ以外 308 区間中 24）. 確率 ∝ exp(−(d / 12 km)²) × (橋・トンネルなら 3.5)
       C_複合   震源 2 つ（別々の地震が重なる）, どこか 1 つの拠点の車が半分に, 予備バッテリー 0〜2 個"""
    base = base or load_sample()
    P = FAMILIES[family]
    rng = np.random.default_rng(seed * 101 + list(FAMILIES).index(family))   # 系統ごとに別の震源
    paths = prefecture_paths()
    allxy = np.vstack([p.vertices for p in paths])
    lo, hi = allxy.min(0), allxy.max(0)
    epis = []
    while len(epis) < P["n_epi"]:
        e = lo + rng.random(2) * (hi - lo)
        if any(p.contains_point(e) for p in paths):
            if all(np.hypot(*(e - q)) > 25000 for q in epis):
                epis.append(e)
    fail = np.zeros(len(rw.sensor_ids), bool)
    segmid = np.array([np.mean(s["geom"], 0) for s in rw.seg])
    closed = set()
    for e in epis:
        d = np.hypot(*(rw.sensor_xy - e).T)
        fail |= (d <= P["R_fail"] * 1000) & (rng.random(len(d)) < P["p_fail"])
        ds = np.hypot(*(segmid - e).T)
        w = np.exp(-(ds / 12000.0) ** 2) * np.array([3.5 if s["structure"] != "none" else 1.0 for s in rw.seg]) \
            * np.array([P["motorway_mult"] if s["hw"].startswith("motorway") else 1.0 for s in rw.seg])
        n_cl = int(rng.poisson(P["n_closed"]))
        idx = rng.choice(len(rw.seg), size=min(n_cl, int((w > 1e-6).sum())), replace=False, p=w / w.sum())
        closed |= {rw.seg_ids[i] for i in idx}
    if not fail.any():
        d = np.hypot(*(rw.sensor_xy - epis[0]).T)
        fail[np.argmin(d)] = True
    sc = json.loads(json.dumps(base))
    sc["scenario_id"] = f"{family}_{seed}"
    sc["description"] = f"{family}: 震源 {[list(np.round(e)) for e in epis]}"
    sc["epicenters"] = [e.tolist() for e in epis]
    sc["disconnected_sensors"] = [rw.sensor_ids[i] for i in np.nonzero(fail)[0]]
    sc["closed_segments"] = sorted(closed)
    if P["fleet_cut"]:
        b = int(rng.integers(len(sc["drone_bases"])))
        sc["drone_bases"][b]["num_vehicles"] = max(1, sc["drone_bases"][b]["num_vehicles"] // 2)
    sc["fleet"]["total_spare_batteries"] = int(rng.integers(P["spares"][0], P["spares"][1] + 1))
    return sc


def load_sample(path=os.path.join(DATA, "phase2_real", "scenario_sample.json")):
    return json.load(open(path))


if __name__ == "__main__":
    import time
    rw = RealWorld()
    sc = load_sample()
    t0 = time.time()
    I = RealInstance(rw, sc)
    print("前処理", round(time.time() - t0, 2), "秒")
    print("通信断", len(I.targets), "回復可能", len(I.recoverable), "対応不能", len(I.unreachable), I.unreach_reason)
    print("飛行", len(I.flights), "うち 2 基以上", sum(len(f["sensors"]) > 1 for f in I.flights), "離陸地点", len(I.launch))
    print("下界", round(I.lower_bound(), 1), "枠割当の下界", round(slot_lower_bound(I), 1), round(time.time() - t0, 2), "秒")
    for fam in FAMILIES:
        for sd in range(3):
            sc2 = make_real_scenario(rw, fam, sd)
            J = RealInstance(rw, sc2)
            print(fam, sd, "通信断", len(J.targets), "回復可能", len(J.recoverable), "通行止め", len(sc2["closed_segments"]),
                  "車", len(J.trucks), "予備", J.spares_left, "飛行", len(J.flights), "下界", round(J.lower_bound(), 1), round(slot_lower_bound(J), 1))
