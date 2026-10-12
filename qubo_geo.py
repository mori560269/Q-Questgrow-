"""
qubo_geo.py : 新緑県データ + 充電つきドローン観測計画を QUBO にして焼きなましで解く

  変数
    x[d,t,c]     機体 d が ステップ t に セル c に居る
    q[d,t,l,m]   ステップ t の「稼働/充電モード m」と「その後のバッテリー残量 l」の組 (one-hot)
    z[...]       alpha/beta の要求を「超過」した分を吸収するスラック(2進展開)

  H = - Σ w[d,c] x                                   被覆の報酬 (線形)
      + λ_ov Σ ov[(d,c),(d',c')] x x'                 被覆の重複ペナルティ (2次, 包除原理の近似)
      + Σ_m W_a ((A_m - R_a,m - s_a,m)/R_a,m)^2       alpha 不足の2乗ペナルティ (スラック s で超過は無罰)
      + Σ_m W_b ((B_m - R_b,m - s_b,m)/R_b,m)^2       beta  同上
      + P1 Σ (Σ_c x - 1)^2 + P1 Σ (Σ q - 1)^2         one-hot
      + P_mode Σ q[work]·x[station] + q[charge]·x[非station]   モードと位置の整合 (2次)
      + P_tr   Σ q[t-1,l,m]·q[t,l',m'] (l' ≠ f(l,m'))    バッテリー遷移の整合 (2次)
      + P_mv   Σ x[t,c]·x[t+1,c'] (到達不可)           移動制約 (2次)

  ポイント: 充電の累積制約 b_t >= 0 は「バッテリー残量を状態変数 q にして
            隣接ステップ間の2次の整合ペナルティ」で QUBO に落とす.
            (モード m を q に含めることで 3体項を避けている)

  評価は常に geo_common.evaluate (厳密な和集合・キャップ付き) で行う.
"""
import time
import json
import numpy as np
import scipy.sparse as sp
import dimod
import neal

import geo_common as g
from geo_common import D, T, D_TYPES, BATT_MAX, CHARGE, E_TYPE

LAM_OV = 0.3     # 被覆重複ペナルティ係数 (1.0 だと過剰に罰する. 要調整)
KAPPA = 2.0      # alpha/beta 不足ペナルティの重み (score 1項あたりの重みの倍率)
NL = BATT_MAX + 1


def f_next(l, m, tid):
    """バッテリー遷移. m=0:稼働, m=1:充電. 不可能なら None"""
    if m == 0:
        l2 = l - E_TYPE[tid]
        return l2 if l2 >= 0 else None
    return min(BATT_MAX, l + CHARGE)


