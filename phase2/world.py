"""
phase2/world.py : Phase 2（災害時ドローン臨時通信確保）の合成データを作る

  課題資料（theme_20261022）の設定に合わせ, これまでのデータ (data_transformed.json) から作る.
  道路網・拠点・災害シナリオは実データではなく合成である.

  - センサー : Phase 1 の最適配置 (200 m マスで解いた MILP 解, 85 基) を設置済みとする
  - 道路網   : 県内に約 4 km 間隔で交差点を置き, ドロネー三角形分割の辺から道路を作る
               種類 = 高速道路 (80 km/h, IC・JCT でのみ乗り降り) / 国道 (50) / 主要地方道 (40) / 一般道 (30)
               通行止めの単位として 1 km 以下の区間 (セグメント) に分ける
  - 拠点     : 県庁 (中央市) 4 台, 西南市役所 2 台, 北東町役場 2 台 のドック搭載車
  - 災害     : 震源の近くほど, センサーの通信断・道路区間の通行止めが起きやすい
"""
import json
import os
import numpy as np
from matplotlib.path import Path
from scipy.spatial import Delaunay
from scipy.sparse.csgraph import minimum_spanning_tree, dijkstra
import scipy.sparse as sp

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
DATA = os.path.join(ROOT, "data", "data_transformed.json")
FINE = os.path.join(ROOT, "results", "placement_fine_grid.json")

SPEED_KMH = {"expressway": 80.0, "national": 50.0, "major": 40.0, "local": 30.0}


def _load_base():
    raw = json.load(open(DATA, encoding="utf-8"))
    mus = raw["municipalities"]
    names = [m["name"].split(" (")[0] for m in mus]
    polys = [np.array(m["polygon_vertices"], float) for m in mus]
    pref = np.array(raw["prefecture_outer_boundary"]["vertices"], float)
    pts, pid, preg = [], [], []
    for mi, m in enumerate(mus):
        for c in m["candidate_locations"]:
            pts.append([c["x"], c["y"]]); pid.append(c["id"]); preg.append(mi)
    kname = [s["sensor_type_id"].split("-")[1] for s in raw["sensor_specifications"]]
    return names, polys, pref, np.array(pts), pid, np.array(preg), kname


def _poisson_disk(pref, spacing, rng, tries=60000):
    lo, hi = pref.min(0), pref.max(0)
    path = Path(pref)
    pts = []
    for _ in range(tries):
        q = lo + rng.random(2) * (hi - lo)
        if not path.contains_point(q):
            continue
        if pts and np.min(np.hypot(*(np.array(pts) - q).T)) < spacing:
            continue
        pts.append(q)
    return np.array(pts)


