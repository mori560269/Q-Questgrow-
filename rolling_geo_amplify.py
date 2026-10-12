"""
rolling_geo_amplify.py : 新緑県 + 充電つき観測計画を Fixstars Amplify の書き方で定式化し,
                         単位時間ごとに再最適化 (ローリングホライズン) する

  Q-Quest GROW ハンズオンのノートブックと同じ流れで書いている.
    1. VariableGenerator で変数 x[d,h,c] を発行
    2. コスト関数を NumPy 風に書く
    3. 制約は one_hot() / greater_equal() で書く
    4. AmplifyAEClient (time_limit_ms=1000) で solve
    5. x.evaluate(...) で 0/1 の配列に戻す

  rolling_geo.py (自前で QUBO 行列を組む版) との違い
    - バッテリーは「状態変数 q + 遷移ペナルティ」ではなく, 窓内の累積残量の
      greater_equal 制約で表す (窓が短いので素直に書ける. ただし BATT_MAX で
      頭打ちになる効果は無視しているため, 最終判定は厳密なシミュレーションで行う)
    - モードと位置の整合 (q と x の対応) が不要になり, 変数が x とスラックだけになる
    - alpha/beta の不足は整数スラック s を使った 2乗ペナルティ W (A - R - s)^2

  backend
    "amplify" : Fixstars Amplify AE で解く (アクセストークンが必要)
    "neal"    : 同じ Model を Amplify で QUBO に変換し, ローカルの焼きなましで解く
                (トークン不要. 定式化の確認用)

  使い方:
    AMPLIFY_TOKEN=xxxx python rolling_geo_amplify.py --unit 2 --horizon 3
    python rolling_geo_amplify.py --backend neal
"""
import argparse
import json
import os
import time
from datetime import timedelta
import numpy as np
from amplify import (VariableGenerator, Model, AmplifyAEClient, solve, one_hot,
                     greater_equal, AcceptableDegrees)

import geo_common as g
from geo_common import D, T, D_TYPES, CHARGE, E_TYPE
from rolling_geo import State, apply_path, score, repair

LAM_OV = 0.3     # 観測の重複ペナルティ (包除原理の2次近似)
KAPPA = 2.0      # alpha/beta 不足ペナルティの重み
PEN = 3.0        # 制約の重み = PEN × (1変数あたりの報酬の最大値)


