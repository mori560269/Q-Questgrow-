"""
phase2/real_run.py : 配布サンプル（実データ）の結果の詳細・図・条件を変えたときの最適値

  python real_run.py          → results/real_sample.json, results/real_sample_map.png, results/real_sample_gantt.png
  python real_run.py --sens   → results/real_sensitivity.json, results/real_sensitivity.png
"""
import json
import os
import sys

import numpy as np
from scipy.sparse.csgraph import dijkstra

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "placement"))
import model
from real import RealWorld, RealInstance, load_sample, slot_lower_bound
from exact import solve_exact
from equal_time import ils

RES = os.path.join(HERE, "..", "results")


def schedule_detail(I, plan):
    """車ごとの行動（走行・離陸準備・飛行・充電待ち）を, 評価器と同じ規則で時刻つきに展開する"""
    ev = I.evaluate(plan)
    out = []
    for tr in I.trucks:
        per = ev["per_truck"][tr.tid]
        fids = per["flights"]
        if not fids:
            out.append(dict(車=tr.tid, 拠点=tr.depot, 予備=False, 行動=[], 完了=0.0))
            continue
        stops = {}
        for f in fids:
            stops.setdefault(I.flights[f]["node"], []).append(f)
        for v in stops:
            stops[v].sort(key=lambda f: I.flights[f]["dur"])
        t, ready, pos, acts = 0.0, 0.0, tr.node, []
        for i, v in enumerate(per["order"]):
            if pos != v:
                d = I.drive(pos, v) - I.setup
                acts.append(dict(種類="走行", 開始=t, 終了=t + d, 発=int(pos), 着=int(v)))
                t += d
            acts.append(dict(種類="離陸準備", 開始=t, 終了=t + I.setup, 地点=int(v)))
            t += I.setup
            pos = v
            for f in stops[v]:
                fl = I.flights[f]
                start = max(t, ready)
                if start > t + 1e-9:
                    acts.append(dict(種類="充電待ち", 開始=t, 終了=start))
                acts.append(dict(種類="飛行", 開始=start, 終了=start + fl["dur"], 地点=int(v),
                                 センサー=[I.target_ids[j] for j in fl["order"]],
                                 回復時刻=[round(start + o, 2) for o in fl["offset"]]))
                t = start + fl["dur"]
                ready = t + model.CHARGE_MIN
        out.append(dict(車=tr.tid, 拠点=tr.depot, 予備=per["spare"], 行動=acts, 完了=round(per["makespan"], 2)))
    return out


