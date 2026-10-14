"""
placement/qubo_amplify.py : センサー配置を Fixstars Amplify で QUBO にして解く

  変数 (すべて 0/1)
    x[p,k] : 候補地 p に種類 k のセンサーを置く                       (86 × 3 = 258)
    y[c]   : マスの組 c が少なくとも1つの円に入っている (被覆されている)
             マスは cell_m 四方. 「どのセンサーの円に入るか」が同じマスは 1 つにまとめ, 重み w_c = マス数

  目的関数
    Σ_{p,k} cost_k x[p,k]                                             … 総調達コスト

  制約 (Amplify の制約オブジェクト. 内部で 2 乗ペナルティ + スラック変数に変換される)
    (1) 面的充足率   greater_equal( Σ_{c∈m} w_c y[c],  ⌈(req_cov_m + 余裕) N_m⌉ )   市町村ごと
    (2) 被覆の整合   less_equal( y[c] - Σ_{(p,k)∈S_c} x[p,k], 0 )               マスの組ごと
                     (S_c = c を覆える (候補地, 種類). 覆っていないマスを y=1 にできない)
    (3) 1 候補地 1 台  Σ_{k<k'} x[p,k] x[p,k'] = 0                        (2次のペナルティ. スラック不要)
    (4) α出力        greater_equal( Σ_{p∈m,k} α_k x[p,k], req_α_m )      市町村ごと
    (5) β出力        greater_equal( Σ_{p∈m,k} β_k x[p,k], req_β_m )      市町村ごと

  重み (ペナルティ係数): 制約違反がコストの節約より必ず高くつくように, 最大コスト c_max = 300 を基準に決める
    (1) λ1 c_max / T_m       (不足 d マスで λ1 c_max d² / T_m)
    (2) 4 λ1 c_max           (y を不正に 1 にしても得にならない大きさ)
    (3) 2 c_max
    (4)(5) λ45 (α・β の不足 1 あたり)

  解き方
    backend="amplify": Fixstars Amplify AE (トークンが必要)
    backend="neal"   : 同じ Amplify のモデルを Amplify で QUBO に変換し, ローカルの焼きなましで解く
"""
import logging
import os
import time
import warnings
from datetime import timedelta
import numpy as np
from amplify import (VariableGenerator, Model, AmplifyAEClient, solve, greater_equal, less_equal,
                     AcceptableDegrees)

from common import Problem


# ======================================================================================
# Amplify AE を安定して呼ぶための部品
#
#   - 「AE は制約の重みを自分で調整する」警告: AE の仕様どおりなので表示しない (重みは neal 用)
#   - 「収束前に時間切れ」のログ: 表示せずに数え, QUBO 2 では次の回から制限時間を自動で延ばす
#   - 通信の一時的な失敗: 2 秒, 4 秒 待って最大 3 回まで送り直す
#   - トークンの誤り: 送り直さず, すぐに分かりやすいメッセージで止める
# ======================================================================================
AE_STATS = dict(calls=0, timeouts=0, retries=0)
AE_MAX_TIME_MS = 5000


class _AETimeLimitFilter(logging.Filter):
    def filter(self, record):
        if "time limit" in record.getMessage():
            AE_STATS["timeouts"] += 1
            return False                     # 数えるだけで表示しない
        return True


_amp_log = logging.getLogger("amplify")
if not any(isinstance(f, _AETimeLimitFilter) for f in _amp_log.filters):
    _amp_log.addFilter(_AETimeLimitFilter())


def ae_client(token=None, time_limit_ms=1000):
    token = (token or os.environ.get("AMPLIFY_TOKEN") or "").strip()
    if not token:
        raise RuntimeError("Amplify AE のトークンがありません. token 引数か 環境変数 AMPLIFY_TOKEN で渡してください")
    client = AmplifyAEClient()
    client.token = token
    client.parameters.time_limit_ms = timedelta(milliseconds=int(time_limit_ms))
    return client


def _is_auth_error(e):
    msg = str(e).lower()
    return any(k in msg for k in ("401", "403", "unauthorized", "forbidden", "token", "authenticat"))


def ae_solve(model, client, retries=3, **kw):
    """amplify.solve を呼ぶ. 戻り値 (結果, この呼び出しで時間切れのログが出たか)"""
    for attempt in range(retries):
        before = AE_STATS["timeouts"]
        try:
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", message=".*ignores the weight.*")
                res = solve(model, client, **kw)
            AE_STATS["calls"] += 1
            return res, AE_STATS["timeouts"] > before
        except Exception as e:
            if _is_auth_error(e):
                raise RuntimeError(f"Amplify AE にトークンを拒否されました. トークンを確かめてください ({e})") from e
            if attempt == retries - 1:
                raise RuntimeError(f"Amplify AE の呼び出しに {retries} 回失敗しました: {e}") from e
            AE_STATS["retries"] += 1
            time.sleep(2 * 2 ** attempt)