def build_qubo(S, lam_ov=LAM_OV, kappa=KAPPA):
    C, M = S.C, S.M
    omega = 1.0 / (3 * M)
    nx = D * T * C
    off_q = nx
    nq = D * T * NL * 2
    off_z = off_q + nq

    def vx(d, t, c): return (d * T + t) * C + c
    def vq(d, t, l, m): return off_q + ((d * T + t) * NL + l) * 2 + m

    lin_parts = {}
    rows, cols, vals = [], [], []
    lin = {}
    offset = 0.0

    def add_lin(i, v):
        lin[i] = lin.get(i, 0.0) + v

    def add_quad_arrays(i, j, v):
        i = np.asarray(i); j = np.asarray(j); v = np.asarray(v, dtype=float)
        lo_ = np.minimum(i, j); hi_ = np.maximum(i, j)
        rows.append(lo_); cols.append(hi_); vals.append(v)

    # ---- 1) 被覆: 報酬 + 重複 (包除原理の2次近似)
    nu = np.zeros(C)
    for m in range(M):
        nu[S.cmuni == m] = omega / (S.req_cov[m] * S.Nm[m])
    tids = sorted(set(D_TYPES))
    Kw = {k: S.K[k] * nu[None, :] for k in tids}
    wgain = {k: Kw[k].sum(1) for k in tids}
    OVnz = {}
    for k1 in tids:
        for k2 in tids:
            ov = Kw[k1] @ S.K[k2].T.astype(float)
            ci, cj = np.nonzero(ov > 1e-15)
            OVnz[(k1, k2)] = (ci, cj, lam_ov * ov[ci, cj])
    lin_x = np.zeros(nx)
    for d in range(D):
        for t in range(T):
            lin_x[vx(d, t, 0): vx(d, t, 0) + C] += -wgain[D_TYPES[d]]
    slots = [(d, t) for d in range(D) for t in range(T)]
    for a in range(len(slots)):
        da, ta = slots[a]
        for b in range(a + 1, len(slots)):
            db, tb = slots[b]
            ci, cj, vv = OVnz[(D_TYPES[da], D_TYPES[db])]
            add_quad_arrays(vx(da, ta, 0) + ci, vx(db, tb, 0) + cj, vv)

    # スケール (ペナルティ係数)
    wmax = max(v.max() for v in wgain.values())
    P1 = 3.0 * wmax          # one-hot
    PM = 3.0 * wmax          # モード整合
    PT = 3.0 * wmax          # バッテリー遷移
    PV = 3.0 * wmax          # 移動

    # ---- 2) one-hot (x と q)
    iu = np.triu_indices(C, k=1)
    iuq = np.triu_indices(NL * 2, k=1)
    for d in range(D):
        for t in range(T):
            bx = vx(d, t, 0)
            lin_x[bx: bx + C] += -P1
            offset += P1
            add_quad_arrays(bx + iu[0], bx + iu[1], np.full(len(iu[0]), 2 * P1))
            bq = vq(d, t, 0, 0)
            for k in range(NL * 2):
                add_lin(bq + k, -P1)
            offset += P1
            add_quad_arrays(bq + iuq[0], bq + iuq[1], np.full(len(iuq[0]), 2 * P1))

    # ---- 3) モードと位置の整合
    st = np.array(S.stations)
    nst = np.where(~S.is_station)[0]
    for d in range(D):
        for t in range(T):
            for l in range(NL):
                ii = np.repeat(vq(d, t, l, 0), len(st))
                add_quad_arrays(ii, vx(d, t, 0) + st, np.full(len(st), PM))     # 稼働なのにステーション
                ii = np.repeat(vq(d, t, l, 1), len(nst))
                add_quad_arrays(ii, vx(d, t, 0) + nst, np.full(len(nst), PM))   # 充電なのに非ステーション

    # ---- 4) バッテリー遷移
    for d in range(D):
        tid = D_TYPES[d]
        for m in (0, 1):                                  # t=0: 初期残量 BATT_MAX から
            for l in range(NL):
                if f_next(BATT_MAX, m, tid) != l:
                    add_lin(vq(d, 0, l, m), PT)
        for t in range(1, T):
            ia, ja, va = [], [], []
            for lp in range(NL):
                for mp in (0, 1):
                    for l in range(NL):
                        for m in (0, 1):
                            if f_next(lp, m, tid) != l:
                                ia.append(vq(d, t - 1, lp, mp)); ja.append(vq(d, t, l, m))
            add_quad_arrays(ia, ja, np.full(len(ia), PT))

    # ---- 5) 移動制約
    unreach = ~S.reach
    u1, u2 = np.nonzero(unreach)
    for d in range(D):
        for c in range(C):
            if not S.reach[S.start[d], c]:
                lin_x[vx(d, 0, c)] += PV
        for t in range(T - 1):
            add_quad_arrays(vx(d, t, 0) + u1, vx(d, t + 1, 0) + u2, np.full(len(u1), PV))

    # ---- 6) alpha / beta の不足 (スラック付き2乗ペナルティ)
    nz = 0
    n_slack = 0
    for kind, req_arr, tab in (("alpha", S.req_a, S.alpha), ("beta", S.req_b, S.beta)):
        for m in range(M):
            R = req_arr[m]
            cells_m = [c for c in np.where(S.cmuni == m)[0] if not S.is_station[c]]
            idx, v = [], []
            for d in range(D):
                a_d = tab[D_TYPES[d]]
                for t in range(T):
                    for c in cells_m:
                        idx.append(vx(d, t, c)); v.append(float(a_d))
            vmax_total = T * sum(tab[tt] for tt in D_TYPES)
            K = int(np.ceil(np.log2(max(1.0, vmax_total - R + 1)))) if vmax_total > R else 0
            for k in range(K):
                idx.append(off_z + nz); v.append(-float(2 ** k)); nz += 1
            n_slack += K
            idx = np.array(idx); v = np.array(v)
            W = kappa * omega / R ** 2
            lin_c = W * (v ** 2 - 2 * R * v)
            for i_, c_ in zip(idx, lin_c):
                if i_ < nx:
                    lin_x[i_] += c_
                else:
                    add_lin(int(i_), float(c_))
            iu2 = np.triu_indices(len(idx), k=1)
            add_quad_arrays(idx[iu2[0]], idx[iu2[1]], 2 * W * v[iu2[0]] * v[iu2[1]])
            offset += W * R ** 2
    nvar = off_z + nz

    linear = np.zeros(nvar)
    linear[:nx] = lin_x
    for i, vv in lin.items():
        linear[i] += vv
    R_ = np.concatenate(rows); C_ = np.concatenate(cols); V_ = np.concatenate(vals)
    Q = sp.coo_matrix((V_, (R_, C_)), shape=(nvar, nvar)).tocsr()   # 重複を合算
    Q = Q.tocoo()
    bqm = dimod.BinaryQuadraticModel.from_numpy_vectors(
        linear, (Q.row, Q.col, Q.data), offset, "BINARY")
    info = dict(nx=nx, nq=nq, nz=nz, off_q=off_q, penalties=dict(P1=P1, PM=PM, PT=PT, PV=PV))
    return bqm, vx, info


