"""
geo_common.py : アップロードされた「新緑県」データで動くドローン観測計画 (充電つき)

【データの使い方】
  data_transformed.json : 県境, 8市町村ポリゴン, 要求値(被覆率/alpha/beta), センサー仕様
  candidate_locations.geojson : 今回は「センサー置き場所は無視」の指示により使わない
  (座標は m, 半径は km と解釈: 18 / 10 / 4.5 km)

【固定センサー問題 → 移動センサー(ドローン)問題への読み替え】
  - センサー種別 (ALPHA/BETA/GAMMA) を搭載したドローン群が, T ステップ飛行する
  - 地域を GRID_KM のセルに分割. ドローンは各ステップでどれか1セルに居る
  - 被覆率    : 市町村内のセルのうち, 期間中に1度でも観測円に入った割合
  - alpha/beta : ドローンが市町村内のセルに居る各ステップごとに, その機体のセンサー
                 種別の alpha / beta を, その市町村に加算 (固定版の「候補点が属する
                 市町村に加算」を時間方向に拡張)
  - 要求値    : 市町村ごとに 被覆率>=req, alpha合計>=req, beta合計>=req (ソフト扱い)

【充電モデル】
  - 充電ステーション(セル)に居るステップは「充電」: 観測せず, バッテリー +CHARGE
  - それ以外のセルに居るステップは「稼働」: 観測し, バッテリー -E[type]
  - バッテリーは 0..BATT_MAX の整数, 0 未満になる計画は実行不可
  - 移動エネルギーは1ステップ一定 (稼働コストに含める) と簡略化

【スコア】 (両手法を同じ物差しで評価)
  score = (1/8) Σ_m (1/3) [ min(1,cov_m/req_cov) + min(1,A_m/req_a) + min(1,B_m/req_b) ]
  1.0 で全市町村の全要求を満たす.
"""
import json
import os
import numpy as np
from matplotlib.path import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, Polygon as MplPolygon
from matplotlib import animation
from matplotlib import font_manager as _fm

_avail = {f.name for f in _fm.fontManager.ttflist}
_jp = [f for f in ["Noto Sans CJK JP", "IPAexGothic", "IPAGothic", "Hiragino Sans",
                   "Yu Gothic", "MS Gothic"] if f in _avail]