def build_world(seed=7, spacing=4000.0, keep_extra=0.45):
    rng = np.random.default_rng(seed)
    names, polys, pref, cpts, pid, preg, kname = _load_base()
    path = Path(pref)

    # ---- 交差点: 一様な点 + 各候補地の近く (候補地は一般道から 6 km 以内という資料の条件を満たす)
    nodes = list(_poisson_disk(pref, spacing, rng))
    for c in cpts:
        for _ in range(50):
            ang, r = rng.random() * 2 * np.pi, 800 + rng.random() * 2200
            q = c + r * np.array([np.cos(ang), np.sin(ang)])
            if path.contains_point(q):
                nodes.append(q); break
    # 拠点 (市役所など) を交差点として足す
    cen = {n: P.mean(0) for n, P in zip(names, polys)}
    depot_xy = {"県庁": cen["中央市"] + np.array([-1500.0, 1500.0]),
                "西南市役所": cen["西南市"], "北東町役場": cen["北東町"]}
    for q in depot_xy.values():
        nodes.append(q)
    nodes = np.array(nodes)

    # ---- 道路: ドロネー三角形分割の辺 → 最小全域木は必ず残し, 残りは一部だけ残す
    tri = Delaunay(nodes)
    E = set()
    for s in tri.simplices:
        for a, b in ((s[0], s[1]), (s[1], s[2]), (s[0], s[2])):
            a, b = min(a, b), max(a, b)
            L = np.hypot(*(nodes[a] - nodes[b]))
            mid = (nodes[a] + nodes[b]) / 2
            if L < 9000 and path.contains_point(mid):
                E.add((a, b))
    E = sorted(E)
    n = len(nodes)
    W = sp.coo_matrix(([np.hypot(*(nodes[a] - nodes[b])) for a, b in E], ([a for a, b in E], [b for a, b in E])),
                      shape=(n, n)).tocsr()
    mst = minimum_spanning_tree(W).tocoo()
    keep = {(min(a, b), max(a, b)) for a, b in zip(mst.row, mst.col)}
    for e in E:
        if e not in keep and rng.random() < keep_extra:
            keep.add(e)
    edges = sorted(keep)
    length = {e: float(np.hypot(*(nodes[e[0]] - nodes[e[1]]))) for e in edges}

    # ---- 道路の種類: 拠点・市町村の中心を結ぶ最短路を国道, その周辺の一部を主要地方道に
    def nearest(q):
        return int(np.argmin(np.hypot(*(nodes - q).T)))

    adj = sp.coo_matrix(([length[e] for e in edges] * 2,
                         ([a for a, b in edges] + [b for a, b in edges], [b for a, b in edges] + [a for a, b in edges])),
                        shape=(n, n)).tocsr()
    cls = {e: "local" for e in edges}

    def mark_path(src, dst, c):
        _, pred = dijkstra(adj, indices=src, return_predecessors=True)
        v = dst
        out = []
        while v != src and v >= 0:
            u = pred[v]
            if u < 0:
                break
            out.append((min(u, v), max(u, v)))
            v = u
        for e in out:
            rank = ["local", "major", "national", "expressway"]
            if rank.index(c) > rank.index(cls[e]):
                cls[e] = c
        return out

    depot_node = {k: nearest(q) for k, q in depot_xy.items()}
    hubs = [nearest(q) for q in cen.values()] + list(depot_node.values())
    for i in range(len(hubs)):
        for j in range(i + 1, len(hubs)):
            if np.hypot(*(nodes[hubs[i]] - nodes[hubs[j]])) < 45000:
                mark_path(hubs[i], hubs[j], "national")
    for e in edges:
        if cls[e] == "local" and rng.random() < 0.18:
            cls[e] = "major"

    # ---- 高速道路: 3 つの IC と 1 つの JCT を結ぶ. 別の層の道として作り, IC・JCT でだけ一般道とつなぐ
    ic_xy = {"西南IC": cen["西南市"] + np.array([6000.0, 6000.0]), "北東IC": cen["北東町"] + np.array([-6000.0, -4000.0]),
             "北西IC": cen["北西市"] + np.array([3000.0, -6000.0]), "中央JCT": cen["中央市"] + np.array([-3000.0, -3000.0])}
    ic_node = {k: nearest(q) for k, q in ic_xy.items()}
    exp_edges = []
    for k in ("西南IC", "北東IC", "北西IC"):
        a, b = nodes[ic_node[k]], nodes[ic_node["中央JCT"]]
        exp_edges.append((k, "中央JCT", float(np.hypot(*(a - b)) * 1.05)))

    # ---- 通行止めの単位: 1 km 以下の区間に分ける
    segs = []           # (edge index, k, mid x, mid y)
    edge_list = []
    for i, e in enumerate(edges):
        L = length[e]
        k = max(1, int(np.ceil(L / 1000.0)))
        for j in range(k):
            t = (j + 0.5) / k
            mid = nodes[e[0]] * (1 - t) + nodes[e[1]] * t
            segs.append((i, j, float(mid[0]), float(mid[1])))
        edge_list.append(dict(a=int(e[0]), b=int(e[1]), length_m=L, cls=cls[e], n_seg=k))

    # ---- センサー: Phase 1 の最適配置 (200 m マス) を設置済みとする
    fine = json.load(open(FINE))
    x = np.array([r for r in fine if r["solve_grid_m"] == 200][0]["x"])
    sensors = []
    for p in range(len(cpts)):
        ks = np.nonzero(x[p])[0]
        if len(ks):
            sensors.append(dict(id=pid[p], muni=names[preg[p]], x=float(cpts[p, 0]), y=float(cpts[p, 1]),
                                kind=kname[ks[0]]))
    return dict(seed=seed, nodes=nodes.round(1).tolist(), edges=edge_list,
                segments=[dict(edge=s[0], k=s[1], x=round(s[2], 1), y=round(s[3], 1)) for s in segs],
                expressway=dict(ic_node=ic_node, edges=exp_edges),
                depots=[dict(name=k, node=depot_node[k], trucks=t) for k, t in
                        (("県庁", 4), ("西南市役所", 2), ("北東町役場", 2))],
                sensors=sensors, municipalities=names, pref=pref.tolist(),
                polys=[P.tolist() for P in polys], centers={k: v.tolist() for k, v in cen.items()})


