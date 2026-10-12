"""
qubo_sa.py : 災害救助ドローン観測計画を QUBO にして焼きなましで解く

  変数  x[d,t,c] ∈ {0,1}  (機体 d が ステップ t に セル c に居る)

  H(x) = - Σ w[c] x[d,t,c]                              ... 観測できる確率質量(線形)
         + λ_ov Σ_{(d,t,c)<(d',t',c')} ov[c,c'] x x'     ... 観測の重複ペナルティ(2次)
         + λ_h  Σ hazard[t,c] x[d,t,c]                   ... 危険領域滞在
         + A Σ_{d,t} (Σ_c x[d,t,c] - 1)^2               ... 1機・1ステップ・1か所 (one-hot)
         + B Σ_{d,t} Σ_{c→c' 到達不可} x[d,t,c] x[d,t+1,c']  ... 移動制約
         + C Σ_{t,c} Σ_{d<d'} x[d,t,c] x[d',t,c]         ... 同時刻の同セル衝突

  w[c]    = Σ_s p[s] cover[c,s]            (位置 c から見える確率質量)
  ov[c,c'] = Σ_s p[s] cover[c,s] cover[c',s] (2つの観測が重なる確率質量)

  ※ λ_ov は 0.3 を既定値にしている (1.0 だと過剰に罰して観測が減る. 感度が高いので要調整)
  ※ 「和集合の質量」は本来2次では書けないので、包除原理の2次までで近似している
    (これが QUBO 版の近似誤差の主因). 評価は常に厳密な和集合で行う.

  ソルバ: dwave-neal (古典のシミュレーテッドアニーリング).
          QPU(実機)で解く場合は末尾の `solve_with_dwave` のコメントを参照.
"""
import time
import json
import numpy as np
import scipy.sparse as sp
import dimod
import neal

import common as cm
from common import N, D, T, LAMBDA_H


def build_qubo(p, hazard, K, lam_ov=0.3):
    nC = N * N
    nvar = D * T * nC

    def vid(d, t, c):
        return (d * T + t) * nC + c

    pK = K * p[None, :]                       # (c, s)
    w = pK.sum(axis=1)                        # (c,)
    ov = pK @ K.T.astype(float)               # ov[c,c'] = Σ_s p_s K[c,s] K[c',s]
    maxw = w.max()
    A = 2.0 * maxw
    B = 3.0 * maxw
    C = 2.0 * maxw

    lin = np.zeros(nvar)
    rows, cols, vals = [], [], []

    def add_quad(i, j, v):
        rows.append(i); cols.append(j); vals.append(v)

    # --- 線形: 報酬 + 危険 + one-hot の線形部分 (-A)
    for d in range(D):
        for t in range(T):
            for c in range(nC):
                lin[vid(d, t, c)] += -w[c] + LAMBDA_H * hazard[t + 1, c] - A
    offset = A * D * T                         # one-hot の定数項

    # --- one-hot の 2次部分: 2A Σ_{i<j}
    iu = np.triu_indices(nC, k=1)
    for d in range(D):
        for t in range(T):
            base = vid(d, t, 0)
            rows.extend(base + iu[0]); cols.extend(base + iu[1])
            vals.extend([2 * A] * len(iu[0]))

    # --- 観測重複 (異なる (d,t) 間のペア). 観測半径が有限なので疎になる
    near = np.argwhere(ov > 1e-12)             # (c,c') with overlap
    slots = [(d, t) for d in range(D) for t in range(T)]
    for a in range(len(slots)):
        da, ta = slots[a]
        for b in range(a + 1, len(slots)):
            db, tb = slots[b]
            for (c, c2) in near:
                coef = lam_ov * ov[c, c2]
                if da == db and ta == tb:
                    continue
                add_quad(vid(da, ta, c), vid(db, tb, c2), coef)

    # --- 衝突 (同時刻・同セル・別機体)
    for t in range(T):
        for d1 in range(D):
            for d2 in range(d1 + 1, D):
                for c in range(nC):
                    add_quad(vid(d1, t, c), vid(d2, t, c), C)

    # --- 移動制約
    unreach = np.array([[not cm.reachable(c1, c2) for c2 in range(nC)]
                        for c1 in range(nC)])
    pairs = np.argwhere(unreach)
    for d in range(D):
        # 初期位置から t=0 へ
        s0 = cm.cid(*cm.START[d])
        for c in range(nC):
            if not cm.reachable(s0, c):
                lin[vid(d, 0, c)] += B
        for t in range(T - 1):
            for (c1, c2) in pairs:
                add_quad(vid(d, t, c1), vid(d, t + 1, c2), B)

    bqm = dimod.BinaryQuadraticModel.from_numpy_vectors(
        lin, (np.array(rows), np.array(cols), np.array(vals)), offset, "BINARY")
    return bqm, vid


def decode(sample_vec, vid):
    """sample (0/1 vector) -> path (D,T), one-hot 違反数"""
    nC = N * N
    path = np.zeros((D, T), dtype=int)
    viol = 0
    for d in range(D):
        for t in range(T):
            blk = sample_vec[vid(d, t, 0): vid(d, t, 0) + nC]
            if blk.sum() != 1:
                viol += 1
            path[d, t] = int(np.argmax(blk))
    return path, viol


