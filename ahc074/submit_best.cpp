// nest + 上掛け商品を模擬計算の地紙手数で選ぶ
#include <bits/stdc++.h>
// timer.hpp — 実時間タイマーと「仮想時計」
//
// 仮想時計: 処理ごとに決めた料金（ns）を足し上げ、その合計で打ち切りなどの判断をする。
// どの機械・どの負荷でも同じ入力なら同じ出力になるので、
//   - 手元とジャッジの速さの差、並列実行の負荷で結果が揺れない
//   - 0.01% 単位の改善でも比較できる
// ビルド時に -DAHC_VIRTUAL_CLOCK を付けると仮想時計、付けなければ実時間で動く。
// 実時間は常に「非常時の打ち切り」として併用する（仮想時計の料金がずれても TLE しない）。
//
// 使い方:
//   Timer T(1.85);                // 制限秒（実時間の安全線）
//   while (!T.over(1.80)) {       // 判断に使う線（仮想 or 実時間）
//       T.tick(COST_NEIGHBOR);    // 1 回の近傍評価の料金を払う（実時間モードでは何もしない）
//       ...
//   }
//   double p = T.progress(1.80);  // 焼きなましの温度などに使う 0..1

#include <chrono>
#include <cstdint>

#ifndef AHC_NS_PER_UNIT
#define AHC_NS_PER_UNIT 1.0  // 料金 1 単位 = 何 ns とみなすか（ジャッジで実測して合わせる）
#endif

struct Timer {
    using clk = std::chrono::steady_clock;
    clk::time_point start;
    double hard_limit_sec;
    uint64_t units = 0;
    uint32_t check_counter = 0;
    bool hard_hit = false;

    explicit Timer(double hard_limit_sec_) : start(clk::now()), hard_limit_sec(hard_limit_sec_) {}

    double real_sec() const {
        return std::chrono::duration<double>(clk::now() - start).count();
    }
    inline void tick(uint64_t cost = 1) {
#ifdef AHC_VIRTUAL_CLOCK
        units += cost;
#else
        (void)cost;
#endif
    }
    // 判断に使う経過秒
    double sec() const {
#ifdef AHC_VIRTUAL_CLOCK
        return units * AHC_NS_PER_UNIT * 1e-9;
#else
        return real_sec();
#endif
    }
    // limit_sec を超えたか（実時間の安全線も見る。実時間の確認は 256 回に 1 回）
    bool over(double limit_sec) {
        if (hard_hit) return true;
        if ((++check_counter & 255) == 0 && real_sec() > hard_limit_sec) {
            hard_hit = true;
            return true;
        }
        return sec() > limit_sec;
    }
    double progress(double limit_sec) const {
        double p = sec() / limit_sec;
        return p < 0 ? 0 : (p > 1 ? 1 : p);
    }
};

// ローカル専用ログ（提出時は消える）
#ifdef AHC_LOCAL
#include <cstdio>
#define LOG(...) std::fprintf(stderr, __VA_ARGS__)
#else
#define LOG(...) ((void)0)
#endif

using namespace std;
typedef unsigned long long u64;

#ifndef NPORT
#define NPORT 43
#endif
#ifndef SLOPE
#define SLOPE 1.0
#endif
#ifndef EXPO
#define EXPO 1.5
#endif
#ifndef PPSORT
#define PPSORT 1
#endif
#ifndef COLSW
#define COLSW 200000
#endif
#ifndef XBIAS
#define XBIAS 0
#endif
#ifndef OUTSW
#define OUTSW 0
#endif
#ifndef WX
#define WX 1.0
#endif
#ifndef KEEPX
#define KEEPX 0
#endif
#ifndef PORTSIM
#define PORTSIM 0
#endif
#ifndef PEVERY
#define PEVERY 40
#endif
#ifndef PWW
#define PWW 1.0
#endif

int N, K, P, R;
vector<string> A;
vector<u64> OPQ, BLK, TG;
vector<int> ord_;          // 上から順の紙番号
vector<int> kind;          // 0: 1マス紙, 1: 上掛け, 2: 全部穴
vector<int> pixWin, pixCol;  // 1マス紙の窓と色
vector<int> ovTarget, ovPort; // 上掛けの商品・ポート
vector<int> ovOf;          // 商品 -> 上掛け紙（なければ -1）
vector<int> isPort;
vector<vector<int>> portOv;  // 未使用（参考）
int raised = -1;
vector<int> parkA;
#ifndef PIXSORT
#define PIXSORT 1
#endif
vector<double> bfreq;
int GROUND = -1;           // 一番上に出している上掛け
string opsOut; int opsCnt;

