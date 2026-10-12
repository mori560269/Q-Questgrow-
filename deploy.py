"""
deploy.py : 各市町村 (領域) に複数のドローンを配置する QUBO

  変数 y[d,p] : 機体 d の基地 (発着・充電地点) を 候補地点 p に置く
                候補地点はデータの candidate_locations (無ければ市町村内に自動で作る)

  H =  Pc Σ_m (n_m - K_m)^2                       ... 市町村 m の機数を目標 K_m (>= 最少機数) に
     + Σ_k w_k M Σ_m (Σ_d rate_k(d)/R_k · y - share_k(m))^2
                                                   ... 被覆・alpha・beta の未達成の度合いの割合に
                                                       見合った能力 (機種) を割り当てる
                                                       (w_k = その能力の未達成の度合いの平均)
     - Σ wc u_p y + Σ wc (範囲の重なり) y y'         ... 基地から往復できる範囲に 未巡回・期限切れの
                                                       ブロックが多い地点を選ぶ (2基地の重なりは減点)
     + Σ (同じ市町村で近い基地どうし) ws (1 - 距離/spread) y y'   ... 基地をばらけさせる
     + Σ (配置換えのコスト: 市町村が変わる / 移動距離) y          ... 見直し時だけ
     + P Σ_d (Σ_p y[d,p] - 1)^2 + P Σ_p Σ_{d<d'} y[d,p] y[d',p]   ... 1機1基地, 1地点1機

  n_m = Σ_{d, p∈m} y[d,p],  K_m は未達成の度合い (スコアの失点) の割合で機数を按分 (各市町村 最少 min_per_region 機)
"""
import numpy as np

from realtime_world import score_parts, value_weights, block_values
from solver_backend import solve_qubo, polish_onehot, qubo_energy


def candidate_points(world, data, n_auto=10, extra_grid_m=0):
    """市町村ごとの候補地点 (m 座標) と その市町村番号.
    データの候補地点に加え, extra_grid_m 間隔の補助地点を足す (基地を未探索の場所へ移せるように)"""
    pts, reg = [], []
    if extra_grid_m:
        gx = np.arange(world.x0 + extra_grid_m / 2, world.x0 + world.nx * world.res, extra_grid_m)
        gy = np.arange(world.y0 + extra_grid_m / 2, world.y0 + world.ny * world.res, extra_grid_m)
        G = np.array([[x, y] for y in gy for x in gx])
        gm = world.muni_at_many(G)
        pts += list(G[gm >= 0])
        reg += list(gm[gm >= 0])
    for m, mu in enumerate(data["municipalities"]):
        got = []
        for c in mu.get("candidate_locations") or []:
            p = np.array([c["x"], c["y"]], float)
            if world.muni_at(p) == m:
                got.append(p)
        if not got:                                    # データに無ければ市町村内に均等に作る
            cells = world.cells[world.muni_flat[world.cells] == m]
            rng = np.random.default_rng(m)
            xy = world.cell_xy(rng.choice(cells, min(4000, len(cells)), replace=False))
            cent = xy[rng.choice(len(xy), min(n_auto, len(xy)), replace=False)]
            for _ in range(30):
                lab = np.argmin(((xy[:, None] - cent[None]) ** 2).sum(-1), axis=1)
                cent = np.array([xy[lab == k].mean(0) if (lab == k).any() else cent[k]
                                 for k in range(len(cent))])
            got = [xy[np.argmin(((xy - c) ** 2).sum(1))] for c in cent]
        pts += got
        reg += [m] * len(got)
    return np.array(pts), np.array(reg)


def region_needs(world, state):
    """市町村ごとの「要求に対する未達成の度合い」(0〜1). スコアの失点にそのまま対応する"""
    _, cov, _ = score_parts(world, state["covered"], state["A"], state["B"])
    return {"cov": 1 - np.minimum(1, cov / world.req_cov),
            "a": 1 - np.minimum(1, state["A"] / world.req_a),
            "b": 1 - np.minimum(1, state["B"] / world.req_b)}


