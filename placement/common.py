"""
placement/common.py : 元の課題「センサーの最適配置」の共通部分 (データ・グリッド・評価)

  課題 (国際航業 課題企画記入シートより)
    86 か所の設置候補地に, 3 種類のセンサー (ALPHA / BETA / GAMMA) のどれを置くか (置かないか) を決める.
    目的: 総調達コスト Σ cost を最小化
    制約: (1) 市町村ごとの面的充足率 (円形カバー範囲の和集合が市町村の面積に占める割合) >= 目標
          (2) 1 候補地に置けるセンサーは 1 台まで
          (3) 市町村ごとの α出力の合計 >= 目標
          (4) 市町村ごとの β出力の合計 >= 目標

  解釈 (課題文に書かれていない点)
    - 面的充足率は, どの市町村に置いたセンサーの円でも数える (隣の市町村のセンサーの重なりも考慮)
    - α・β出力は, その市町村の候補地に置いたセンサーの値を合計する
    - 半径は km (18 / 10 / 4.5 km), 座標は m
    - 円の和集合の面積は, 市町村を正方形のマスに分けて「マスの中心が円の中」で数えて近似する
"""
import json
import os
import numpy as np
from matplotlib.path import Path

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data", "data_transformed.json")


class Problem:
    def __init__(self, data_path=DATA, cell_m=1000.0, extra_grid_m=None):
        """extra_grid_m: 規模を変えた比較用. この間隔の格子点を設置候補地として足す (None なら元の 86 か所)"""
        raw = json.load(open(data_path, encoding="utf-8"))
        self.raw = raw
        self.sens = raw["sensor_specifications"]
        self.K = len(self.sens)
        self.cost = np.array([s["unit_procurement_cost"] for s in self.sens], float)
        self.radius = np.array([s["effective_coverage_radius"] for s in self.sens], float) * 1000.0
        self.alpha = np.array([s["alpha_field_response"] for s in self.sens], float)
        self.beta = np.array([s["beta_density_resolution"] for s in self.sens], float)
        self.kname = [s["sensor_type_id"].split("-")[1] for s in self.sens]
        mu = raw["municipalities"]
        self.M = len(mu)
        self.names = [m["name"].split(" (")[0] for m in mu]
        self.polys = [np.array(m["polygon_vertices"], float) for m in mu]
        self.req_cov = np.array([m["required_coverage_rate"] for m in mu], float)
        self.req_a = np.array([m["required_alpha_response"] for m in mu], float)
        self.req_b = np.array([m["required_beta_resolution"] for m in mu], float)
        pts, preg, pid = [], [], []
        for m, x in enumerate(mu):
            for c in x["candidate_locations"]:
                pts.append([c["x"], c["y"]]); preg.append(m); pid.append(c["id"])
        if extra_grid_m:
            allv = np.vstack(self.polys)
            lo, hi = allv.min(0), allv.max(0)
            for gx in np.arange(lo[0] + extra_grid_m / 2, hi[0], extra_grid_m):
                for gy in np.arange(lo[1] + extra_grid_m / 2, hi[1], extra_grid_m):
                    for m, poly in enumerate(self.polys):
                        if Path(poly).contains_point((gx, gy)):
                            pts.append([gx, gy]); preg.append(m); pid.append(f"X{len(pid)}")
                            break
        self.pts, self.preg, self.pid = np.array(pts), np.array(preg), pid
        self.P = len(self.pts)
        self.pref = np.array(raw["prefecture_outer_boundary"]["vertices"], float)
        self.set_grid(cell_m)

    # ---- グリッド
    def make_grid(self, cell_m):
        allv = np.vstack(self.polys)
        lo, hi = allv.min(0), allv.max(0)
        xs = np.arange(lo[0] + cell_m / 2, hi[0], cell_m)
        ys = np.arange(lo[1] + cell_m / 2, hi[1], cell_m)
        X, Y = np.meshgrid(xs, ys)
        C = np.c_[X.ravel(), Y.ravel()]
        reg = np.full(len(C), -1)
        for m, poly in enumerate(self.polys):
            inside = Path(poly).contains_points(C) & (reg < 0)
            reg[inside] = m
        keep = reg >= 0
        return C[keep], reg[keep]

    def set_grid(self, cell_m):
        self.cell_m = cell_m
        self.cells, self.creg = self.make_grid(cell_m)
        self.N = len(self.cells)
        self.Nm = np.bincount(self.creg, minlength=self.M)
        # cover[g, i]: マス g がセンサー i = (候補地 p, 種類 k) の円に入るか.  i = p*K + k
        d = np.hypot(*(self.cells[:, None, :] - self.pts[None, :, :]).transpose(2, 0, 1))  # (N, P)
        self.cover = (d[:, :, None] <= self.radius[None, None, :]).reshape(self.N, self.P * self.K)

    # ---- 評価 (どの手法の解も同じ物差しで)
    def evaluate(self, x, cell_m=200.0):
        """x: (P, K) の 0/1. 細かいマス (cell_m) で面的充足率を数え直して, 制約を確かめる"""
        x = np.asarray(x).reshape(self.P, self.K).astype(int)
        cells, creg = self.make_grid(cell_m)
        covered = np.zeros(len(cells), bool)
        for p, k in zip(*np.nonzero(x)):
            covered |= np.hypot(*(cells - self.pts[p]).T) <= self.radius[k]
        cov = np.bincount(creg[covered], minlength=self.M) / np.bincount(creg, minlength=self.M)
        A = np.array([(x[self.preg == m] * self.alpha).sum() for m in range(self.M)])
        B = np.array([(x[self.preg == m] * self.beta).sum() for m in range(self.M)])
        ok_cov = cov >= self.req_cov - 1e-9
        ok = dict(coverage=bool(ok_cov.all()), alpha=bool((A >= self.req_a).all()),
                  beta=bool((B >= self.req_b).all()), one_per_point=bool((x.sum(1) <= 1).all()))
        return dict(cost=float((x * self.cost).sum()), feasible=all(ok.values()), checks=ok,
                    n_sensors={self.kname[k]: int(x[:, k].sum()) for k in range(self.K)},
                    cov=cov.round(4).tolist(), A=A.tolist(), B=B.tolist(),
                    short_cov=[round(float(max(0, r - c)), 4) for r, c in zip(self.req_cov, cov)],
                    eval_cell_m=cell_m, x=x.tolist())


