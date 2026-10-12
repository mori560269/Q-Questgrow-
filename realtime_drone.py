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

from realtime_world import World, deep_update, load_inputs, score_parts
from solver_backend import solve_qubo


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
        self.battery = self.cap
        self.pos = np.array(start, float)
        self.target = self.pos.copy()
        self.mode = "fly"          # standby / fly / return / charge / failed
        self.step = self.speed * sc["plan_step_sec"]


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

    # 観測済みでない & 被覆率の要求を満たしていない市町村のマスの価値
    _, cov, _ = score_parts(world, covered, A, B)
    wm = np.where(cov < world.req_cov, omega / (world.req_cov * world.Nm), 0.0)
    resA = np.maximum(world.req_a - A, 0)
    resB = np.maximum(world.req_b - B, 0)

    cand = []          # dict(d, h, ij, pos, swath, gain, muni, a, b, tgt)
    for d in drones:
        for h in range(H):
            R = h + 1
            for i in range(-R, R + 1):
                for j in range(-R, R + 1):
                    p = d.pos + d.step * np.array([i, j], float)
                    m = world.muni_at(p)
                    if m < 0:
                        continue
                    # 親 (1つ前のステップの格子点) から掃く
                    pi, pj = (0, 0) if h == 0 else (int(np.clip(i, -h, h)), int(np.clip(j, -h, h)))
                    p0 = d.pos + d.step * np.array([pi, pj], float)
                    if any(point_seg_dist(np.array([z["x"], z["y"]]), p0, p) <= z["radius_m"]
                           for z in hazards):
                        continue
                    # 戻れなくなる地点は除く
                    left = d.battery - d.drain * R * sc["plan_step_sec"]
                    _, dist = world.nearest_station(p)
                    if left < d.drain * dist / d.speed * margin:
                        continue
                    sw = world.swath(p0, p, d.r)
                    sw = sw[~covered[sw]]
                    a = d.alpha * sc["plan_step_sec"] / per
                    b = d.beta * sc["plan_step_sec"] / per
                    tg = [k for k, z in enumerate(targets)
                          if np.hypot(p[0] - z["x"], p[1] - z["y"]) <= d.r]
                    cand.append(dict(d=d.i, h=h, ij=(i, j), pos=p, swath=sw, muni=m, a=a, b=b,
                                     tgt=tg))
    n = len(cand)
    if n == 0:
        return None
    slot = np.array([c["d"] * H + c["h"] for c in cand])
    gain = np.zeros(n)
    for k, c in enumerate(cand):
        m = c["muni"]
        gain[k] = wm[world.muni_flat[c["swath"]]].sum()
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
        dn = min(drones, key=lambda d: np.hypot(*(d.pos - zc)))
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
    lin = -gain
    P = so["pen"] * max(gain.max(), 1e-12)

    rows, cols, vals = [], [], []
    dd = np.array([c["d"] for c in cand])
    hh = np.array([c["h"] for c in cand])

    # 重複: S (候補 × マス) から  S W S^T
    ptr = np.cumsum([0] + [len(c["swath"]) for c in cand])
    idx = np.concatenate([c["swath"] for c in cand]) if ptr[-1] else np.zeros(0, int)
    if len(idx):
        uniq, col = np.unique(idx, return_inverse=True)          # 候補が見るマスだけに詰める
        S1 = sp.csr_matrix((np.ones(len(idx)), col, ptr), shape=(n, len(uniq)))
        Sw = sp.csr_matrix((wm[world.muni_flat[idx]], col, ptr), shape=(n, len(uniq)))
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

    # one-hot
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
    return n, lin, rows, cols, vals, offset, cand