int posOf(int k) { for (int i = 0; i < (int)ord_.size(); i++) if (ord_[i] == k) return i; return -1; }
bool visible(int k) {
    u64 ex = OPQ[k];
    for (int i = 0; i < (int)ord_.size() && ord_[i] != k; i++) ex &= ~OPQ[ord_[i]];
    return ex != 0;
}
// 紙 k を抜いて、抜いた後の並びの d 番目に入れる
bool SIMM = false;
void mv(int k, int d) {
    if (!SIMM) assert(visible(k));
    int p = posOf(k);
    ord_.erase(ord_.begin() + p);
    ord_.insert(ord_.begin() + d, k);
    if (!SIMM) opsOut += to_string(k) + " " + to_string(d) + "\n";
    opsCnt++;
    parkA[k] = -2;
}
u64 display(int ex = -1) {
    u64 cov = 0, b = 0;
    for (int k : ord_) { if (k == ex) continue; b |= BLK[k] & ~cov; cov |= OPQ[k]; }
    return b;
}
// 窓 j で一番上の紙
int topAt(int j) { for (int k : ord_) if (OPQ[k] >> j & 1) return k; return -1; }
int colorAt(int k, int j) { return BLK[k] >> j & 1; }
// ポート p の上掛け（並び順）
vector<int> portStack(int p) {
    vector<int> v;
    for (int k : ord_) if (kind[k] == 1 && k != raised && ovPort[k] == p) v.push_back(k);
    return v;
}
int portFront(int p) { for (int k : ord_) if (kind[k] == 1 && k != raised && ovPort[k] == p) return k; return -1; }
// 上掛けをポートの列に戻す（色が交互になる位置へ）
void putBack(int k) {
    int p = ovPort[k];
    // 抜いた後の位置で考える
    int c = colorAt(k, p);
    vector<int> st;
    for (int x : ord_) if (x != k && kind[x] == 1 && ovPort[x] == p) st.push_back(x);
    // 末尾の色が c と違えば末尾の後ろ、先頭の色が c と違えば先頭の前
    int d;
    auto idxAfterRemoval = [&](int x) { int i = posOf(x); return i > posOf(k) ? i - 1 : i; };
    if (st.empty()) d = (int)ord_.size() - 1;
    else if (colorAt(st.back(), p) != c) d = idxAfterRemoval(st.back()) + 1;
    else d = idxAfterRemoval(st.front());
    mv(k, d);
}
// ポート p の色を変える（先頭を列の末尾の後ろへ）
int portBackPos(int p) { for (int i = (int)ord_.size() - 1; i >= 0; i--) { int k = ord_[i]; if (kind[k] == 1 && k != raised && ovPort[k] == p) return i; } return -1; }
void portFlip(int p) {
    int x = portFront(p);
    int d = portBackPos(p);  // 抜くと last の位置が 1 つ前にずれるので、その後ろ = 元の posOf(last)
    mv(x, d);
}
void pixFlip(int j) {
    int a = topAt(j);
    assert(kind[a] == 0);
    int b = (a % 2 == 0) ? a + 1 : a - 1;  // 相方
    int d = posOf(b);  // 抜くと b が 1 つ前にずれる -> その直後 = 元の posOf(b)
    if (posOf(b) < posOf(a)) d = posOf(b) + 1;
    mv(a, d);
}

