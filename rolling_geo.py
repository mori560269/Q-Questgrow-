"""
rolling_geo.py : 新緑県 + 充電つきの観測計画を「単位時間ごとの再最適化」(ローリングホライズン) で解く

  qubo_geo.py は T=10 ステップ全体を1つの QUBO にするので, 2次項が約119万になり遅い.
  ここでは
    状態 = (各機の位置, バッテリー残量, 観測済みセル, 市町村ごとの alpha/beta 累計)
  を持ち, 先読み HORIZON ステップぶんの小さな QUBO を解いて, 先頭 UNIT ステップだけ確定する.

  窓ごとの QUBO は qubo_geo.py と同じ構成 (被覆報酬 + 重複ペナルティ + alpha/beta 不足の
  2乗ペナルティ + one-hot + モード整合 + バッテリー遷移 + 移動) で, 次の点だけ変えている.
    - 被覆報酬: 観測済みセルと, 被覆率の要求をもう満たした市町村のセルは 0
    - alpha/beta: 要求値から累計を引いた「残り」だけを目標にする (満たしていれば項ごと省略)
    - バッテリー: 窓の最初の残量は BATT_MAX ではなく現在の残量
    - ペナルティ係数: 被覆報酬だけでなく alpha/beta の報酬も含めた最大値を基準にする
      (qubo_geo.py では制約を破るほうが得になる場合があった)

  使い方:
    python rolling_geo.py --unit 2 --horizon 3
    python rolling_geo.py --backend amplify --token XXXX
"""
import argparse
import json
import time
import numpy as np

import geo_common as g
from geo_common import D, T, D_TYPES, BATT_MAX, CHARGE, E_TYPE
from solver_backend import solve_qubo

NL = BATT_MAX + 1
LAM_OV = 0.3
KAPPA = 2.0
PEN = 3.0


def f_next(l, m, tid):
    """バッテリー遷移. m=0:稼働, m=1:充電. 不可能なら None"""
    if m == 0:
        l2 = l - E_TYPE[tid]
        return l2 if l2 >= 0 else None
    return min(BATT_MAX, l + CHARGE)


class State:
    def __init__(self, S):
        self.pos = list(S.start)
        self.bat = [BATT_MAX] * D
        self.covered = np.zeros(S.C, dtype=bool)
        self.A = np.zeros(S.M)
        self.B = np.zeros(S.M)


def apply_path(S, st, path):
    """窓の経路を状態に適用した結果 (新しい State, 実行可能か) を返す"""
    new = State(S)
    new.pos, new.bat = list(st.pos), list(st.bat)
    new.covered, new.A, new.B = st.covered.copy(), st.A.copy(), st.B.copy()
    ok = True
    for d in range(D):
        tid = D_TYPES[d]
        for h in range(path.shape[1]):
            c = int(path[d, h])
            ok &= bool(S.reach[new.pos[d], c])
            new.pos[d] = c
            if S.is_station[c]:
                new.bat[d] = min(BATT_MAX, new.bat[d] + CHARGE)
                continue
            new.bat[d] -= E_TYPE[tid]
            ok &= new.bat[d] >= 0
            new.covered |= S.K[tid][c]
            new.A[S.cmuni[c]] += S.alpha[tid]
            new.B[S.cmuni[c]] += S.beta[tid]
    return new, ok


def score(S, st):
    cov = np.array([st.covered[S.cmuni == m].mean() for m in range(S.M)])
    r = (np.minimum(1, cov / S.req_cov) + np.minimum(1, st.A / S.req_a)
         + np.minimum(1, st.B / S.req_b))
    return float(r.sum() / (3 * S.M))