def decode(vec, S):
    C = S.C
    path = np.zeros((D, T), dtype=int)
    viol = 0
    for d in range(D):
        for t in range(T):
            blk = vec[(d * T + t) * C: (d * T + t + 1) * C]
            if blk.sum() != 1:
                viol += 1
            path[d, t] = int(np.argmax(blk))
    return path, viol


def repair(S, path):
    """バッテリー切れ・移動違反を軽く修復: 切れそうなら到達可能な最寄りステーションへ"""
    path = path.copy()
    for d in range(D):
        e = E_TYPE[D_TYPES[d]]
        b = BATT_MAX
        prev = S.start[d]
        for t in range(T):
            c = path[d, t]
            if not S.reach[prev, c]:
                cand = np.where(S.reach[prev])[0]
                c = int(cand[np.argmin(((S.xy[cand] - S.xy[c]) ** 2).sum(1))])
            if not S.is_station[c] and b - e < 0:
                cand = np.where(S.reach[prev])[0]
                stc = [x for x in cand if S.is_station[x]]
                if stc:
                    c = int(stc[0])
                else:
                    sts = S.xy[S.stations]
                    tgt = sts[np.argmin(((sts - S.xy[prev]) ** 2).sum(1))]
                    c = int(cand[np.argmin(((S.xy[cand] - tgt) ** 2).sum(1))])
            path[d, t] = c
            b = min(BATT_MAX, b + CHARGE) if S.is_station[c] else b - e
            prev = c
    return path


def solve(num_reads=30, num_sweeps=3000, seed=0):
    S = g.build_scenario()
    t0 = time.time()
    bqm, vx, info = build_qubo(S)
    t_build = time.time() - t0
    print(f"[QUBO] 変数={bqm.num_variables} (x {info['nx']} + q {info['nq']} + slack {info['nz']}) "
          f"2次項={bqm.num_interactions}  構築 {t_build:.1f}s", flush=True)
    t0 = time.time()
    ss = neal.SimulatedAnnealingSampler().sample(bqm, num_reads=num_reads,
                                                 num_sweeps=num_sweeps, seed=seed)
    t_solve = time.time() - t0
    print(f"[SA ] {num_reads} reads x {num_sweeps} sweeps  {t_solve:.1f}s", flush=True)

    var_index = {v: i for i, v in enumerate(ss.variables)}
    perm = np.array([var_index[v] for v in range(bqm.num_variables)])
    order = np.argsort(ss.record.energy)
    raw, rep = [], []
    for idx in order:
        vec = ss.record.sample[idx][perm]
        path, viol = decode(vec, S)
        ev = g.evaluate(S, path)
        raw.append((ev["score"] if (ev["feasible"] and viol == 0) else -1, path, ev, viol))
        p2 = repair(S, path)
        ev2 = g.evaluate(S, p2)
        rep.append((ev2["score"] if ev2["feasible"] else -1, p2, ev2, viol))
    n_raw_ok = sum(1 for r in raw if r[0] >= 0)
    best_raw = max(raw, key=lambda r: r[0])
    best_rep = max(rep, key=lambda r: r[0])
    used_repair = False
    if best_raw[0] >= 0:
        sc, path, ev, viol = best_raw
    else:
        sc, path, ev, viol = best_rep
        used_repair = True
    print(f"[結果] 修復なしで全制約OKのサンプル {n_raw_ok}/{num_reads}   修復使用={used_repair}")
    print(f"[結果] score={ev['score']:.4f} 要求達成 {ev['requirements_met']}/{ev['requirements_total']} "
          f"充電ステップ={ev['charge_steps']} feasible={ev['feasible']}", flush=True)
    out = dict(method="QUBO + simulated annealing (neal)", score=ev["score"],
               feasible=bool(ev["feasible"]), requirements_met=ev["requirements_met"],
               requirements_total=ev["requirements_total"], charge_steps=ev["charge_steps"],
               min_battery=ev["min_battery"], cov=ev["cov"].round(3).tolist(),
               A=ev["A"].tolist(), B=ev["B"].tolist(), n_vars=bqm.num_variables,
               n_quadratic=bqm.num_interactions, build_sec=t_build, solve_sec=t_solve,
               raw_feasible_samples=n_raw_ok, num_reads=num_reads,
               used_repair=used_repair, path=path.tolist())
    return out, path, S


if __name__ == "__main__":
    res, path, S = solve()
    json.dump(res, open("result_qubo_geo.json", "w"), indent=1)
    g.make_video(S, path, "qubo_geo.mp4",
                 title="QUBO + シミュレーテッドアニーリング : 新緑県 / 充電つき",
                 subtitle=f"セル {S.C} / 機体 {D} / {T}ステップ / 変数 {res['n_vars']} / "
                          f"2次項 {res['n_quadratic']} / score={res['score']:.3f} / "
                          f"要求達成 {res['requirements_met']}/{res['requirements_total']} / "
                          f"求解 {res['solve_sec']:.0f}s")
    print("saved: qubo_geo.mp4, result_qubo_geo.json")