#ifndef PT
#define PT 2
#endif
int dispCol(int j) { return colorAt(topAt(j), j); }
void unpark(int h, u64 tgt) {
    int c = ovPort[h], t = tgt >> c & 1, cc = colorAt(h, c);
    vector<int> st; for (int x : ord_) if (x != h && kind[x] == 1 && ovPort[x] == c) st.push_back(x);
    int pk = posOf(h);
    auto after = [&](int x) { int i = posOf(x); return i > pk ? i - 1 : i; };
    mv(h, (t == cc) ? after(st.front()) : after(st.back()) + 1);
}
// ポート lo.. を目標に合わせる。列 c の先頭を前の列の前へ「駐車」してポート (a,c] をまとめて合わせる
#ifndef PTF
#define PTF 0
#endif
#ifndef PT2
#define PT2 1
#endif
#ifndef PT3
#define PT3 1
#endif
int gPT = PT, gPT2 = PT2, gPT3 = PT3, gDir = 0;
void parkTo(int h, int j, int c) {
    int d = -1, i2 = 0; bool stg = false;
    for (int x : ord_) { if (x == h) continue; if (kind[x] == 0 || kind[x] == 3) stg = true; if (stg && kind[x] == 1 && parkA[x] == -2 && ovPort[x] > j && ovPort[x] < c) { d = i2; break; } i2++; }
    mv(h, d); parkA[h] = j;
}
// 浮いた上掛け h を、列へ戻す代わりに駐車できれば駐車する（同じ 1 手）
bool tryParkLoose(int h, int lo, u64 tgt) {
#if PT3 < 100
    int c = ovPort[h];
    if (colorAt(h, c) != (int)(tgt >> c & 1)) return false;
    vector<int> pc(NPORT, 0);
    for (int k : ord_) if (kind[k] == 1 && k != h && parkA[k] != -2) for (int i = parkA[k] + 1; i <= ovPort[k]; i++) pc[i] = 1;
    int j = c - 1;
    while (j >= lo && !pc[j] && colorAt(h, j) == (int)(tgt >> j & 1)) j--;
    if (j >= c - 1) return false;
    int gain = 0;
    u64 D = display(h) ^ tgt;
    for (int i = j + 1; i < c; i++) gain += D >> i & 1;
    if (gain < gPT3) return false;
    parkTo(h, j, c);
    return true;
#else
    return false;
#endif
}
long long SP[8];
void fixPorts(int lo, u64 tgt) {
#ifdef STAT
    if (lo == 0) { SP[0]++; SP[1] += __builtin_popcountll((display() ^ tgt) & ((1ULL << NPORT) - 1)); }
#endif
    vector<int> cov(NPORT, 0), pcov(NPORT, 0), pend(NPORT, -1);
    vector<int> pk; for (int k : ord_) if (kind[k] == 1 && parkA[k] != -2) pk.push_back(k);
    auto T = [&](int j) { return (int)(tgt >> j & 1); };
    for (int k : pk) {
        int c = ovPort[k], a = parkA[k];
        if (a + 1 < lo) {
#if KEEPX
            for (int j = lo; j <= c; j++) cov[j] = 1;
#endif
            continue;
        }
        bool ok = true; for (int j = a + 1; j <= c; j++) if (colorAt(k, j) != T(j)) ok = false;
        if (ok) { for (int j = a + 1; j <= c; j++) cov[j] = 1; }
        else { pend[c] = k; for (int j = a + 1; j <= c; j++) pcov[j] = 1; }
    }
    auto parkAt = [&](int h, int j, int c) {
        parkTo(h, j, c);
        for (int i = j + 1; i <= c; i++) cov[i] = 1;
    };
    u64 D0 = display() ^ tgt;
    for (int c = NPORT - 1; c >= lo; c--) if (pend[c] >= 0) {
            int h = pend[c], a = parkA[h];
            for (int i = a + 1; i <= c; i++) pcov[i] = 0;
            if (colorAt(h, c) == T(c)) {
                int j = c - 1;
                while (j >= lo && !cov[j] && !pcov[j] && colorAt(h, j) == T(j)) j--;
                int gain = 0;
                for (int i = j + 1; i < c; i++) { gain += (i > a) ? colorAt(portFront(i), i) != T(i) : (int)(D0 >> i & 1); }
                if (j < c - 1 && gain >= gPT2) { parkAt(h, j, c);
#ifdef STAT
                    if (lo == 0) SP[2]++;
#endif
                    continue; }
            }
            unpark(h, tgt);
#ifdef STAT
            if (lo == 0) SP[3]++;
#endif
    }
#if PT < 100
    D0 = display() ^ tgt;
    if (gDir == 3) {
        int n = NPORT - lo;
        vector<int> f(n + 1, 1 << 29), from(n + 1, -2), hf(n + 1, 0);
        f[0] = 0;
        for (int c = lo; c < NPORT; c++) {
            int i = c - lo;
            int base = f[i] + (cov[c] ? 0 : (int)(D0 >> c & 1));
            if (base < f[i + 1]) { f[i + 1] = base; from[i + 1] = -1; }
            if (cov[c]) continue;
            vector<int> st = portStack(c);
            int fl = colorAt(st[0], c) != T(c);
            int h = st[fl];
            int j = c - 1;
            while (j >= lo && !cov[j] && colorAt(h, j) == T(j)) {
                int v = f[j - lo] + 1 + fl;
                if (v < f[i + 1]) { f[i + 1] = v; from[i + 1] = j - 1; hf[i + 1] = fl; }
                j--;
            }
        }
        vector<array<int,3>> ps;
        for (int i = n; i > 0; ) {
            if (from[i] == -1) { i--; continue; }
            int c = lo + i - 1, j = from[i];
            ps.push_back({c, j, hf[i]});
            i = j + 1 - lo;
        }
        for (auto [c, j, fl] : ps) {
            vector<int> st = portStack(c);
            int h = st[fl];
            if (fl) portFlip(c);
            parkAt(h, j, c);
        }
    } else
    if (gDir == 2) {
        while (true) {
            int bg = -1, bc = -1, bj = -1, bf = 0;
            for (int c = NPORT - 1; c >= lo; c--) {
                if (cov[c]) continue;
                vector<int> st = portStack(c);
                int fl = colorAt(st[0], c) != T(c);
                int h = st[fl];
                int j = c - 1;
                while (j >= lo && !cov[j] && colorAt(h, j) == T(j)) j--;
                int gain = 0; for (int i = j + 1; i < c; i++) gain += D0 >> i & 1;
                if (gain >= gPT && gain > bg) { bg = gain; bc = c; bj = j; bf = fl; }
            }
            if (bc < 0) break;
            vector<int> st = portStack(bc);
            int h = st[bf];
            if (bf) portFlip(bc);
            parkAt(h, bj, bc);
        }
    } else
    for (int ci = 0; ci < NPORT - lo; ci++) {
        int c = gDir ? lo + ci : NPORT - 1 - ci;
        if (cov[c]) continue;
        int h0 = -1, h1 = -1;
        for (int k : ord_) if (kind[k] == 1 && k != raised && ovPort[k] == c) { if (h0 < 0) h0 = k; else { h1 = k; break; } }
        int fl = colorAt(h0, c) != T(c);
        int h = fl ? h1 : h0;
        int j = c - 1;
        while (j >= lo && !cov[j] && colorAt(h, j) == T(j)) j--;
        int gain = 0; for (int i = j + 1; i < c; i++) gain += D0 >> i & 1;
        if (gain < gPT + fl * PTF) continue;
        if (fl) portFlip(c);
        parkAt(h, j, c);
#ifdef STAT
        if (lo == 0) { SP[4]++; SP[5] += fl; SP[7] += c - j; }
#endif
    }
#endif
    D0 = display() ^ tgt;
    for (int q = lo; q < NPORT; q++) if (!cov[q] && (D0 >> q & 1)) { portFlip(q);
#ifdef STAT
        if (lo == 0) SP[6]++;
#endif
    }
}

