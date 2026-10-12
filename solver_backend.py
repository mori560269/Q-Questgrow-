"""
solver_backend.py : QUBO を解くバックエンドの共通窓口

  solve_qubo(n, lin, rows, cols, vals, offset, backend=...)
      -> (samples, energies, sec)   samples は 0/1 の ndarray (エネルギー昇順)

  backend
    "neal"    : dwave-neal のシミュレーテッドアニーリング (ローカル, トークン不要)
    "amplify" : Fixstars Amplify AE (クラウド, アクセストークンが必要)
                トークンは引数 token か 環境変数 AMPLIFY_TOKEN で渡す.

  QUBO は  E(x) = offset + Σ_i lin[i] x_i + Σ_k vals[k] x_{rows[k]} x_{cols[k]}
  の形で受け取る (rows[k] < cols[k], 同じペアの重複は合算される).
"""
import os
import time
import datetime
import numpy as np
import scipy.sparse as sp


def merge_quadratic(n, rows, cols, vals):
    """2次項の配列リストを (i<j) にそろえて重複を合算する"""
    if not rows:
        e = np.zeros(0, dtype=np.int64)
        return e, e, np.zeros(0)
    r = np.concatenate([np.asarray(x, dtype=np.int64) for x in rows])
    c = np.concatenate([np.asarray(x, dtype=np.int64) for x in cols])
    v = np.concatenate([np.asarray(x, dtype=float) for x in vals])
    lo, hi = np.minimum(r, c), np.maximum(r, c)
    Q = sp.coo_matrix((v, (lo, hi)), shape=(n, n)).tocsr().tocoo()
    keep = Q.data != 0
    return Q.row[keep], Q.col[keep], Q.data[keep]


def _solve_neal(n, lin, r, c, v, offset, num_reads, num_sweeps, seed):
    import dimod
    import neal
    bqm = dimod.BinaryQuadraticModel.from_numpy_vectors(lin, (r, c, v), offset, "BINARY")
    ss = neal.SimulatedAnnealingSampler().sample(bqm, num_reads=num_reads,
                                                 num_sweeps=num_sweeps, seed=seed)
    var_index = {x: i for i, x in enumerate(ss.variables)}
    perm = np.array([var_index[x] for x in range(n)])
    order = np.argsort(ss.record.energy)
    samples = [ss.record.sample[i][perm].astype(np.int8) for i in order]
    energies = [float(ss.record.energy[i]) for i in order]
    return samples, energies


def _solve_amplify(n, lin, r, c, v, offset, token, time_limit_ms):
    from amplify import VariableGenerator, AmplifyAEClient, solve
    token = token or os.environ.get("AMPLIFY_TOKEN")
    if not token:
        raise RuntimeError("Fixstars Amplify AE のアクセストークンがありません. "
                           "--token か 環境変数 AMPLIFY_TOKEN で指定してください.")
    gen = VariableGenerator()
    m = gen.matrix("Binary", n)
    Q = np.zeros((n, n))
    Q[r, c] = v
    m.quadratic = Q
    m.linear = np.asarray(lin, dtype=float)
    m.constant = float(offset)
    client = AmplifyAEClient()
    client.token = token
    client.parameters.time_limit_ms = datetime.timedelta(milliseconds=time_limit_ms)
    res = solve(m, client)
    q = m.variable_array
    samples, energies = [], []
    for sol in res:                      # 係数0で落ちた変数は 0 とみなす
        samples.append(np.rint(np.asarray(q.evaluate(sol.values, 0.0))).astype(np.int8))
        energies.append(float(sol.objective))
    if not samples:
        raise RuntimeError("Amplify AE から解が返りませんでした")
    order = np.argsort(energies)
    return [samples[i] for i in order], [energies[i] for i in order]


def solve_qubo(n, lin, rows, cols, vals, offset=0.0, backend="neal",
               num_reads=30, num_sweeps=2000, seed=0,
               token=None, time_limit_ms=1000):
    r, c, v = merge_quadratic(n, rows, cols, vals)
    t0 = time.time()
    if backend == "neal":
        samples, energies = _solve_neal(n, lin, r, c, v, offset, num_reads, num_sweeps, seed)
    elif backend == "amplify":
        samples, energies = _solve_amplify(n, lin, r, c, v, offset, token, time_limit_ms)
    else:
        raise ValueError(f"unknown backend: {backend}")
    return samples, energies, time.time() - t0, len(v)


def polish_onehot(n, lin, rows, cols, vals, slot, sample, passes=5):
    """one-hot のグループ (slot が同じ変数の組) ごとに1つ選ぶ解を, 局所探索で磨く.

    アニーリングの解を出発点に, 「1つのグループの選択だけを変えて QUBO のエネルギーが
    下がるなら変える」を繰り返す. one-hot は常に満たした状態で探索する.
    戻り値: {slot の値: 選んだ変数の番号}"""
    slot = np.asarray(slot)
    r = np.concatenate([np.asarray(x, int) for x in rows]) if rows else np.zeros(0, int)
    c = np.concatenate([np.asarray(x, int) for x in cols]) if cols else np.zeros(0, int)
    v = np.concatenate([np.asarray(x, float) for x in vals]) if vals else np.zeros(0)
    keep = (r < n) & (c < n)
    r, c, v = r[keep], c[keep], v[keep]
    keep = slot[r] != slot[c]                          # one-hot の項は除く (構造で満たす)
    Q = sp.coo_matrix((v[keep], (r[keep], c[keep])), shape=(n, n)).tocsr()
    Q = (Q + Q.T).tocsr()
    groups = {s_: np.where(slot == s_)[0] for s_ in np.unique(slot)}
    sel = {}
    for s_, ks in groups.items():
        on = ks[np.asarray(sample)[ks] == 1]
        sel[s_] = int(on[0]) if len(on) == 1 else int(ks[np.argmin(np.asarray(lin)[ks])])
    x = np.zeros(n)
    x[list(sel.values())] = 1
    field = np.asarray(lin, float) + Q @ x
    for _ in range(passes):
        changed = False
        for s_, ks in groups.items():
            cur = sel[s_]
            f = field[ks] - Q[ks, cur].toarray().ravel()   # 自分のグループの寄与を除く
            j = int(np.argmin(f))
            if ks[j] != cur and f[j] < field[cur] - 1e-15:
                field += Q[:, ks[j]].toarray().ravel() - Q[:, cur].toarray().ravel()
                sel[s_] = int(ks[j])
                changed = True
        if not changed:
            break
    return sel


def qubo_energy(x, lin, rows, cols, vals, offset=0.0):
    """0/1 ベクトル x の QUBO エネルギー"""
    x = np.asarray(x, float)
    r = np.concatenate([np.asarray(a, int) for a in rows]) if rows else np.zeros(0, int)
    c = np.concatenate([np.asarray(a, int) for a in cols]) if cols else np.zeros(0, int)
    v = np.concatenate([np.asarray(a, float) for a in vals]) if vals else np.zeros(0)
    return float(offset + np.asarray(lin) @ x + (v * x[r] * x[c]).sum())