def build_model(S, st, H, lam_ov=LAM_OV, kappa=KAPPA, pen=PEN):
    """現在の状態 st から H ステップぶんの Amplify Model を作る"""
    C, M = S.C, S.M
    omega = 1.0 / (3 * M)

    # ---- 変数を発行
    gen = VariableGenerator()
    x = gen.array("Binary", shape=(D, H, C))

    # ---- コスト関数 1: 被覆 (未観測かつ要求未達の市町村のセルだけ報酬)
    cov_now = np.array([st.covered[S.cmuni == m].mean() for m in range(M)])
    nu = np.zeros(C)
    for m in range(M):
        if cov_now[m] < S.req_cov[m] - 1e-9:
            nu[S.cmuni == m] = omega / (S.req_cov[m] * S.Nm[m])
    nu[st.covered] = 0.0
    tids = sorted(set(D_TYPES))
    Kw = {k: S.K[k] * nu[None, :] for k in tids}
    wgain = {k: Kw[k].sum(1) for k in tids}
    OV = {(k1, k2): lam_ov * (Kw[k1] @ S.K[k2].T.astype(float)) for k1 in tids for k2 in tids}

    cover = 0
    for d in range(D):
        cover -= (wgain[D_TYPES[d]] * x[d]).sum()
    slots = [(d, h) for d in range(D) for h in range(H)]
    overlap = 0
    for a in range(len(slots)):
        for b in range(a + 1, len(slots)):
            (da, ha), (db, hb) = slots[a], slots[b]
            mat = OV[(D_TYPES[da], D_TYPES[db])]
            if mat.any():
                overlap += ((x[da, ha] @ mat) * x[db, hb]).sum()
    rew_max = max(v.max() for v in wgain.values())

    # ---- コスト関数 2: alpha / beta の残り要求 (整数スラック付き 2乗ペナルティ)
    shortfall = 0
    for tab, req, done in ((S.alpha, S.req_a, st.A), (S.beta, S.req_b, st.B)):
        for m in range(M):
            rest = req[m] - done[m]
            if rest <= 1e-9:
                continue
            mask = ((S.cmuni == m) & ~S.is_station).astype(float)
            amount = 0
            for d in range(D):
                amount += (tab[D_TYPES[d]] * mask * x[d]).sum()
            vmax = H * sum(tab[k] for k in D_TYPES)
            target = min(rest, vmax)
            W = kappa * omega / req[m] ** 2
            s = gen.scalar("Integer", bounds=(0, max(1, int(np.ceil(vmax - target)))))
            shortfall += W * (amount - target - s) ** 2
            vv = max(tab.values())
            rew_max = max(rew_max, W * (2 * target * vv - vv ** 2))

    P = pen * max(rew_max, 1e-4)

    # ---- 罰金項: 移動制約 (窓の最初は現在位置から)
    U = (~S.reach).astype(float)
    move = 0
    for d in range(D):
        move += (x[d, 0] * U[st.pos[d]]).sum()
        for h in range(H - 1):
            move += ((x[d, h] @ U) * x[d, h + 1]).sum()

    # ---- 制約: one-hot と バッテリー
    constraints = one_hot(x, axis=2) * P
    st_mask = S.is_station.astype(float)
    for d in range(D):
        e = E_TYPE[D_TYPES[d]]
        cum = 0
        for h in range(H):
            # 残量 = b0 + Σ (CHARGE·充電 - e·稼働) >= 0  ⇔  Σ (CHARGE+e)·充電 >= e(h+1) - b0
            cum += (CHARGE + e) * (x[d, h] * st_mask).sum()
            need = e * (h + 1) - st.bat[d]
            if need > 0:
                constraints += greater_equal(cum, need) * P

    model = Model(cover + overlap + shortfall + P * move, constraints)
    return model, x


def solve_window(model, x, backend, token=None, time_limit_ms=1000,
                 num_reads=20, num_sweeps=1000, seed=0):
    """Model を解いて, x を (D,H,C) の 0/1 配列にしたものを候補として返す"""
    t0 = time.time()
    if backend == "amplify":
        client = AmplifyAEClient()
        client.token = token or os.environ.get("AMPLIFY_TOKEN")
        if not client.token:
            raise RuntimeError("Amplify AE のアクセストークンを --token か AMPLIFY_TOKEN で指定してください")
        client.parameters.time_limit_ms = timedelta(milliseconds=time_limit_ms)
        # 制約違反の解も受け取り, 後段で修復・採点する
        result = solve(model, client, filter_solution=False)
        cands = [np.rint(x.evaluate(sol.values, 0.0)).astype(int) for sol in result]
        info = dict(n_vars=None)
    else:
        import dimod
        import neal
        im, _ = model.to_intermediate_model(AcceptableDegrees(objective={"Binary": "Quadratic"}))
        poly = im.to_unconstrained_poly()
        lin, quad, off = {}, {}, 0.0
        for k, v in poly.as_dict().items():
            if len(k) == 0:
                off += v
            elif len(k) == 1 or k[0] == k[1]:
                lin[k[0]] = lin.get(k[0], 0.0) + v
            else:
                quad[k] = quad.get(k, 0.0) + v
        bqm = dimod.BinaryQuadraticModel(lin, quad, off, "BINARY")
        ss = neal.SimulatedAnnealingSampler().sample(bqm, num_reads=num_reads,
                                                     num_sweeps=num_sweeps, seed=seed)
        ids = np.array([v.as_variable().id for v in x.flat]).reshape(x.shape)
        cands = []
        for rec in ss.data(["sample"], sorted_by="energy"):
            smp = rec.sample
            cands.append(np.vectorize(lambda i: smp.get(int(i), 0))(ids).astype(int))
        info = dict(n_vars=len(bqm.variables), n_quadratic=len(bqm.quadratic))
    return cands, time.time() - t0, info