#ifndef MG
#define MG 1
#endif
vector<int> GR, grpOf;  // 部分地紙, 窓 -> グループ
int nG;
// 白にする黒紙 k を地紙 G の下へ（同じグループの黒紙が黒の頻度の降順になる位置、上掛けより上）
void sinkPix(int k, int G) {
#if PIXSORT
    vector<int> o; for (int x : ord_) if (x != k) o.push_back(x);
    int i = find(o.begin(), o.end(), G) - o.begin() + 1;
    int g = grpOf[pixWin[k]];
    while (i < (int)o.size() && (kind[o[i]] == 3 || (kind[o[i]] == 0 && !(grpOf[pixWin[o[i]]] == g && bfreq[o[i]] < bfreq[k])))) i++;
    mv(k, i);
#else
    mv(k, posOf(G));
#endif
}
// 紙 x の直後へ地紙 G を移す（x<0 なら一番上）
void groundAfter(int G, int x) {
    int gp = posOf(G);
    int d = x < 0 ? 0 : (posOf(x) > gp ? posOf(x) : posOf(x) + 1);
    if (d != gp) mv(G, d);
}
// グループ g の計画: 返り値は手数。mode 0: 1回以内, 1: 下げて上げる
struct Plan { int cost, mode, t; };
Plan planGroup(int g, u64 tgt, vector<int>& L, int& c, int& dstar) {
    int G = GR[g];
    L.clear(); c = 0;
    bool seenG = false;
    for (int k : ord_) {
        if (k == G) { seenG = true; continue; }
        if (kind[k] == 0 && grpOf[pixWin[k]] == g) { L.push_back(k); if (!seenG) c++; }
    }
    int n = L.size();
    vector<int> x(n), pre(n + 1, 0);
    int B = 0;
    for (int i = 0; i < n; i++) { x[i] = tgt >> pixWin[L[i]] & 1; pre[i + 1] = pre[i] + !x[i]; B += x[i]; }
    auto mism = [&](int t) { return pre[t] + (B - (t - pre[t])); };
    dstar = -1;
    for (int i = c; i < n; i++) if (x[i]) dstar = i + 1;
    Plan best{INT_MAX, 0, c};
    if (dstar < 0) {
        for (int t = 0; t <= n; t++) {
            if (t < c && c == n && pre[t] == 0) continue;
            int v = (t != c) + mism(t);
            if (v < best.cost) best = {v, 0, t};
        }
    } else {
        for (int t = dstar; t <= n; t++) { int v = 1 + mism(t); if (v < best.cost) best = {v, 0, t}; }
        for (int t = 0; t < dstar; t++) {
            if (dstar == n && pre[t] == 0) continue;
            int v = 2 + mism(t);
            if (v < best.cost) best = {v, 1, t};
        }
    }
    return best;
}
// 地紙より下に要黒がない状態で、閾値 t (< c) へ上げる
void upTo(int g, u64 tgt, const vector<int>& L, int c, int t) {
    int G = GR[g];
    for (int i = t; i < c; i++) if (tgt >> pixWin[L[i]] & 1) mv(L[i], 0);
    for (int i = 0; i < t; i++) if (!(tgt >> pixWin[L[i]] & 1)) sinkPix(L[i], G);
    int deep = -1;
    for (int k : ord_) { if (k == G) break; if (kind[k] == 0 && grpOf[pixWin[k]] == g && (tgt >> pixWin[k] & 1)) deep = k; }
    groundAfter(G, deep);
}
void fixGroup(int g, u64 tgt) {
    vector<int> L; int c, dstar;
    Plan pl = planGroup(g, tgt, L, c, dstar);
    int G = GR[g];
    int t = pl.t;
    if (pl.mode == 1) {
        groundAfter(G, L[dstar - 1]);
        upTo(g, tgt, L, dstar, t);
        return;
    }
    if (t > c) groundAfter(G, L[t - 1]);
    if (t < c) { upTo(g, tgt, L, c, t); return; }
    for (int i = 0; i < t; i++) if (!(tgt >> pixWin[L[i]] & 1)) sinkPix(L[i], G);
}
int groundCost(u64 tgt) {
    int s = 0; vector<int> L; int c, dstar;
    for (int g = 0; g < nG; g++) s += planGroup(g, tgt, L, c, dstar).cost;
    return s;
}
void groundFix(u64 tgt) { for (int g = 0; g < nG; g++) fixGroup(g, tgt); }



