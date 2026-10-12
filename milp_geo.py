"""
milp_geo.py : 新緑県データ + 充電つきドローン観測計画を MILP (QUBOなし) で解く

  変数  x[d,t,c] ∈ {0,1}   機体 d が ステップ t に セル c に居る
        b[d,t]   ∈ [0,B]   バッテリー残量 (連続)
        y[s]     ∈ [0,1]   セル s が一度でも観測されたか
        uc,ua,ub[m] ∈ [0,1] 市町村 m の 被覆率/alpha/beta の達成度 (上限1でキャップ)

  max  (1/(3M)) Σ_m (uc[m] + ua[m] + ub[m])

  s.t. Σ_c x[d,t,c] = 1
       移動:   x[d,t+1,c'] ≤ Σ_{c→c' 到達可} x[d,t,c]
       充電:   b[d,t] ≤ b[d,t-1] - E_d + (E_d + CHARGE) * Σ_{c∈ST} x[d,t,c]
               (ステーションに居れば +CHARGE, 居なければ -E_d. b>=0 が実行可能条件)
       観測:   y[s] ≤ Σ_{d,t,c: K_d[c,s]} x[d,t,c]
       被覆:   uc[m] ≤ (Σ_{s∈m} y[s] / N_m) / req_cov[m]
       alpha:  ua[m] ≤ (Σ_{d,t,c∈m,c∉ST} alpha_d x[d,t,c]) / req_a[m]
       beta:   ub[m] ≤ (同様) / req_b[m]

  「和集合」「min(1,·) のキャップ」「バッテリーの累積制約」を厳密に線形で書ける.
"""
import time
import json
import numpy as np
import scipy.sparse as sp
from scipy.optimize import milp, LinearConstraint, Bounds

import geo_common as g
from geo_common import D, T, D_TYPES, BATT_MAX, CHARGE, E_TYPE


