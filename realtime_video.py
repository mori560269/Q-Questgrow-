"""
realtime_video.py : realtime_drone.py の結果を動画にする

  左   : 全体図 (緑 = 観測済み, 黄三角 = 充電ステーション, 点 = ドローン, 線 = 直近の軌跡)
  中央 : 直近のトラブル地点を中心にした拡大図 (見える範囲の円も描く)
         トラブル: 灰色の破線 = 未発見の危険区域 / 赤 = 発見済み (飛行禁止)
                   灰色の星 = 未発見の要救助者 / 橙 = 発見・見守り中 / 緑 = 見守り完了
  右   : 各機のバッテリーと状態, 総合スコアの推移 / 中央下: トラブルと QUBO 組み直しの記録
"""
import numpy as np
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

SENSOR_COLOR = {"SENS-ALPHA-01": "#d62728", "SENS-BETA-02": "#1f77b4", "SENS-GAMMA-03": "#2ca02c"}
SENSOR_NAME = {"SENS-ALPHA-01": "ALPHA", "SENS-BETA-02": "BETA", "SENS-GAMMA-03": "GAMMA"}
MUNI_COLORS = ["#f4e9d8", "#e8f0e0", "#e6eaf4", "#f4e4ea", "#efeadb", "#e2f0ef", "#f1ebf5", "#eef2dc"]
MODE_JP = {"fly": "飛行", "return": "帰還", "charge": "充電", "failed": "故障", "standby": "待機"}