#ifndef PW
#if PORTSIM
#define PW 0.0
#else
#define PW 3.0
#endif
#endif
// 状態を 1 度だけ読み、全商品の地紙側の手数を足す
void groundCostAll(vector<double>& acc) {
    static int Lw[8][64], Ln[8], Lc[8];
    for (int g = 0; g < nG; g++) {
        int G = GR[g]; Ln[g] = 0; Lc[g] = 0; bool seen = false;
        for (int k : ord_) {
            if (k == G) { seen = true; continue; }
            if (kind[k] == 0 && grpOf[pixWin[k]] == g) { Lw[g][Ln[g]++] = pixWin[k]; if (!seen) Lc[g]++; }
        }
    }
    int pre[66];
    u64 disp = display(), pmask = (1ULL << NPORT) - 1;
    for (int u = 0; u < P; u++) {
        u64 tgt = TG[u]; int s = 0;
        for (int g = 0; g < nG; g++) {
            int n = Ln[g], c = Lc[g], B = 0; pre[0] = 0; int dstar = -1;
            for (int i = 0; i < n; i++) { int x = tgt >> Lw[g][i] & 1; pre[i + 1] = pre[i] + !x; B += x; if (x && i >= c) dstar = i + 1; }
            int best = INT_MAX;
            if (dstar < 0) {
                for (int t = 0; t <= n; t++) {
                    if (t < c && c == n && pre[t] == 0) continue;
                    int v = (t != c) + pre[t] + (B - (t - pre[t])); if (v < best) best = v;
                }
            } else {
                for (int t = dstar; t <= n; t++) { int v = 1 + pre[t] + (B - (t - pre[t])); if (v < best) best = v; }
                for (int t = 0; t < dstar; t++) {
                    if (dstar == n && pre[t] == 0) continue;
                    int v = 2 + pre[t] + (B - (t - pre[t])); if (v < best) best = v;
                }
            }
            s += best;
        }
        acc[u] += s + PW * __builtin_popcountll((disp ^ tgt) & pmask);
    }
}
vector<int> pw;
vector<string> S;
// 設計を作る（prio の大きい商品から上掛けを割り当てる）
void build(const vector<double>& prio) {
    S.clear(); kind.clear(); pixWin.clear(); pixCol.clear(); ovTarget.clear(); ovPort.clear(); GR.clear();
    raised = -1;
    isPort.assign(N, 0);
    for (int j = 0; j < NPORT; j++) isPort[j] = 1;
    for (int j = 0; j < N; j++) if (!isPort[j]) {
        string s(N, '.'); s[j] = '1'; S.push_back(s); kind.push_back(0); pixWin.push_back(j); pixCol.push_back(1); ovTarget.push_back(-1); ovPort.push_back(-1);
    }
    {
        vector<int> np; for (int j = 0; j < N; j++) if (!isPort[j]) np.push_back(j);
        nG = MG; grpOf.assign(N, -1);
        for (int i = 0; i < (int)np.size(); i++) grpOf[np[i]] = (long long)i * nG / np.size();
        for (int g = 0; g < nG; g++) {
            string s(N, '.'); for (int j : np) if (grpOf[j] == g) s[j] = '0';
            GR.push_back(S.size()); S.push_back(s); kind.push_back(3); pixWin.push_back(-1); pixCol.push_back(-1); ovTarget.push_back(-1); ovPort.push_back(-1);
        }
        GROUND = GR[0];
    }
    int npix = S.size();
    int nov = K - npix;
    ovOf.assign(P, -1);
    int pairs = nov / 2;
    vector<vector<int>> plan(NPORT);
    vector<int> perPairs(NPORT);
    {
        double ws = 0; for (int p = 0; p < NPORT; p++) ws += 1 + SLOPE * pow(p, EXPO);
        int acc = 0; double cum = 0;
        for (int p = 0; p < NPORT; p++) { cum += (1 + SLOPE * pow(p, EXPO)) / ws * pairs; int t = (int)llround(cum); perPairs[p] = max(1, t - acc); acc += perPairs[p]; }
        perPairs[NPORT - 1] -= acc - pairs;
#if PPSORT
        sort(perPairs.begin(), perPairs.end());
#endif
    }
    vector<array<int,2>> quota(NPORT);
    for (int p = 0; p < NPORT; p++) {
        int per = 2 * perPairs[p];
        quota[p] = {(per + 1) / 2, per / 2};
    }
#ifdef PPENV
    if (getenv("PPT")) {
        string t = getenv("PPT"); for (auto& ch : t) if (ch == ',') ch = ' ';
        istringstream is(t); int tot = 0;
        for (int p = 0; p < NPORT; p++) { int n = 0; is >> n; quota[p] = {(n + 1) / 2, n / 2}; tot += n; }
        assert(tot <= nov);
    }
#endif
    vector<int> pr(P); iota(pr.begin(), pr.end(), 0);
    stable_sort(pr.begin(), pr.end(), [&](int x, int y) { return prio[x] > prio[y]; });
    for (int u : pr) {
        int bp = -1;
        for (int p = 0; p < NPORT; p++) { int c = A[u][p] - '0'; if (quota[p][c] > 0 && (bp < 0 || quota[p][c] > quota[bp][A[u][bp] - '0'])) bp = p; }
        if (bp < 0) continue;
        quota[bp][A[u][bp] - '0']--; plan[bp].push_back(u);
    }
#if COLSW
    {
        vector<int> cb(NPORT, 0); for (int u = 0; u < P; u++) for (int q = 0; q < NPORT; q++) cb[q] += A[u][q] - '0';
        // fc[u][p] = 列 p に置いたときの直しの期待数
        vector<array<double, 64>> fc(P);
        for (int u = 0; u < P; u++) { double acc = 0; for (int q = NPORT - 1; q >= 0; q--) { fc[u][q] = acc; int x = A[u][q] - '0'; acc += (x ? P - cb[q] : cb[q]) / (double)P; } }
        vector<pair<int,int>> items; // (列, 添字)
        for (int q = 0; q < NPORT; q++) for (int i = 0; i < (int)plan[q].size(); i++) items.push_back({q, i});
        mt19937 rr(99);
        int M = items.size();
#if OUTSW
        vector<int> outs; { vector<int> in(P, 0); for (int q = 0; q < NPORT; q++) for (int u : plan[q]) in[u] = 1; for (int u = 0; u < P; u++) if (!in[u]) outs.push_back(u); }
#endif
        for (int it = 0; it < COLSW; it++) {
#if OUTSW
            if (!outs.empty() && (it & 1)) {
                auto [p1, i1] = items[rr() % M]; int oi = rr() % outs.size();
                int u = plan[p1][i1], v = outs[oi];
                if (A[u][p1] != A[v][p1]) continue;
                double d = (prio[v] - WX * fc[v][p1]) - (prio[u] - WX * fc[u][p1]);
                if (d > 0) { plan[p1][i1] = v; outs[oi] = u; }
                continue;
            }
#endif
            auto [p1, i1] = items[rr() % M]; auto [p2, i2] = items[rr() % M];
            if (p1 == p2) continue;
            int u = plan[p1][i1], v = plan[p2][i2];
            if (A[u][p1] != A[v][p1] || A[u][p2] != A[v][p2]) continue;
            double d = fc[v][p1] + fc[u][p2] - fc[u][p1] - fc[v][p2];
            if (d < 0) swap(plan[p1][i1], plan[p2][i2]);
        }
    }
#endif
    for (int p = 0; p < NPORT; p++) {
        vector<int> z, o; for (int u : plan[p]) (A[u][p] == '0' ? z : o).push_back(u);
        vector<int> seq; for (size_t i = 0; i < max(z.size(), o.size()); i++) { if (i < z.size()) seq.push_back(z[i]); if (i < o.size()) seq.push_back(o[i]); }
        plan[p] = seq;
    }
    for (int p = 0; p < NPORT; p++) for (int u : plan[p]) {
        string s = A[u];
        for (int j = p + 1; j < NPORT; j++) s[j] = '.';
        ovOf[u] = S.size();
        S.push_back(s); kind.push_back(1); pixWin.push_back(-1); pixCol.push_back(-1); ovTarget.push_back(u); ovPort.push_back(p);
    }
    while ((int)S.size() < K) { S.push_back(string(N, '.')); kind.push_back(2); pixWin.push_back(-1); pixCol.push_back(-1); ovTarget.push_back(-1); ovPort.push_back(-1); }
    bfreq.assign(K, 0);
    for (int k = 0; k < K; k++) if (kind[k] == 0) for (int u = 0; u < P; u++) if (ovOf[u] < 0) bfreq[k] += A[u][pixWin[k]] - '0';
    OPQ.assign(K, 0); BLK.assign(K, 0);
    for (int k = 0; k < K; k++) { for (int j = 0; j < N; j++) { if (S[k][j] != '.') OPQ[k] |= 1ULL << j; if (S[k][j] == '1') BLK[k] |= 1ULL << j; } }
    ord_.resize(K); iota(ord_.begin(), ord_.end(), 0);
    parkA.assign(K, -2);
}

