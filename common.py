"""
common.py : 災害救助ドローン観測計画の共通部分
  - シナリオ定義 (生存者確率マップ, 延焼する危険領域, ドローン初期位置)
  - 評価関数 (QUBO版・MILP版を同じ物差しで比較するため)
  - 動画生成

問題設定
  N x N のグリッド上で D 機のドローンが T ステップ飛行し, 生存者の存在確率を
  できるだけ多く「観測」する. 各機は1ステップに最大 VMAX マス動ける.
  観測半径は RSENSE マス. 危険領域(延焼)は時間とともに広がり,
  その中に入った機体は 1機・1ステップあたり LAMBDA_H のペナルティ.

  目的 J = (観測できた確率質量の合計: 重複は1回だけ数える) - LAMBDA_H * (危険領域滞在数)
"""
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle
from matplotlib import animation

# 日本語フォント (環境にあるものだけを使う)
from matplotlib import font_manager as _fm
_avail = {f.name for f in _fm.fontManager.ttflist}
_jp = [f for f in ["Noto Sans CJK JP", "IPAexGothic", "IPAGothic", "Hiragino Sans",
                   "Yu Gothic", "MS Gothic"] if f in _avail]
plt.rcParams["font.family"] = _jp + ["DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

# ------------------------------------------------------------------ 設定
N = 10            # グリッド一辺
D = 3             # ドローン台数
T = 6             # 計画ステップ数 (t=1..T)
VMAX = 2          # 1ステップの最大移動 (チェビシェフ距離)
RSENSE = 1.5      # 観測半径 (マス)
LAMBDA_H = 0.10   # 危険領域に1機が1ステップ滞在するペナルティ
START = [(0, 0), (0, 1), (1, 0)]   # 初期位置 (row, col) ベース付近


def cells():
    return [(r, c) for r in range(N) for c in range(N)]


def cid(r, c):
    return r * N + c


def build_scenario():
    """生存者確率マップ p[s], 危険領域 hazard[t, c] (t=0..T) を作る"""
    rr, cc = np.meshgrid(np.arange(N), np.arange(N), indexing="ij")
    blobs = [  # (row, col, sigma, weight)
        (7.0, 2.0, 1.2, 0.30),   # A: 右下寄り
        (2.0, 7.0, 1.2, 0.25),   # B: 左上寄り
        (7.0, 7.0, 1.5, 0.45),   # C: 火元に近い (時間との競争)
    ]
    p = np.zeros((N, N))
    for (br, bc, sg, w) in blobs:
        g = np.exp(-((rr - br) ** 2 + (cc - bc) ** 2) / (2 * sg ** 2))
        p += w * g / g.sum()
    p = (p / p.sum()).ravel()

    # 延焼: 火元 (8,8) から半径が 0.8 + 0.5 t で広がる
    fire = (8.0, 8.0)
    hazard = np.zeros((T + 1, N * N), dtype=bool)
    for t in range(T + 1):
        rad = 0.8 + 0.5 * t
        d = np.sqrt((rr - fire[0]) ** 2 + (cc - fire[1]) ** 2)
        hazard[t] = (d <= rad).ravel()
    return p, hazard


def cover_matrix():
    """cover[c, s] = 1 if 位置 c から セル s を観測できる"""
    K = np.zeros((N * N, N * N), dtype=bool)
    for (r, c) in cells():
        for (r2, c2) in cells():
            if (r - r2) ** 2 + (c - c2) ** 2 <= RSENSE ** 2:
                K[cid(r, c), cid(r2, c2)] = True
    return K


def reachable(c_from, c_to):
    r1, c1 = divmod(c_from, N)
    r2, c2 = divmod(c_to, N)
    return max(abs(r1 - r2), abs(c1 - c2)) <= VMAX


# ------------------------------------------------------------------ 評価
def evaluate(path, p, hazard, K):
    """
    path: shape (D, T) 各機が t=1..T に居るセルID
    戻り値: dict(J, covered, hazard_steps, feasible, ...)
    """
    path = np.asarray(path)
    feasible = True
    msgs = []
    # 移動制約
    for d in range(D):
        s0 = cid(*START[d])
        seq = [s0] + list(path[d])
        for t in range(T):
            if not reachable(seq[t], seq[t + 1]):
                feasible = False
                msgs.append(f"drone{d} t={t+1}: 移動制約違反")
    # 衝突 (同時刻同セル)
    for t in range(T):
        if len(set(path[:, t])) < D:
            feasible = False
            msgs.append(f"t={t+1}: 同一セルに複数機")
    covered = np.zeros(N * N, dtype=bool)
    hz = 0
    for d in range(D):
        for t in range(T):
            covered |= K[path[d, t]]
            hz += int(hazard[t + 1, path[d, t]])
    mass = float(p[covered].sum())
    J = mass - LAMBDA_H * hz
    return dict(J=J, covered_mass=mass, hazard_steps=hz,
                feasible=feasible, messages=msgs)


# ------------------------------------------------------------------ 動画
def make_video(path, p, hazard, K, out_path, title, subtitle="", fps=20, sub=24):
    """
    path を動画にする. 各ステップ間を sub フレームで補間して滑らかに動かす.
    左: 生存者確率マップ(未観測分のみ表示) + 危険領域 + ドローン + 観測円
    右: 累積の観測率の推移
    """
    path = np.asarray(path)
    pos = [np.array([START[d]], dtype=float) for d in range(D)]
    waypoints = np.zeros((D, T + 1, 2))
    for d in range(D):
        waypoints[d, 0] = START[d]
        for t in range(T):
            waypoints[d, t + 1] = divmod(path[d, t], N)

    # ステップごとの累積観測マスク
    cum_cov = [np.zeros(N * N, dtype=bool)]
    for t in range(T):
        m = cum_cov[-1].copy()
        for d in range(D):
            m |= K[path[d, t]]
        cum_cov.append(m)
    cum_frac = [float(p[m].sum()) for m in cum_cov]

    colors = ["#1f77b4", "#2ca02c", "#9467bd"]
    fig = plt.figure(figsize=(10.5, 5.6), dpi=100)
    ax = fig.add_axes([0.04, 0.07, 0.52, 0.77])
    ax2 = fig.add_axes([0.64, 0.17, 0.32, 0.62])
    fig.suptitle(title, fontsize=14, fontweight="bold", x=0.02, y=0.985, ha="left")
    if subtitle:
        fig.text(0.02, 0.925, subtitle, fontsize=9.5, color="#444")

    frames = []
    for t in range(T):
        for k in range(sub):
            frames.append((t, k / sub))
    frames.append((T - 1, 1.0))
    frames += [(T - 1, 1.0)] * (fps)  # 最後に1秒静止

    def draw(i):
        t, a = frames[i]
        ax.clear()
        ax2.clear()
        # 表示するステップ (a=1 で t+1 に到達)
        tt = t + 1 if a >= 1.0 else t
        # 未観測の生存者確率
        remaining = np.where(cum_cov[t], 0.0, p)
        if a >= 1.0:
            remaining = np.where(cum_cov[tt], 0.0, p)
        im = ax.imshow(remaining.reshape(N, N), cmap="YlOrBr", vmin=0,
                       vmax=p.max(), origin="upper")
        # 観測済みセルを薄い緑で
        obs = (cum_cov[tt] if a >= 1.0 else cum_cov[t]).reshape(N, N)
        overlay = np.zeros((N, N, 4))
        overlay[obs] = [0.2, 0.7, 0.3, 0.25]
        ax.imshow(overlay, origin="upper")
        # 危険領域 (補間的に: 次ステップの危険を半透明)
        hz_now = hazard[tt if a >= 1.0 else t].reshape(N, N)
        hz_next = hazard[min(t + 1, T)].reshape(N, N)
        ov = np.zeros((N, N, 4))
        ov[hz_next] = [0.9, 0.1, 0.1, 0.18]
        ov[hz_now] = [0.9, 0.1, 0.1, 0.55]
        ax.imshow(ov, origin="upper")
        # ドローン
        for d in range(D):
            p0 = waypoints[d, t]
            p1 = waypoints[d, t + 1]
            cur = p0 + (p1 - p0) * a
            ax.add_patch(Circle((cur[1], cur[0]), RSENSE, fill=False,
                                ec=colors[d], lw=1.6, ls="--"))
            tr = waypoints[d, :t + 1]
            tr = np.vstack([tr, cur])
            ax.plot(tr[:, 1], tr[:, 0], "-", color=colors[d], lw=2, alpha=.8)
            ax.plot(cur[1], cur[0], "o", color=colors[d], ms=11, mec="k", zorder=5)
            ax.text(cur[1], cur[0], str(d + 1), color="w", ha="center",
                    va="center", fontsize=8, fontweight="bold", zorder=6)
        ax.plot(START[0][1], START[0][0], "ks", ms=0)
        ax.set_xlim(-0.5, N - 0.5)
        ax.set_ylim(N - 0.5, -0.5)
        ax.set_xticks(range(N))
        ax.set_yticks(range(N))
        ax.tick_params(labelsize=7)
        ax.set_title(f"step t = {tt}/{T}   (橙: 未観測の生存者確率 / 赤: 危険領域 / 緑: 観測済)",
                     fontsize=9)
        # 右グラフ
        xs = list(range(T + 1))
        ax2.plot(xs, [100 * v for v in cum_frac], "-", color="#ccc", lw=2)
        upto = tt
        ax2.plot(xs[:upto + 1], [100 * v for v in cum_frac[:upto + 1]], "o-",
                 color="#d62728", lw=2.5)
        ax2.set_ylim(0, 100)
        ax2.set_xlim(0, T)
        ax2.set_xlabel("step", fontsize=9)
        ax2.set_ylabel("累積 観測率 [%] (確率質量)", fontsize=9)
        ax2.grid(alpha=.3)
        ax2.set_title(f"観測率 {100 * cum_frac[upto]:.1f} %", fontsize=11)

    ani = animation.FuncAnimation(fig, draw, frames=len(frames), interval=1000 / fps)
    writer = animation.FFMpegWriter(fps=fps, codec="libx264",
                                    extra_args=["-pix_fmt", "yuv420p"])
    ani.save(out_path, writer=writer)
    plt.close(fig)