def choose_targets(sample, cand, lin, rows, cols, vals, drones, passes=5):
    """解から各機の次の目的地 (h=0) を決める.

    アニーリングの解を出発点に, 「1つの (機体, ステップ) の選択だけを変えて QUBO の
    エネルギーが下がるなら変える」局所探索で磨く (one-hot は常に満たした状態で探索)"""
    n = len(cand)
    slot = np.array([c["d"] * 100 + c["h"] for c in cand])
    r = np.concatenate([np.asarray(x, int) for x in rows]) if rows else np.zeros(0, int)
    c_ = np.concatenate([np.asarray(x, int) for x in cols]) if cols else np.zeros(0, int)
    v = np.concatenate([np.asarray(x, float) for x in vals]) if vals else np.zeros(0)
    keep = slot[r] != slot[c_]                         # one-hot の項は除く (構造で満たす)
    Q = sp.coo_matrix((v[keep], (r[keep], c_[keep])), shape=(n, n)).tocsr()
    Q = (Q + Q.T).tocsr()
    groups = {s_: np.where(slot == s_)[0] for s_ in np.unique(slot)}
    sel = {}
    for s_, ks in groups.items():
        on = ks[sample[ks] == 1]
        sel[s_] = int(on[0]) if len(on) == 1 else int(ks[np.argmin(lin[ks])])
    x = np.zeros(n)
    x[list(sel.values())] = 1
    field = lin + Q @ x
    for _ in range(passes):
        changed = False
        for s_, ks in groups.items():
            cur = sel[s_]
            f = field[ks] - Q[ks, cur].toarray().ravel()   # 自分の slot の寄与を除く
            best = int(ks[np.argmin(f)])
            if best != cur and f[np.argmin(f)] < field[cur] - Q[cur, cur] - 1e-15:
                field += Q[:, best].toarray().ravel() - Q[:, cur].toarray().ravel()
                sel[s_] = best
                changed = True
        if not changed:
            break
    out = {}
    for d in drones:
        k = sel.get(d.i * 100 + 0)
        if k is not None:
            out[d.i] = cand[k]["pos"]
    return out


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

    state = dict(covered=np.zeros(world.nx * world.ny, bool),
                 first_seen=np.full(world.nx * world.ny, np.inf, np.float32),
                 A=np.zeros(world.M), B=np.zeros(world.M), incidents=[])
    for k, z in enumerate(sc["incidents"]):
        z = dict(z); z["id"] = k
        z["status"] = "scheduled" if z["type"] in ("drone_failure", "battery_fault") else "hidden"
        z.setdefault("radius_m", 0.0); z.setdefault("observe_sec", 60); z["watched"] = 0.0
        state["incidents"].append(z)

    events, replans, track = [], [], []
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
                    if d.mode in ("fly", "return") and np.hypot(*(d.pos - c)) <= z["radius_m"] + d.r:
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

        # ---- 2) 最適化 (定期 / トラブル発生時は即時)
        flying = [d for d in drones if d.mode == "fly"]
        trigger = "event" if new_events else ("periodic" if t - last_plan >= sc["replan_sec"] - 1e-9 else None)
        if trigger and flying:
            tb = time.time()
            built = build_qubo(world, flying, state, sc)
            t_build = time.time() - tb
            if built is None:
                for d in flying:
                    d.mode = "return"
            else:
                n, lin, rows, cols, vals, off, cand = built
                samples, _, t_solve, nq = solve_qubo(
                    n, lin, rows, cols, vals, off, backend=so["backend"],
                    num_reads=so["num_reads"], num_sweeps=so["num_sweeps"],
                    seed=int(so["seed"] + t), token=token, time_limit_ms=so["time_limit_ms"])
                tg = choose_targets(samples[0], cand, lin, rows, cols, vals, flying)
                for d in flying:
                    if d.i in tg:
                        d.target = tg[d.i]
                    else:
                        d.mode = "return"      # 戻れる候補しか残っていない
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
                if t + dt >= d.launch_t:
                    d.mode = "fly"; d.target = d.pos.copy()
                continue
            if d.mode == "charge":
                d.battery = min(d.cap, d.battery + d.cap / sc["battery"]["full_charge_sec"] * dt)
                if d.battery >= sc["battery"]["resume_ratio"] * d.cap:
                    d.mode = "fly"; d.target = d.pos.copy()
                continue
            k, dist = world.nearest_station(d.pos)
            if d.mode == "fly":
                need = d.drain * (dist / d.speed * sc["battery"]["reserve_margin"] + dt)
                if d.battery - d.drain * dt < need:
                    d.mode = "return"
            goal = world.stations[k] if d.mode == "return" else d.target
            v = goal - d.pos
            L = float(np.hypot(*v))
            step = min(L, d.speed * dt)
            new = d.pos + (v / L * step if L > 0 else 0)
            sw = world.swath(d.pos, new, d.r)
            fresh = sw[~state["covered"][sw]]
            state["covered"][fresh] = True
            state["first_seen"][fresh] = t + dt
            m = world.muni_at(new)
            if m >= 0:
                state["A"][m] += d.alpha * dt / sc["alpha_beta_per_sec"]
                state["B"][m] += d.beta * dt / sc["alpha_beta_per_sec"]
            d.pos = new
            d.battery -= d.drain * dt
            if d.mode == "return" and L <= d.speed * dt + 1e-6:
                d.mode = "charge"
            if d.battery < 0:
                d.mode = "failed"
                carry.append(dict(t=t, kind="battery_empty", drone=d.i,
                                  msg=f"機体{d.i + 1} が電池切れで不時着"))

        t += dt
        sc_now, _, met = score_parts(world, state["covered"], state["A"], state["B"])
        track.append(dict(t=t, score=sc_now, met=met,
                          pos=[[round(float(d.pos[0]), 1), round(float(d.pos[1]), 1)] for d in drones],
                          bat=[round(d.battery / d.cap, 3) for d in drones],
                          mode=[d.mode for d in drones]))
        if verbose and int(t) % 300 == 0:
            print(f"[t={t:6.0f}s] score={sc_now:.3f} 要求達成 {met}/{3 * world.M} "
                  f"飛行 {sum(d.mode == 'fly' for d in drones)} / 帰還 {sum(d.mode == 'return' for d in drones)} / "
                  f"充電 {sum(d.mode == 'charge' for d in drones)} / 待機 {sum(d.mode == 'standby' for d in drones)} / "
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
               replans_total=len(replans),
               replans_by_event=sum(r["trigger"] == "event" for r in replans),
               solve_ms_mean=float(sm.mean()), solve_ms_max=float(sm.max()),
               build_ms_mean=float(np.mean([r["build_ms"] for r in replans])) if replans else 0.0,
               wall_sec=time.time() - wall0, replans=replans, track=track,
               stations=world.stations.tolist(),
               drones=[dict(id=d.i, sensor=d.sensor, r=d.r, speed=d.speed) for d in drones])
    if verbose:
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
    print("saved:", a.out)
    if a.video:
        from realtime_video import make_video
        make_video(res, world, state, a.video)
        print("saved:", a.video)
