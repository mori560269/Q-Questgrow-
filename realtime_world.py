"""
realtime_world.py : 毎秒最適化シミュレーション (realtime_drone.py) の地図・シナリオ・評価・動画

  入力 JSON (data_transformed.json と同じ形式なら どの地域でもよい)
    prefecture_outer_boundary.vertices : 外周 [[x, y], ...]  (単位 m)
    municipalities[] : name, polygon_vertices, required_coverage_rate,
                       required_alpha_response, required_beta_resolution
    sensor_specifications[] : sensor_type_id, alpha_field_response, beta_density_resolution
                              (effective_coverage_radius は使わず, シナリオの値を使う)

  シナリオ JSON (省略可. 入力 JSON の "scenario" キーに入れてもよい)
    DEFAULT_SCENARIO を上書きする. 例: data/scenario_example.json
"""
import copy
import json
import numpy as np
from matplotlib.path import Path

# ------------------------------------------------------------------ 既定のシナリオ
DEFAULT_SCENARIO = {
    "raster_m": 100,            # 観測済みかどうかを管理するマスの大きさ [m]
    "duration_sec": 1800,       # 運用時間 [s]
    "tick_sec": 1,              # シミュレーションの刻み = 再最適化の間隔 [s]
    "replan_sec": 1,            # 定期的に QUBO を解き直す間隔 [s] (トラブル時は即時)
    "plan_step_sec": 30,        # 先読みの1ステップの長さ [s] (= 候補地点の間隔 速度×これ)
    "horizon": 2,               # 先読みステップ数
    # 機体: 見える範囲 (sensor_radius_m) は高度 100〜150 m の搭載センサーを想定
    "fleet": [
        {"sensor": "SENS-ALPHA-01", "count": 4, "speed_mps": 12, "sensor_radius_m": 500,
         "drain_per_sec": 1.2},
        {"sensor": "SENS-BETA-02", "count": 8, "speed_mps": 15, "sensor_radius_m": 300,
         "drain_per_sec": 1.0},
        {"sensor": "SENS-GAMMA-03", "count": 8, "speed_mps": 15, "sensor_radius_m": 150,
         "drain_per_sec": 0.8},
    ],
    # バッテリーは「標準消費で飛べる秒数」で表す. 15分飛行・満充電 45分
    "battery": {"capacity_sec": 900, "full_charge_sec": 2700,
                "resume_ratio": 0.9,      # ここまで充電したら再出発
                "reserve_margin": 1.3},   # 最寄りステーションに戻る分 × この倍率 は残す
    "stations": {"count": 8, "points": None},   # points: [[x, y], ...] で直接指定も可
    "launch_waves": 1,          # 交代運用: 何組に分けて出発するか (1 = 全機同時)
    "launch_interval_sec": 900, # 組ごとの出発のずれ [s]
    "alpha_beta_per_sec": 60,   # 稼働 60 秒ごとに alpha/beta を1回分加算
    # 配置: 各市町村 (領域) に複数機を置き, 基地 (発着・充電地点) を候補地点から選ぶ
    "deployment": {"enabled": True,
                   "min_per_region": 2,       # 1つの市町村に置く最少機数
                   "redeploy_sec": 900,       # 配置を見直す間隔 [s] (故障・電池切れ時は即時)
                   "spread_m": 6000,          # 同じ市町村の基地どうしをこれより離したい
                   "auto_candidates": 10},    # 候補地点がデータに無い市町村は自動で作る数
    "incidents": [],            # トラブル (data/scenario_example.json 参照)
    "solver": {"backend": "neal", "num_reads": 4, "num_sweeps": 200, "time_limit_ms": 500,
               "lam_ov": 0.5, "pen": 3.0, "target_factor": 5.0, "inertia": 0.5, "seed": 0},
    "video_every_sec": 15,
}


