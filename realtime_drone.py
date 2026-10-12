"""
realtime_drone.py : 任意の地域データ (JSON) で, ドローン群の動きを毎秒 QUBO で最適化し直す.
                    飛行中にトラブルを見つけたら, その場で QUBO を組み直す.

  毎秒 (tick_sec ごと) の処理
    1. トラブルの検知
         - hazard   (火災・強風など)   : 機体の見える範囲に入ったら発見 → 以後 飛行禁止
         - survivor (要救助者など)     : 見える範囲に入ったら発見 → 誰か1機が observe_sec 秒 見守る
         - drone_failure               : 指定時刻に機体が故障して離脱
         - battery_fault               : 指定時刻にバッテリー残量が急減
       新しいトラブルがあれば「QUBO を組み直す」(制約・報酬が変わる) と記録する
    2. QUBO を組んで解く (replan_sec ごと, またはトラブル発生時は即時)
    3. 各機を1秒ぶん動かす (観測・alpha/beta の加算・バッテリー消費/充電)

  QUBO (飛行中の機体だけが対象)
    変数 x[d,h,k] : 機体 d が 先読みステップ h で 候補地点 k に向かう
                    候補地点 = 現在地を中心に 速度×plan_step_sec 間隔で並べた格子
                    (h=0 は 3×3, h=1 は 5×5). 地域外・飛行禁止区域・
                    「戻れなくなる地点」(バッテリー不足) は候補から外す (= 制約を満たす解だけ)
    H = - Σ (新たに見えるマスの価値 + alpha/beta の残り要求への寄与 + 要救助者の見守り) x
        + λ Σ (2つの候補で同じマスを見る価値) x x'         ... 重複
        + Σ (同じ市町村の alpha/beta を取り合う過剰分) x x'
        + Σ (同じ要救助者に2機以上が向かう) x x'
        + P Σ (Σ_k x[d,h,k] - 1)^2                        ... one-hot
        + P Σ x[d,0,k] x[d,1,k'] (隣り合わない格子)        ... 移動

  使い方:
    python realtime_drone.py --data data/data_transformed.json --scenario data/scenario_example.json \\
                             --out results/realtime_run.json --video videos/realtime_run.mp4
    python realtime_drone.py --data 任意の.json            # シナリオ省略時は既定値
    python realtime_drone.py ... --backend amplify --token XXXX --realtime   # 実時間 1 秒ごと
"""
import argparse
import json
import time
import numpy as np
import scipy.sparse as sp

from realtime_world import (World, deep_update, load_inputs, score_parts, value_weights,
                            cell_values, block_values)
from deploy import candidate_points, deploy
from solver_backend import solve_qubo, polish_onehot


# ------------------------------------------------------------------ 機体
class Drone:
    def __init__(self, i, spec, sensor, start, sc):
        self.i = i
        self.sensor = spec["sensor"]
        self.speed = float(spec["speed_mps"])
        self.r = float(spec["sensor_radius_m"])
        self.drain = float(spec["drain_per_sec"])
        self.alpha = float(sensor["alpha_field_response"])
        self.beta = float(sensor["beta_density_resolution"])
        self.cap = float(sc["battery"]["capacity_sec"])
        self.margin = float(sc["battery"]["reserve_margin"])
        self.battery = self.cap
        self.pos = np.array(start, float)
        self.target = self.pos.copy()
        self.mode = "fly"          # standby / fly / transit / return / charge / failed
        self.step = self.speed * sc["plan_step_sec"]
        self.base = self.pos.copy()     # 基地 (発着・充電地点)
        self.base_pt = None             # 基地にしている候補地点の番号
        self.region = None              # 担当する市町村 (None なら どこでも飛ぶ)
        self.next_pt = None             # 配置換えで次に移る候補地点 (移動前)


def point_seg_dist(c, p0, p1):
    v = p1 - p0
    L2 = float(v @ v)
    t = 0.0 if L2 == 0 else float(np.clip((c - p0) @ v / L2, 0, 1))
    return float(np.hypot(*(p0 + t * v - c)))