def build_window_qubo(S, st, H, lam_ov=LAM_OV, kappa=KAPPA, pen=PEN):
    C, M = S.C, S.M
    omega = 1.0 / (3 * M)
    nx = D * H * C
    off_q = nx
    nq = D * H * NL * 2
    off_z = off_q + nq

    def vx(d, h, c=0): return (d * H + h) * C + c
    def vq(d, h, l, m): return off_q + ((d * H + h) * NL + l) * 2 + m

    lin = {}
    lin_x = np.zeros(nx)
    rows, cols, vals = [], [], []
    offset = 0.0

    def add_lin(i, v):
        lin[i] = lin.get(i, 0.0) + v

    # ---- 1) 被覆 (未観測かつ要求未達の市町村のセルだけ報酬)
    cov_now = np.array([st.covered[S.cmuni == m].mean() for m in range(M)])
    nu = np.zeros(C)
    for m in range(M):
        if cov_now[m] < S.req_cov[m] - 1e-9:
            nu[S.cmuni == m] = omega / (S.req_cov[m] * S.Nm[m])
    nu[st.covered] = 0.0
    tids = sorted(set(D_TYPES))
    Kw = {k: S.K[k] * nu[None, :] for k in tids}
    wgain = {k: Kw[k].sum(1) for k in tids}
    for d in range(D):
        for h in range(H):
            lin_x[vx(d, h): vx(d, h) + C] -= wgain[D_TYPES[d]]
    OV = {}
    for k1 in tids:
        for k2 in tids:
            ov = Kw[k1] @ S.K[k2].T.astype(float)
            ci, cj = np.nonzero(ov > 1e-15)
            OV[(k1, k2)] = (ci, cj, lam_ov * ov[ci, cj])
    slots = [(d, h) for d in range(D) for h in range(H)]
    for a in range(len(slots)):
        for b in range(a + 1, len(slots)):
            ci, cj, vv = OV[(D_TYPES[slots[a][0]], D_TYPES[slots[b][0]])]
            if len(vv):
                rows.append(vx(*slots[a]) + ci); cols.append(vx(*slots[b]) + cj); vals.append(vv)

    # ---- 2) alpha / beta の残り要求 (スラック付き2乗ペナルティ)
    nz = 0
    for kind, req_arr, tab, done in (("alpha", S.req_a, S.alpha, st.A),
                                     ("beta", S.req_b, S.beta, st.B)):
        for m in range(M):
            Rr = req_arr[m] - done[m]
            if Rr <= 1e-9:
                continue
            cells_m = [c for c in np.where(S.cmuni == m)[0] if not S.is_station[c]]
            idx, v = [], []
            for d in range(D):
                for h in range(H):
                    for c in cells_m:
                        idx.append(vx(d, h, c)); v.append(float(tab[D_TYPES[d]]))
            vmax_total = H * sum(tab[tt] for tt in D_TYPES)
            nbit = int(np.ceil(np.log2(vmax_total - Rr + 1))) if vmax_total > Rr else 0
            for k in range(nbit):
                idx.append(off_z + nz); v.append(-float(2 ** k)); nz += 1
            idx = np.array(idx); v = np.array(v)
            W = kappa * omega / req_arr[m] ** 2
            lc = W * (v ** 2 - 2 * Rr * v)
            xs = idx < nx
            np.add.at(lin_x, idx[xs], lc[xs])
            for i_, c_ in zip(idx[~xs], lc[~xs]):
                add_lin(int(i_), float(c_))
            iu = np.triu_indices(len(idx), k=1)
            rows.append(idx[iu[0]]); cols.append(idx[iu[1]]); vals.append(2 * W * v[iu[0]] * v[iu[1]])
            offset += W * Rr ** 2

    # ペナルティ係数: 1変数あたりの報酬の最大値を基準にする
    P = pen * max(-lin_x.min(), 1e-4)

    # ---- 3) one-hot (x と q)
    iu = np.triu_indices(C, k=1)
    iuq = np.triu_indices(NL * 2, k=1)
    for d, h in slots:
        bx = vx(d, h)
        lin_x[bx: bx + C] -= P
        rows.append(bx + iu[0]); cols.append(bx + iu[1]); vals.append(np.full(len(iu[0]), 2 * P))
        bq = vq(d, h, 0, 0)
        for k in range(NL * 2):
            add_lin(bq + k, -P)
        rows.append(bq + iuq[0]); cols.append(bq + iuq[1]); vals.append(np.full(len(iuq[0]), 2 * P))
        offset += 2 * P

    # ---- 4) モードと位置の整合
    stn = np.array(S.stations)
    nst = np.where(~S.is_station)[0]
    for d, h in slots:
        for l in range(NL):
            rows.append(np.full(len(stn), vq(d, h, l, 0))); cols.append(vx(d, h) + stn)
            vals.append(np.full(len(stn), P))
            rows.append(np.full(len(nst), vq(d, h, l, 1))); cols.append(vx(d, h) + nst)
            vals.append(np.full(len(nst), P))

    # ---- 5) バッテリー遷移 (窓の最初は現在の残量から)
    for d in range(D):
        tid = D_TYPES[d]
        for m in (0, 1):
            for l in range(NL):
                if f_next(st.bat[d], m, tid) != l:
                    add_lin(vq(d, 0, l, m), P)
        for h in range(1, H):
            ia, ja = [], []
            for lp in range(NL):
                for mp in (0, 1):
                    for l in range(NL):
                        for m in (0, 1):
                            if f_next(lp, m, tid) != l:
                                ia.append(vq(d, h - 1, lp, mp)); ja.append(vq(d, h, l, m))
            rows.append(np.array(ia)); cols.append(np.array(ja)); vals.append(np.full(len(ia), P))

    # ---- 6) 移動 (窓の最初は現在の位置から)
    u1, u2 = np.nonzero(~S.reach)
    for d in range(D):
        lin_x[vx(d, 0): vx(d, 0) + C] += P * (~S.reach[st.pos[d]])
        for h in range(H - 1):
            rows.append(vx(d, h) + u1); cols.append(vx(d, h + 1) + u2)
            vals.append(np.full(len(u1), P))

    n = off_z + nz
    linear = np.zeros(n)
    linear[:nx] = lin_x
    for i, v in lin.items():
        linear[i] += v
    return n, linear, rows, cols, vals, offset


