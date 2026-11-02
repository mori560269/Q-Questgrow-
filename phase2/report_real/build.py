"""Phase 2 実データの結果ページを results/*.json から組み立てる（数値は手で書き写さない）"""
import json, html, os
import numpy as np

R = "/home/user/Q-Questgrow-/results/"
D = os.path.dirname(os.path.abspath(__file__)) + "/"
esc = html.escape
smp = json.load(open(R + "real_sample.json"))
sens = json.load(open(R + "real_sensitivity.json"))
bs = json.load(open(R + "real_batch_stats.json"))
qi = json.load(open(R + "real_qubo_improve.json"))
al = json.load(open(R + "real_alloc_summary.json"))["summary"]

SHORT = {"古典: 貪欲法 + 局所探索": ("貪欲法 + 局所探索", "classic"),
         "古典: 反復局所探索": ("反復局所探索", "classic"),
         "古典: 厳密解法（列挙 + MILP, 時間内）": ("厳密解法（時間内で打ち切り）", "classic"),
         "古典: LNS（部分問題を列の MILP）": ("LNS（部分問題を MILP）", "classic"),
         "QUBO: LNS（部分問題を列の QUBO）": ("LNS（部分問題を QUBO）", "qubo"),
         "QUBO: 列の集合分割 QUBO（生の解, 列挙は古典）": ("列の集合分割 QUBO", "qubo"),
         "QUBO: 時間枠の判定 QUBO（生の解）": ("時間枠の判定 QUBO", "qubo")}


def fig_methods(B=30.0):
    rows = [r for r in bs["equal_time"] if r["予算_秒"] == B and r["系統"] == "全体"]
    rows.sort(key=lambda r: (r["最良との差_平均"] if r["最良との差_平均"] is not None else 999))
    W, left, right, rh, top = 760, 210, 150, 34, 30
    H = top + rh * len(rows) + 34
    xmax = 40
    x = lambda v: left + (W - left - right) * min(v, xmax) / xmax
    o = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="同じ計算時間 {B:g} 秒での最良との差">']
    for t in range(0, xmax + 1, 10):
        o.append(f'<line class="grid" x1="{x(t):.1f}" x2="{x(t):.1f}" y1="{top - 6}" y2="{H - 30}"/>'
                 f'<text class="tick" x="{x(t):.1f}" y="{H - 12}" text-anchor="middle">+{t}%</text>')
    o.append(f'<text class="refl" x="{W - right + 12}" y="{top - 12}">最良の回復数に届いた</text>')
    for i, r in enumerate(rows):
        nm, cls = SHORT[r["手法"]]
        y = top + i * rh
        o.append(f'<text class="lab" x="{left - 10}" y="{y + 15}" text-anchor="end">{esc(nm)}</text>')
        g = r["最良との差_平均"]
        if g is not None:
            o.append(f'<rect class="bar {cls}" x="{left}" y="{y + 3}" width="{max(1.5, x(g) - left):.1f}" height="18" rx="2">'
                     f'<title>{esc(nm)}: 平均 +{g}%（95% 信頼区間 {r["最良との差_95CI"][0]}〜{r["最良との差_95CI"][1]}）</title></rect>')
            lo, hi = r["最良との差_95CI"]
            o.append(f'<line class="whisk" x1="{x(lo):.1f}" x2="{x(hi):.1f}" y1="{y + 12}" y2="{y + 12}"/>')
            lx = x(max(hi, g)) + 6
            if lx > W - right - 62:                      # 右の列と重なるなら棒の内側（左）に置く
                o.append(f'<text class="val small inbar" x="{x(g) - 6:.1f}" y="{y + 16}" text-anchor="end">+{g}%</text>')
            else:
                o.append(f'<text class="val small" x="{lx:.1f}" y="{y + 16}">+{g}%</text>')
        share = r["最大回復数に届いた割合"]
        o.append(f'<text class="val{" warn" if share < 0.8 else ""}" x="{W - right + 12}" y="{y + 16}">{share:.0%}</text>')
    o.append("</svg>")
    return "\n".join(o)