# ------------------------------------------------------------------ QUBO
def build_qubo(world, drones, state, sc):
    """飛行中の機体について, 先読み horizon ステップの QUBO を組む"""
    so = sc["solver"]
    H = int(sc["horizon"])
    M = world.M
    omega = 1.0 / (3 * M)
    per = float(sc["alpha_beta_per_sec"])
    margin = sc["battery"]["reserve_margin"]
    covered, A, B = state["covered"], state["A"], state["B"]
    hazards = [z for z in state["incidents"] if z["type"] == "hazard" and z["status"] == "found"]
    targets = [z for z in state["incidents"] if z["type"] == "survivor" and z["status"] == "found"]

    t = state["t"]
    base_m, wm_cov = value_weights(world, state)
    resA = np.maximum(world.req_a - A, 0)
    resB = np.maximum(world.req_b - B, 0)

    cand = []          # dict(d, h, ij, pos, p0, muni, a, b, tgt)
    for d in drones:
        for h in range(H):
            R = h + 1
            I, J = np.mgrid[-R:R + 1, -R:R + 1]
            I, J = I.ravel(), J.ravel()
            P = d.pos + d.step * np.c_[I, J]
            m = world.muni_at_many(P)
            ok = (m >= 0) if d.region is None else (m == d.region)   # 担当の市町村の外には出ない
            # 親 (1つ前のステップの格子点) から掃く
            PI, PJ = (np.zeros_like(I), np.zeros_like(J)) if h == 0 else (np.clip(I, -h, h), np.clip(J, -h, h))
            P0 = d.pos + d.step * np.c_[PI, PJ]
            for z in hazards:                                         # 飛行禁止区域を横切らない
                c = np.array([z["x"], z["y"]])
                v = P - P0
                L2 = (v ** 2).sum(1)
                tt = np.clip(((c - P0) * v).sum(1) / np.where(L2 > 0, L2, 1), 0, 1)
                ok &= np.hypot(*(P0 + tt[:, None] * v - c).T) > z["radius_m"]
            dhome = np.hypot(*(P - d.base).T)
            if d.mode == "return":
                # 帰り道: 1 ステップごとに基地へ 0.8 ステップ以上近づく候補だけ
                # (道のりは最短の 1.25 倍以内 → 電池の余裕 reserve_margin の範囲で戻れる)
                ok &= dhome <= np.hypot(*(d.pos - d.base)) - 0.8 * d.step * R
            else:
                # 戻れなくなる地点は除く
                left = d.battery - d.drain * R * sc["plan_step_sec"]
                ok &= left >= d.drain * dhome / d.speed * margin
            a = d.alpha * sc["plan_step_sec"] / per
            b = d.beta * sc["plan_step_sec"] / per
            for k in np.where(ok)[0]:
                tg = [q for q, z in enumerate(targets)
                      if np.hypot(P[k, 0] - z["x"], P[k, 1] - z["y"]) <= d.r]
                cand.append(dict(d=d.i, h=h, ij=(int(I[k]), int(J[k])), pos=P[k], p0=P0[k],
                                 r=d.r, muni=int(m[k]), a=a, b=b, tgt=tg))
    if cand:
        sws = world.swaths([c["p0"] for c in cand], [c["pos"] for c in cand], [c["r"] for c in cand])
        for c, sw in zip(cand, sws):
            c["swath"] = sw
    n = len(cand)
    if n == 0:
        return None
    allsw = np.concatenate([c["swath"] for c in cand])
    allv = cell_values(world, state, allsw, t, sc, base_m, wm_cov)
    ptr0 = np.cumsum([0] + [len(c["swath"]) for c in cand])
    for k, c in enumerate(cand):
        sw, sv = c["swath"], allv[ptr0[k]:ptr0[k + 1]]
        c["swath"], c["sval"] = sw[sv > 0], sv[sv > 0]
    slot = np.array([c["d"] * 100 + c["h"] for c in cand])
    gain = np.zeros(n)
    for k, c in enumerate(cand):
        m = c["muni"]
        gain[k] = c["sval"].sum()
        gain[k] += omega / world.req_a[m] * min(c["a"], resA[m])
        gain[k] += omega / world.req_b[m] * min(c["b"], resB[m])
    # 各 (機体, ステップ) では必ず1つ選ぶので, 候補に共通の値を引いても答えは変わらない.
    # 「その機体の候補どうしの差」だけを残して, 小さな差 (どちらへ飛ぶと多く見えるか) を際立たせる
    best = np.zeros(n)
    for s_ in np.unique(slot):
        ks = slot == s_
        gain[ks] -= gain[ks].min()
        best[ks] = gain[ks].max()
    base = max(gain.max(), 1e-12)
    tw = so["target_factor"] * base
    by_id = {d.i: d for d in drones}
    # 発見済みの要救助者: 見える範囲に入る候補に大きな報酬. まだ遠いときは
    # 最寄りの1機に「近づくほど得」な報酬を付けて向かわせる
    goto = {}
    for z in targets:
        zc = np.array([z["x"], z["y"]])
        if any(np.hypot(*(d.pos - zc)) <= d.r for d in drones):
            continue
        zm = world.muni_at(zc)
        pool = [d for d in drones if d.region == zm] or drones      # その市町村の担当機から
        dn = min(pool, key=lambda d: np.hypot(*(d.pos - zc)))
        goto.setdefault(dn.i, []).append(zc)
    for k, c in enumerate(cand):
        if c["tgt"]:
            gain[k] += tw * (1.0 if c["h"] == 0 else 0.5)
        d = by_id[c["d"]]
        for zc in goto.get(d.i, []):
            closer = np.hypot(*(d.pos - zc)) - np.hypot(*(c["pos"] - zc))
            gain[k] += 0.8 * tw * max(closer, 0.0) / (d.step * (c["h"] + 1))
        if c["h"] == 0 and np.hypot(*(c["pos"] - d.target)) < d.step * 0.5 and \
                np.hypot(*(d.target - d.pos)) > 1e-6:
            # 今の方向を続ける候補に「その機体の最良候補の inertia 倍」を上乗せ.
            # 他の方向が明らかに良いときだけ曲がる (毎秒の解き直しでジグザグしないように)
            gain[k] += so["inertia"] * best[k] + 1e-3 * base
    rows, cols, vals = [], [], []
    dd = np.array([c["d"] for c in cand])
    hh = np.array([c["h"] for c in cand])

    # ---- 次の目的地 (巡回ブロック) の変数 g[d,j]: 未巡回・期限切れのブロックへ向かわせる
    pt = sc["patrol"]
    BV, overdue = block_values(world, state, t, sc, base_m, wm_cov)
    goals, g_gain = [], []
    G0 = {}
    for d in drones:
        # 新しいマスを 1 ステップ掃いたときの典型的な価値 (目的地の報酬の物差し)
        G0[d.i] = float(np.median(base_m)) * (2 * d.r * d.step) / world.res ** 2
        if d.mode == "return":
            continue                                   # 帰還中は目的地を持たない
        bs = np.arange(world.NB) if d.region is None else np.where(world.block_muni == d.region)[0]
        dn = np.hypot(*(world.block_xy[bs] - d.pos).T)
        dh = np.hypot(*(world.block_xy[bs] - d.base).T)
        ok = (dn + dh) * d.drain / d.speed * margin <= d.battery       # 行って基地に戻れる
        bs, dn = bs[ok], dn[ok]
        if len(bs) == 0 or BV[bs].max() <= 0:
            continue
        sc_b = BV[bs] / (1 + dn / 5000.0)
        top = bs[np.argsort(-sc_b)[: int(pt["goal_candidates"])]]
        vmax = BV[top].max()
        for b in top:
            g = pt["goal_w"] * G0[d.i] * BV[b] / vmax
            if getattr(d, "goal_block", None) == b:
                g += 0.3 * pt["goal_w"] * G0[d.i]                       # 目的地を毎秒変えない
            goals.append(dict(d=d.i, b=int(b), pos=world.block_xy[b], overdue=bool(overdue[b])))
            g_gain.append(g)
    ng = len(goals)
    g_gain = np.array(g_gain)
    for d in drones:                                                    # 機体ごとに最小値を引く
        ks = [j for j, gl in enumerate(goals) if gl["d"] == d.i]
        if ks:
            g_gain[ks] -= g_gain[ks].min()
    # 目的地に近づく候補ほど得 (x と g の 2 次の結合)
    cpl = 0.0
    cpos = np.array([c["pos"] for c in cand])
    for j, gl in enumerate(goals):
        d = by_id[gl["d"]]
        ks = np.where(dd == d.i)[0]
        d0 = np.hypot(*(gl["pos"] - d.pos))
        prog = (d0 - np.hypot(*(cpos[ks] - gl["pos"]).T)) / (d.step * (hh[ks] + 1))
        r_ = pt["progress_w"] * G0[d.i] * np.minimum(prog, 1.0) * np.where(hh[ks] == 0, 1.0, 0.5)
        ok = prog > 0
        rows.append(ks[ok]); cols.append(np.full(ok.sum(), n + j)); vals.append(-r_[ok])
        if ok.any():
            cpl = max(cpl, float(r_[ok].max()))
    # 別の機体が同じ (または隣の) ブロックを目指さない
    if ng > 1:
        gpos = np.array([gl["pos"] for gl in goals]); gd = np.array([gl["d"] for gl in goals])
        gG = np.array([G0[x] for x in gd])
        iu = np.triu_indices(ng, k=1)
        near = (gd[iu[0]] != gd[iu[1]]) & \
               (np.hypot(*(gpos[iu[0]] - gpos[iu[1]]).T) < 1.5 * pt["block_m"])
        rows.append(n + iu[0][near]); cols.append(n + iu[1][near])
        vals.append(pt["goal_w"] * np.maximum(gG[iu[0][near]], gG[iu[1][near]]))
    gain = np.r_[gain, g_gain]
    slot = np.r_[slot, np.array([gl["d"] * 100 + 99 for gl in goals], int)]
    lin = -gain
    P = so["pen"] * max(gain.max(), cpl, 1e-12)

    # 重複: S (候補 × マス) から  S W S^T
    ptr = np.cumsum([0] + [len(c["swath"]) for c in cand])
    idx = np.concatenate([c["swath"] for c in cand]) if ptr[-1] else np.zeros(0, int)
    if len(idx):
        uniq, col = np.unique(idx, return_inverse=True)          # 候補が見るマスだけに詰める
        S1 = sp.csr_matrix((np.ones(len(idx)), col, ptr), shape=(n, len(uniq)))
        Sw = sp.csr_matrix((np.concatenate([c["sval"] for c in cand]), col, ptr), shape=(n, len(uniq)))
        OV = sp.triu(Sw @ S1.T, k=1).tocoo()
        keep = slot[OV.row] != slot[OV.col]
        rows.append(OV.row[keep]); cols.append(OV.col[keep]); vals.append(so["lam_ov"] * OV.data[keep])

    # alpha/beta の取り合い (同じ市町村・別の slot)
    mm = np.array([c["muni"] for c in cand])
    aa = np.array([c["a"] for c in cand]); bb = np.array([c["b"] for c in cand])
    for m in np.unique(mm):
        ks = np.where(mm == m)[0]
        if len(ks) < 2:
            continue
        iu = np.triu_indices(len(ks), k=1)
        i1, i2 = ks[iu[0]], ks[iu[1]]
        ok = slot[i1] != slot[i2]
        i1, i2 = i1[ok], i2[ok]
        pen = np.zeros(len(i1))
        for amt, res, req in ((aa, resA[m], world.req_a[m]), (bb, resB[m], world.req_b[m])):
            ex = np.clip(amt[i1] + amt[i2] - res, 0, np.minimum(amt[i1], amt[i2]))
            ex = np.minimum(ex, np.minimum(amt[i1], res) + np.minimum(amt[i2], res))
            pen += omega / req * ex
        nz = pen > 0
        rows.append(i1[nz]); cols.append(i2[nz]); vals.append(pen[nz])

    # 同じ要救助者に別の機体が同じステップで向かわない
    for k1 in range(n):
        if not cand[k1]["tgt"]:
            continue
        for k2 in range(k1 + 1, n):
            if dd[k1] != dd[k2] and hh[k1] == hh[k2] and set(cand[k1]["tgt"]) & set(cand[k2]["tgt"]):
                rows.append([k1]); cols.append([k2]); vals.append([tw])

    # one-hot (x の各 (機体, ステップ) と 目的地 g の各機体)
    offset = 0.0
    for s in np.unique(slot):
        ks = np.where(slot == s)[0]
        lin[ks] -= P
        offset += P
        iu = np.triu_indices(len(ks), k=1)
        rows.append(ks[iu[0]]); cols.append(ks[iu[1]]); vals.append(np.full(len(iu[0]), 2 * P))

    # 移動 (h と h+1 の格子が隣り合わない組)
    ij = np.array([c["ij"] for c in cand])
    for d in drones:
        for h in range(H - 1):
            k0 = np.where((dd == d.i) & (hh == h))[0]
            k1 = np.where((dd == d.i) & (hh == h + 1))[0]
            if len(k0) == 0 or len(k1) == 0:
                continue
            far = np.abs(ij[k0][:, None, :] - ij[k1][None, :, :]).max(-1) > 1
            a, b = np.nonzero(far)
            rows.append(k0[a]); cols.append(k1[b]); vals.append(np.full(len(a), P))
    return n + ng, lin, rows, cols, vals, offset, cand, goals, slot