plt.rcParams["font.family"] = _jp + ["DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

# 環境変数 GEO_DATA_PATH で上書き可. 既定はリポジトリ内の data/data_transformed.json
DATA_PATH = os.environ.get(
    "GEO_DATA_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "data_transformed.json"))

# ------------------------------------------------------------------ 設定
GRID_KM = 10.0      # セル一辺 [km]
D_TYPES = ["SENS-ALPHA-01", "SENS-BETA-02", "SENS-BETA-02",
           "SENS-GAMMA-03", "SENS-GAMMA-03"]   # 機体ごとのセンサー種別 (5機)
T = 10              # 計画ステップ数
VMAX = 2            # 1ステップの最大移動 [セル] (チェビシェフ)
N_STATIONS = 3      # 充電ステーション数
BATT_MAX = 8        # バッテリー最大 (整数)
CHARGE = 4          # 充電ステーションに居る1ステップの回復量
E_TYPE = {"SENS-ALPHA-01": 3, "SENS-BETA-02": 2, "SENS-GAMMA-03": 1}  # 稼働消費/ステップ
D = len(D_TYPES)


class Scenario:
    pass


def build_scenario():
    raw = json.load(open(DATA_PATH, encoding="utf-8"))
    S = Scenario()
    S.sens = {s["sensor_type_id"]: s for s in raw["sensor_specifications"]}
    S.muni = raw["municipalities"]
    S.M = len(S.muni)
    S.polys = [np.array(m["polygon_vertices"]) / 1000.0 for m in S.muni]   # km
    S.pref = np.array(raw["prefecture_outer_boundary"]["vertices"]) / 1000.0

    allv = np.vstack(S.polys)
    x0, y0 = allv.min(0)
    x1, y1 = allv.max(0)
    g = GRID_KM
    xs = np.arange(x0 + g / 2, x1, g)
    ys = np.arange(y0 + g / 2, y1, g)
    paths = [Path(p) for p in S.polys]
    cells, cmuni = [], []
    for j, y in enumerate(ys):
        for i, x in enumerate(xs):
            for m, pa in enumerate(paths):
                if pa.contains_point((x, y)):
                    cells.append((x, y, i, j))
                    cmuni.append(m)
                    break
    S.xy = np.array([[c[0], c[1]] for c in cells])          # (C,2) km
    S.ij = np.array([[c[2], c[3]] for c in cells])          # 格子インデックス
    S.cmuni = np.array(cmuni)                               # (C,)
    S.C = len(cells)
    S.Nm = np.array([(S.cmuni == m).sum() for m in range(S.M)])

    # 充電ステーション: セル座標の k-means(固定シード) → 最寄りセルに吸着
    rng = np.random.default_rng(0)
    cent = S.xy[rng.choice(S.C, N_STATIONS, replace=False)]
    for _ in range(50):
        lab = np.argmin(((S.xy[:, None] - cent[None]) ** 2).sum(-1), axis=1)
        cent = np.array([S.xy[lab == k].mean(0) if (lab == k).any() else cent[k]
                         for k in range(N_STATIONS)])
    S.stations = sorted({int(np.argmin(((S.xy - c) ** 2).sum(1))) for c in cent})
    S.is_station = np.zeros(S.C, dtype=bool)
    S.is_station[S.stations] = True

    # 種別ごとの観測行列 K[type][c, s] (ステーションでは観測しない)
    dist = np.sqrt(((S.xy[:, None] - S.xy[None]) ** 2).sum(-1))
    S.K = {}
    for tid, sp in S.sens.items():
        K = dist <= sp["effective_coverage_radius"]
        K[S.is_station] = False
        S.K[tid] = K
    # 到達可能性
    dij = np.abs(S.ij[:, None, :] - S.ij[None, :, :]).max(-1)
    S.reach = dij <= VMAX
    # 初期位置: ステーションに順番に配置
    S.start = [S.stations[d % len(S.stations)] for d in range(D)]
    # 要求値
    S.req_cov = np.array([m["required_coverage_rate"] for m in S.muni])
    S.req_a = np.array([m["required_alpha_response"] for m in S.muni], dtype=float)
    S.req_b = np.array([m["required_beta_resolution"] for m in S.muni], dtype=float)
    S.alpha = {tid: sp["alpha_field_response"] for tid, sp in S.sens.items()}
    S.beta = {tid: sp["beta_density_resolution"] for tid, sp in S.sens.items()}
    return S


# ------------------------------------------------------------------ 評価
def battery_trace(S, path):
    """path (D,T) -> 各機のバッテリー推移 (D,T+1), 実行可能か"""
    bat = np.zeros((D, T + 1), dtype=int)
    ok = True
    for d in range(D):
        b = BATT_MAX
        bat[d, 0] = b
        for t in range(T):
            if S.is_station[path[d, t]]:
                b = min(BATT_MAX, b + CHARGE)
            else:
                b -= E_TYPE[D_TYPES[d]]
                if b < 0:
                    ok = False
            bat[d, t + 1] = b
    return bat, ok


def evaluate(S, path):
    path = np.asarray(path)
    msgs = []
    feasible = True
    for d in range(D):
        seq = [S.start[d]] + list(path[d])
        for t in range(T):
            if not S.reach[seq[t], seq[t + 1]]:
                feasible = False
                msgs.append(f"drone{d} t={t+1}: 移動制約違反")
    bat, bok = battery_trace(S, path)
    if not bok:
        feasible = False
        msgs.append("バッテリー切れ")
    covered = np.zeros(S.C, dtype=bool)
    A = np.zeros(S.M)
    B = np.zeros(S.M)
    charge_steps = 0
    for d in range(D):
        tid = D_TYPES[d]
        for t in range(T):
            c = path[d, t]
            if S.is_station[c]:
                charge_steps += 1
                continue
            covered |= S.K[tid][c]
            A[S.cmuni[c]] += S.alpha[tid]
            B[S.cmuni[c]] += S.beta[tid]
    cov = np.array([covered[S.cmuni == m].mean() for m in range(S.M)])
    r_cov = np.minimum(1, cov / S.req_cov)
    r_a = np.minimum(1, A / S.req_a)
    r_b = np.minimum(1, B / S.req_b)
    score = float((r_cov + r_a + r_b).sum() / (3 * S.M))
    met = int(((cov >= S.req_cov - 1e-9)).sum() + (A >= S.req_a).sum() + (B >= S.req_b).sum())
    return dict(score=score, feasible=feasible, messages=msgs, cov=cov, A=A, B=B,
                r_cov=r_cov, r_a=r_a, r_b=r_b, requirements_met=met,
                requirements_total=3 * S.M, charge_steps=charge_steps,
                min_battery=int(bat.min()))


# ------------------------------------------------------------------ 動画
TYPE_STYLE = {"SENS-ALPHA-01": ("#d62728", "ALPHA", 13),
              "SENS-BETA-02": ("#1f77b4", "BETA", 10),
              "SENS-GAMMA-03": ("#2ca02c", "GAMMA", 8)}


def make_video(S, path, out_path, title, subtitle="", fps=20, sub=16):
    path = np.asarray(path)
    wp = np.zeros((D, T + 1, 2))
    for d in range(D):
        wp[d, 0] = S.xy[S.start[d]]
        for t in range(T):
            wp[d, t + 1] = S.xy[path[d, t]]
    bat, _ = battery_trace(S, path)

    # ステップごとの累積状態
    cum_cov = [np.zeros(S.C, bool)]
    cum_A = [np.zeros(S.M)]
    cum_B = [np.zeros(S.M)]
    for t in range(T):
        cv = cum_cov[-1].copy(); A = cum_A[-1].copy(); B = cum_B[-1].copy()
        for d in range(D):
            tid = D_TYPES[d]; c = path[d, t]
            if S.is_station[c]:
                continue
            cv |= S.K[tid][c]
            A[S.cmuni[c]] += S.alpha[tid]
            B[S.cmuni[c]] += S.beta[tid]
        cum_cov.append(cv); cum_A.append(A); cum_B.append(B)

    def ratios(k):
        cov = np.array([cum_cov[k][S.cmuni == m].mean() for m in range(S.M)])
        return (np.minimum(1, cov / S.req_cov), np.minimum(1, cum_A[k] / S.req_a),
                np.minimum(1, cum_B[k] / S.req_b))

    scores = []
    for k in range(T + 1):
        a, b, c = ratios(k)
        scores.append((a + b + c).sum() / (3 * S.M))

    fig = plt.figure(figsize=(13, 7), dpi=100)
    ax = fig.add_axes([0.03, 0.05, 0.50, 0.82])
    axb = fig.add_axes([0.60, 0.67, 0.37, 0.20])
    axm = fig.add_axes([0.65, 0.30, 0.32, 0.30])
    axs = fig.add_axes([0.60, 0.07, 0.37, 0.14])
    fig.suptitle(title, fontsize=14, fontweight="bold", x=0.02, y=0.985, ha="left")
    if subtitle:
        fig.text(0.02, 0.925, subtitle, fontsize=9.5, color="#444")

    frames = [(t, k / sub) for t in range(T) for k in range(sub)]
    frames += [(T - 1, 1.0)] * (fps * 2)
    short = [m["name"].split(" (")[0] for m in S.muni]
    cent = [p.mean(0) for p in S.polys]
    half = GRID_KM / 2

    def draw(i):
        t, a = frames[i]
        k = t + 1 if a >= 1.0 else t        # 完了済みステップ数
        for x in (ax, axb, axm, axs):
            x.clear()
        # --- 地図
        for m, poly in enumerate(S.polys):
            ax.add_patch(MplPolygon(poly, closed=True, fc="#f4f1e8", ec="#555", lw=1.2))
        cv = cum_cov[k]
        for c in range(S.C):
            col = (0.25, 0.7, 0.35, 0.40) if cv[c] else (0.8, 0.8, 0.8, 0.0)
            ax.add_patch(plt.Rectangle((S.xy[c, 0] - half, S.xy[c, 1] - half), GRID_KM,
                                       GRID_KM, fc=col, ec=(0.5, 0.5, 0.5, 0.25), lw=0.4))
        for m in range(S.M):
            ax.text(cent[m][0], cent[m][1], short[m], ha="center", va="center",
                    fontsize=8, color="#333", alpha=0.75)
        for s in S.stations:
            ax.plot(*S.xy[s], marker="^", ms=13, color="#f1c40f", mec="k", zorder=4)
            ax.text(S.xy[s, 0], S.xy[s, 1] - 4.2, "充電", ha="center", fontsize=7,
                    zorder=4)
        for d in range(D):
            tid = D_TYPES[d]; col, nm, ms = TYPE_STYLE[tid]
            p0, p1 = wp[d, t], wp[d, t + 1]
            cur = p0 + (p1 - p0) * a
            tgt_cell = path[d, t]
            charging = S.is_station[tgt_cell] and a >= 1.0
            if not S.is_station[tgt_cell]:
                ax.add_patch(Circle(cur, S.sens[tid]["effective_coverage_radius"],
                                    fill=False, ec=col, lw=1.3, ls="--", alpha=0.8))
            tr = np.vstack([wp[d, :t + 1], cur])
            ax.plot(tr[:, 0], tr[:, 1], "-", color=col, lw=1.8, alpha=0.7)
            ax.plot(*cur, "o", color=col, ms=ms, mec="k", zorder=6)
            ax.text(cur[0], cur[1], str(d + 1), color="w", ha="center", va="center",
                    fontsize=7, fontweight="bold", zorder=7)
            if charging:
                ax.text(cur[0] + 2, cur[1] + 3, "⚡", fontsize=11, zorder=8)
        ax.plot(S.pref[:, 0], S.pref[:, 1], "-", color="k", lw=1.8)
        ax.set_aspect("equal")
        ax.set_xlim(S.pref[:, 0].min() - 3, S.pref[:, 0].max() + 3)
        ax.set_ylim(S.pref[:, 1].min() - 3, S.pref[:, 1].max() + 3)
        ax.tick_params(labelsize=7)
        ax.set_xlabel("x [km]", fontsize=8); ax.set_ylabel("y [km]", fontsize=8)
        ax.set_title(f"step {k}/{T}   緑=観測済セル  破線=観測円  黄三角=充電ステーション",
                     fontsize=9)
        # --- バッテリー
        for d in range(D):
            tid = D_TYPES[d]; col, nm, _ = TYPE_STYLE[tid]
            lv = bat[d, k]
            axb.barh(d, BATT_MAX, color="#e5e5e5", height=0.65)
            axb.barh(d, lv, color=col if lv > 2 else "#e67e22", height=0.65)
            axb.text(BATT_MAX + 0.15, d, f"{lv}", va="center", fontsize=9)
        axb.set_yticks(range(D))
        axb.set_yticklabels([f"{d+1}:{TYPE_STYLE[D_TYPES[d]][1]}" for d in range(D)],
                            fontsize=8)
        axb.invert_yaxis(); axb.set_xlim(0, BATT_MAX + 1)
        axb.set_title("バッテリー残量", fontsize=9)
        axb.tick_params(labelsize=7)
        # --- 市町村ごとの達成率
        rc, ra, rb = ratios(k)
        yy = np.arange(S.M)
        axm.barh(yy - 0.27, 100 * rc, height=0.26, color="#2ca02c", label="被覆率")
        axm.barh(yy, 100 * ra, height=0.26, color="#d62728", label="alpha")
        axm.barh(yy + 0.27, 100 * rb, height=0.26, color="#1f77b4", label="beta")
        axm.set_yticks(yy); axm.set_yticklabels(short, fontsize=7)
        axm.invert_yaxis(); axm.set_xlim(0, 100)
        axm.axvline(100, color="k", lw=0.8)
        axm.set_title("要求の達成率 [%] (100で達成)", fontsize=9)
        axm.legend(fontsize=6.5, loc="lower right", ncol=3)
        axm.tick_params(labelsize=7)
        # --- スコア推移
        axs.plot(range(T + 1), scores, "-", color="#ccc", lw=2)
        axs.plot(range(k + 1), scores[:k + 1], "o-", color="#d62728", lw=2.2)
        axs.set_xlim(0, T); axs.set_ylim(0, 1)
        axs.set_title(f"総合スコア {scores[k]:.3f}", fontsize=9)
        axs.grid(alpha=.3); axs.tick_params(labelsize=7)

    ani = animation.FuncAnimation(fig, draw, frames=len(frames), interval=1000 / fps)
    writer = animation.FFMpegWriter(fps=fps, codec="libx264",
                                    extra_args=["-pix_fmt", "yuv420p"])
    ani.save(out_path, writer=writer)
    plt.close(fig)