def save_map(prob, results, path, cols=3):
    """手法ごとの配置を地図に並べて描く"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Circle, Polygon as MplPolygon
    from matplotlib import font_manager as fm
    av = {f.name for f in fm.fontManager.ttflist}
    plt.rcParams["font.family"] = [f for f in ["Noto Sans CJK JP", "IPAexGothic", "IPAGothic"] if f in av] + ["DejaVu Sans"]
    col = ["#d62728", "#1f77b4", "#2ca02c"]
    n = len(results)
    rows = (n + cols - 1) // cols
    fig, axes = plt.subplots(rows, cols, figsize=(6 * cols, 6.3 * rows), squeeze=False)
    for ax, (name, r) in zip(axes.ravel(), results.items()):
        x = np.array(r["x"])
        for poly in prob.polys:
            ax.add_patch(MplPolygon(poly / 1000, closed=True, fc="#f4f1e8", ec="#666", lw=0.8))
        for p, k in zip(*np.nonzero(x)):
            ax.add_patch(Circle(prob.pts[p] / 1000, prob.radius[k] / 1000, fc=col[k], alpha=0.12,
                                ec=col[k], lw=0.8))
        ax.plot(prob.pts[:, 0] / 1000, prob.pts[:, 1] / 1000, ".", color="#999", ms=3)
        for p, k in zip(*np.nonzero(x)):
            ax.plot(*(prob.pts[p] / 1000), "o", color=col[k], ms=7, mec="k")
        ax.plot(prob.pref[:, 0] / 1000, prob.pref[:, 1] / 1000, "k-", lw=1.2)
        ax.set_aspect("equal"); ax.set_xlim(-50, 52); ax.set_ylim(-55, 55)
        ns = r["n_sensors"]
        ax.set_title(f"{name}\nコスト {r['cost']:.0f} / {'実行可能' if r['feasible'] else '制約違反あり'} / "
                     f"ALPHA {ns['ALPHA']}・BETA {ns['BETA']}・GAMMA {ns['GAMMA']}", fontsize=11)
        ax.tick_params(labelsize=7)
    for ax in axes.ravel()[n:]:
        ax.axis("off")
    fig.text(0.01, 0.005, "赤=ALPHA(18km) 青=BETA(10km) 緑=GAMMA(4.5km) / 灰色の点=設置候補地", fontsize=10)
    fig.tight_layout(rect=(0, 0.02, 1, 1))
    fig.savefig(path, dpi=90)
    plt.close(fig)