def solve(time_limit=150, mip_rel_gap=1e-3):
    S = g.build_scenario()
    C, M = S.C, S.M
    nx = D * T * C
    ib0 = nx                      # b[d,t] (t=1..T)
    iy0 = ib0 + D * T
    iu0 = iy0 + C                 # uc, ua, ub : 3*M
    nvar = iu0 + 3 * M

    def vx(d, t, c): return (d * T + t) * C + c
    def vb(d, t): return ib0 + d * T + t
    def vy(s): return iy0 + s
    def vu(kind, m): return iu0 + kind * M + m   # kind 0:cov 1:alpha 2:beta

    rows, cols, vals, lo, hi = [], [], [], [], []
    r = 0

    def add(ent, l, u):
        nonlocal r
        for j, v in ent:
            rows.append(r); cols.append(j); vals.append(v)
        lo.append(l); hi.append(u); r += 1

    st = list(S.stations)
    for d in range(D):
        tid = D_TYPES[d]
        e = E_TYPE[tid]
        for t in range(T):
            add([(vx(d, t, c), 1.0) for c in range(C)], 1, 1)               # one-hot
            # バッテリー
            prev = [(vb(d, t - 1), -1.0)] if t > 0 else []
            const = BATT_MAX if t == 0 else 0
            # b[t] - b[t-1] + e - (e+CHARGE)*s <= 0  (t=0 は b[-1]=BATT_MAX)
            ent = [(vb(d, t), 1.0)] + prev + [(vx(d, t, c), -(e + CHARGE)) for c in st]
            add(ent, -np.inf, -e + const)
        for t in range(T - 1):                                               # 移動
            for c2 in range(C):
                ent = [(vx(d, t + 1, c2), 1.0)] + \
                      [(vx(d, t, c1), -1.0) for c1 in range(C) if S.reach[c1, c2]]
                add(ent, -np.inf, 0)
    # 観測の和集合
    for s in range(C):
        ent = [(vy(s), 1.0)]
        for d in range(D):
            K = S.K[D_TYPES[d]]
            for t in range(T):
                for c in np.where(K[:, s])[0]:
                    ent.append((vx(d, t, c), -1.0))
        add(ent, -np.inf, 0)
    # 市町村ごとの達成度
    for m in range(M):
        cells_m = np.where(S.cmuni == m)[0]
        # 被覆
        ent = [(vu(0, m), 1.0)] + [(vy(s), -1.0 / (S.Nm[m] * S.req_cov[m])) for s in cells_m]
        add(ent, -np.inf, 0)
        # alpha / beta
        for kind, req, tab in ((1, S.req_a[m], S.alpha), (2, S.req_b[m], S.beta)):
            ent = [(vu(kind, m), 1.0)]
            for d in range(D):
                w = tab[D_TYPES[d]] / req
                for t in range(T):
                    for c in cells_m:
                        if not S.is_station[c]:
                            ent.append((vx(d, t, c), -w))
            add(ent, -np.inf, 0)

    A = sp.csr_matrix((vals, (rows, cols)), shape=(r, nvar))
    cvec = np.zeros(nvar)
    cvec[iu0:] = -1.0 / (3 * M)
    lb = np.zeros(nvar)
    ub = np.ones(nvar)
    for d in range(D):
        for t in range(T):
            ub[vb(d, t)] = BATT_MAX
        for c in range(C):                                                    # 初期位置から届かない
            if not S.reach[S.start[d], c]:
                ub[vx(d, 0, c)] = 0
    integrality = np.zeros(nvar)
    integrality[:nx] = 1

    print(f"[MILP] 変数={nvar} (2値 {nx}) 制約={r} 非零={A.nnz}  セル={C} 機体={D} T={T}")
    t0 = time.time()
    res = milp(cvec, constraints=LinearConstraint(A, lo, hi), integrality=integrality,
               bounds=Bounds(lb, ub),
               options=dict(time_limit=time_limit, mip_rel_gap=mip_rel_gap, disp=False))
    t_solve = time.time() - t0
    print(f"[MILP] status={res.status} ({res.message.split('(')[0].strip()}) {t_solve:.1f}s")
    if res.x is None:
        raise RuntimeError("解なし: " + res.message)
    path = np.zeros((D, T), dtype=int)
    for d in range(D):
        for t in range(T):
            path[d, t] = int(np.argmax(res.x[vx(d, t, 0): vx(d, t, 0) + C]))
    ev = g.evaluate(S, path)
    gap = getattr(res, "mip_gap", None)
    print(f"[結果] score={ev['score']:.4f} 要求達成 {ev['requirements_met']}/{ev['requirements_total']} "
          f"充電ステップ={ev['charge_steps']} 最小電池={ev['min_battery']} "
          f"feasible={ev['feasible']} gap={gap}")
    out = dict(method="MILP (scipy/HiGHS)", score=ev["score"], feasible=bool(ev["feasible"]),
               requirements_met=ev["requirements_met"], requirements_total=ev["requirements_total"],
               charge_steps=ev["charge_steps"], min_battery=ev["min_battery"],
               cov=ev["cov"].round(3).tolist(), A=ev["A"].tolist(), B=ev["B"].tolist(),
               n_vars=int(nvar), n_binary=int(nx), n_constraints=int(r), solve_sec=t_solve,
               mip_gap=None if gap is None else float(gap), status=int(res.status),
               path=path.tolist())
    return out, path, S


if __name__ == "__main__":
    res, path, S = solve()
    json.dump(res, open("result_milp_geo.json", "w"), indent=1)
    gap = "" if res["mip_gap"] is None else f" / gap {res['mip_gap']*100:.2f}%"
    g.make_video(S, path, "classical_geo.mp4",
                 title="古典最適化 (MILP) ※QUBOなし : 新緑県 / 充電つき",
                 subtitle=f"セル {S.C} / 機体 {D} / {T}ステップ / 変数 {res['n_vars']} / "
                          f"score={res['score']:.3f} / 要求達成 {res['requirements_met']}/"
                          f"{res['requirements_total']} / 求解 {res['solve_sec']:.0f}s{gap}")
    print("saved: classical_geo.mp4, result_milp_geo.json")