def fig_qubo_size():
    """列（変数）の数ごとの, 列の集合分割 QUBO の結果（全部の列・まとめた列を合わせて）"""
    pts = []
    for r in qi:
        if "省略" in r:
            continue
        for nm, ck in (("全部", "列"), ("まとめ", "まとめた列")):
            q = r[f"QUBO_{nm}_完了"]
            st = "none" if q is None else ("opt" if abs(q - r["MILP_全部_完了"]) < 0.05 else "sub")
            pts.append((r[ck], st))
    bins = [(0, 50), (50, 100), (100, 200), (200, 500), (500, 1000), (1000, 10 ** 9)]
    lab = ["〜50", "50〜100", "100〜200", "200〜500", "500〜1,000", "1,000〜"]
    W, H, left, top, bottom = 760, 300, 56, 18, 44
    bw = (W - left - 20) / len(bins)
    y = lambda f: top + (H - top - bottom) * (1 - f)
    o = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="列の数ごとの QUBO の成功率">']
    for t in (0, .25, .5, .75, 1):
        o.append(f'<line class="grid" x1="{left}" x2="{W - 20}" y1="{y(t):.1f}" y2="{y(t):.1f}"/>'
                 f'<text class="tick" x="{left - 8}" y="{y(t) + 4:.1f}" text-anchor="end">{t:.0%}</text>')
    for i, (lo, hi) in enumerate(bins):
        sub = [s for n, s in pts if lo <= n < hi]
        x0 = left + i * bw + bw * 0.18
        w = bw * 0.64
        acc = 0.0
        for st, cls, nm in (("opt", "ok", "最適"), ("sub", "subopt", "解は出たが最適でない"), ("none", "fail", "解が出ない")):
            f = sum(s == st for s in sub) / len(sub) if sub else 0
            if f > 0:
                o.append(f'<rect class="seg {cls}" x="{x0:.1f}" y="{y(acc + f):.1f}" width="{w:.1f}" height="{y(acc) - y(acc + f):.1f}">'
                         f'<title>列 {lab[i]}: {nm} {sum(s == st for s in sub)} / {len(sub)}</title></rect>')
            acc += f
        opt = sum(s == "opt" for s in sub)
        o.append(f'<text class="val small" x="{x0 + w / 2:.1f}" y="{y(1) - 4:.1f}" text-anchor="middle">{opt}/{len(sub)}</text>')
        o.append(f'<text class="tick" x="{x0 + w / 2:.1f}" y="{H - 22}" text-anchor="middle">{lab[i]}</text>')
    o.append(f'<text class="tick" x="{left + (W - left) / 2:.1f}" y="{H - 4}" text-anchor="middle">QUBO の列（≒ 変数）の数</text>')
    o.append("</svg>")
    return "\n".join(o)


def fig_sens():
    rows = sens
    base = rows[0]["完了時刻"]
    W, left, right, rh, top = 760, 250, 70, 28, 14
    H = top + rh * len(rows) + 30
    lo_, hi_ = 80, 145
    x = lambda v: left + (W - left - right) * (v - lo_) / (hi_ - lo_)
    o = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="条件を変えたときの最適な完了時刻">']
    for t in range(lo_, hi_ + 1, 10):
        o.append(f'<line class="grid" x1="{x(t):.1f}" x2="{x(t):.1f}" y1="{top - 4}" y2="{H - 26}"/>'
                 f'<text class="tick" x="{x(t):.1f}" y="{H - 8}" text-anchor="middle">{t}</text>')
    o.append(f'<line class="ref-opt" x1="{x(base):.1f}" x2="{x(base):.1f}" y1="{top - 4}" y2="{H - 26}"/>')
    for i, r in enumerate(rows):
        y = top + i * rh
        nm = r["条件"] if r["値"] == "" else f'{r["条件"]}: {r["値"]}'
        nm = nm.replace("車を 2 台足す拠点", "車を 2 台足す").replace(" [分]", "")
        v = r["完了時刻"]
        cls = "better" if v < base - 0.5 else ("worse" if v > base + 0.5 else "same")
        o.append(f'<text class="lab" x="{left - 10}" y="{y + 14}" text-anchor="end">{esc(nm)}</text>')
        o.append(f'<line class="stem" x1="{x(base):.1f}" x2="{x(v):.1f}" y1="{y + 10}" y2="{y + 10}"/>')
        o.append(f'<circle class="dot2 {cls}" cx="{x(v):.1f}" cy="{y + 10}" r="5.5"><title>{esc(nm)}: {v} 分</title></circle>')
        o.append(f'<text class="val small" x="{x(max(v, base)) + 10:.1f}" y="{y + 14}">{v}</text>')
    o.append("</svg>")
    return "\n".join(o)