def draw(rw, I, plan, detail, path_png, gantt_png):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager as fm
    av = {f.name for f in fm.fontManager.ttflist}
    plt.rcParams["font.family"] = [f for f in ["Noto Sans CJK JP", "IPAexGothic", "IPAGothic"] if f in av] + ["DejaVu Sans"]
    M = json.load(open(os.path.join(HERE, "..", "data", "municipalities.geojson")))["features"]
    closed = set(I.sc["closed_segments"])
    fig, ax = plt.subplots(figsize=(11, 11.5))
    for f in M:
        P = np.array(f["geometry"]["coordinates"][0]) / 1000
        ax.fill(P[:, 0], P[:, 1], fc="#f4f1e8", ec="#b8b2a0", lw=0.6, zorder=0)
    width = dict(motorway=2.2, motorway_link=1.2, trunk=1.4, primary=1.0, secondary=0.6)
    for sid, s in zip(rw.seg_ids, rw.seg):
        g = np.array(s["geom"]) / 1000
        if sid in closed:
            continue
        ax.plot(g[:, 0], g[:, 1], color="#9aa3a8" if s["hw"] != "motorway" else "#6f7c85", lw=width[s["hw"]], zorder=1)
    for sid in closed:
        g = np.array(rw.seg[rw.sid[sid]]["geom"]) / 1000
        ax.plot(g[:, 0], g[:, 1], color="#d62728", lw=3.2, zorder=3, solid_capstyle="butt")
    # 車の経路（最短経路を道路に沿って描く）
    colors = ["#1f5fbf", "#2a9d8f", "#e76f51", "#8e44ad", "#c99700", "#4d7c0f", "#b5179e", "#0b7285"]
    edge_seg = {}
    for sid, s in zip(rw.seg_ids, rw.seg):
        if sid not in closed:
            edge_seg[(s["a"], s["b"])] = s; edge_seg[(s["b"], s["a"])] = s
    for d in detail:
        col = colors[d["車"] % len(colors)]
        for a in d["行動"]:
            if a["種類"] != "走行":
                continue
            _, pred = dijkstra(I.G, indices=a["発"], return_predecessors=True)
            v = a["着"]
            while v != a["発"] and v >= 0:
                u = pred[v]
                s = edge_seg.get((u, v))
                if s is not None:
                    g = np.array(s["geom"]) / 1000
                    ax.plot(g[:, 0], g[:, 1], color=col, lw=2.6, alpha=0.85, zorder=4)
                v = u
        for a in d["行動"]:
            if a["種類"] == "飛行":
                p = rw.nodes[a["地点"]] / 1000
                ax.plot(*p, "^", color=col, ms=9, mec="white", zorder=6)
                for sid_ in a["センサー"]:
                    q = rw.sensor_xy[rw.sensor_ids.index(sid_)] / 1000
                    ax.plot([p[0], q[0]], [p[1], q[1]], ls=(0, (2, 2)), color=col, lw=1.3, zorder=5)
    fail = set(I.target_ids)
    unr = {I.target_ids[j] for j in I.unreachable}
    for sid_, (x, y) in zip(rw.sensor_ids, rw.sensor_xy / 1000):
        if sid_ in unr:
            ax.plot(x, y, "X", color="#d62728", ms=11, mec="white", zorder=7)
        elif sid_ in fail:
            ax.plot(x, y, "o", color="#14213D", ms=8, mec="white", zorder=7)
        else:
            ax.plot(x, y, "o", color="#c9c9c9", ms=4, zorder=2)
    rt = I.evaluate(plan)["rec_time"]
    for j in I.recoverable:
        k = I.targets[j]
        x, y = rw.sensor_xy[k] / 1000
        ax.annotate(f"{rw.sensor_ids[k]} {rt[k]:.0f}分", (x, y), xytext=(5, 4), textcoords="offset points", fontsize=8, zorder=8)
    for j in I.unreachable:
        k = I.targets[j]
        x, y = rw.sensor_xy[k] / 1000
        ax.annotate(f"{rw.sensor_ids[k]} 対応不能", (x, y), xytext=(5, -10), textcoords="offset points", fontsize=8,
                    color="#d62728", zorder=8)
    for nid, nm in rw.base_nodes.items():
        p = rw.nodes[rw.nid[nid]] / 1000
        ax.plot(*p, "s", color="#6f42c1", ms=12, mec="white", zorder=9)
        ax.annotate(nm.replace("（災害対策本部）", ""), p, xytext=(7, -14), textcoords="offset points", fontsize=10,
                    color="#6f42c1", weight="bold", zorder=9)
    from matplotlib.lines import Line2D
    h = [Line2D([], [], color="#d62728", lw=3, label="通行止め区間"),
         Line2D([], [], color="#14213D", marker="o", ls="", label="通信断（回復した時刻）"),
         Line2D([], [], color="#d62728", marker="X", ls="", label="対応不能"),
         Line2D([], [], color="#6f42c1", marker="s", ls="", label="拠点"),
         Line2D([], [], color="#1f5fbf", lw=2.6, label="車の経路（色 = 車）"),
         Line2D([], [], color="#1f5fbf", marker="^", ls="", label="離陸地点"),
         Line2D([], [], color="#1f5fbf", ls=(0, (2, 2)), label="ドローンの飛行")]
    ax.legend(handles=h, loc="lower right", fontsize=10, framealpha=0.95)
    ax.set_aspect("equal"); ax.set_xlabel("km"); ax.set_ylabel("km")
    ax.set_title(f"配布サンプル: 最適計画（完了 {I.evaluate(plan)['makespan']:.1f} 分, 回復 {len(I.recoverable)} 基 / 対応不能 {len(I.unreachable)} 基）")
    fig.savefig(path_png, dpi=90, bbox_inches="tight")
    plt.close(fig)

    used = [d for d in detail if d["行動"]]
    fig, ax = plt.subplots(figsize=(11, 0.6 * len(used) + 1.4))
    cm = {"走行": "#9aa3a8", "離陸準備": "#e9c46a", "飛行": "#1f5fbf", "充電待ち": "#f4a6a6"}
    for r, d in enumerate(used):
        for a in d["行動"]:
            ax.barh(r, a["終了"] - a["開始"], left=a["開始"], color=cm[a["種類"]], height=0.6, edgecolor="white", lw=0.5)
            if a["種類"] == "飛行":
                ax.text((a["開始"] + a["終了"]) / 2, r, a["センサー"][0], ha="center", va="center", fontsize=7, color="white")
    ax.set_yticks(range(len(used)))
    ax.set_yticklabels([f"車 {d['車']}（{d['拠点'].replace('（災害対策本部）', '')}）" for d in used])
    ax.invert_yaxis()
    ax.set_xlabel("災害発生からの時間 [分]")
    from matplotlib.patches import Patch
    ax.legend(handles=[Patch(color=c, label=k) for k, c in cm.items()], ncol=4, loc="upper center",
              bbox_to_anchor=(0.5, -0.18), fontsize=10, frameon=False)
    ax.axvline(I.evaluate(plan)["makespan"], color="#d62728", lw=1, ls="--")
    fig.savefig(gantt_png, dpi=90, bbox_inches="tight")
    plt.close(fig)