def check_ae(token=None):
    """小さな QUBO を AE で解いて, トークンと通信を確かめる. 失敗したら例外"""
    gen = VariableGenerator()
    q = gen.array("Binary", 4)
    model = Model((q.sum() - 2) ** 2)
    t0 = time.time()
    res, _ = ae_solve(model, ae_client(token, 1000))
    if len(res) == 0:
        raise RuntimeError("Amplify AE から解が返ってきませんでした")
    return dict(ok=True, sec=round(time.time() - t0, 2), energy=float(res.best.objective))


def merged_cells(prob):
    """覆うセンサーの組が同じマスをまとめる → (市町村, 覆う変数の番号の配列, マス数) のリスト"""
    groups = {}
    for g in range(prob.N):
        key = (int(prob.creg[g]), prob.cover[g].tobytes())
        if key in groups:
            groups[key][2] += 1
        else:
            groups[key] = [int(prob.creg[g]), np.nonzero(prob.cover[g])[0], 1]
    return list(groups.values())


def build_model(prob, margin=0.01, lam1=3.0, lam45=100.0):
    P, K, M = prob.P, prob.K, prob.M
    cmax = prob.cost.max()
    gen = VariableGenerator()
    x = gen.array("Binary", shape=(P, K))
    cells = merged_cells(prob)
    y = gen.array("Binary", shape=(len(cells),))
    xf = x.flatten()                                      # i = p*K + k

    objective = (x * prob.cost).sum()

    cons = None

    def add(c):
        nonlocal cons
        cons = c if cons is None else cons + c

    # (1) 面的充足率 と (2) 被覆の整合
    for m in range(M):
        idx = [c for c, cl in enumerate(cells) if cl[0] == m]
        T = int(np.ceil((prob.req_cov[m] + margin) * prob.Nm[m]))
        T = min(T, int(prob.Nm[m]))
        covered = sum(cells[c][2] * y[c] for c in idx)
        add(greater_equal(covered, T) * (lam1 * cmax / T))
    for c, (m, S, w) in enumerate(cells):
        add(less_equal(y[c] - sum(xf[int(i)] for i in S), 0) * (4 * lam1 * cmax))
    # (3) 1 候補地に 1 台まで (2次のペナルティ)
    one = 0
    for p in range(P):
        for k1 in range(K):
            for k2 in range(k1 + 1, K):
                one += x[p, k1] * x[p, k2]
    # (4)(5) α・β出力
    for m in range(M):
        ps = [int(p) for p in np.where(prob.preg == m)[0]]
        A = sum(int(prob.alpha[k]) * x[p, k] for p in ps for k in range(K))
        B = sum(int(prob.beta[k]) * x[p, k] for p in ps for k in range(K))
        add(greater_equal(A, int(prob.req_a[m])) * lam45)
        add(greater_equal(B, int(prob.req_b[m])) * lam45)
    model = Model(objective + 2 * cmax * one, cons)
    info = dict(n_x=P * K, n_y=len(cells), cells_merged_from=int(prob.N), margin=margin,
                weights=dict(coverage=f"{lam1}*c_max/T_m", consistency=4 * lam1 * cmax,
                             one_per_point=2 * cmax, alpha_beta=lam45),
                y_ids=[int(v.as_variable().id) for v in y])
    return model, x, info