def repair_moves(path):
    """移動制約違反だけを軽く修復 (到達可能で元の位置に最も近いセルへ)"""
    path = path.copy()
    nC = N * N
    for d in range(D):
        prev = cm.cid(*cm.START[d])
        for t in range(T):
            if not cm.reachable(prev, path[d, t]):
                tr, tc = divmod(path[d, t], N)
                best, bd = None, 1e9
                for c in range(nC):
                    if cm.reachable(prev, c):
                        r, cc_ = divmod(c, N)
                        dist = (r - tr) ** 2 + (cc_ - tc) ** 2
                        if dist < bd:
                            best, bd = c, dist
                path[d, t] = best
            prev = path[d, t]
    return path


def solve(num_reads=100, num_sweeps=8000, seed=0):
    p, hazard = cm.build_scenario()
    K = cm.cover_matrix()
    t0 = time.time()
    bqm, vid = build_qubo(p, hazard, K)
    t_build = time.time() - t0
    print(f"[QUBO] 変数数={bqm.num_variables}  2次項数={bqm.num_interactions}  "
          f"構築 {t_build:.1f}s")

    t0 = time.time()
    sampler = neal.SimulatedAnnealingSampler()
    ss = sampler.sample(bqm, num_reads=num_reads, num_sweeps=num_sweeps, seed=seed)
    t_solve = time.time() - t0
    print(f"[SA ] {num_reads} reads x {num_sweeps} sweeps  {t_solve:.1f}s")

    # 全サンプルを厳密な評価関数で採点し, 実行可能な最良解を選ぶ
    # (アニーラが返す「多様な低エネルギー解」を候補集合として使う発想)
    cands = []
    order = np.argsort(ss.record.energy)
    var_index = {v: i for i, v in enumerate(ss.variables)}
    perm = np.array([var_index[v] for v in range(bqm.num_variables)])
    n_onehot_ok = 0
    n_feasible = 0
    for idx in order:
        vec = ss.record.sample[idx][perm]
        path, viol = decode(vec, vid)
        if viol == 0:
            n_onehot_ok += 1
        ev = cm.evaluate(path, p, hazard, K)
        if ev["feasible"] and viol == 0:
            n_feasible += 1
        cands.append((ev["J"] if ev["feasible"] else -1e9, idx, path, viol, ev,
                      float(ss.record.energy[idx])))
    cands.sort(key=lambda x: -x[0])
    best = cands[0]
    if best[0] < -1e8:                         # 実行可能解が1つも無ければ修復
        path = repair_moves(cands[0][2])
        ev = cm.evaluate(path, p, hazard, K)
        best = (ev["J"], cands[0][1], path, cands[0][3], ev, cands[0][5])
        print("[warn] 実行可能解なし -> 移動制約のみ修復")
    _, _, path, viol, ev, energy = best
    # QUBOエネルギー最小のサンプル自体の質も記録
    low = cands[int(np.argmin([c[5] for c in cands]))]

    print(f"[結果] 実行可能なサンプル {n_onehot_ok}/{num_reads} (one-hot OK) / "
          f"{n_feasible}/{num_reads} (全制約OK)")
    print(f"[結果] 最良解: J={ev['J']:.4f}  観測率={100*ev['covered_mass']:.1f}%  "
          f"危険滞在={ev['hazard_steps']}  feasible={ev['feasible']}")
    res = dict(method="QUBO + simulated annealing (neal)",
               J=ev["J"], covered_mass=ev["covered_mass"],
               hazard_steps=ev["hazard_steps"], feasible=bool(ev["feasible"]),
               n_vars=bqm.num_variables, n_quadratic=bqm.num_interactions,
               build_sec=t_build, solve_sec=t_solve,
               feasible_samples=n_feasible, num_reads=num_reads,
               path=path.tolist())
    return res, path, p, hazard, K


if __name__ == "__main__":
    res, path, p, hazard, K = solve()
    with open("result_qubo.json", "w") as f:
        json.dump(res, f, indent=1)
    cm.make_video(path, p, hazard, K, "qubo_run.mp4",
                  title="QUBO + シミュレーテッドアニーリング",
                  subtitle=f"変数 {res['n_vars']} / 2次項 {res['n_quadratic']} / "
                           f"J={res['J']:.3f} / 観測率 {100*res['covered_mass']:.1f}% / "
                           f"求解 {res['solve_sec']:.0f}s")
    print("saved: qubo_run.mp4, result_qubo.json")

# ---------------------------------------------------------------------------
# D-Wave 実機(QPU)で解く場合 (要 dwave-ocean-sdk と Leap アカウント):
#
#   from dwave.system import DWaveSampler, EmbeddingComposite
#   sampler = EmbeddingComposite(DWaveSampler())
#   ss = sampler.sample(bqm, num_reads=200, annealing_time=500, chain_strength=...)
#
# ただし本問題の変数は 1800 で密結合を含むため, そのままでは埋め込みできません.
# 候補セルの絞り込み / 時間窓分解 / 領域分解 / ハイブリッドソルバ(LeapHybridBQMSampler)
# で小さくする必要があります (これが次の研究課題).
# ---------------------------------------------------------------------------
