import type { MapEdge, MapNode } from "../data/event";

export type Route = { path: string[]; distance: number };

const dist = (a: MapNode, b: MapNode) => Math.hypot(a.x - b.x, a.y - b.y);

/** ダイクストラ法で最短経路を求める。avoidStairs で階段のある辺を除外する。 */
export function shortestPath(
  nodes: MapNode[],
  edges: MapEdge[],
  from: string,
  to: string,
  opts: { avoidStairs?: boolean } = {},
): Route | null {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  if (!byId.has(from) || !byId.has(to)) return null;

  const adj = new Map<string, { to: string; w: number }[]>();
  for (const e of edges) {
    if (opts.avoidStairs && e.stairs) continue;
    const w = dist(byId.get(e.a)!, byId.get(e.b)!);
    adj.set(e.a, [...(adj.get(e.a) ?? []), { to: e.b, w }]);
    adj.set(e.b, [...(adj.get(e.b) ?? []), { to: e.a, w }]);
  }

  const best = new Map<string, number>([[from, 0]]);
  const prev = new Map<string, string>();
  const done = new Set<string>();
  while (true) {
    let cur: string | null = null;
    for (const [id, d] of best) if (!done.has(id) && (cur === null || d < best.get(cur)!)) cur = id;
    if (cur === null) return null;
    if (cur === to) break;
    done.add(cur);
    for (const { to: nxt, w } of adj.get(cur) ?? []) {
      const nd = best.get(cur)! + w;
      if (nd < (best.get(nxt) ?? Infinity)) {
        best.set(nxt, nd);
        prev.set(nxt, cur);
      }
    }
  }

  const path = [to];
  while (path[0] !== from) path.unshift(prev.get(path[0])!);
  return { path, distance: best.get(to)! };
}

/** 地図座標の距離を徒歩分数に換算（1px ≒ 0.25m, 徒歩 60m/分 + 案内余裕） */
export function walkMinutes(distance: number): number {
  return Math.max(1, Math.round((distance * 0.25) / 60 + 0.5));
}