def decode(vec, S, H):
    C = S.C
    path = np.zeros((D, H), dtype=int)
    viol = 0
    for d in range(D):
        for h in range(H):
            blk = vec[(d * H + h) * C:(d * H + h + 1) * C]
            viol += int(blk.sum() != 1)
            path[d, h] = int(np.argmax(blk))
    return path, viol


def repair(S, st, path):
    """移動違反・バッテリー切れを修復 (qubo_geo.repair を現在の状態から始めるようにしたもの)"""
    path = path.copy()
    for d in range(D):
        e = E_TYPE[D_TYPES[d]]
        b = st.bat[d]
        prev = st.pos[d]
        for h in range(path.shape[1]):
            c = path[d, h]
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
            path[d, h] = c
            b = min(BATT_MAX, b + CHARGE) if S.is_station[c] else b - e
            prev = c
    return path


def solve(unit=2, horizon=3, backend="neal", num_reads=20, num_sweeps=1000, seed=0,
          token=None, time_limit_ms=1000, verbose=True):
    S = g.build_scenario()
    st = State(S)
    full = np.zeros((D, T), dtype=int)
    log = []
    t_all = time.time()
    t0 = 0
    while t0 < T:
        H = min(horizon, T - t0)
        U = min(unit, H)
        tb = time.time()
        n, lin, rows, cols, vals, off = build_window_qubo(S, st, H)
        t_build = time.time() - tb
        samples, _, t_solve, nq = solve_qubo(n, lin, rows, cols, vals, off, backend=backend,
                                              num_reads=num_reads, num_sweeps=num_sweeps,
                                              seed=seed + t0, token=token,
                                              time_limit_ms=time_limit_ms)
        best, n_raw_ok = None, 0
        for vec in samples:
            path, viol = decode(vec, S, H)
            new, ok = apply_path(S, st, path)
            if not (ok and viol == 0):
                path = repair(S, st, path)
                new, ok = apply_path(S, st, path)
                if not ok:
                    continue
            else:
                n_raw_ok += 1
            cand = (score(S, new), path)
            if best is None or cand[0] > best[0]:
                best = cand
        if best is None:
            raise RuntimeError(f"t={t0}: 修復しても実行可能な解が得られませんでした")
        path = best[1]
        full[:, t0:t0 + U] = path[:, :U]
        st, _ = apply_path(S, st, path[:, :U])
        log.append(dict(t0=t0, horizon=H, unit=U, n_vars=int(n), n_quadratic=int(nq),
                        build_sec=t_build, solve_sec=t_solve,
                        raw_feasible=n_raw_ok, num_samples=len(samples)))
        if verbose:
            print(f"[窓 t={t0}..{t0 + H - 1}] 変数 {n} / 2次項 {nq} / 構築 {t_build:.2f}s / "
                  f"求解 {t_solve:.2f}s / 修復なしOK {n_raw_ok}/{len(samples)} / "
                  f"score(確定分) {score(S, st):.3f}", flush=True)
        t0 += U
    total = time.time() - t_all
    ev = g.evaluate(S, full)
    if verbose:
        print(f"[結果] score={ev['score']:.4f} 要求達成 {ev['requirements_met']}/"
              f"{ev['requirements_total']} 充電ステップ={ev['charge_steps']} "
              f"feasible={ev['feasible']} 合計 {total:.1f}s")
    out = dict(method=f"rolling QUBO ({backend})", unit=unit, horizon=horizon,
               score=ev["score"], feasible=bool(ev["feasible"]),
               requirements_met=ev["requirements_met"],
               requirements_total=ev["requirements_total"], charge_steps=ev["charge_steps"],
               min_battery=ev["min_battery"], cov=ev["cov"].round(3).tolist(),
               A=ev["A"].tolist(), B=ev["B"].tolist(), total_sec=total,
               solve_sec=sum(x["solve_sec"] for x in log),
               raw_feasible_windows=sum(1 for x in log if x["raw_feasible"] > 0),
               windows=log, path=full.tolist())
    return out, full, S


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--unit", type=int, default=2, help="1回の最適化で確定するステップ数 (単位時間)")
    ap.add_argument("--horizon", type=int, default=3, help="先読みするステップ数 (>= unit)")
    ap.add_argument("--backend", choices=["neal", "amplify"], default="neal")
    ap.add_argument("--reads", type=int, default=20)
    ap.add_argument("--sweeps", type=int, default=1000)
    ap.add_argument("--token", default=None, help="Fixstars Amplify AE のトークン (AMPLIFY_TOKEN でも可)")
    ap.add_argument("--time-limit-ms", type=int, default=1000, help="Amplify AE の1窓あたりの制限時間")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default="result_rolling_geo.json")
    ap.add_argument("--video", default=None, help="動画の出力先 (省略時は作らない)")
    a = ap.parse_args()
    res, path, S = solve(a.unit, max(a.horizon, a.unit), a.backend, a.reads, a.sweeps, a.seed,
                         a.token, a.time_limit_ms)
    json.dump(res, open(a.out, "w"), indent=1)
    if a.video:
        g.make_video(S, path, a.video,
                     title=f"ローリング QUBO ({a.backend}) : 新緑県 / 単位 {a.unit} / 先読み {res['horizon']}",
                     subtitle=f"score={res['score']:.3f} / 要求達成 {res['requirements_met']}/"
                              f"{res['requirements_total']} / 合計 {res['total_sec']:.1f}s")
    print("saved:", a.out, a.video or "")
