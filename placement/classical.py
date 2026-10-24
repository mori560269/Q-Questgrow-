"""
placement/classical.py : 古典的な解き方 (QUBO を使わない)

  (A) MILP (混合整数線形計画, scipy.optimize.milp = HiGHS)  ... 厳密な最適解
      変数  x[p,k] ∈ {0,1}  候補地 p に種類 k を置く
            y[g]   ∈ [0,1]  マス g が少なくとも1つの円に入る (和集合)
      min   Σ_{p,k} cost_k x[p,k]
      s.t.  y[g] <= Σ_{(p,k): g が円の中} x[p,k]          (覆われたマスだけ y=1 にできる)
            Σ_{g∈m} y[g] >= req_cov_m · N_m               (面的充足率)
            Σ_k x[p,k] <= 1                               (1候補地に1台まで)
            Σ_{p∈m,k} α_k x[p,k] >= req_α_m,  β も同様     (α・β出力)
      マスが細かいときのために, 同じ市町村で「覆えるセンサーの組」が同じマスは 1 つの y にまとめ,
      マス数 w を重みにする (Σ w_c y_c >= req·N_m. 最適解は まとめない場合と同じ)

  (B) 貪欲法 (コスト当たりの「制約の不足をどれだけ埋めるか」が最大の手 (置く / 種類を変える) を
      繰り返し, 行き詰まったら 2 手の組み合わせも試す. 最後に要らないセンサーを高い順に外す)
"""
import time
import numpy as np
import scipy.sparse as sp
from scipy.optimize import milp, LinearConstraint, Bounds


def solve_milp(prob, time_limit=300, margin=0.0, obj=None, cost_cap=None):
    """obj: 目的を総コストの代わりに使うベクトル（長さ P*K）. cost_cap: 総コストの上限（制約として足す）"""
    P, K, M = prob.P, prob.K, prob.M
    nx = P * K
    # 覆えるセンサーの組が同じマスをまとめる (市町村ごと). w = まとめたマスの数
    _, first, inv, w = np.unique(np.c_[prob.creg[:, None].astype(np.uint8),
                                       np.packbits(prob.cover, axis=1)], axis=0,
                                 return_index=True, return_inverse=True, return_counts=True)
    N = len(first)
    creg, cover = prob.creg[first], prob.cover[first]
    n = nx + N
    c = np.r_[np.tile(prob.cost, P) if obj is None else np.asarray(obj, float), np.zeros(N)]
    rows = []
    if cost_cap is not None:
        rows.append((sp.csr_matrix(np.r_[np.tile(prob.cost, P), np.zeros(N)][None, :]), -np.inf, cost_cap))
    # y[c] - Σ cover x <= 0
    cov = sp.csr_matrix(cover.astype(float))
    A1 = sp.hstack([-cov, sp.identity(N)])
    rows.append((A1, -np.inf, 0))
    # Σ_{c∈m} w_c y[c] >= req·N_m
    G = sp.csr_matrix((w.astype(float), (creg, np.arange(N))), shape=(M, N))
    rows.append((sp.hstack([sp.csr_matrix((M, nx)), G]), (prob.req_cov + margin) * prob.Nm, np.inf))
    # Σ_k x[p,k] <= 1
    O = sp.kron(sp.identity(P), np.ones((1, K)))
    rows.append((sp.hstack([O, sp.csr_matrix((P, N))]), -np.inf, 1))
    # α, β
    for val, req in ((prob.alpha, prob.req_a), (prob.beta, prob.req_b)):
        R = sp.csr_matrix((np.tile(val, P), (np.repeat(prob.preg, K), np.arange(nx))), shape=(M, nx))
        rows.append((sp.hstack([R, sp.csr_matrix((M, N))]), req, np.inf))
    A = sp.vstack([r[0] for r in rows]).tocsr()
    lo = np.concatenate([np.broadcast_to(r[1], r[0].shape[0]) for r in rows])
    hi = np.concatenate([np.broadcast_to(r[2], r[0].shape[0]) for r in rows])
    t0 = time.time()
    res = milp(c, constraints=LinearConstraint(A, lo, hi), integrality=np.r_[np.ones(nx), np.zeros(N)],
               bounds=Bounds(0, 1), options=dict(time_limit=time_limit, disp=False))
    sec = time.time() - t0
    x = np.rint(res.x[:nx]).reshape(P, K) if res.x is not None else np.zeros((P, K))
    return x, dict(sec=sec, status=int(res.status), message=res.message,
                   gap=float(getattr(res, "mip_gap", np.nan) or 0.0), n_vars=int(n), cells=int(prob.N), merged_cells=int(N),
                   n_constraints=int(A.shape[0]))