// 案 Y のポート側の実手数（浮いた上掛けの戻し + fixPorts）。状態は戻す
int yPortCost(int a) {
    vector<int> o0 = ord_, p0 = parkA; string s0 = opsOut; int c0 = opsCnt;
    u64 tgt = TG[a];
    vector<int> loose;
    for (int k : ord_) { if (kind[k] == 0 || kind[k] == 3) break; if (kind[k] == 1) loose.push_back(k); }
    for (int k : loose) {
        if (tryParkLoose(k, 0, tgt)) continue;
        int p = ovPort[k], c = colorAt(k, p), t = A[a][p] - '0';
        vector<int> st; for (int x : ord_) if (x != k && kind[x] == 1 && ovPort[x] == p) st.push_back(x);
        int pk = posOf(k);
        auto after = [&](int x) { int i = posOf(x); return i > pk ? i - 1 : i; };
        mv(k, (t == c) ? after(st.front()) : after(st.back()) + 1);
    }
    fixPorts(0, tgt);
    int r = opsCnt - c0;
    ord_ = o0; parkA = p0; opsOut = s0; opsCnt = c0;
    return r;
}
#ifndef LAS
#define LAS 6
#endif
#ifndef LAM
#define LAM 0.0
#endif
#ifndef NALT
#define NALT 8
#endif
int gLA = 0; mt19937 larng(4242);
void fixPortsLA(int lo, u64 tgt, int a) {
    if (!gLA) { fixPorts(lo, tgt); return; }
    static const int alt[][3] = {{PT, PT2, 0}, {1, PT2, 0}, {3, PT2, 0}, {100, PT2, 0}, {PT, 100, 0}, {PT, PT2, 1}, {PT, PT2, 2}, {0, PT2, 3}, {1, PT2, 2}, {3, PT2, 2}, {1, PT2, 1}, {3, PT2, 1}};
    int vs[64]; for (int i = 0; i < LAS; i++) { int v; do v = larng() % P; while (v == a); vs[i] = v; }
    vector<int> o0 = ord_, p0 = parkA; string s0 = opsOut; int c0 = opsCnt;
    vector<int> bo, bp; string bs; int bc = 0; double best = 1e18;
    for (int t = 0; t < NALT; t++) {
        ord_ = o0; parkA = p0; opsOut = s0; opsCnt = c0;
        gPT = alt[t][0]; gPT2 = alt[t][1]; gDir = alt[t][2];
        fixPorts(lo, tgt);
        gPT = PT; gPT2 = PT2; gDir = 0;
        double sc = opsCnt - c0, f = 0;
        if (LAM != 0) { for (int i = 0; i < LAS; i++) f += yPortCost(vs[i]); sc += LAM * f / LAS; }
        if (sc < best) { best = sc; bo = ord_; bp = parkA; bs = opsOut; bc = opsCnt; }
    }
    ord_ = bo; parkA = bp; opsOut = bs; opsCnt = bc;
}
long long XS[8];
long long STX[40], STY[3]; int gcY;
int serve(int a) {
    opsOut.clear(); opsCnt = 0;
    u64 tgt = TG[a];
    vector<int> ord0 = ord_, pa0 = parkA; string out0 = opsOut; int cnt0 = opsCnt;
    {
        vector<int> loose, fixedp(NPORT, 0);
        for (int k : ord_) { if (kind[k] == 0 || kind[k] == 3) break; if (kind[k] == 1) loose.push_back(k); }
        for (int k : loose) {
            if (tryParkLoose(k, 0, tgt)) continue;
            int p = ovPort[k], c = colorAt(k, p), t = A[a][p] - '0';
            vector<int> st; for (int x : ord_) if (x != k && kind[x] == 1 && ovPort[x] == p) st.push_back(x);
            int pk = posOf(k);
            auto after = [&](int x) { int i = posOf(x); return i > pk ? i - 1 : i; };
            int d = (t == c) ? after(st.front()) : after(st.back()) + 1;
            mv(k, d); fixedp[p] = 1;
        }
        fixPortsLA(0, tgt, a);
        int g0 = opsCnt; groundFix(tgt); gcY = opsCnt - g0;
    }
    int costY = opsCnt - cnt0;
#ifdef STAT
    STY[0]++; STY[1] += costY; STY[2] += gcY;
#endif
    int ov = ovOf[a];
    if (ov >= 0) {
        vector<int> ordY = ord_, paY = parkA; string outY = opsOut; int cntY = opsCnt;
        ord_ = ord0; parkA = pa0; opsOut = out0; opsCnt = cnt0;
        int p = ovPort[ov];
        {
            vector<int> loose;
            for (int k : ord_) { if (kind[k] == 0 || kind[k] == 3) break; if (kind[k] == 1) loose.push_back(k); }
            for (int k : loose) if (ovPort[k] > p) {
                if (tryParkLoose(k, p + 1, tgt)) continue;
                int pl = ovPort[k], c = colorAt(k, pl), t = A[a][pl] - '0';
                vector<int> st; for (int x : ord_) if (x != k && kind[x] == 1 && ovPort[x] == pl) st.push_back(x);
                int pk = posOf(k);
                auto after = [&](int x) { int i = posOf(x); return i > pk ? i - 1 : i; };
                mv(k, (t == c) ? after(st.front()) : after(st.back()) + 1);
            }
        }
        {
            vector<int> pk; for (int k : ord_) if (kind[k] == 1 && parkA[k] != -2 && ovPort[k] > p && parkA[k] < p) pk.push_back(k);
            for (int k : pk) {
#if KEEPX
                bool ok = true; for (int j = p + 1; j <= ovPort[k]; j++) if (colorAt(k, j) != (int)(tgt >> j & 1)) ok = false;
                if (ok) continue;
#endif
                unpark(k, tgt);
            }
        }
        vector<int> st = portStack(p);
        int depth = find(st.begin(), st.end(), ov) - st.begin();
        int xc0 = opsCnt;
        for (int t = 0; t < depth; t++) portFlip(p);
        mv(ov, 0);
        int xc1 = opsCnt;
        fixPortsLA(p + 1, tgt, a);
        int xc2 = opsCnt;
        int costX = opsCnt - cnt0;
        if (costX + XBIAS >= costY) { ord_ = ordY; parkA = paY; opsOut = outY; opsCnt = cntY; }
#ifdef STAT
        else { XS[0]++; XS[1] += xc0 - cnt0; XS[2] += xc1 - xc0; XS[3] += xc2 - xc1; XS[4] += NPORT - 1 - p; STX[0]++; STX[1] += costX; STX[2] += costY; STX[3+min(p,29)]++; return opsCnt; }
#endif
    }
    return opsCnt;
}
#ifndef SALT
#define SALT 0
#endif
int serveBest(int a) {
#if SALT
    static const int alt[][3] = {{PT, PT2, PT3}, {1, PT2, PT3}, {3, PT2, PT3}, {100, PT2, PT3}, {PT, 100, PT3}, {PT, PT2, 100}, {PT, PT2, 2}, {1, 100, PT3}, {3, 100, PT3}, {1, PT2, 100}};
    vector<int> o0 = ord_, p0 = parkA;
    vector<int> bo, bp; string bs; int bc = INT_MAX;
    for (int t = 0; t < SALT; t++) {
        ord_ = o0; parkA = p0;
        gPT = alt[t][0]; gPT2 = alt[t][1]; gPT3 = alt[t][2];
        serve(a);
        if (opsCnt < bc) { bc = opsCnt; bo = ord_; bp = parkA; bs = opsOut; }
    }
    gPT = PT; gPT2 = PT2; gPT3 = PT3;
    ord_ = bo; parkA = bp; opsOut = bs; opsCnt = bc;
    return bc;
#else
    return serve(a);
#endif
}
#ifndef HW
#define HW 0
#endif
#ifndef HB
#define HB 1
#endif
#ifndef BL
#define BL 0.0
#endif
#ifndef SIMIT
#define SIMIT 3
#endif
#ifndef SIMSTEP
#define SIMSTEP 3000
#endif
#ifndef SIMTL
#define SIMTL 0.9
#endif
#ifndef SIMEVERY
#define SIMEVERY 4
#endif