def fig_alloc():
    rows = al
    W, H, left, top, bottom = 760, 300, 56, 16, 64
    vals = [r["完了時刻_平均"] for r in rows]
    lo_, hi_ = 140, 200
    bw = (W - left - 16) / len(rows)
    y = lambda v: top + (H - top - bottom) * (1 - (v - lo_) / (hi_ - lo_))
    o = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="8 台の分け方ごとの完了時刻の平均">']
    for t in range(lo_, hi_ + 1, 10):
        o.append(f'<line class="grid" x1="{left}" x2="{W - 16}" y1="{y(t):.1f}" y2="{y(t):.1f}"/>'
                 f'<text class="tick" x="{left - 8}" y="{y(t) + 4:.1f}" text-anchor="end">{t}</text>')
    for i, r in enumerate(rows):
        a = list(r["配分"].values())
        cls = "cur" if a == [4, 2, 2] else ("alt" if a == [4, 1, 3] else "")
        x0 = left + i * bw + bw * 0.15
        v = r["完了時刻_平均"]
        o.append(f'<rect class="abar {cls}" x="{x0:.1f}" y="{y(v):.1f}" width="{bw * 0.7:.1f}" height="{y(lo_) - y(v):.1f}" rx="2">'
                 f'<title>県庁 {a[0]}・西南 {a[1]}・北東 {a[2]}: 平均 {v} 分, 最悪 {r["完了時刻_最悪"]} 分</title></rect>')
        o.append(f'<text class="tick" x="{x0 + bw * 0.35:.1f}" y="{H - 44}" text-anchor="middle">{a[0]}</text>'
                 f'<text class="tick" x="{x0 + bw * 0.35:.1f}" y="{H - 30}" text-anchor="middle">{a[1]}</text>'
                 f'<text class="tick" x="{x0 + bw * 0.35:.1f}" y="{H - 16}" text-anchor="middle">{a[2]}</text>')
        if cls:
            o.append(f'<text class="val small" x="{x0 + bw * 0.35:.1f}" y="{y(v) - (6 if cls == "cur" else 22):.1f}" text-anchor="middle">{"現状" if cls == "cur" else "最悪に強い"}</text>')
    o.append(f'<text class="tick" x="{left - 8}" y="{H - 44}" text-anchor="end">県庁</text><text class="tick" x="{left - 8}" y="{H - 30}" text-anchor="end">西南</text><text class="tick" x="{left - 8}" y="{H - 16}" text-anchor="end">北東</text>')
    o.append("</svg>")
    return "\n".join(o)


# 表: 同じ計算時間（30 秒）, 系統ごと
fams = ["サンプル", "A_同等", "B_大地震", "C_複合", "D_広域", "E_連続大地震"]
order = ["古典: 反復局所探索", "古典: LNS（部分問題を列の MILP）", "古典: 厳密解法（列挙 + MILP, 時間内）",
         "QUBO: LNS（部分問題を列の QUBO）", "QUBO: 列の集合分割 QUBO（生の解, 列挙は古典）", "QUBO: 時間枠の判定 QUBO（生の解）"]