def feasible_on_grid(prob, x):
    xi = x.reshape(-1).astype(bool)
    covered = prob.cover[:, xi].any(1)
    cov = np.bincount(prob.creg[covered], minlength=prob.M) / prob.Nm
    A = np.array([(x[prob.preg == m] * prob.alpha).sum() for m in range(prob.M)])
    B = np.array([(x[prob.preg == m] * prob.beta).sum() for m in range(prob.M)])
    return cov, A, B


def deficit(prob, x, margin=0.0):
    cov, A, B = feasible_on_grid(prob, x)
    return (np.maximum(prob.req_cov + margin - cov, 0) * prob.Nm).sum() / prob.Nm.mean() * 10 \
        + np.maximum(prob.req_a - A, 0).sum() + np.maximum(prob.req_b - B, 0).sum()


def _moves(prob, x, ps):
    """候補地 ps の中で, 1台を新しく置く / 種類を変える 手の一覧 (p, k)"""
    out = []
    for p in ps:
        cur = int(np.argmax(x[p])) if x[p].sum() else -1
        out += [(p, k) for k in range(prob.K) if k != cur]
    return out


def _apply(x, p, k):
    y = x.copy(); y[p] = 0; y[p, k] = 1
    return y


def _cost(prob, x):
    return float((x * prob.cost).sum())


def improve_until_feasible(prob, x, margin=0.0):
    """コスト当たりの不足の減り方が最大の手を繰り返す.
    1 手で減らせないときは, 不足のある市町村の中で 2 手の組み合わせも試す"""
    x = np.array(x, float).reshape(prob.P, prob.K)
    x[x.sum(1) > 1] = 0                              # 1 候補地に複数置いていたら外す
    while True:
        d0 = deficit(prob, x, margin)
        if d0 <= 1e-9:
            break
        c0 = _cost(prob, x)
        best, bv = None, 0.0
        for p, k in _moves(prob, x, range(prob.P)):
            y = _apply(x, p, k)
            v = (d0 - deficit(prob, y, margin)) / max(_cost(prob, y) - c0, 1.0)
            if v > bv:
                best, bv = y, v
        if best is None:
            _, A, B = feasible_on_grid(prob, x)
            bad = np.where((A < prob.req_a) | (B < prob.req_b))[0]
            ps = np.where(np.isin(prob.preg, bad))[0]
            mv = _moves(prob, x, ps)
            for i, (p1, k1) in enumerate(mv):
                y1 = _apply(x, p1, k1)
                for p2, k2 in mv[i + 1:]:
                    if p2 == p1:
                        continue
                    y = _apply(y1, p2, k2)
                    v = (d0 - deficit(prob, y, margin)) / max(_cost(prob, y) - c0, 1.0)
                    if v > bv:
                        best, bv = y, v
        if best is None:
            break
        x = best
    # 要らないセンサーを高い順に外す
    for p, k in sorted(zip(*np.nonzero(x)), key=lambda t: -prob.cost[t[1]]):
        x[p, k] = 0
        if deficit(prob, x, margin) > 1e-9:
            x[p, k] = 1
    return x


def solve_greedy(prob, margin=0.0):
    t0 = time.time()
    x = improve_until_feasible(prob, np.zeros((prob.P, prob.K)), margin)
    return x, dict(sec=time.time() - t0)


def repair(prob, x, margin=0.0):
    """制約を満たしていない解を, 貪欲法と同じ手で満たすまで直し, 要らないセンサーを外す"""
    return improve_until_feasible(prob, x, margin)