int main() {
    auto T0 = chrono::steady_clock::now();
    auto el = [&]() { return chrono::duration<double>(chrono::steady_clock::now() - T0).count(); };
    cin >> N >> K >> P >> R;
    A.resize(P); for (auto& a : A) cin >> a;
    pw.resize(N); iota(pw.begin(), pw.end(), 0);
    {
        int nNo = P - (K - (N - NPORT) - MG);
        mt19937 rng(12345);
        vector<int> in(N, 0); for (int j = 0; j < NPORT; j++) in[j] = 1;
        vector<int> b(P, 0);
        vector<int> cb(N, 0); for (int u = 0; u < P; u++) for (int j = 0; j < N; j++) cb[j] += A[u][j] - '0';
        auto wc = [&](int u, int j) { int x = A[u][j] - '0'; return HW * (x ? P - cb[j] : cb[j]) + HB * P * x; };
        for (int u = 0; u < P; u++) for (int j = 0; j < N; j++) if (in[j]) b[u] += wc(u, j);
        auto eval = [&]() { vector<int> t = b; nth_element(t.begin(), t.begin() + nNo, t.end()); long long s = 0; for (int i = 0; i < nNo; i++) s += t[i]; return s; };
        long long cur = eval();
        for (int it = 0; it < 20000; it++) {
            int x = rng() % N, y = rng() % N;
            if (in[x] == in[y]) continue;
            if (!in[x]) swap(x, y);
            for (int u = 0; u < P; u++) b[u] += wc(u, y) - wc(u, x);
            long long nv = eval();
            if (nv <= cur) { cur = nv; in[x] = 0; in[y] = 1; }
            else for (int u = 0; u < P; u++) b[u] -= wc(u, y) - wc(u, x);
        }
        int c = 0; for (int j = 0; j < N; j++) if (in[j]) pw[c++] = j;
        for (int j = 0; j < N; j++) if (!in[j]) pw[c++] = j;
        for (auto& a : A) { string t(N, '0'); for (int i = 0; i < N; i++) t[i] = a[pw[i]]; a = t; }
    }
    TG.assign(P, 0);
    for (int u = 0; u < P; u++) for (int j = 0; j < N; j++) if (A[u][j] == '1') TG[u] |= 1ULL << j;
    vector<double> prio(P);
    for (int u = 0; u < P; u++) { int c = 0; for (int j = 0; j < NPORT; j++) c += A[u][j] - '0'; prio[u] = c; }
    vector<double> prio0 = prio;
    build(prio);
    mt19937 srng(777);
    SIMM = true;
    for (int it = 0; it < SIMIT; it++) {
        vector<double> acc(P, 0); int ns = 0;
        int prev = srng() % P;
        bool late = false;
        for (int s = 0; s < SIMSTEP; s++) {
            if (s % 64 == 0 && el() > SIMTL) { late = true; break; }
            int a; do a = srng() % P; while (a == prev);
            serve(a); prev = a;
            if (s >= 200 && s % SIMEVERY == 0) {
                groundCostAll(acc);
                ns++;
            }
        }
        if (late && ns < 100) { build(prio); break; }
        vector<double> np(P);
        for (int u = 0; u < P; u++) np[u] = acc[u] / ns + BL * prio0[u] + 1e-3 * prio[u];
        prio = np;
        build(prio);
    }
    SIMM = false;
#ifdef STAT
    memset(STX,0,sizeof STX); memset(STY,0,sizeof STY);
#endif
#if defined(EXPECT) || defined(TIMING)
    fprintf(stderr, "SIMTIME = %.3f\n", (double)clock() / CLOCKS_PER_SEC);
#endif
    string out; for (auto& s : S) { string o(N, '.'); for (int i = 0; i < N; i++) o[pw[i]] = s[i]; out += o + "\n"; }
    cout << out << flush;
    gLA = !SALT;
    for (int r = 0; r < R; r++) {
        int a; if (!(cin >> a) || a < 0) return 0;
#ifndef EXPK
#define EXPK 1
#endif
#ifdef EXPECT
        {
            static int prevA = -1; static double ex = 0;
            if (r % EXPK == 0) {
                vector<int> o0 = ord_, q0 = parkA;
                double t = 0; int c = 0;
                for (int u = 0; u < P; u++) if (u != prevA) { t += serve(u); c++; ord_ = o0; parkA = q0; }
                ex += t / c * EXPK;
            }
            prevA = a;
            if (r == R - 1) fprintf(stderr, "EXPECT = %.1f\n", ex);
        }
#endif
        serveBest(a);
        if (display() != TG[a]) LOG("mismatch at %d\n", r);
        cout << opsCnt << "\n" << opsOut << flush;
    }
#ifdef TIMING
    fprintf(stderr, "TOTAL = %.3f\n", (double)clock() / CLOCKS_PER_SEC);
#endif
#ifdef STAT
    fprintf(stderr, "Yall n=%lld avg=%.2f ground=%.2f | Xused n=%lld costX=%.2f (Y would %.2f)\n", STY[0], (double)STY[1]/STY[0], (double)STY[2]/STY[0], STX[0], (double)STX[1]/STX[0], (double)STX[2]/STX[0]);
    for (int p = 0; p < NPORT; p++) fprintf(stderr, "%lld ", STX[3+p]); fprintf(stderr, "\n");
#endif
}