def _dist_to_segment(P, a, b):
    v = b - a
    t = np.clip(((P - a) @ v) / (v @ v), 0, 1)
    return np.hypot(*(P - (a + t[:, None] * v)).T)


def make_scenario(world, seed=1, epicenter=None, n_fail=18, n_closed=34, fail_r=12000.0, close_r=9000.0,
                  fault_len=0.0, fault_angle=None, fault_w=1200.0):
    """震源に近いセンサー・道路区間ほど選ばれやすいように, 決まった数だけ通信断・通行止めにする.
    fault_len > 0 なら, 通行止めは震源を通る断層の線 (長さ fault_len) の近くに集中させる"""
    rng = np.random.default_rng(seed)
    cen = world["centers"]
    if epicenter is None:
        epicenter = (np.array(cen["東南村"]) + np.array([-9000.0, 0.0])).tolist()   # 東南村西部
    E = np.array(epicenter)
    S = np.array([[s["x"], s["y"]] for s in world["sensors"]])
    d = np.hypot(*(S - E).T)
    w = np.exp(-(d / fail_r) ** 2) + 1e-9
    fail = rng.choice(len(S), size=min(n_fail, len(S)), replace=False, p=w / w.sum())
    G = np.array([[s["x"], s["y"]] for s in world["segments"]])
    if fault_len > 0:
        ang = rng.random() * np.pi if fault_angle is None else fault_angle
        u = np.array([np.cos(ang), np.sin(ang)]) * fault_len / 2
        dg = _dist_to_segment(G, E - u, E + u)
        wg = np.exp(-(dg / fault_w) ** 2) + 1e-12
    else:
        dg = np.hypot(*(G - E).T)
        wg = np.exp(-(dg / close_r) ** 2) + 1e-12
    closed = rng.choice(len(G), size=min(n_closed, len(G)), replace=False, p=wg / wg.sum())
    return dict(seed=seed, epicenter=list(map(float, E)), failed=sorted(int(i) for i in fail),
                closed_segments=sorted(int(i) for i in closed), fault_len=fault_len)


if __name__ == "__main__":
    w = build_world()
    sc = make_scenario(w)
    os.makedirs(os.path.join(ROOT, "data"), exist_ok=True)
    json.dump(w, open(os.path.join(ROOT, "data", "phase2_world.json"), "w"), ensure_ascii=False)
    json.dump(sc, open(os.path.join(ROOT, "data", "phase2_scenario_sample.json"), "w"), ensure_ascii=False, indent=1)
    from collections import Counter
    print("交差点", len(w["nodes"]), "道路", len(w["edges"]), "区間", len(w["segments"]),
          Counter(e["cls"] for e in w["edges"]), "センサー", len(w["sensors"]))
    print("通信断", len(sc["failed"]), "通行止め", len(sc["closed_segments"]))