def deep_update(base, new):
    out = copy.deepcopy(base)
    for k, v in (new or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_update(out[k], v)
        else:
            out[k] = v
    return out


def load_inputs(data_path, scenario_path=None):
    data = json.load(open(data_path, encoding="utf-8"))
    for key in ("municipalities", "sensor_specifications"):
        if not data.get(key):
            raise ValueError(f"{data_path}: '{key}' がないか空です")
    need = ("polygon_vertices", "required_coverage_rate", "required_alpha_response",
            "required_beta_resolution")
    for m in data["municipalities"]:
        miss = [k for k in need if k not in m]
        if miss:
            raise ValueError(f"{data_path}: 市町村 {m.get('name', '?')} に {miss} がありません")
    sc = deep_update(DEFAULT_SCENARIO, data.get("scenario"))
    if scenario_path:
        sc = deep_update(sc, json.load(open(scenario_path, encoding="utf-8")))
    return data, sc


# ------------------------------------------------------------------ 地図
class World:
    def __init__(self, data, sc):
        self.sc = sc
        self.muni = data["municipalities"]
        self.M = len(self.muni)
        self.names = [m["name"] for m in self.muni]
        self.polys = [np.asarray(m["polygon_vertices"], float) for m in self.muni]
        pref = data.get("prefecture_outer_boundary", {}).get("vertices")
        self.pref = np.asarray(pref, float) if pref else None
        self.req_cov = np.array([m["required_coverage_rate"] for m in self.muni], float)
        self.req_a = np.array([m["required_alpha_response"] for m in self.muni], float)
        self.req_b = np.array([m["required_beta_resolution"] for m in self.muni], float)
        self.sens = {s["sensor_type_id"]: s for s in data["sensor_specifications"]}

        # ラスタ (マスの中心が市町村ポリゴン内なら その市町村)
        res = float(sc["raster_m"])
        allv = np.vstack(self.polys)
        self.x0, self.y0 = allv.min(0)
        x1, y1 = allv.max(0)
        self.res = res
        self.nx = int(np.ceil((x1 - self.x0) / res))
        self.ny = int(np.ceil((y1 - self.y0) / res))
        xs = self.x0 + (np.arange(self.nx) + 0.5) * res
        ys = self.y0 + (np.arange(self.ny) + 0.5) * res
        X, Y = np.meshgrid(xs, ys)
        pts = np.c_[X.ravel(), Y.ravel()]
        muni = np.full(len(pts), -1, dtype=np.int16)
        for m, poly in enumerate(self.polys):
            lo, hi = poly.min(0), poly.max(0)
            box = np.where((pts[:, 0] >= lo[0]) & (pts[:, 0] <= hi[0]) &
                           (pts[:, 1] >= lo[1]) & (pts[:, 1] <= hi[1]) & (muni < 0))[0]
            inside = Path(poly).contains_points(pts[box])
            muni[box[inside]] = m
        self.muni_flat = muni
        self.cells = np.where(muni >= 0)[0]
        self.Nm = np.bincount(muni[self.cells], minlength=self.M).astype(float)
        if (self.Nm == 0).any():
            raise ValueError("マスを1つも持たない市町村があります. raster_m を小さくしてください")

        # 充電ステーション
        st = sc["stations"]
        if st.get("points"):
            self.stations = np.asarray(st["points"], float)
        else:
            rng = np.random.default_rng(0)
            sample = pts[self.cells[rng.choice(len(self.cells), min(20000, len(self.cells)),
                                               replace=False)]]
            cent = sample[rng.choice(len(sample), st["count"], replace=False)]
            for _ in range(50):
                lab = np.argmin(((sample[:, None] - cent[None]) ** 2).sum(-1), axis=1)
                cent = np.array([sample[lab == k].mean(0) if (lab == k).any() else cent[k]
                                 for k in range(len(cent))])
            self.stations = cent
        self._disk = {}

    # --- 座標とマス
    def cell_of(self, p):
        j = int((p[0] - self.x0) // self.res)
        i = int((p[1] - self.y0) // self.res)
        if 0 <= i < self.ny and 0 <= j < self.nx:
            return i * self.nx + j
        return -1

    def cell_xy(self, flat):
        i, j = np.divmod(np.asarray(flat), self.nx)
        return np.c_[self.x0 + (j + 0.5) * self.res, self.y0 + (i + 0.5) * self.res]

    def muni_at(self, p):
        c = self.cell_of(p)
        return int(self.muni_flat[c]) if c >= 0 else -1

    def nearest_station(self, p):
        d = np.sqrt(((self.stations - p) ** 2).sum(1))
        k = int(np.argmin(d))
        return k, float(d[k])

    def disk(self, r):
        if r not in self._disk:
            k = int(np.ceil(r / self.res))
            ii, jj = np.mgrid[-k:k + 1, -k:k + 1]
            m = (ii * self.res) ** 2 + (jj * self.res) ** 2 <= r ** 2
            self._disk[r] = np.c_[ii[m], jj[m]]
        return self._disk[r]

    def swath(self, p0, p1, r):
        """p0 → p1 を半径 r で掃いたときに見えるマス (地域内のみ, flat index)"""
        L = float(np.hypot(*(p1 - p0)))
        n = max(2, int(np.ceil(L / max(r * 0.5, self.res))) + 1)
        pts = p0 + (p1 - p0) * np.linspace(0, 1, n)[:, None]
        ci = ((pts[:, 1] - self.y0) // self.res).astype(int)
        cj = ((pts[:, 0] - self.x0) // self.res).astype(int)
        off = self.disk(r)
        ii = (ci[:, None] + off[None, :, 0]).ravel()
        jj = (cj[:, None] + off[None, :, 1]).ravel()
        ok = (ii >= 0) & (ii < self.ny) & (jj >= 0) & (jj < self.nx)
        flat = np.unique(ii[ok] * self.nx + jj[ok])
        return flat[self.muni_flat[flat] >= 0]


# ------------------------------------------------------------------ 評価
def score_parts(world, covered, A, B):
    cov = np.bincount(world.muni_flat[world.cells[covered[world.cells]]],
                      minlength=world.M) / world.Nm
    rc = np.minimum(1, cov / world.req_cov)
    ra = np.minimum(1, A / world.req_a)
    rb = np.minimum(1, B / world.req_b)
    score = float((rc + ra + rb).sum() / (3 * world.M))
    met = int((cov >= world.req_cov - 1e-9).sum() + (A >= world.req_a).sum() + (B >= world.req_b).sum())
    return score, cov, met