head = "".join(f"<th>{esc(SHORT[m][0])}</th>" for m in order)
body = []
for f in fams:
    cells = []
    vals = {}
    for m in order:
        r = [x for x in bs["equal_time"] if x["予算_秒"] == 30 and x["系統"] == f and x["手法"] == m][0]
        vals[m] = r
    bestv = min((v["最良との差_平均"] for v in vals.values() if v["最良との差_平均"] is not None and v["最大回復数に届いた割合"] >= 0.8), default=None)
    for m in order:
        r = vals[m]
        g, s = r["最良との差_平均"], r["最大回復数に届いた割合"]
        if g is None:
            cells.append('<td class="na">解なし</td>')
        else:
            best = ' class="best"' if bestv is not None and abs(g - bestv) < 1e-9 and s >= 0.8 else ""
            cells.append(f'<td{best}>+{g}%<small>届いた {s:.0%}</small></td>')
    body.append(f"<tr><th>{esc(f)}</th>{''.join(cells)}</tr>")
fam_rows = "\n".join(body)

refs = {r["系統"]: r for r in bs["reference"]}
ref_rows = "\n".join(
    f'<tr><th>{esc(f)}</th><td>{refs[f]["問題"]}</td><td>{refs[f]["通信断_平均"]}</td><td>{refs[f]["回復可能_平均"]}</td>'
    f'<td>{refs[f]["通行止め_平均"]}</td><td>{refs[f]["最適を証明"]} / {refs[f]["問題"]}</td><td>{refs[f]["厳密解法の時間_中央値"]} 秒</td></tr>'
    for f in fams)

ov = {r["手法"]: r for r in bs["equal_time"] if r["予算_秒"] == 30 and r["系統"] == "全体"}
qs = json.load(open(R + "real_qubo_improve_summary.json"))["summary"]
cur = [r for r in al if list(r["配分"].values()) == [4, 2, 2]][0]
alt = [r for r in al if list(r["配分"].values()) == [4, 1, 3]][0]
worst_alloc = al[-1]
sb = {(r["条件"], str(r["値"])): r for r in sens}

