// 会場マップの「形」（開発担当が管理）。
// エリアの名前・説明・ブース名はキャストが content/venue.yaml で編集する。
// SVG座標系 (0..360 x 0..520)。node はルート検索用のグラフ頂点。

export type ZoneType = "hall" | "room" | "booth" | "food" | "service" | "lounge";

export type ZoneLayout = { id: string; type: ZoneType; x: number; y: number; w: number; h: number; nodeId: string };

export const ZONE_LAYOUT: ZoneLayout[] = [
  { id: "main", type: "hall", x: 20, y: 20, w: 320, h: 150, nodeId: "n_main" },
  { id: "studioA", type: "room", x: 20, y: 200, w: 110, h: 80, nodeId: "n_studioA" },
  { id: "studioB", type: "room", x: 20, y: 290, w: 110, h: 70, nodeId: "n_studioB" },
  { id: "lounge", type: "lounge", x: 230, y: 200, w: 110, h: 110, nodeId: "n_lounge" },
  { id: "booths", type: "booth", x: 150, y: 200, w: 60, h: 160, nodeId: "n_booths" },
  { id: "food", type: "food", x: 230, y: 320, w: 110, h: 60, nodeId: "n_food" },
  { id: "lobby", type: "service", x: 100, y: 410, w: 160, h: 90, nodeId: "n_lobby" },
  { id: "wc", type: "service", x: 20, y: 380, w: 60, h: 50, nodeId: "n_wc" },
  { id: "first_aid", type: "service", x: 290, y: 410, w: 50, h: 50, nodeId: "n_aid" },
];

/** 展示ブースの枠（B1〜B6）。マップ上の縦位置 */
export const BOOTH_SLOTS: Record<string, number> = { B1: 215, B2: 240, B3: 265, B4: 290, B5: 315, B6: 340 };

export type MapNode = { id: string; x: number; y: number };
export type MapEdge = { a: string; b: string; stairs?: boolean };

export const NODES: MapNode[] = [
  { id: "n_lobby", x: 180, y: 420 },
  { id: "n_hub", x: 180, y: 390 },
  { id: "n_west", x: 140, y: 390 },
  { id: "n_east", x: 220, y: 390 },
  { id: "n_corrW", x: 140, y: 245 },
  { id: "n_corrE", x: 220, y: 245 },
  { id: "n_top", x: 180, y: 185 },
  { id: "n_main", x: 180, y: 170 },
  { id: "n_studioA", x: 130, y: 240 },
  { id: "n_studioB", x: 130, y: 325 },
  { id: "n_booths", x: 180, y: 360 },
  { id: "n_lounge", x: 230, y: 255 },
  { id: "n_food", x: 230, y: 350 },
  { id: "n_wc", x: 80, y: 405 },
  { id: "n_aid", x: 290, y: 435 },
];

export const EDGES: MapEdge[] = [
  { a: "n_lobby", b: "n_hub" },
  { a: "n_hub", b: "n_west" },
  { a: "n_hub", b: "n_east" },
  { a: "n_hub", b: "n_booths" },
  { a: "n_west", b: "n_studioB" },
  { a: "n_west", b: "n_corrW" },
  { a: "n_west", b: "n_wc" },
  { a: "n_studioB", b: "n_corrW" },
  { a: "n_corrW", b: "n_studioA" },
  { a: "n_corrW", b: "n_top" },
  { a: "n_east", b: "n_food" },
  { a: "n_east", b: "n_corrE" },
  { a: "n_food", b: "n_corrE" },
  { a: "n_corrE", b: "n_lounge" },
  { a: "n_corrE", b: "n_top" },
  { a: "n_top", b: "n_main" },
  { a: "n_lobby", b: "n_aid" },
  // 展示ブース中央を抜ける近道（階段あり）
  { a: "n_booths", b: "n_top", stairs: true },
];