def choose_targets(sample, n, lin, rows, cols, vals, slot, cand, goals, drones):
    """解から各機の次の目的地 (h=0 の格子点) と 目指す巡回ブロックを決める
    (one-hot を保った局所探索で磨いてから)"""
    sel = polish_onehot(n, lin, rows, cols, vals, slot, sample)
    nx = len(cand)
    tg = {d.i: cand[sel[d.i * 100]]["pos"] for d in drones if d.i * 100 in sel}
    gb = {d.i: goals[sel[d.i * 100 + 99] - nx]["b"] for d in drones if d.i * 100 + 99 in sel}
    return tg, gb


# ------------------------------------------------------------------ シミュレーション
def run(data_path, scenario_path=None, overrides=None, token=None, realtime=False, verbose=True):
    data, sc = load_inputs(data_path, scenario_path)
    sc = deep_update(sc, overrides)
    world = World(data, sc)
    so = sc["solver"]
    dt = float(sc["tick_sec"])

    drones = []
    for spec in sc["fleet"]:
        if spec["sensor"] not in world.sens:
            raise ValueError(f"センサー種別 {spec['sensor']} が入力データにありません")
        for _ in range(int(spec["count"])):
            st = world.stations[len(drones) % len(world.stations)]
            drones.append(Drone(len(drones), spec, world.sens[spec["sensor"]], st, sc))
    # 交代運用: launch_waves 組に分け, launch_interval_sec ずつずらして出発
    waves = max(1, int(sc.get("launch_waves", 1)))
    for d in drones:
        d.launch_t = (d.i % waves) * float(sc.get("launch_interval_sec", 0))
        if d.launch_t > 0:
            d.mode = "standby"

    margin = sc["battery"]["reserve_margin"]
    dep = sc["deployment"]
    pts = reg = None
    deployments = []

    def try_transit(d):
        """配置換えが決まっていて, 新しい基地まで電池が持つなら移動を始める"""
        if d.next_pt is None:
            return False
        dist = float(np.hypot(*(pts[d.next_pt] - d.pos)))
        if d.battery >= d.drain * dist / d.speed * margin + d.drain:
            d.mode = "transit"
            return True
        return False

    def apply_deploy(t, trigger, moving_cost):
        state["t"] = t
        active = [d for d in drones if d.mode != "failed"]
        assign, info = deploy(world, active, pts, reg, state, sc, token=token,
                              moving_cost=moving_cost, seed=int(so["seed"] + t))
        moved = []
        for d in active:
            p = int(assign[d.i])
            if d.base_pt is None:                      # 初期配置: 基地から出発
                d.base_pt, d.base, d.region = p, pts[p].copy(), int(reg[p])
                d.pos, d.target = pts[p].copy(), pts[p].copy()
            elif p == d.base_pt and d.next_pt is not None:    # 配置換えの取り消し
                d.next_pt, d.region = None, int(reg[p])
                if d.mode == "transit":
                    d.mode = "fly"
            elif d.mode == "transit":
                continue                               # 移動中は行き先を変えない (電池の安全のため)
            elif p != d.base_pt and p != d.next_pt:
                moved.append((d.i, int(d.region), int(reg[p])))
                d.next_pt, d.region = p, int(reg[p])
                if d.mode == "fly" and not try_transit(d):
                    d.mode = "return"                  # 電池が足りなければ 一度戻って充電してから
        counts = np.bincount([d.region for d in active], minlength=world.M).tolist()
        deployments.append(dict(t=t, trigger=trigger, counts=counts, moved=moved,
                                assign={d.i: int(d.next_pt if d.next_pt is not None else d.base_pt)
                                        for d in active}, **info))
        return moved, counts

    state = dict(covered=np.zeros(world.nx * world.ny, bool),
                 first_seen=np.full(world.nx * world.ny, np.inf, np.float32),
                 A=np.zeros(world.M), B=np.zeros(world.M), incidents=[],
                 last_seen=np.full(world.nx * world.ny, -np.inf, np.float32),   # 最後に見た時刻
                 block_visit=np.full(world.NB, -np.inf),                         # ブロックを最後に通った時刻
                 block_snaps=[], sc=sc, t=0.0)
    for k, z in enumerate(sc["incidents"]):
        z = dict(z); z["id"] = k
        z["status"] = "scheduled" if z["type"] in ("drone_failure", "battery_fault") else "hidden"
        z.setdefault("radius_m", 0.0); z.setdefault("observe_sec", 60); z["watched"] = 0.0
        state["incidents"].append(z)

    events, replans, track = [], [], []
    if dep.get("enabled", True):
        pts, reg = candidate_points(world, data, int(dep.get("auto_candidates", 10)),
                                    float(dep.get("extra_grid_m", 0)))
        _, counts = apply_deploy(0.0, "initial", moving_cost=False)
        events.append(dict(t=0.0, kind="deploy", msg="初期配置: " + " ".join(
            f"{world.names[m].split(' (')[0]}{c}機" for m, c in enumerate(counts))))
        if verbose:
            print("[t=     0s] 初期配置 (配置 QUBO):", events[-1]["msg"], flush=True)
    else:
        pts, reg = world.stations, np.full(len(world.stations), -1)
        for d in drones:
            d.base_pt = d.i % len(pts)
    last_deploy = 0.0
    carry = []                         # 前の秒の移動中に起きたトラブル (電池切れ) → 次の秒に組み直す
    last_plan = -1e9
    t = 0.0
    wall0 = time.time()
    while t < sc["duration_sec"] - 1e-9:
        tick_wall = time.time()
        new_events, carry = carry, []
        # ---- 1) トラブルの検知
        for z in state["incidents"]:
            if z["status"] == "scheduled" and t >= z["time_sec"]:
                d = drones[int(z["drone"]) - 1]        # 機体番号は 1 始まり
                if z["type"] == "drone_failure" and d.mode != "failed":
                    d.mode = "failed"
                    new_events.append(dict(t=t, kind="drone_failure", drone=d.i,
                                           msg=f"機体{d.i + 1} が故障して離脱"))
                elif z["type"] == "battery_fault":
                    d.battery = min(d.battery, z.get("battery_ratio", 0.2) * d.cap)
                    new_events.append(dict(t=t, kind="battery_fault", drone=d.i,
                                           msg=f"機体{d.i + 1} のバッテリー異常 (残量 {d.battery / d.cap:.0%})"))
                z["status"] = "done"
            elif z["status"] == "hidden" and t >= z.get("appear_sec", 0):
                c = np.array([z["x"], z["y"]])
                for d in drones:
                    if d.mode in ("fly", "transit", "return") and np.hypot(*(d.pos - c)) <= z["radius_m"] + d.r:
                        z["status"] = "found"; z["found_t"] = t; z["found_by"] = d.i
                        label = z.get("label", z["type"])
                        new_events.append(dict(t=t, kind=f"found_{z['type']}", drone=d.i, incident=z["id"],
                                               msg=f"機体{d.i + 1} が {label} を発見"))
                        break
            elif z["status"] == "found" and z["type"] == "survivor":
                c = np.array([z["x"], z["y"]])
                if any(d.mode == "fly" and np.hypot(*(d.pos - c)) <= d.r for d in drones):
                    z["watched"] += dt
                if z["watched"] >= z["observe_sec"]:
                    z["status"] = "resolved"; z["resolved_t"] = t
                    new_events.append(dict(t=t, kind="resolved", incident=z["id"],
                                           msg=f"{z.get('label', '要救助者')} の見守り完了"))
        events += [e for e in new_events if e not in events]
        if verbose:
            for e in new_events:
                print(f"[t={t:6.0f}s] ⚠ {e['msg']} → QUBO を組み直します", flush=True)

        # ---- 1.5) 配置の見直し (定期 / 機体が減ったときは即時)
        lost = [e for e in new_events if e["kind"] in ("drone_failure", "battery_empty")]
        if dep.get("enabled", True) and t > 0 and (lost or t - last_deploy >= dep["redeploy_sec"] - 1e-9):
            why = "機体の離脱" if lost else "定期"
            moved, counts = apply_deploy(t, "event" if lost else "periodic", moving_cost=True)
            last_deploy = t
            msg = f"配置を見直し ({why}): " + (", ".join(
                f"機体{i + 1} {world.names[a].split(' (')[0]}→{world.names[b].split(' (')[0]}"
                for i, a, b in moved[:3]) + (" ほか" if len(moved) > 3 else "") if moved else "変更なし")
            e = dict(t=t, kind="redeploy", msg=msg)
            events.append(e)
            new_events.append(e)
            if verbose:
                print(f"[t={t:6.0f}s] 配置 QUBO: {msg}", flush=True)

        # ---- 2) 最適化 (定期 / トラブル発生時は即時)
        flying = [d for d in drones if d.mode in ("fly", "return")]
        trigger = "event" if new_events else ("periodic" if t - last_plan >= sc["replan_sec"] - 1e-9 else None)
        if trigger and flying:
            tb = time.time()
            state["t"] = t
            built = build_qubo(world, flying, state, sc)
            t_build = time.time() - tb
            if built is None:
                for d in flying:
                    d.mode, d.target = "return", d.base.copy()
            else:
                n, lin, rows, cols, vals, off, cand, goals, slot = built
                Pq = float(-lin.min())                           # ≒ one-hot のペナルティの大きさ
                samples, _, t_solve, nq = solve_qubo(
                    n, lin, rows, cols, vals, off, backend=so["backend"],
                    num_reads=so["num_reads"], num_sweeps=so["num_sweeps"],
                    seed=int(so["seed"] + t), token=token, time_limit_ms=so["time_limit_ms"],
                    beta_range=(np.log(2) / (2 * Pq), np.log(100) / (0.005 * Pq)))
                tg, gb = choose_targets(samples[0], n, lin, rows, cols, vals, slot, cand, goals, flying)
                for d in flying:
                    d.goal_block = gb.get(d.i)
                    if d.i in tg:
                        d.target = tg[d.i]
                    else:                       # 戻れる候補が残っていない → 基地へ一直線
                        d.mode, d.target = "return", d.base.copy()
                replans.append(dict(t=t, trigger=trigger, n_drones=len(flying), n_vars=int(n),
                                    n_quadratic=int(nq), build_ms=1000 * t_build,
                                    solve_ms=1000 * t_solve,
                                    events=[e["kind"] for e in new_events]))
            last_plan = t

        # ---- 3) 1 秒ぶん動かす
        for d in drones:
            if d.mode == "failed":
                continue
            if d.mode == "standby":
                if t + dt >= d.launch_t and not try_transit(d):
                    d.mode = "fly"; d.target = d.pos.copy()
                continue
            if d.mode == "charge":
                d.battery = min(d.cap, d.battery + d.cap / sc["battery"]["full_charge_sec"] * dt)
                if d.battery >= sc["battery"]["resume_ratio"] * d.cap and not try_transit(d):
                    d.mode = "fly"; d.target = d.pos.copy()
                continue
            dist = float(np.hypot(*(d.base - d.pos)))
            if d.mode == "fly":
                need = d.drain * (dist / d.speed * margin + dt)
                if d.battery - d.drain * dt < need:
                    d.mode = "return"
            if d.mode == "return" and np.hypot(*(d.target - d.base)) >= dist - 1e-6:
                d.target = d.base.copy()        # 基地へ近づかない目的地は使わない
            goal = pts[d.next_pt] if d.mode == "transit" and d.next_pt is not None else d.target
            v = goal - d.pos
            L = float(np.hypot(*v))
            step = min(L, d.speed * dt)
            new = d.pos + (v / L * step if L > 0 else 0)
            sw = world.swath(d.pos, new, d.r)
            fresh = sw[~state["covered"][sw]]
            state["covered"][fresh] = True
            state["first_seen"][fresh] = t + dt
            state["last_seen"][sw] = t + dt
            c_ = world.cell_of(new)
            if c_ >= 0 and world.block_of[c_] >= 0:
                state["block_visit"][world.block_of[c_]] = t + dt          # このブロックを巡回した
            m = world.muni_at(new)
            if m >= 0:
                state["A"][m] += d.alpha * dt / sc["alpha_beta_per_sec"]
                state["B"][m] += d.beta * dt / sc["alpha_beta_per_sec"]
            d.pos = new
            d.battery -= d.drain * dt
            if d.mode == "return" and np.hypot(*(new - d.base)) <= 1e-6:
                d.mode = "charge"
            elif d.mode == "return" and L <= d.speed * dt + 1e-6:
                d.target = d.base.copy()        # 途中の目的地に着いた → 次の秒の最適化まで基地へ
            elif d.mode == "transit" and L <= d.speed * dt + 1e-6:   # 新しい基地に着いた
                d.base_pt, d.base, d.next_pt = d.next_pt, pts[d.next_pt].copy(), None
                d.mode, d.target = "fly", d.pos.copy()
            if d.battery < 0:
                d.mode = "failed"
                carry.append(dict(t=t, kind="battery_empty", drone=d.i,
                                  msg=f"機体{d.i + 1} が電池切れで不時着"))

        t += dt
        sc_now, _, met = score_parts(world, state["covered"], state["A"], state["B"])
        bv = state["block_visit"]
        visited = float(np.isfinite(bv).mean())                                     # 一度でも巡回
        fresh_b = float((t - bv <= sc["patrol"]["revisit_sec"]).mean())             # 期限内に巡回
        if int(t) % int(sc.get("video_every_sec", 15)) == 0:
            state["block_snaps"].append((t, bv.copy()))
        track.append(dict(t=t, score=sc_now, met=met, visited=round(visited, 4), fresh=round(fresh_b, 4),
                          pos=[[round(float(d.pos[0]), 1), round(float(d.pos[1]), 1)] for d in drones],
                          bat=[round(d.battery / d.cap, 3) for d in drones],
                          mode=[d.mode for d in drones],
                          base=[int(d.base_pt) if d.base_pt is not None else -1 for d in drones],
                          region=[-1 if d.region is None else int(d.region) for d in drones]))
        if verbose and int(t) % 300 == 0:
            print(f"[t={t:6.0f}s] score={sc_now:.3f} 要求達成 {met}/{3 * world.M} "
                  f"巡回済み {visited:.0%} 期限内 {fresh_b:.0%} "
                  f"飛行 {sum(d.mode == 'fly' for d in drones)} / 帰還 {sum(d.mode == 'return' for d in drones)} / "
                  f"充電 {sum(d.mode == 'charge' for d in drones)} / 待機 {sum(d.mode == 'standby' for d in drones)} / "
                  f"移動 {sum(d.mode == 'transit' for d in drones)} / "
                  f"故障 {sum(d.mode == 'failed' for d in drones)}",
                  flush=True)
        if realtime:
            time.sleep(max(0.0, dt - (time.time() - tick_wall)))

    score, cov, met = score_parts(world, state["covered"], state["A"], state["B"])
    sm = np.array([r["solve_ms"] for r in replans]) if replans else np.zeros(1)
    out = dict(data=data_path, scenario=sc, score=score, requirements_met=met,
               requirements_total=3 * world.M,
               municipalities=[dict(name=world.names[m], cov=round(float(cov[m]), 4),
                                    req_cov=float(world.req_cov[m]), alpha=round(float(state["A"][m]), 2),
                                    req_alpha=float(world.req_a[m]), beta=round(float(state["B"][m]), 2),
                                    req_beta=float(world.req_b[m])) for m in range(world.M)],
               incidents=[{k: v for k, v in z.items()} for z in state["incidents"]],
               events=events,
               patrol=dict(blocks=int(world.NB), block_m=sc["patrol"]["block_m"],
                           revisit_sec=sc["patrol"]["revisit_sec"],
                           visited=track[-1]["visited"] if track else 0.0,
                           fresh=track[-1]["fresh"] if track else 0.0,
                           cells_seen=float(state["covered"][world.cells].mean())),
               replans_total=len(replans),
               replans_by_event=sum(r["trigger"] == "event" for r in replans),
               solve_ms_mean=float(sm.mean()), solve_ms_max=float(sm.max()),
               build_ms_mean=float(np.mean([r["build_ms"] for r in replans])) if replans else 0.0,
               wall_sec=time.time() - wall0, replans=replans, track=track,
               stations=world.stations.tolist(),
               points=np.asarray(pts).tolist(), point_region=np.asarray(reg).tolist(),
               deployments=deployments,
               drones=[dict(id=d.i, sensor=d.sensor, r=d.r, speed=d.speed) for d in drones])
    if verbose:
        print(f"[結果] 巡回済みブロック {out['patrol']['visited']:.0%} / 期限内 {out['patrol']['fresh']:.0%} / "
              f"一度でも見たマス {out['patrol']['cells_seen']:.1%}")
        print(f"[結果] score={score:.3f} 要求達成 {met}/{3 * world.M} / 最適化 {len(replans)} 回 "
              f"(うちトラブル起因 {out['replans_by_event']} 回) / 1回あたり 構築 {out['build_ms_mean']:.0f} ms + "
              f"求解 {out['solve_ms_mean']:.0f} ms / 実時間 {out['wall_sec']:.0f} s")
    return out, world, state


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/data_transformed.json", help="地域データ (任意の JSON)")
    ap.add_argument("--scenario", default=None, help="シナリオ JSON (機体・電池・トラブルなど)")
    ap.add_argument("--duration", type=float, default=None, help="運用時間 [s] の上書き")
    ap.add_argument("--backend", choices=["neal", "amplify"], default=None)
    ap.add_argument("--token", default=None, help="Amplify AE のトークン (AMPLIFY_TOKEN でも可)")
    ap.add_argument("--realtime", action="store_true", help="実時間で 1 tick = tick_sec 秒 に合わせる")
    ap.add_argument("--out", default="realtime_run.json")
    ap.add_argument("--video", default=None)
    a = ap.parse_args()
    ov = {}
    if a.duration:
        ov["duration_sec"] = a.duration
    if a.backend:
        ov["solver"] = {"backend": a.backend}
    res, world, state = run(a.data, a.scenario, ov, a.token, a.realtime)
    json.dump(res, open(a.out, "w"), ensure_ascii=False)
    # 動画を後から作り直せるように, 地図上の観測状態も保存する
    np.savez_compressed(a.out + ".state.npz", first_seen=state["first_seen"],
                        snap_t=np.array([x[0] for x in state["block_snaps"]]),
                        snap_v=np.array([x[1] for x in state["block_snaps"]]))
    print("saved:", a.out, a.out + ".state.npz")
    if a.video:
        from realtime_video import make_video
        make_video(res, world, state, a.video)
        print("saved:", a.video)