def run(unit=2, horizon=3, backend="amplify", token=None, time_limit_ms=1000,
        num_reads=20, num_sweeps=1000, seed=0, verbose=True):
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
        model, x = build_model(S, st, H)
        t_build = time.time() - tb
        cands, t_solve, info = solve_window(model, x, backend, token, time_limit_ms,
                                            num_reads, num_sweeps, seed + t0)
        best, n_raw_ok = None, 0
        for arr in cands:
            path = arr.argmax(axis=2)
            viol = int((arr.sum(axis=2) != 1).sum())
            new, ok = apply_path(S, st, path)
            if ok and viol == 0:
                n_raw_ok += 1
            else:
                path = repair(S, st, path)
                new, ok = apply_path(S, st, path)
                if not ok:
                    continue
            if best is None or score(S, new) > best[0]:
                best = (score(S, new), path)
        if best is None:
            raise RuntimeError(f"t={t0}: 実行可能な解が得られませんでした")
        path = best[1]
        full[:, t0:t0 + U] = path[:, :U]
        st, _ = apply_path(S, st, path[:, :U])
        log.append(dict(t0=t0, horizon=H, unit=U, build_sec=t_build, solve_sec=t_solve,
                        raw_feasible=n_raw_ok, num_samples=len(cands), **info))
        if verbose:
            print(f"[窓 t={t0}..{t0 + H - 1}] 構築 {t_build:.2f}s / 求解 {t_solve:.2f}s / "
                  f"修復なしOK {n_raw_ok}/{len(cands)} / score(確定分) {score(S, st):.3f}",
                  flush=True)
        t0 += U
    total = time.time() - t_all
    ev = g.evaluate(S, full)
    if verbose:
        print(f"[結果] score={ev['score']:.4f} 要求達成 {ev['requirements_met']}/"
              f"{ev['requirements_total']} feasible={ev['feasible']} 合計 {total:.1f}s")
    out = dict(method=f"rolling Amplify model ({backend})", unit=unit, horizon=horizon,
               score=ev["score"], feasible=bool(ev["feasible"]),
               requirements_met=ev["requirements_met"],
               requirements_total=ev["requirements_total"], charge_steps=ev["charge_steps"],
               min_battery=ev["min_battery"], cov=ev["cov"].round(3).tolist(),
               A=ev["A"].tolist(), B=ev["B"].tolist(), total_sec=total,
               solve_sec=sum(w["solve_sec"] for w in log), windows=log, path=full.tolist())
    return out, full, S


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--unit", type=int, default=2, help="1回の最適化で確定するステップ数 (単位時間)")
    ap.add_argument("--horizon", type=int, default=3, help="先読みするステップ数 (>= unit)")
    ap.add_argument("--backend", choices=["amplify", "neal"], default="amplify")
    ap.add_argument("--token", default=None, help="Amplify AE のトークン (AMPLIFY_TOKEN でも可)")
    ap.add_argument("--time-limit-ms", type=int, default=1000)
    ap.add_argument("--reads", type=int, default=20)
    ap.add_argument("--sweeps", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default="result_rolling_geo_amplify.json")
    ap.add_argument("--video", default=None)
    a = ap.parse_args()
    res, path, S = run(a.unit, max(a.horizon, a.unit), a.backend, a.token, a.time_limit_ms,
                       a.reads, a.sweeps, a.seed)
    json.dump(res, open(a.out, "w"), indent=1)
    if a.video:
        g.make_video(S, path, a.video,
                     title=f"ローリング最適化 (Amplify 定式化 / {a.backend}) : 新緑県",
                     subtitle=f"単位 {a.unit} / 先読み {res['horizon']} / score={res['score']:.3f} / "
                              f"要求達成 {res['requirements_met']}/{res['requirements_total']} / "
                              f"合計 {res['total_sec']:.1f}s")
    print("saved:", a.out, a.video or "")
