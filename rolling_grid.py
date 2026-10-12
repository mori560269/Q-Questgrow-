"""
rolling_grid.py : グリッド版の観測計画を「単位時間ごとの再最適化」(ローリングホライズン) で解く

  全 T ステップを一度に QUBO にすると, 観測重複の2次項が (D·T)^2 に比例して増え,
  焼きなましが遅くなる. そこで
    1) 現在の位置と「これまでに観測済みのセル」を状態として持ち,
    2) 先読み HORIZON ステップぶんだけの小さな QUBO を作って解き,
    3) そのうち先頭 UNIT ステップ (= 単位時間) だけを確定して実行,
    4) 状態を更新して 2) に戻る
  を繰り返す. 観測済みセルの確率は 0 として扱うので, 次の窓では未観測の場所を優先する.

  QUBO の中身は qubo_sa.py と同じ (観測報酬 + 重複ペナルティ + 危険領域 + one-hot +
  移動制約 + 衝突) だが, 構築を numpy でベクトル化している.

  使い方:
    python rolling_grid.py --unit 1 --horizon 2                 # neal (ローカル)
    python rolling_grid.py --backend amplify --token XXXX        # Fixstars Amplify AE
"""
import argparse
import json
import time
import numpy as np

import common as cm
from common import N, D, T, LAMBDA_H
from solver_backend import solve_qubo

NC = N * N
REACH = np.array([[cm.reachable(a, b) for b in range(NC)] for a in range(NC)])


def build_window_qubo(p_rem, hazard, K, t0, H, pos, lam_ov=0.3):
    """t0 から H ステップぶんの QUBO. pos[d] は t0 直前の各機の位置"""
    nx = D * H * NC

    def base(d, h):
        return (d * H + h) * NC

    pK = K * p_rem[None, :]
    w = pK.sum(1)
    ov = pK @ K.T.astype(float)
    scale = max(w.max(), LAMBDA_H)
    PA, PB, PC = 2.0 * scale, 3.0 * scale, 2.0 * scale

    lin = np.zeros(nx)
    rows, cols, vals = [], [], []
    offset = PA * D * H
    iu = np.triu_indices(NC, k=1)
    ci, cj = np.nonzero(ov > 1e-12)
    ovv = lam_ov * ov[ci, cj]
    u1, u2 = np.nonzero(~REACH)
    slots = [(d, h) for d in range(D) for h in range(H)]

    for d, h in slots:
        b = base(d, h)
        lin[b:b + NC] += -w + LAMBDA_H * hazard[t0 + h + 1] - PA
        rows.append(b + iu[0]); cols.append(b + iu[1]); vals.append(np.full(len(iu[0]), 2 * PA))
    for a in range(len(slots)):                       # 観測の重複 (異なる slot 間)
        for b_ in range(a + 1, len(slots)):
            rows.append(base(*slots[a]) + ci); cols.append(base(*slots[b_]) + cj); vals.append(ovv)
    for h in range(H):                                # 衝突
        for d1 in range(D):
            for d2 in range(d1 + 1, D):
                rows.append(base(d1, h) + np.arange(NC)); cols.append(base(d2, h) + np.arange(NC))
                vals.append(np.full(NC, PC))
    for d in range(D):                                # 移動
        lin[base(d, 0): base(d, 0) + NC] += PB * (~REACH[pos[d]])
        for h in range(H - 1):
            rows.append(base(d, h) + u1); cols.append(base(d, h + 1) + u2)
            vals.append(np.full(len(u1), PB))
    return nx, lin, rows, cols, vals, offset


def decode(vec, H):
    path = np.zeros((D, H), dtype=int)
    viol = 0
    for d in range(D):
        for h in range(H):
            blk = vec[(d * H + h) * NC:(d * H + h + 1) * NC]
            viol += int(blk.sum() != 1)
            path[d, h] = int(np.argmax(blk))
    return path, viol


def repair(path, pos):
    """移動制約と衝突を, 元の位置に近い到達可能セルへずらして修復する"""
    path = path.copy()
    prev = list(pos)
    rc = np.array([divmod(c, N) for c in range(NC)])
    for h in range(path.shape[1]):
        used = set()
        for d in range(D):
            c = path[d, h]
            if not REACH[prev[d], c] or c in used:
                cand = [x for x in np.where(REACH[prev[d]])[0] if x not in used]
                c = int(min(cand, key=lambda x: ((rc[x] - rc[path[d, h]]) ** 2).sum()))
                path[d, h] = c
            used.add(c)
            prev[d] = c
    return path