def make_video(res, world, state, out_path, fps=10, trail_sec=180, zoom_km=10.0):
    track = res["track"]
    every = int(res["scenario"].get("video_every_sec", 15))
    frames = [k for k in range(len(track)) if int(track[k]["t"]) % every == 0] or [len(track) - 1]
    frames += [frames[-1]] * (fps * 2)
    pos = np.array([tr["pos"] for tr in track]) / 1000.0          # (T, D, 2) km
    times = np.array([tr["t"] for tr in track])
    scores = np.array([tr["score"] for tr in track])
    drones = res["drones"]
    D = len(drones)
    km = 1000.0
    ext = [world.x0 / km, (world.x0 + world.nx * world.res) / km,
           world.y0 / km, (world.y0 + world.ny * world.res) / km]

    base = np.ones((world.ny * world.nx, 3))
    for m in range(world.M):
        base[world.muni_flat == m] = matplotlib.colors.to_rgb(MUNI_COLORS[m % len(MUNI_COLORS)])
    green = np.array(matplotlib.colors.to_rgb("#3fae5a"))
    seen = state["first_seen"]
    inc = {z["id"]: z for z in res["incidents"]}

    def focus(t):
        """拡大図の中心: 直近のトラブル地点 (なければ最初のステーション)"""
        for e in reversed([e for e in res["events"] if e["t"] <= t]):
            if "incident" in e and "x" in inc[e["incident"]]:
                z = inc[e["incident"]]
                return np.array([z["x"], z["y"]]) / km, e["msg"]
            if "drone" in e:
                k = min(int(e["t"]), len(track) - 1)
                return pos[k, e["drone"]], e["msg"]
        return world.stations[0] / km, "充電ステーション 1 付近"

    fig = plt.figure(figsize=(16, 8), dpi=85)
    ax = fig.add_axes([0.02, 0.05, 0.40, 0.84])
    axz = fig.add_axes([0.45, 0.33, 0.30, 0.56])
    axe = fig.add_axes([0.45, 0.02, 0.32, 0.25])
    axb = fig.add_axes([0.81, 0.33, 0.17, 0.56])
    axs = fig.add_axes([0.81, 0.07, 0.17, 0.17])
    sc = res["scenario"]
    fig.suptitle("毎秒 QUBO 再最適化 + トラブル時の即時組み直し", fontsize=14, fontweight="bold",
                 x=0.02, y=0.985, ha="left")
    fig.text(0.02, 0.94, f"機体 {D} / 見える範囲 " +
             " ".join(f"{SENSOR_NAME.get(f['sensor'], f['sensor'])} {f['sensor_radius_m']:.0f}m×{f['count']}"
                      for f in sc["fleet"]) +
             f" / 電池 {sc['battery']['capacity_sec'] / 60:.0f}分飛行・満充電 {sc['battery']['full_charge_sec'] / 60:.0f}分"
             f" / {sc.get('launch_waves', 1)}組で交代出発"
             f" / 最適化 {res['replans_total']}回 (トラブル起因 {res['replans_by_event']}回)",
             fontsize=9, color="#444")

    def draw_map(a, k, t, img, detail):
        a.imshow(img, origin="lower", extent=ext, interpolation="nearest")
        for poly in world.polys:
            a.add_patch(MplPolygon(poly / km, closed=True, fill=False, ec="#666", lw=0.8))
        if world.pref is not None:
            a.plot(world.pref[:, 0] / km, world.pref[:, 1] / km, "-", color="k", lw=1.4)
        st = world.stations / km
        a.plot(st[:, 0], st[:, 1], "^", ms=12 if detail else 9, color="#f1c40f", mec="k", zorder=4)
        for z in res["incidents"]:
            found = z.get("found_t") is not None and z["found_t"] <= t
            if z["type"] == "hazard":
                a.add_patch(Circle((z["x"] / km, z["y"] / km), z["radius_m"] / km,
                                   fc=(0.9, 0.1, 0.1, 0.35) if found else "none",
                                   ec="#c0392b" if found else "#888", ls="-" if found else "--",
                                   lw=1.4, zorder=3))
                if found or detail:
                    a.text(z["x"] / km, z["y"] / km, z.get("label", "危険") + ("" if found else "\n(未発見)"),
                           color="#a00" if found else "#777", fontsize=8 if detail else 7, ha="center",
                           va="center", zorder=7, fontweight="bold")
            elif z["type"] == "survivor":
                done = z.get("resolved_t") is not None and z["resolved_t"] <= t
                col = "#2ecc71" if done else ("#e67e22" if found else "#aaaaaa")
                a.plot(z["x"] / km, z["y"] / km, "*", ms=18 if detail else 12, color=col, mec="k", zorder=6)
                if detail:
                    a.text(z["x"] / km, z["y"] / km + 0.35, z.get("label", "要救助者") +
                           (" 見守り完了" if done else (" 見守り中" if found else " (未発見)")),
                           fontsize=8, ha="center", color="#333", zorder=7)
        k0 = max(0, k - trail_sec)
        modes = track[k]["mode"]
        for d in range(D):
            col = SENSOR_COLOR.get(drones[d]["sensor"], "#333")
            tr = pos[k0:k + 1, d]
            a.plot(tr[:, 0], tr[:, 1], "-", color=col, lw=1.2 if detail else 0.8, alpha=0.75, zorder=5)
            x, y = pos[k, d]
            if modes[d] == "failed":
                a.plot(x, y, "x", ms=10, color="k", mew=2, zorder=8)
                continue
            if detail and modes[d] in ("fly", "return"):
                a.add_patch(Circle((x, y), drones[d]["r"] / km, fc=matplotlib.colors.to_rgba(col, 0.12),
                                   ec=col, lw=1.0, zorder=5))
            a.plot(x, y, "o", ms=7 if detail else 5, color=col if modes[d] == "fly" else "white", mec=col,
                   mew=1.5, zorder=8)
            if detail:
                a.text(x + 0.15, y + 0.15, str(d + 1), fontsize=7, zorder=9)

    def draw(fi):
        k = frames[fi]
        t = times[k]
        for a in (ax, axz, axe, axb, axs):
            a.clear()
        img = base.copy()
        img[seen <= t] = green
        img = img.reshape(world.ny, world.nx, 3)
        # 全体図
        draw_map(ax, k, t, img, detail=False)
        c, why = focus(t)
        h = zoom_km / 2
        ax.add_patch(plt.Rectangle((c[0] - h, c[1] - h), zoom_km, zoom_km, fill=False, ec="#8e44ad", lw=1.5,
                                   zorder=9))
        ax.set_xlim(ext[0], ext[1]); ax.set_ylim(ext[2], ext[3]); ax.set_aspect("equal")
        ax.tick_params(labelsize=7)
        ax.set_title(f"全体図  t = {int(t) // 60:02d}:{int(t) % 60:02d}   ● 飛行  ○ 帰還/充電/待機  × 故障",
                     fontsize=9)
        # 拡大図
        draw_map(axz, k, t, img, detail=True)
        axz.set_xlim(c[0] - h, c[0] + h); axz.set_ylim(c[1] - h, c[1] + h); axz.set_aspect("equal")
        axz.tick_params(labelsize=7)
        axz.set_title(f"拡大 {zoom_km:.0f} km 四方: {why}", fontsize=9, color="#8e44ad")
        for sp_ in axz.spines.values():
            sp_.set_edgecolor("#8e44ad")
        # 記録
        evs = [e for e in res["events"] if e["t"] <= t][-7:]
        axe.axis("off")
        axe.text(0, 1.0, "トラブルと QUBO の組み直し", fontsize=10, transform=axe.transAxes, va="top",
                 fontweight="bold")
        for i, e in enumerate(evs):
            red = "found" in e["kind"] or e["kind"] in ("drone_failure", "battery_fault", "battery_empty")
            axe.text(0.0, 0.82 - i * 0.13, f"{int(e['t']) // 60:02d}:{int(e['t']) % 60:02d}  {e['msg']}"
                     "  → QUBO 組み直し", fontsize=8.5, transform=axe.transAxes,
                     color="#a00" if red else "#2c7a3f", va="top")
        if not evs:
            axe.text(0.0, 0.8, "(まだトラブルなし. 毎秒の定期最適化のみ)", fontsize=9, color="#777",
                     transform=axe.transAxes, va="top")
        # バッテリー
        bat = np.array(track[k]["bat"])
        modes = track[k]["mode"]
        for d in range(D):
            col = SENSOR_COLOR.get(drones[d]["sensor"], "#333")
            axb.barh(d, 1, color="#eee", height=0.7)
            axb.barh(d, max(bat[d], 0), color="#e67e22" if bat[d] < 0.25 else col, height=0.7)
            axb.text(1.03, d, MODE_JP.get(modes[d], modes[d]), fontsize=7, va="center")
        axb.set_xlim(0, 1.25); axb.invert_yaxis()
        axb.set_yticks(range(D)); axb.set_yticklabels([str(d + 1) for d in range(D)], fontsize=6.5)
        axb.tick_params(axis="x", labelsize=7)
        axb.set_title("バッテリー残量と状態\n赤=ALPHA 青=BETA 緑=GAMMA", fontsize=9)
        # スコア
        axs.plot(times / 60, scores, "-", color="#ccc", lw=1.5)
        axs.plot(times[:k + 1] / 60, scores[:k + 1], "-", color="#d62728", lw=2)
        axs.set_xlim(0, times[-1] / 60); axs.set_ylim(0, 1); axs.grid(alpha=.3)
        axs.set_title(f"総合スコア {scores[k]:.3f}", fontsize=9)
        axs.set_xlabel("分", fontsize=8)
        axs.tick_params(labelsize=7)

    ani = animation.FuncAnimation(fig, draw, frames=len(frames), interval=1000 / fps)
    ani.save(out_path, writer=animation.FFMpegWriter(fps=fps, codec="libx264",
                                                     extra_args=["-pix_fmt", "yuv420p"]))
    plt.close(fig)