def main():
    rw = RealWorld()
    sc = load_sample()
    I = RealInstance(rw, sc)
    lb_old = model.Instance.lower_bound(I)
    lb = slot_lower_bound(I)
    st = ils(I, 10.0, 0)
    plan, info = solve_exact(I, start=st, time_limit=300)
    e = I.evaluate(plan)
    detail = schedule_detail(I, plan)
    res = dict(
        条件=dict(車=len(I.trucks), 予備バッテリー=I.spares_left, 離陸準備_分=I.setup, 充電_分=model.CHARGE_MIN,
                  車の速さ=sc["vehicle"]["speed_kmh"], 離陸できる道路=sc["vehicle"]["launchable_highways"]),
        通信断=len(I.targets), 回復可能=len(I.recoverable), 対応不能=[I.target_ids[j] for j in I.unreachable],
        対応不能の理由=I.unreach_reason, 飛行の候補=len(I.flights), 離陸地点の候補=len(I.launch),
        二基以上を回る飛行=sum(len(f["sensors"]) > 1 for f in I.flights),
        下界_単純=round(lb_old, 2), 下界_枠割当=round(lb, 2), 最適な完了時刻=round(e["makespan"], 2),
        最適を証明=info["optimal"], 厳密解法=info,
        回復時刻={k: round(v, 1) for k, v in sorted(e["rec_time"].items(), key=lambda kv: kv[1])},
        平均回復時刻=round(float(np.mean(list(e["rec_time"].values()))), 2),
        予備バッテリーを積む車=[d["車"] for d in detail if d["予備"]], 車ごと=detail)
    json.dump(res, open(os.path.join(RES, "real_sample.json"), "w"), ensure_ascii=False, indent=1)
    draw(rw, I, plan, detail, os.path.join(RES, "real_sample_map.png"), os.path.join(RES, "real_sample_gantt.png"))
    print({k: v for k, v in res.items() if k not in ("車ごと", "回復時刻")})


def sensitivity():
    """サンプルで条件を 1 つずつ変え, 厳密解法で最適な完了時刻を求める（会社との相談材料）"""
    rw = RealWorld()
    base = load_sample()
    out = []

    def solve(sc, label, value):
        I = RealInstance(rw, sc)
        st = ils(I, 5.0, 0)
        p, info = solve_exact(I, start=st, time_limit=300)
        e = I.evaluate(p)
        rt = list(e["rec_time"].values())
        out.append(dict(条件=label, 値=value, 回復=e["recovered"], 対応不能=len(I.unreachable),
                        完了時刻=round(e["makespan"], 1), 平均回復時刻=round(float(np.mean(rt)), 1) if rt else None,
                        最適=info["optimal"], 下界=round(I.lower_bound(), 1)))
        print(out[-1], flush=True)

    solve(base, "基準（配布サンプル）", "")
    for v in (0, 2, 3):
        sc = json.loads(json.dumps(base)); sc["fleet"]["total_spare_batteries"] = v
        solve(sc, "予備バッテリーの数", v)
    for v in (0, 5, 20):
        sc = json.loads(json.dumps(base)); sc["vehicle"]["launch_setup_time_min"] = v
        solve(sc, "離陸準備の時間 [分]", v)
    for v in (15, 20, 45):
        model.CHARGE_MIN = float(v)
        solve(base, "充電の時間 [分]", v)
    model.CHARGE_MIN = 30.0
    for nm, add in (("県庁", 2), ("西南市役所", 2), ("北東町役場", 2)):
        sc = json.loads(json.dumps(base))
        for b in sc["drone_bases"]:
            if b["name"].startswith(nm):
                b["num_vehicles"] += add
        solve(sc, "車を 2 台足す拠点", nm)
    for v in (1.5, 2.0):
        sc = json.loads(json.dumps(base))
        sc["vehicle"]["speed_kmh"] = {k: s * v for k, s in base["vehicle"]["speed_kmh"].items()}
        solve(sc, "車の速さ（倍）", v)
    sc = json.loads(json.dumps(base)); sc["vehicle"]["launchable_highways"] = ["trunk", "primary", "secondary", "motorway", "motorway_link"]
    solve(sc, "高速道路上でも離陸できる", "可")
    json.dump(out, open(os.path.join(RES, "real_sensitivity.json"), "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    if "--sens" in sys.argv:
        sensitivity()
    else:
        main()
