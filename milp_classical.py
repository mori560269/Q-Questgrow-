"""
milp_classical.py : 同じ問題を QUBO を使わず, 混合整数線形計画(MILP)で厳密に解く

  変数  x[d,t,c] ∈ {0,1}   機体 d が ステップ t に セル c に居る
        y[s]     ∈ [0,1]   セル s が一度でも観測されたか

  max  Σ_s p[s] y[s]  -  λ_h Σ hazard[t,c] x[d,t,c]

  s.t. Σ_c x[d,t,c] = 1                              (各機・各ステップで1か所)
       y[s] ≤ Σ_{d,t,c : cover[c,s]} x[d,t,c]         (観測された時だけ y=1)
       x[d,t+1,c'] ≤ Σ_{c: c→c' 到達可能} x[d,t,c]    (移動制約: 線形のまま書ける)
       Σ_d x[d,t,c] ≤ 1                               (同時刻・同セルに複数機を置かない)

  ポイント: 「和集合の質量」を y[s] で厳密に表せるので, QUBO版のような
  包除原理の近似(2次まで)が不要. 制約も不等式のまま書けるので
  ペナルティ係数 A,B,C の調整も不要. ソルバは scipy.optimize.milp (HiGHS).
"""
import time
import json
import numpy as np
import scipy.sparse as sp
from scipy.optimize import milp, LinearConstraint, Bounds

import common as cm
from common import N, D, T, LAMBDA_H


def solve(time_limit=120, mip_rel_gap=1e-4):
    p, hazard = cm.build_scenario()
    K = cm.cover_matrix()
    nC = N * N
    nx = D * T * nC
    nvar = nx + nC

    def vid(d, t, c):
        return (d * T + t) * nC + c

    # 目的 (milp は最小化なので符号反転)
    cvec = np.zeros(nvar)
    for d in range(D):
        for t in range(T):
            for c in range(nC):
                cvec[vid(d, t, c)] = LAMBDA_H * hazard[t + 1, c]
    cvec[nx:] = -p

    rows, cols, vals = [], [], []
    lo, hi = [], []
    r = 0

    def add_row(entries, l, u):
        nonlocal r
        for (j, v) in entries:
            rows.append(r); cols.append(j); vals.append(v)
        lo.append(l); hi.append(u)
        r += 1

    # (1) one-hot
    for d in range(D):
        for t in range(T):
            add_row([(vid(d, t, c), 1.0) for c in range(nC)], 1, 1)
    # (2) 観測の和集合
    for s in range(nC):
        ent = [(nx + s, 1.0)]
        for d in range(D):
            for t in range(T):
                for c in np.where(K[:, s])[0]:
                    ent.append((vid(d, t, c), -1.0))
        add_row(ent, -np.inf, 0)
    # (3) 移動制約
    for d in range(D):
        for t in range(T - 1):
            for c2 in range(nC):
                ent = [(vid(d, t + 1, c2), 1.0)]
                for c1 in range(nC):
                    if cm.reachable(c1, c2):
                        ent.append((vid(d, t, c1), -1.0))
                add_row(ent, -np.inf, 0)
    # (4) 衝突回避
    for t in range(T):
        for c in range(nC):
            add_row([(vid(d, t, c), 1.0) for d in range(D)], -np.inf, 1)

    A = sp.csr_matrix((vals, (rows, cols)), shape=(r, nvar))
    ub = np.ones(nvar)
    # 初期位置から1ステップで届かない場所は変数ごと 0 に固定
    for d in range(D):
        s0 = cm.cid(*cm.START[d])
        for c in range(nC):
            if not cm.reachable(s0, c):
                ub[vid(d, 0, c)] = 0
    integrality = np.r_[np.ones(nx), np.zeros(nC)]

    print(f"[MILP] 変数数={nvar} (2値 {nx} + 連続 {nC})  制約数={r}  非零={A.nnz}")
    t0 = time.time()
    res = milp(cvec, constraints=LinearConstraint(A, lo, hi),
               integrality=integrality, bounds=Bounds(np.zeros(nvar), ub),
               options=dict(time_limit=time_limit, mip_rel_gap=mip_rel_gap,
                            disp=False))
    t_solve = time.time() - t0
    print(f"[MILP] status={res.status} ({res.message})  {t_solve:.1f}s")

    x = res.x[:nx]
    path = np.zeros((D, T), dtype=int)
    for d in range(D):
        for t in range(T):
            blk = x[vid(d, t, 0): vid(d, t, 0) + nC]
            path[d, t] = int(np.argmax(blk))
    ev = cm.evaluate(path, p, hazard, K)
    gap = getattr(res, "mip_gap", None)
    print(f"[結果] J={ev['J']:.4f}  観測率={100*ev['covered_mass']:.1f}%  "
          f"危険滞在={ev['hazard_steps']}  feasible={ev['feasible']}  gap={gap}")
    out = dict(method="MILP (scipy.optimize.milp / HiGHS)", J=ev["J"],
               covered_mass=ev["covered_mass"], hazard_steps=ev["hazard_steps"],
               feasible=bool(ev["feasible"]), n_vars=int(nvar), n_constraints=int(r),
               solve_sec=t_solve, mip_gap=None if gap is None else float(gap),
               status=int(res.status), path=path.tolist())
    return out, path, p, hazard, K


if __name__ == "__main__":
    res, path, p, hazard, K = solve()
    with open("result_milp.json", "w") as f:
        json.dump(res, f, indent=1)
    gap_txt = "" if res["mip_gap"] is None else f" / gap {res['mip_gap']*100:.2f}%"
    cm.make_video(path, p, hazard, K, "classical_run.mp4",
                  title="古典最適化 (MILP / HiGHS) ※QUBOなし",
                  subtitle=f"変数 {res['n_vars']} / 制約 {res['n_constraints']} / "
                           f"J={res['J']:.3f} / 観測率 {100*res['covered_mass']:.1f}% / "
                           f"求解 {res['solve_sec']:.0f}s{gap_txt}")
    print("saved: classical_run.mp4, result_milp.json")
