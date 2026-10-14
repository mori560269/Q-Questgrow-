"""
placement/fine_grid.py : 面積を数えるマスを細かくして MILP を解き直す

  1 km マスで最適な解 (6,160) は, 200 m マスで数え直すと 西南市が 89.92% (目標 90%) でわずかに足りなかった.
  そこで 500 m / 250 m / 200 m のマスで MILP を解き直し, それぞれの解を 1 km 〜 100 m のマスで判定する.

  python fine_grid.py   → results/placement_fine_grid.json, results/placement_fine_grid.png
"""
import json
import os
import sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import Problem, save_map
from classical import solve_milp

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
SOLVE_GRIDS = (1000, 500, 250, 200)
CHECK_GRIDS = (1000, 500, 250, 200, 100)


def main():
    rows, maps = [], {}
    base = None
    for g in SOLVE_GRIDS:
        prob = Problem(cell_m=float(g))
        x, info = solve_milp(prob, time_limit=600)
        cost = float((x * prob.cost).sum())
        base = base or cost
        checks = {}
        for h in CHECK_GRIDS:
            ev = prob.evaluate(x, cell_m=float(h))
            worst = int(np.argmax(np.array(ev["short_cov"])))
            checks[f"{h}m"] = dict(feasible=ev["feasible"],
                                   worst=None if ev["feasible"] else f"{prob.names[worst]} {ev['cov'][worst]:.2%}")
        r = dict(solve_grid_m=g, cells=info["cells"], merged_cells=info["merged_cells"], cost=cost,
                 vs_1km=round((cost - base) / base, 4), sec=round(info["sec"], 1),
                 optimal=info["status"] == 0, gap=info["gap"], n_sensors=ev["n_sensors"], checks=checks, x=ev["x"])
        rows.append(r)
        print(f"{g} m マスで解く: コスト {cost:.0f} ({r['vs_1km']:+.1%})  {r['sec']} 秒  最適={r['optimal']}  "
              + "  ".join(f"{k}:{'○' if v['feasible'] else '× ' + v['worst']}" for k, v in checks.items()), flush=True)
        maps[f"MILP ({g} m マス)"] = prob.evaluate(x, cell_m=1000.0)
    os.makedirs(os.path.join(ROOT, "results"), exist_ok=True)
    json.dump(rows, open(os.path.join(ROOT, "results", "placement_fine_grid.json"), "w"), ensure_ascii=False, indent=1)
    save_map(Problem(cell_m=1000.0), maps, os.path.join(ROOT, "results", "placement_fine_grid.png"), cols=4)


if __name__ == "__main__":
    main()