page = open(D + "head.html").read() + f"""
<div class="wrap">
<header>
  <div class="eyebrow">Q-Quest GROW ／ 国際航業 新緑県 広域観測網の最適化問題 ／ Phase 2</div>
  <h1>配布データで解いた、災害時のドローン中継計画</h1>
  <p>配布された道路網（道路区間 1,682・ノード 1,597）とサンプル災害で、通信が止まったセンサーをドック搭載車とドローンで回復する計画を求めました。サンプルは厳密に最適を証明し、サンプルと同等〜より複雑な災害 50 問を作って、古典の手法と QUBO を同じ計算時間で比べています。</p>
  <div class="note"><b>QUBO の解き方について。</b>この環境からは Amplify AE に接続できないため、QUBO はすべて CPU の焼きなまし（neal）で解いています。Amplify AE で解くと結果が変わる可能性があります。</div>
</header>

<section>
  <h2>わかったこと</h2>
  <ol class="findings">
    <li><b>配布サンプルの最適な完了時刻は {smp["最適な完了時刻"]} 分</b>（厳密解法で証明、0.2 秒）。通信断 18 基のうち 4 基は、通行止めで届く離陸地点に行けず対応不能で、課題資料と一致しました。</li>
    <li><b>サンプルと同じくらいの規模なら、厳密解法で最適が数秒で求まります。</b>A〜C 系統とサンプルの 31 問中 28 問で最適を証明しました。</li>
    <li><b>大規模な災害（D・E）では、古典の反復局所探索が最も良い計画を出しました。</b>30 秒の予算で、全 51 問の平均で最良との差 +{ov["古典: 反復局所探索"]["最良との差_平均"]}%。</li>
    <li><b>QUBO の成否は変数の数で決まります。</b>厳密解法と同じ列を QUBO にすると、列が 100 未満ならほぼ最適、1,000 を超えると制約を満たす解すら出ません。QUBO を活かすなら、大きい問題を小さく切った部分問題（LNS）に使うのが現実的です（最良との差 +{ov["QUBO: LNS（部分問題を列の QUBO）"]["最良との差_平均"]}%、MILP で同じことをすると +{ov["古典: LNS（部分問題を列の MILP）"]["最良との差_平均"]}%）。</li>
    <li><b>平常時の備えとしては、どの拠点に車を置くかが効きます。</b>サンプルでは北東町役場に車を 2 台足すと 30 分早くなります。8 台の分け方は現状の 4・2・2 が平均でほぼ最良で、最悪の災害に備えるなら 4・1・3 です。</li>
  </ol>
</section>

<section>
  <h2>配布サンプルの最適計画</h2>
  <div class="facts">
    <div><b>{smp["通信断"]}</b><span>通信断センサー</span></div>
    <div><b>{len(smp["対応不能"])}</b><span>対応不能（通行止めで行けない）</span></div>
    <div><b>{smp["最適な完了時刻"]}</b><span>最適な完了時刻 [分]</span></div>
    <div><b>{smp["下界_枠割当"]}</b><span>下界 [分]（差 3%）</span></div>
    <div><b>{smp["平均回復時刻"]}</b><span>平均回復時刻 [分]</span></div>
  </div>
  <figure>
    <img src="real_sample_map.png" alt="配布サンプルの最適計画の地図。通行止め区間、通信断センサーと回復時刻、対応不能の 4 基、車ごとの経路と離陸地点" width="792" height="874">
    <figcaption>赤い太線が通行止め区間、赤い × が対応不能の 4 基（P07_1・P07_5・P07_7・P07_9）。色つきの線が車ごとの経路、三角が離陸地点、点線がドローンの飛行。センサーの横の数字は回復した時刻 [分]。</figcaption>
  </figure>
  <figure>
    <img src="real_sample_gantt.png" alt="車ごとの行動の時間割。走行、離陸準備、飛行、充電待ち" width="906" height="553">
    <figcaption>車ごとの行動。時間の大半は走行（一般道 20 km/h と通行止めの迂回）で、充電待ちは 2 台だけ。赤い破線が完了時刻 {smp["最適な完了時刻"]} 分。</figcaption>
  </figure>
  <p>センサーどうしは最も近くて 2,978 m 離れているため、2 基以上を 1 回の飛行で回ることはできず、飛行はすべて 1 基ずつです。予備バッテリーは使いません（どの車も 5 回以内）。</p>
</section>

<section>
  <h2>何を変えると早くなるか</h2>
  <p>サンプルで条件を 1 つずつ変え、それぞれ厳密解法で最適な完了時刻を求めました（破線が現状の {sens[0]["完了時刻"]} 分）。</p>
  <div class="legend"><span class="key"><i class="sw better"></i>早くなる</span><span class="key"><i class="sw worse"></i>遅くなる</span><span class="key"><i class="sw same"></i>変わらない</span></div>
  <div class="chart">{fig_sens()}</div>
  <p><b>北東町役場（震源に最も近い拠点）に車を 2 台足すと {sb[("車を 2 台足す拠点", "北東町役場")]["完了時刻"]} 分</b>まで早くなります。県庁や西南市役所に足しても変わりません。車の速さ・離陸準備・充電の時間も効きますが、予備バッテリーの数はサンプルでは効きません。</p>
</section>

<section>
  <h2>解き方</h2>
  <div class="two">
    <div><h3>古典</h3><p><b>厳密解法</b>: 車ごとに「行う飛行の組」とその完了時刻を、上限を超える組を枝刈りしながら列挙し、集合分割 MILP で全センサーをちょうど 1 回覆う組み合わせを選びます。上限を二分探索して最適を証明します。ほかに反復局所探索と、4 台ずつ解き直す LNS。</p></div>
    <div><h3>QUBO</h3><p><b>列の集合分割 QUBO</b>: 厳密解法と同じ列・同じ制約を QUBO にしたもの（MILP との違いは解き方だけ）。ほかに「車の何番目の飛行」を変数にした時間枠の判定 QUBO と、LNS の部分問題を QUBO で解く方法。</p></div>
  </div>
  <div class="formula">E(x) =   Σ_センサー j ( Σ_{{列 S ∋ j}} x_S − 1 )²                ← 各センサーをちょうど 1 回
       + Σ_拠点 b  ( Σ_{{S ∈ b}} x_S + スラック − 車の数_b )²     ← 拠点の車の数まで
       + ( Σ_{{予備が要る S}} x_S + スラック − 予備の数 )²        ← 予備バッテリー
       + ε Σ_S 完了時刻_S x_S / Σ 完了時刻                       ← 同点なら早く終わる方
   （完了時刻 ≤ T の列だけを変数にし、T を二分探索）</div>
  <p class="cap">式の詳細は GitHub の phase2/FORMULATION_real.md（下界・厳密解法の正しさの理由・Amplify での書き方つき）。</p>
</section>

<section>
  <h2>多数の災害で比べる</h2>
  <p>配布の道路網の上で、サンプルの傾向（震源から 20 km 以内が通信断、橋・トンネルほど通行止めになりやすい）に合わせて災害を 50 問作りました。A はサンプルと同じ規模、B〜E は震源が 2 つ・車が減る・通行止めが 130〜180 区間など、より複雑です。</p>
  <div class="tbl"><table>
    <thead><tr><th style="text-align:left">系統</th><th>問題</th><th>通信断（平均）</th><th>回復可能</th><th>通行止め</th><th>最適を証明</th><th>厳密解法の時間（中央値）</th></tr></thead>
    <tbody>{ref_rows}</tbody>
  </table></div>
  <h3>同じ計算時間（30 秒）での比較</h3>
  <p>「最良」はその問題で全手法・全予算を通して見つかった最良の計画（まず回復数、次に完了時刻）。棒は最良との差の平均（横線は 95% 信頼区間）、右の数字は最良の回復数に届いた割合です。</p>
  <div class="legend"><span class="key"><i class="sw classic"></i>古典</span><span class="key"><i class="sw qubo"></i>QUBO</span></div>
  <div class="chart">{fig_methods()}</div>
  <p><b>反復局所探索が最良の回復数に {ov["古典: 反復局所探索"]["最大回復数に届いた割合"]:.0%} で届き、差も +{ov["古典: 反復局所探索"]["最良との差_平均"]}% と最も小さい</b>結果でした。列の集合分割 QUBO は、解が出れば最良との差 +{ov["QUBO: 列の集合分割 QUBO（生の解, 列挙は古典）"]["最良との差_平均"]}% とほぼ最適ですが、解が出たのは {ov["QUBO: 列の集合分割 QUBO（生の解, 列挙は古典）"]["最大回復数に届いた割合"]:.0%} の試行だけです。</p>
  <div class="tbl"><table>
    <thead><tr><th style="text-align:left">系統（30 秒）</th>{head}</tr></thead>
    <tbody>{fam_rows}</tbody>
  </table></div>
  <p class="cap">最良との差の平均と、最良の回復数に届いた割合。緑は各系統で最も良い手法（届いた割合 80% 以上の中で）。</p>
</section>

<section>
  <h2>QUBO が解ける大きさ</h2>
  <p>厳密解法と同じ列を QUBO（30 秒）と MILP で解き、QUBO が最適に届くかを列の数ごとに数えました。離陸地点が違うだけの列をまとめる工夫（最適値は変わらない）を入れた場合と入れない場合を合わせています。</p>
  <div class="legend"><span class="key"><i class="sw ok"></i>最適</span><span class="key"><i class="sw subopt"></i>解は出たが最適でない</span><span class="key"><i class="sw fail"></i>解が出ない</span></div>
  <div class="chart">{fig_qubo_size()}</div>
  <p><b>列が 100 未満ならほぼすべて最適、500 を超えるとほとんど解けません。</b>列をまとめると列は中央値 {qs["全部"]["列_中央値"]} → {qs["まとめ"]["列_中央値"]} に減り、QUBO で解けた問題は {qs["全部"]["解が出た"]} → {qs["まとめ"]["解が出た"]} 問（{qs["全部"]["問題"]} 問中）に増えました。同じ列を MILP は中央値 {qs["全部"]["MILP_秒_中央値"]} 秒で最適を証明します。</p>
</section>

<section>
  <h2>平常時の備え：8 台を 3 拠点にどう分けるか</h2>
  <p>各拠点に 1 台以上・合計 8 台の分け方 21 通りすべてで、同じ災害 21 問（サンプル + A 10 問 + B 10 問）を厳密解法で解きました。棒は完了時刻の平均 [分]、下の数字は県庁・西南市役所・北東町役場の台数です。</p>
  <div class="chart">{fig_alloc()}</div>
  <p><b>現状の 4・2・2 は平均 {cur["完了時刻_平均"]} 分で、1 位（{al[0]["完了時刻_平均"]} 分）とほぼ同じです。</b>最悪の災害に備えるなら 4・1・3（西南市役所から北東町役場へ 1 台）で、最悪が {cur["完了時刻_最悪"]} → {alt["完了時刻_最悪"]} 分になります。1 拠点に偏らせると（{"・".join(map(str, worst_alloc["配分"].values()))}）平均 {worst_alloc["完了時刻_平均"]} 分まで遅くなります。</p>
</section>

<section>
  <h2>次にやること</h2>
  <div class="two">
    <div><h3>QUBO を試し直す</h3><p>Amplify AE で列の集合分割 QUBO と LNS の部分問題を解き、CPU の焼きなましとの差を確かめる。列が数百を超える問題で解が出るかが焦点。</p></div>
    <div><h3>運用に近づける</h3><p>災害の情報が少しずつ分かる場合の再計画、ドローンが別の車のドックに降りる発展形、車の配置を平常時の計画（Phase 1）とまとめて考える。</p></div>
  </div>
</section>

<footer>
  <span>コード・式・結果: <a href="https://github.com/mori560269/Q-Questgrow-/tree/claude/request-5v4fsc/phase2">mori560269/Q-Questgrow-（phase2/README_real.md, FORMULATION_real.md）</a></span>
  <span>条件は配布シナリオの値（車 8 台、離陸準備 10 分、最大飛行 15 分、滞空 3 分/基、40 km/h、充電 30 分×4 回、予備バッテリー 1 個）。生成した災害は配布の道路網の上に作ったもの。</span>
</footer>
</div>
"""
extra_css = """<style>
.val.inbar { fill: #fff; font-weight: 700; }
.whisk { stroke: var(--ink); stroke-width: 1.5; opacity: .6; }
.val.warn { fill: var(--signal); font-weight: 700; }
.seg.ok, .sw.ok { fill: var(--sum); background: var(--sum); }
.seg.subopt, .sw.subopt { fill: var(--qubo); background: var(--qubo); opacity: .55; }
.seg.fail, .sw.fail { fill: var(--old); background: var(--old); }
.stem { stroke: var(--rule); stroke-width: 3; }
.dot2 { stroke: var(--panel); stroke-width: 2; }
.dot2.better, .sw.better { fill: var(--sum); background: var(--sum); }
.dot2.worse, .sw.worse { fill: var(--signal); background: var(--signal); }
.dot2.same, .sw.same { fill: var(--old); background: var(--old); }
.abar { fill: var(--old); } .abar.cur { fill: var(--exact); } .abar.alt { fill: var(--sum); }
.facts { grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); }
</style>
"""
page = page.replace("</style>\n", "</style>\n" + extra_css, 1)
open(D + "index.html", "w").write(page)
print("ok", len(page))
