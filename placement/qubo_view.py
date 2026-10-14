"""
placement/qubo_view.py : QUBO 行列を取り出して, 見て, 検算する (Colab の「QUBO 行列を見る」から呼ぶ)

  QUBO の形   E(x) = Σ_i Q_ii x_i + Σ_{i<j} Q_ij x_i x_j + 定数      (x_i ∈ {0,1}, x_i² = x_i なので 1 次の項は対角に置く)

  qubo1_matrix(...)  QUBO 1: Amplify が制約 (スラック付きの 2 乗ペナルティ) を展開した後の行列
  qubo2_matrix(...)  QUBO 2: ラグランジュ緩和の行列 (Amplify AE にはこの行列をそのまま送る)
  check_qubo2(...)   QUBO 2 の行列で計算したエネルギーが, 式の各項を別々に足したものと一致するかを確かめる
"""
import numpy as np
import scipy.sparse as sp
from amplify import AcceptableDegrees

from qubo_amplify import build_model, lagrangian_terms, lagrangian_qubo


def qubo1_matrix(prob2km, **kw):
    """Amplify のモデル → 制約を展開した QUBO → 上三角の疎行列. 変数は x, y, スラックの順に並べ直す"""
    model, x, info = build_model(prob2km, **kw)
    im, _ = model.to_intermediate_model(AcceptableDegrees(objective={"Binary": "Quadratic"}))
    poly = im.to_unconstrained_poly()
    terms = poly.as_dict()
    x_ids = [int(v.as_variable().id) for v in x.flatten()]
    y_ids = info["y_ids"]
    used = sorted({int(i) for k in terms for i in k})
    known = set(x_ids) | set(y_ids)
    slack_ids = [i for i in used if i not in known]
    order = x_ids + y_ids + slack_ids
    pos = {v: n for n, v in enumerate(order)}
    rows, cols, vals, const = [], [], [], 0.0
    for k, v in terms.items():
        if len(k) == 0:
            const += v
            continue
        i, j = pos[int(k[0])], pos[int(k[-1])]
        i, j = min(i, j), max(i, j)
        rows.append(i); cols.append(j); vals.append(v)
    n = len(order)
    Q = sp.coo_matrix((vals, (rows, cols)), shape=(n, n)).tocsr()   # 同じ位置の項は足される
    blocks = dict(x=len(x_ids), y=len(y_ids), slack=len(slack_ids))
    return Q, const, blocks


def qubo2_matrix(prob, mu=None, nu=None, rho=None):
    """QUBO 2 の (1 次の係数, 上三角の 2 次の係数). 乗数を省略すると solve_lagrangian の初期値"""
    M = prob.M
    mu = np.full(M, 0.5) if mu is None else np.asarray(mu, float)
    nu = np.full(M, 30.0) if nu is None else np.asarray(nu, float)
    rho = np.full(M, 15.0) if rho is None else np.asarray(rho, float)
    terms = lagrangian_terms(prob)
    lin, Q = lagrangian_qubo(prob, terms, mu, nu, rho)
    return lin, Q, terms, (mu, nu, rho)


def labels(prob):
    return [f"{prob.pid[p]}-{prob.kname[k]}" for p in range(prob.P) for k in range(prob.K)]


def check_qubo2(prob, x, lin, Q, terms, mults):
    """x: (P, K) の 0/1. 行列で計算したエネルギーと, 式の項ごとの計算が一致するか"""
    mu, nu, rho = mults
    v = np.asarray(x, float).reshape(-1)
    e_matrix = float(lin @ v + v @ Q @ v)
    cost = float(terms["c"] @ v)
    bonf = np.array([terms["a"][m] @ v - v @ terms["b"][m] @ v for m in range(prob.M)])   # 和集合の下界
    covered = prob.cover[:, v.astype(bool)].any(1)
    union = np.bincount(prob.creg[covered], minlength=prob.M).astype(float)             # 本当の被覆マス数
    A = np.array([(terms["al"] * v)[terms["owner"] == m].sum() for m in range(prob.M)])
    B = np.array([(terms["be"] * v)[terms["owner"] == m].sum() for m in range(prob.M)])
    P_one = 2 * prob.cost.max() + np.abs(lin_without_penalty(terms, mults)).max()   # lagrangian_qubo と同じ値
    dup = float(v @ terms["same"] @ v)
    e_terms = cost - float(mu @ bonf) - float(nu @ A) - float(rho @ B) + P_one * dup
    return dict(energy_from_matrix=round(e_matrix, 6), energy_from_terms=round(float(e_terms), 6),
                match=bool(np.isclose(e_matrix, e_terms)), cost=cost,
                bonferroni_lower_bound=bonf.round(1).tolist(), true_union=union.tolist(),
                bound_ok=bool((bonf <= union + 1e-9).all()))


def lin_without_penalty(terms, mults):
    mu, nu, rho = mults
    lin = terms["c"] - mu @ terms["a"]
    return lin - nu[terms["owner"]] * terms["al"] - rho[terms["owner"]] * terms["be"]