def target_counts(D, share, kmin):
    """必要量の割合 share で D 機を按分 (各市町村 最少 kmin 機, 最大剰余法)"""
    M = len(share)
    kmin = min(kmin, D // M)
    K = np.full(M, kmin)
    rest = D - K.sum()
    q = rest * share
    K += np.floor(q).astype(int)
    for m in np.argsort(-(q - np.floor(q)))[: D - K.sum()]:
        K[m] += 1
    return K


def build_deploy_qubo(world, drones, pts, reg, state, dep, moving_cost=True):
    M, D, Np = world.M, len(drones), len(pts)
    n = D * Np
    dd = np.repeat(np.arange(D), Np)
    pp = np.tile(np.arange(Np), D)
    rr = reg[pp]

    needs = region_needs(world, state)
    rates = {"cov": np.array([d.speed * 2 * d.r for d in drones]),
             "a": np.array([d.alpha for d in drones]),
             "b": np.array([d.beta for d in drones])}
    shares = {k: v / v.sum() for k, v in needs.items() if v.sum() > 1e-9}
    wk = {k: needs[k].sum() / M for k in shares}               # その能力がまだどれだけ要るか
    total = sum(needs.values())
    share = total / total.sum() if total.sum() > 1e-9 else np.full(M, 1.0 / M)
    K = target_counts(D, share, int(dep["min_per_region"]))

    lin = np.zeros(n)
    rows, cols, vals = [], [], []
    offset = 0.0
    Pc = 5.0 / M                 # 機数の目標 (配置換えのコストより強く)
    wb = 1.0                     # 能力の割り当て
    ws = 0.3 / M                 # 基地のばらけ

    def add_square(idx, coef, target, w):
        """w (Σ coef_i y_i - target)^2  (同じ機体どうしの組は one-hot で 0 なので省く)"""
        nonlocal offset
        lin[idx] += w * (coef ** 2 - 2 * target * coef)
        offset += w * target ** 2
        iu = np.triu_indices(len(idx), k=1)
        i1, i2 = idx[iu[0]], idx[iu[1]]
        keep = dd[i1] != dd[i2]
        rows.append(i1[keep]); cols.append(i2[keep])
        vals.append(2 * w * coef[iu[0]][keep] * coef[iu[1]][keep])

    for m in range(M):
        idx = np.where(rr == m)[0]
        add_square(idx, np.ones(len(idx)), float(K[m]), Pc)
        for k, sh in shares.items():
            add_square(idx, rates[k][dd[idx]] / rates[k].sum(), float(sh[m]), wb * M * wk[k])

    # 基地から往復できる範囲 (半径 Rc) にある「未巡回・期限切れの価値」. 多いほど良い基地.
    # 2つの基地の範囲が重なる分はペナルティ (同じところを2機で回らない)
    t = state.get("t", 0.0)
    base_m, wm_cov = value_weights(world, state)
    BV, _ = block_values(world, state, t, state["sc"], base_m, wm_cov)
    one_way = np.median([d.cap / d.drain * d.speed / d.margin / 2 for d in drones])
    Rc = 0.7 * one_way
    Db = np.hypot(*(pts[:, None, :] - world.block_xy[None, :, :]).transpose(2, 0, 1))   # (Np, NB)
    inside = (Db <= Rc) & (world.block_muni[None, :] == reg[:, None])
    U = inside.astype(float) @ BV
    Umax = np.array([max(U[reg == m].max(), 1e-12) if (reg == m).any() else 1.0 for m in range(M)])
    u = U / Umax[reg]
    wc = float(dep.get("catch_w", 2.0)) / M
    for di in range(D):
        lin[di * Np:(di + 1) * Np] -= wc * u
    for m in range(M):
        ps = np.where(reg == m)[0]
        if len(ps) < 2:
            continue
        ov = (inside[ps].astype(float) * BV) @ inside[ps].T.astype(float) / Umax[m]   # 重なりの価値
        a_, b_ = np.triu_indices(len(ps), k=1)
        w_ = wc * ov[a_, b_]
        nzp = w_ > 1e-9
        for pa, pb, w in zip(ps[a_[nzp]], ps[b_[nzp]], w_[nzp]):
            I, J = np.meshgrid(np.arange(D) * Np + pa, np.arange(D) * Np + pb, indexing="ij")
            off = ~np.eye(D, dtype=bool)
            rows.append(I[off]); cols.append(J[off]); vals.append(np.full(off.sum(), w))

    # 同じ市町村の近い基地どうし
    spread = float(dep["spread_m"])
    for m in range(M):
        ps = np.where(reg == m)[0]
        for a in range(len(ps)):
            for b in range(a + 1, len(ps)):
                dist = float(np.hypot(*(pts[ps[a]] - pts[ps[b]])))
                if dist >= spread:
                    continue
                w = ws * (1 - dist / spread)
                i = np.arange(D)[:, None] * Np + ps[a]
                j = np.arange(D)[None, :] * Np + ps[b]
                I, J = np.broadcast_arrays(i, j)
                off = ~np.eye(D, dtype=bool)
                rows.append(I[off]); cols.append(J[off]); vals.append(np.full(off.sum(), w))

    # 配置換えのコスト (見直し時). 今の基地 (または移動先) のままなら 0.
    # 変えるなら 変更 0.3 + 市町村が変わる 0.5 + 移動時間 15 分あたり 1.0 (最大 3) を 1/M 単位で
    if moving_cost:
        for di, d in enumerate(drones):
            if d.base_pt is None:
                continue
            keep = d.next_pt if d.next_pt is not None else d.base_pt
            dist = np.hypot(*(pts - d.pos).T)
            cost = (0.3 + 0.5 * (reg != d.region) + 1.0 * np.minimum(dist / (d.speed * 900), 3)) / M
            if d.mode == "transit":
                cost = np.full(Np, 20.0 / M)       # 移動中の機体は行き先を変えない (電池の安全のため)
            cost[keep] = 0.0
            lin[di * Np:(di + 1) * Np] += cost

    # 1機1基地 (one-hot), 1地点1機
    P = 3.0 * max(np.abs(lin).max(), Pc)
    iu = np.triu_indices(Np, k=1)
    for di in range(D):
        lin[di * Np:(di + 1) * Np] -= P
        offset += P
        rows.append(di * Np + iu[0]); cols.append(di * Np + iu[1]); vals.append(np.full(len(iu[0]), 2 * P))
    iuD = np.triu_indices(D, k=1)
    for p in range(Np):
        rows.append(iuD[0] * Np + p); cols.append(iuD[1] * Np + p); vals.append(np.full(len(iuD[0]), P))
    return n, lin, rows, cols, vals, offset, dd, K


def deploy(world, drones, pts, reg, state, sc, token=None, moving_cost=True, seed=0):
    """配置 QUBO を解いて {機体番号: 候補地点番号} を返す"""
    dep, so = sc["deployment"], sc["solver"]
    n, lin, rows, cols, vals, off, dd, K = build_deploy_qubo(world, drones, pts, reg, state, dep,
                                                            moving_cost)
    samples, _, t_solve, nq = solve_qubo(n, lin, rows, cols, vals, off, backend=so["backend"],
                                         num_reads=8, num_sweeps=500, seed=seed, token=token,
                                         time_limit_ms=so["time_limit_ms"])
    Np = len(pts)
    # アニーリングの解と「今の配置」(ウォームスタート) の両方から局所探索で磨き, 低い方を採る
    starts = list(samples[:3])
    if moving_cost:
        cur = np.zeros(n)
        for di, d in enumerate(drones):
            keep = d.next_pt if d.next_pt is not None else d.base_pt
            if keep is not None:
                cur[di * Np + keep] = 1
        starts.append(cur)
    best = None
    for x0 in starts:
        sel = polish_onehot(n, lin, rows, cols, vals, dd, x0, passes=20)
        x = np.zeros(n)
        x[list(sel.values())] = 1
        e = qubo_energy(x, lin, rows, cols, vals, off)
        if best is None or e < best[0]:
            best = (e, sel)
    sel = best[1]
    assign = {drones[di].i: sel[di] - di * Np for di in range(len(drones))}
    return assign, dict(n_vars=int(n), n_quadratic=int(nq), solve_ms=1000 * t_solve,
                        target_counts=K.tolist())