def window_value(path, pos, p_rem, hazard, K, t0):
    """窓内の厳密な目的値 (新たに観測した確率 - 危険ペナルティ) と実行可能性"""
    H = path.shape[1]
    ok = all(REACH[pos[d], path[d, 0]] for d in range(D))
    ok &= all(REACH[path[d, h], path[d, h + 1]] for d in range(D) for h in range(H - 1))
    ok &= all(len(set(path[:, h])) == D for h in range(H))
    cov = K[path.ravel()].any(0)
    hz = sum(int(hazard[t0 + h + 1, path[d, h]]) for d in range(D) for h in range(H))
    return float(p_rem[cov].sum()) - LAMBDA_H * hz, ok


def solve(unit=1, horizon=2, backend="neal", num_reads=30, num_sweeps=2000, seed=0,
          token=None, time_limit_ms=1000, lam_ov=0.3, verbose=True):
    p, hazard = cm.build_scenario()
    K = cm.cover_matrix()
    pos = [cm.cid(*s) for s in cm.START]
    covered = np.zeros(NC, dtype=bool)
    full = np.zeros((D, T), dtype=int)
    log = []
    t_all = time.time()
    t0 = 0
    while t0 < T:
        H = min(horizon, T - t0)
        U = min(unit, H)
        p_rem = np.where(covered, 0.0, p)
        tb = time.time()
        nx, lin, rows, cols, vals, off = build_window_qubo(p_rem, hazard, K, t0, H, pos, lam_ov)
        t_build = time.time() - tb
        samples, _, t_solve, nq = solve_qubo(nx, lin, rows, cols, vals, off, backend=backend,
                                              num_reads=num_reads, num_sweeps=num_sweeps,
                                              seed=seed + t0, token=token,
                                              time_limit_ms=time_limit_ms)
        best, n_raw_ok = None, 0
        for vec in samples:
            path, viol = decode(vec, H)
            val, ok = window_value(path, pos, p_rem, hazard, K, t0)
            if ok and viol == 0:
                n_raw_ok += 1
                cand = (val, path)
            else:
                path = repair(path, pos)
                cand = (window_value(path, pos, p_rem, hazard, K, t0)[0], path)
            if best is None or cand[0] > best[0]:
                best = cand
        path = best[1]
        full[:, t0:t0 + U] = path[:, :U]
        for d in range(D):
            covered |= K[path[d, :U]].any(0)
            pos[d] = int(path[d, U - 1])
        log.append(dict(t0=t0, horizon=H, unit=U, n_vars=nx, n_quadratic=int(nq),
                        build_sec=t_build, solve_sec=t_solve,
                        raw_feasible=n_raw_ok, num_samples=len(samples)))
        if verbose:
            print(f"[窓 t={t0}..{t0 + H - 1}] 変数 {nx} / 2次項 {nq} / 構築 {t_build:.2f}s / "
                  f"求解 {t_solve:.2f}s / 修復なしOK {n_raw_ok}/{len(samples)}", flush=True)
        t0 += U
    total = time.time() - t_all
    ev = cm.evaluate(full, p, hazard, K)
    if verbose:
        print(f"[結果] J={ev['J']:.4f} 観測率={100 * ev['covered_mass']:.1f}% "
              f"危険滞在={ev['hazard_steps']} feasible={ev['feasible']} 合計 {total:.1f}s")
    out = dict(method=f"rolling QUBO ({backend})", unit=unit, horizon=horizon,
               J=ev["J"], covered_mass=ev["covered_mass"], hazard_steps=ev["hazard_steps"],
               feasible=bool(ev["feasible"]), total_sec=total,
               solve_sec=sum(x["solve_sec"] for x in log), windows=log, path=full.tolist())
    return out, full, p, hazard, K


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--unit", type=int, default=1, help="1回の最適化で確定するステップ数 (単位時間)")
    ap.add_argument("--horizon", type=int, default=2, help="先読みするステップ数 (>= unit)")
    ap.add_argument("--backend", choices=["neal", "amplify"], default="neal")
    ap.add_argument("--reads", type=int, default=30)
    ap.add_argument("--sweeps", type=int, default=2000)
    ap.add_argument("--token", default=None, help="Fixstars Amplify AE のトークン (AMPLIFY_TOKEN でも可)")
    ap.add_argument("--time-limit-ms", type=int, default=1000, help="Amplify AE の1窓あたりの制限時間")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default="result_rolling_grid.json")
    ap.add_argument("--video", default=None, help="動画の出力先 (省略時は作らない)")
    a = ap.parse_args()
    res, path, p, hazard, K = solve(a.unit, max(a.horizon, a.unit), a.backend, a.reads, a.sweeps,
                                    a.seed, a.token, a.time_limit_ms)
    json.dump(res, open(a.out, "w"), indent=1)
    if a.video:
        cm.make_video(path, p, hazard, K, a.video,
                      title=f"ローリング QUBO ({a.backend}) : 単位 {a.unit} / 先読み {res['horizon']}",
                      subtitle=f"J={res['J']:.3f} / 観測率 {100 * res['covered_mass']:.1f}% / "
                               f"合計 {res['total_sec']:.1f}s")
    print("saved:", a.out, a.video or "")