def solve_model(model, x, backend="neal", token=None, time_limit_ms=10000,
                num_reads=10, num_sweeps=2000, seed=0):
    """解を (P, K) の 0/1 配列のリスト (良い順) で返す"""
    t0 = time.time()
    if backend == "amplify":
        result, timed_out = ae_solve(model, ae_client(token, time_limit_ms), filter_solution=False)
        sols = [np.rint(x.evaluate(s.values, 0.0)) for s in result]
        if not sols:
            raise RuntimeError("Amplify AE から解が返ってきませんでした")
        info = dict(execution_sec=result.execution_time.total_seconds(), ae_timed_out=timed_out)
    else:
        import dimod
        import neal
        im, _ = model.to_intermediate_model(AcceptableDegrees(objective={"Binary": "Quadratic"}))
        poly = im.to_unconstrained_poly()
        lin, quad, off = {}, {}, 0.0
        for kk, v in poly.as_dict().items():
            if len(kk) == 0:
                off += v
            elif len(kk) == 1 or kk[0] == kk[1]:
                lin[kk[0]] = lin.get(kk[0], 0.0) + v
            else:
                quad[kk] = quad.get(kk, 0.0) + v
        bqm = dimod.BinaryQuadraticModel(lin, quad, off, "BINARY")
        ss = neal.SimulatedAnnealingSampler().sample(bqm, num_reads=num_reads, num_sweeps=num_sweeps,
                                                     seed=seed)
        ids = np.array([v.as_variable().id for v in x.flatten()]).reshape(x.shape)
        sols = []
        for rec in ss.data(["sample"], sorted_by="energy"):
            smp = rec.sample
            sols.append(np.vectorize(lambda i: smp.get(int(i), 0))(ids).astype(float))
        info = dict(qubo_vars=len(bqm.variables), qubo_quadratic=len(bqm.quadratic))
    info["sec"] = time.time() - t0
    return sols, info


# ======================================================================================
# 定式化 2 : ラグランジュ緩和 (スラック変数なし) + 乗数の外側ループ
#
#   内側の QUBO (変数は x[p,k] の 258 個だけ, すべて 2 次以下)
#     E(x) = Σ_i c_i x_i
#            - Σ_m μ_m ( Σ_i a_mi x_i - Σ_{i<j} b_mij x_i x_j )      … 面的充足 (和集合の 2 次近似)
#            - Σ_m ν_m Σ_{i∈m} α_i x_i - Σ_m ρ_m Σ_{i∈m} β_i x_i     … α・β出力
#            + P Σ_p Σ_{k<k'} x[p,k] x[p,k']                         … 1 候補地 1 台
#     a_mi  = 市町村 m のマスのうち センサー i の円に入る数
#     b_mij = 市町村 m のマスのうち センサー i と j の両方の円に入る数
#     (Σ a - Σ b は和集合のマス数の下界 = ボンフェローニの不等式)
#
#   外側のループ (乗数の更新). 解 x の 面的充足率・α・β を 厳密に数え,
#     μ_m ← μ_m exp(η (T_m - 被覆マス数_m) / T_m)   (不足なら上げ, 余っていれば下げる)
#     ν_m, ρ_m も同様.  実行可能な解のうち最安のものを残す.
# ======================================================================================
def lagrangian_terms(prob):
    P, K, M = prob.P, prob.K, prob.M
    n = P * K
    cov = prob.cover.astype(np.float64)                      # (N, n)
    a = np.zeros((M, n))
    b = []
    for m in range(M):
        Cm = cov[prob.creg == m]
        a[m] = Cm.sum(0)
        b.append(np.triu(Cm.T @ Cm, k=1))                    # 両方の円に入るマス数
    owner = np.repeat(prob.preg, K)                          # 変数 i の市町村
    al = np.tile(prob.alpha, P); be = np.tile(prob.beta, P); c = np.tile(prob.cost, P)
    same = np.zeros((n, n))
    for p in range(P):
        for k1 in range(K):
            for k2 in range(k1 + 1, K):
                same[p * K + k1, p * K + k2] = 1.0
    return dict(a=a, b=b, owner=owner, al=al, be=be, c=c, same=same)


def lagrangian_qubo(prob, terms, mu, nu, rho, P_one=None):
    """内側の QUBO を (1次の係数, 上三角の 2 次係数) で返す"""
    a, b = terms["a"], terms["b"]
    lin = terms["c"].copy()
    Q = np.zeros((prob.P * prob.K, prob.P * prob.K))
    for m in range(prob.M):
        lin -= mu[m] * a[m]
        Q += mu[m] * b[m]
    lin -= nu[terms["owner"]] * terms["al"] + rho[terms["owner"]] * terms["be"]
    P_one = P_one or 2 * prob.cost.max() + np.abs(lin).max()
    Q += P_one * terms["same"]
    return lin, Q


