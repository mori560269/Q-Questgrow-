// nest: 列 p の上掛けはポート 0..p で不透明、列ブロックは p の昇順
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
#define NPORT 30
#endif
#ifndef SLOPE
#define SLOPE 5.0
#endif
#ifndef XBIAS
#define XBIAS 0
#endif

int N, K, P, R;
vector<string> A;
vector<u64> OPQ, BLK;
vector<int> ord_;          // 上から順の紙番号
vector<int> kind;          // 0: 1マス紙, 1: 上掛け, 2: 全部穴
vector<int> pixWin, pixCol;  // 1マス紙の窓と色
vector<int> ovTarget, ovPort; // 上掛けの商品・ポート
vector<int> ovOf;          // 商品 -> 上掛け紙（なければ -1）
vector<int> isPort;
vector<vector<int>> portOv;  // 未使用（参考）
int raised = -1;
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
void mv(int k, int d) {
    assert(visible(k));
    int p = posOf(k);
    ord_.erase(ord_.begin() + p);
    ord_.insert(ord_.begin() + d, k);
    opsOut += to_string(k) + " " + to_string(d) + "\n"; opsCnt++;
}
u64 display() {
    u64 cov = 0, b = 0;
    for (int k : ord_) { b |= BLK[k] & ~cov; cov |= OPQ[k]; }
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
void portFlip(int p) {
    vector<int> st = portStack(p);
    int x = st.front();
    int last = st.back();
    int d = posOf(last);  // 抜くと last の位置が 1 つ前にずれるので、その後ろ = 元の posOf(last)
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

#ifndef MG
#define MG 2
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

int main() {
    cin >> N >> K >> P >> R;
    A.resize(P); for (auto& a : A) cin >> a;
    // ポートにする窓を選ぶ: 上掛けのない商品のポート内の黒が少なくなるように
    vector<int> pw(N); iota(pw.begin(), pw.end(), 0);
    {
        int nNo = P - (K - (N - NPORT) - MG);
        mt19937 rng(12345);
        vector<int> in(N, 0); for (int j = 0; j < NPORT; j++) in[j] = 1;
        vector<int> b(P, 0);
        for (int u = 0; u < P; u++) for (int j = 0; j < N; j++) if (in[j]) b[u] += A[u][j] - '0';
        auto eval = [&]() { vector<int> t = b; nth_element(t.begin(), t.begin() + nNo, t.end()); long long s = 0; for (int i = 0; i < nNo; i++) s += t[i]; return s; };
        long long cur = eval();
        for (int it = 0; it < 20000; it++) {
            int x = rng() % N, y = rng() % N;
            if (in[x] == in[y]) continue;
            if (!in[x]) swap(x, y);  // x: ポート -> 外す, y: 入れる
            for (int u = 0; u < P; u++) b[u] += (A[u][y] - '0') - (A[u][x] - '0');
            long long nv = eval();
            if (nv <= cur) { cur = nv; in[x] = 0; in[y] = 1; }
            else for (int u = 0; u < P; u++) b[u] -= (A[u][y] - '0') - (A[u][x] - '0');
        }
        int c = 0; for (int j = 0; j < N; j++) if (in[j]) pw[c++] = j;
        for (int j = 0; j < N; j++) if (!in[j]) pw[c++] = j;
        for (auto& a : A) { string t(N, '0'); for (int i = 0; i < N; i++) t[i] = a[pw[i]]; a = t; }
    }
    // 窓 0..NPORT-1 をポートにする
    isPort.assign(N, 0);
    for (int j = 0; j < NPORT; j++) isPort[j] = 1;
    vector<string> S;
    // 黒の 1 マス紙（ポート以外の窓）と白の地紙
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
    // 上掛け: 各ポートに nov/NPORT 枚、ポートでの色が半々になるよう割り当て
    ovOf.assign(P, -1);
    vector<int> used(P, 0);
    int pairs = nov / 2;
    vector<vector<int>> plan(NPORT);
    vector<array<int,2>> quota(NPORT);
    vector<int> perPairs(NPORT);
    {
        double ws = 0; for (int p = 0; p < NPORT; p++) ws += 1 + SLOPE * p;
        int acc = 0; double cum = 0;
        for (int p = 0; p < NPORT; p++) { cum += (1 + SLOPE * p) / ws * pairs; int t = (int)llround(cum); perPairs[p] = max(1, t - acc); acc += perPairs[p]; }
        perPairs[NPORT - 1] -= acc - pairs;
    }
    for (int p = 0; p < NPORT; p++) {
        int per = 2 * perPairs[p];
        quota[p] = {(per + 1) / 2, per / 2};
    }
    vector<int> pr(P); iota(pr.begin(), pr.end(), 0);
    auto sc = [&](int u) { int c = 0; for (int j = 0; j < NPORT; j++) c += A[u][j] - '0'; return c; };
    stable_sort(pr.begin(), pr.end(), [&](int x, int y) { return sc(x) > sc(y); });
    for (int u : pr) {
        int bp = -1;
        for (int p = 0; p < NPORT; p++) { int c = A[u][p] - '0'; if (quota[p][c] > 0 && (bp < 0 || quota[p][c] > quota[bp][A[u][bp] - '0'])) bp = p; }
        if (bp < 0) continue;
        quota[bp][A[u][bp] - '0']--; used[u] = 1; plan[bp].push_back(u);
    }
    // 交互の色に並べる
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
    string out; for (auto& s : S) { string o(N, '.'); for (int i = 0; i < N; i++) o[pw[i]] = s[i]; out += o + "\n"; }
    cout << out << flush;
    OPQ.resize(K); BLK.resize(K);
    for (int k = 0; k < K; k++) { OPQ[k] = BLK[k] = 0; for (int j = 0; j < N; j++) { if (S[k][j] != '.') OPQ[k] |= 1ULL << j; if (S[k][j] == '1') BLK[k] |= 1ULL << j; } }
    ord_.resize(K); iota(ord_.begin(), ord_.end(), 0);

    for (int r = 0; r < R; r++) {
        int a; if (!(cin >> a) || a < 0) return 0;
        opsOut.clear(); opsCnt = 0;
        u64 tgt = 0; for (int j = 0; j < N; j++) if (A[a][j] == '1') tgt |= 1ULL << j;
        vector<int> ord0 = ord_; string out0 = opsOut; int cnt0 = opsCnt;
        // 案 Y: 浮いている上掛けをポート列へ戻し（色が合う側へ）、ポートと地紙で直す
        {
            vector<int> loose, fixedp(NPORT, 0);
            for (int k : ord_) { if (kind[k] == 0 || kind[k] == 3) break; if (kind[k] == 1) loose.push_back(k); }
            for (int k : loose) {
                int p = ovPort[k], c = colorAt(k, p), t = A[a][p] - '0';
                vector<int> st; for (int x : ord_) if (x != k && kind[x] == 1 && ovPort[x] == p) st.push_back(x);
                int pk = posOf(k);
                auto after = [&](int x) { int i = posOf(x); return i > pk ? i - 1 : i; };
                int d = (t == c) ? after(st.front()) : after(st.back()) + 1;
                mv(k, d); fixedp[p] = 1;
            }
            for (int q = 0; q < NPORT; q++) if (!fixedp[q] && colorAt(portStack(q).front(), q) != A[a][q] - '0') portFlip(q);
            groundFix(tgt);
        }
        int costY = opsCnt - cnt0;
        int ov = ovOf[a];
        if (ov >= 0) {
            vector<int> ordY = ord_; string outY = opsOut; int cntY = opsCnt;
            ord_ = ord0; opsOut = out0; opsCnt = cnt0;
            int p = ovPort[ov];
            {
                vector<int> loose;
                for (int k : ord_) { if (kind[k] == 0 || kind[k] == 3) break; if (kind[k] == 1) loose.push_back(k); }
                for (int k : loose) if (ovPort[k] > p) {
                    int pl = ovPort[k], c = colorAt(k, pl), t = A[a][pl] - '0';
                    vector<int> st; for (int x : ord_) if (x != k && kind[x] == 1 && ovPort[x] == pl) st.push_back(x);
                    int pk = posOf(k);
                    auto after = [&](int x) { int i = posOf(x); return i > pk ? i - 1 : i; };
                    mv(k, (t == c) ? after(st.front()) : after(st.back()) + 1);
                }
            }
            vector<int> st = portStack(p);
            int depth = find(st.begin(), st.end(), ov) - st.begin();
            for (int t = 0; t < depth; t++) portFlip(p);
            mv(ov, 0);
            for (int q = p + 1; q < NPORT; q++) {
                if (colorAt(portStack(q).front(), q) != (A[a][q] - '0')) portFlip(q);
            }
            int costX = opsCnt - cnt0;
            if (costX + XBIAS >= costY) { ord_ = ordY; opsOut = outY; opsCnt = cntY; }
        }
        if (display() != tgt) LOG("mismatch at %d\n", r);
        cout << opsCnt << "\n" << opsOut << flush;
    }
}