def solve_inner(lin, Q, backend="neal", token=None, time_limit_ms=1000, num_reads=10,
                num_sweeps=1000, seed=0):
    """解のリスト (良い順) と, AE が収束前に時間切れになったか を返す"""
    n = len(lin)
    if backend == "amplify":
        gen = VariableGenerator()
        m = gen.matrix("Binary", n)
        m.linear = lin
        m.quadratic = Q
        res, timed_out = ae_solve(m, ae_client(token, time_limit_ms))
        q = m.variable_array
        sols = [np.rint(q.evaluate(s.values, 0.0)) for s in res]
        return (sols or [np.zeros(n)]), timed_out
    import dimod
    import neal
    r, c = np.nonzero(Q)
    bqm = dimod.BinaryQuadraticModel.from_numpy_vectors(lin, (r, c, Q[r, c]), 0.0, "BINARY")
    ss = neal.SimulatedAnnealingSampler().sample(bqm, num_reads=num_reads, num_sweeps=num_sweeps,
                                                 seed=seed)
    order = np.argsort(ss.record.energy)
    var_index = {v: i for i, v in enumerate(ss.variables)}
    perm = np.array([var_index[v] for v in range(n)])
    return [ss.record.sample[i][perm].astype(float) for i in order], False


def solve_lagrangian(prob, iters=40, eta=1.0, backend="neal", token=None, time_limit_ms=1000,
                     num_reads=10, num_sweeps=1000, seed=0, margin=0.0, log=None):
    """外側のループで乗数を調整しながら, 内側の QUBO を繰り返し解く"""
    t0 = time.time()
    terms = lagrangian_terms(prob)
    M = prob.M
    T = np.ceil((prob.req_cov + margin) * prob.Nm)
    mu = np.full(M, 0.5)                           # 被覆マス 1 つの値段 (コスト/マス 程度から始める)
    nu = np.full(M, 30.0)                          # α 1 の値段
    rho = np.full(M, 15.0)                         # β 1 の値段
    best, history, n_feasible = None, [], 0
    least = None                                   # 実行可能な解が無いとき用: 不足が最も少ない解
    tl, n_timeout = time_limit_ms, 0               # AE の制限時間 (時間切れなら次から 2 倍, 上限 5 秒)
    for it in range(iters):
        lin, Q = lagrangian_qubo(prob, terms, mu, nu, rho)
        sols, timed_out = solve_inner(lin, Q, backend, token, tl, num_reads, num_sweeps, seed + it)
        if timed_out:
            n_timeout += 1
            tl = min(tl * 2, AE_MAX_TIME_MS)
        x = sols[0].reshape(prob.P, prob.K)
        xi = x.reshape(-1).astype(bool)
        covered = prob.cover[:, xi].any(1)
        cv = np.bincount(prob.creg[covered], minlength=M).astype(float)
        A = np.array([(x[prob.preg == m] * prob.alpha).sum() for m in range(M)])
        B = np.array([(x[prob.preg == m] * prob.beta).sum() for m in range(M)])
        one_ok = (x.sum(1) <= 1).all()
        feas = one_ok and (cv >= T).all() and (A >= prob.req_a).all() and (B >= prob.req_b).all()
        cost = float((x * prob.cost).sum())
        n_feasible += int(feas)
        if feas and (best is None or cost < best[0]):
            best = (cost, x.copy(), it)
        short = (np.maximum(T - cv, 0) / T).sum() + (np.maximum(prob.req_a - A, 0) / prob.req_a).sum() \
            + (np.maximum(prob.req_b - B, 0) / prob.req_b).sum() + (0 if one_ok else 1)
        if least is None or short < least[0]:
            least = (short, x.copy())
        history.append(dict(it=it, cost=cost, feasible=bool(feas),
                            cov_short=int(np.maximum(T - cv, 0).sum()),
                            a_short=float(np.maximum(prob.req_a - A, 0).sum()),
                            b_short=float(np.maximum(prob.req_b - B, 0).sum())))
        if log:
            log(history[-1])
        # 乗数の更新 (足りなければ上げ, 余っていれば下げる. 余りの側は弱めに)
        step = eta / np.sqrt(it + 1)
        g_cov = (T - cv) / T
        g_a = (prob.req_a - A) / prob.req_a
        g_b = (prob.req_b - B) / prob.req_b
        mu *= np.exp(step * np.where(g_cov > 0, g_cov * 3, g_cov * 0.5))
        nu *= np.exp(step * np.where(g_a > 0, g_a * 3, g_a * 0.5))
        rho *= np.exp(step * np.where(g_b > 0, g_b * 3, g_b * 0.5))
    return best, dict(sec=time.time() - t0, iters=iters, feasible_iters=n_feasible, history=history,
                      least_violating_x=least[1], ae_timeouts=n_timeout, ae_time_limit_ms_final=tl,
                      n_vars=prob.P * prob.K, final_mu=mu.round(3).tolist(),
                      final_nu=nu.round(2).tolist(), final_rho=rho.round(2).tolist())
