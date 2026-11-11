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

#ifndef DEPTH
#define DEPTH 5
#endif
#ifndef LAMBDA
#define LAMBDA 0.5
#endif
#ifndef LOOK
#define LOOK 3
#endif
#ifndef MU
#define MU 0.0
#endif
#ifndef SPREAD0
#define SPREAD0 15.0
#endif
#ifndef DECAY
#define DECAY 0.5
#endif

struct RNG {
    uint64_t x = 88172645463325252ULL;
    inline uint64_t next() { x ^= x << 7; x ^= x >> 9; return x; }
    inline int range(int n) { return (int)(next() % (uint64_t)n); }
};

constexpr int N = 128, M = 150, K = 3;
int T_in;
int S[2];
int G[M][2];
int PT[M + 1][2];  // PT[0]=S, PT[i+1]=G[i]

struct Aff { int a[2]; int b; };

struct Cand {
    float ev;
    int cost;
    int parent;
    int8_t depth;
    int16_t seq;
    int8_t w[2];
};

struct State {
    int cost;
    int parent;
    int8_t depth;
    int16_t seq;
    int8_t w[2];
    uint8_t tk[K][2];
};

static int curG[2];
static int curParent;
static int curCost;
static int curLeg;
static int maxDepth;
static vector<Cand>* outC;

static inline int clampi(int v, int lo, int hi) { return v < lo ? lo : (v > hi ? hi : v); }
static inline int floordiv(int a, int b) {
    int q = a / b;
    if ((a % b != 0) && ((a < 0) != (b < 0))) q--;
    return q;
}

// 先読みの評価：次の LOOK 区間について「1 回の転移で行けたら」の費用の見積もり
static float tgt[LOOK][2];
static float tgtD[LOOK];
static int nTgt;
static inline float heur(const int tk[K][2]) {
    float h = 0, wt = 1;
    for (int j = 0; j < nTgt; j++) {
        float best = tgtD[j];
        for (int k = 0; k < K; k++) {
            float c = 2 * (fabsf(tk[k][0] - tgt[j][0]) + fabsf(tk[k][1] - tgt[j][1])) + 1;
            best = min(best, c);
        }
        h += wt * best;
        wt *= DECAY;
    }
    if (MU > 0) {
        float cx = (tk[0][0] + tk[1][0] + tk[2][0]) / 3.0f, cy = (tk[0][1] + tk[1][1] + tk[2][1]) / 3.0f;
        float sp = 0;
        for (int k = 0; k < K; k++) sp += max(0.0f, fabsf(tk[k][0] - cx) + fabsf(tk[k][1] - cy) - (float)SPREAD0);
        h += MU / LAMBDA * sp;
    }
    return h;
}

static inline int fcost(int A, int B, int g, int w) { return abs(w) + abs(g - A - B * w); }

static void evaluate(int depth, int seq, const Aff& P, const Aff* tok, const int* lo, const int* hi) {
    // 各座標で最小費用と、最小を取る w の区間
    int wl[2], wr[2], wc[2], fc[2];
    for (int d = 0; d < 2; d++) {
        int A = P.a[d], B = P.b, g = curG[d];
        int bc = INT_MAX, bw = 0;
        auto ev = [&](int w) {
            w = clampi(w, lo[d], hi[d]);
            int c = fcost(A, B, g, w);
            if (c < bc || (c == bc && abs(w) < abs(bw))) { bc = c; bw = w; }
        };
        ev(0);
        if (B != 0) { int t = floordiv(g - A, B); ev(t); ev(t + 1); }
        wc[d] = bw; fc[d] = bc;
        // 最小値の区間（凸なので二分探索の代わりに広げる：B=±1 のとき広い）
        if (abs(B) == 1) {
            // f(w)=|w|+|g-A-Bw|：w が 0 と (g-A)/B の間で一定
            int e = (g - A) * B;
            int l = min(0, e), r = max(0, e);
            l = max(l, lo[d]); r = min(r, hi[d]);
            if (l <= r && fcost(A, B, g, l) == bc && fcost(A, B, g, r) == bc) { wl[d] = l; wr[d] = r; }
            else { wl[d] = wr[d] = bw; }
        } else { wl[d] = wr[d] = bw; }
    }
    int baseCost = curCost + depth + fc[0] + fc[1];
    // 候補の w
    float bestEv = 1e30f; int bestCost = 0, bw0 = 0, bw1 = 0;
    auto tryw = [&](int w0, int w1) {
        w0 = clampi(w0, lo[0], hi[0]); w1 = clampi(w1, lo[1], hi[1]);
        int c = curCost + depth + fcost(P.a[0], P.b, curG[0], w0) + fcost(P.a[1], P.b, curG[1], w1);
        if (c > baseCost + 4) return;
        int tk[K][2];
        for (int k = 0; k < K; k++) { tk[k][0] = tok[k].a[0] + tok[k].b * w0; tk[k][1] = tok[k].a[1] + tok[k].b * w1; }
        float e = c + LAMBDA * heur(tk);
        if (e < bestEv) { bestEv = e; bestCost = c; bw0 = w0; bw1 = w1; }
    };
    tryw(wc[0], wc[1]);
    for (int k = 0; k < K; k++) {
        if (tok[k].b == 0) continue;
        for (int j = 0; j < nTgt; j++) {
            int s0 = (int)lround((tgt[j][0] - tok[k].a[0]) / tok[k].b);
            int s1 = (int)lround((tgt[j][1] - tok[k].a[1]) / tok[k].b);
            tryw(s0, s1);
            tryw(clampi(s0, wl[0], wr[0]), clampi(s1, wl[1], wr[1]));
        }
    }
    if (bestEv > 1e29f) return;
    Cand cd;
    cd.ev = bestEv; cd.cost = bestCost; cd.parent = curParent;
    cd.depth = depth; cd.seq = seq; cd.w[0] = bw0; cd.w[1] = bw1;
    outC->push_back(cd);
}

static void dfs(int depth, int seq, int pw3, const Aff& P, const Aff* tok, const int* lo, const int* hi) {
    if (depth >= 1) evaluate(depth, seq, P, tok, lo, hi);
    if (depth == maxDepth) return;
    for (int k = 0; k < K; k++) {
        const Aff& t = tok[k];
        if (t.b == P.b && t.a[0] == P.a[0] && t.a[1] == P.a[1]) continue;
        Aff np;
        np.b = 2 * t.b - P.b;
        int nlo[2] = {lo[0], lo[1]}, nhi[2] = {hi[0], hi[1]};
        bool ok = true;
        for (int d = 0; d < 2; d++) {
            np.a[d] = 2 * t.a[d] - P.a[d];
            if (np.b == 0) {
                if (np.a[d] < 0 || np.a[d] >= N) { ok = false; break; }
            } else if (np.b > 0) {
                nlo[d] = max(nlo[d], -floordiv(np.a[d], np.b));
                nhi[d] = min(nhi[d], floordiv(N - 1 - np.a[d], np.b));
            } else {
                int nb = -np.b;
                nhi[d] = min(nhi[d], floordiv(np.a[d], nb));
                nlo[d] = max(nlo[d], -floordiv(-(np.a[d] - (N - 1)), nb));
            }
            if (nlo[d] > nhi[d]) { ok = false; break; }
        }
        if (!ok) continue;
        Aff ntok[K] = {tok[0], tok[1], tok[2]};
        ntok[k] = P;
        dfs(depth + 1, seq + k * pw3, pw3 * 3, np, ntok, nlo, nhi);
    }
}

static void apply_leg(const int* x, int tk[K][2], int depth, int seq, const int8_t* w, const int* g, string* ops) {
    int p[2] = {x[0], x[1]};
    auto walk_to = [&](int ti, int tj) {
        while (p[0] < ti) { p[0]++; if (ops) *ops += "D\n"; }
        while (p[0] > ti) { p[0]--; if (ops) *ops += "U\n"; }
        while (p[1] < tj) { p[1]++; if (ops) *ops += "R\n"; }
        while (p[1] > tj) { p[1]--; if (ops) *ops += "L\n"; }
    };
    if (depth > 0) walk_to(x[0] + w[0], x[1] + w[1]);
    for (int s = 0; s < depth; s++) {
        int k = seq % 3; seq /= 3;
        int a = tk[k][0], b = tk[k][1];
        if (ops) *ops += "J " + to_string(a) + " " + to_string(b) + "\n";
        tk[k][0] = p[0]; tk[k][1] = p[1];
        p[0] = 2 * a - p[0]; p[1] = 2 * b - p[1];
    }
    walk_to(g[0], g[1]);
}

static uint64_t tokkey(const int tk[K][2]) {
    int v[K];
    for (int k = 0; k < K; k++) v[k] = tk[k][0] * N + tk[k][1];
    sort(v, v + K);
    uint64_t h = 0;
    for (int k = 0; k < K; k++) h = h * 1000003ULL + v[k];
    return h;
}

static void setTargets(int leg) {
    // leg 番目の区間を終えた直後（位置 = G[leg]）から見た、次の区間たちの中点
    nTgt = 0;
    for (int j = 0; j < LOOK; j++) {
        int l = leg + 1 + j;  // 区間 l: PT[l] -> PT[l+1]
        if (l >= M) break;
        tgt[nTgt][0] = (PT[l][0] + PT[l + 1][0]) * 0.5f;
        tgt[nTgt][1] = (PT[l][1] + PT[l + 1][1]) * 0.5f;
        tgtD[nTgt] = abs(PT[l][0] - PT[l + 1][0]) + abs(PT[l][1] - PT[l + 1][1]);
        nTgt++;
    }
}

int main() {
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
    Timer TM(1.85);
    RNG rng;
    int n_, m_, k_;
    cin >> n_ >> m_ >> k_ >> T_in;
    cin >> S[0] >> S[1];
    for (int i = 0; i < M; i++) cin >> G[i][0] >> G[i][1];
    PT[0][0] = S[0]; PT[0][1] = S[1];
    for (int i = 0; i < M; i++) { PT[i + 1][0] = G[i][0]; PT[i + 1][1] = G[i][1]; }

    maxDepth = DEPTH;
    vector<vector<State>> layers(M + 1);
    {
        // 初期配置：最初の数区間の中点の近く + ランダム
        vector<State>& L0 = layers[0];
        unordered_set<uint64_t> seen;
        for (int t = 0; t < 400; t++) {
            State st{};
            st.cost = 0; st.parent = -1;
            int tk[K][2];
            for (int k = 0; k < K; k++) {
                int l = (t < 200) ? (k + (t / 50)) : rng.range(6);
                l = min(l, M - 1);
                int r = (t % 50 == 0 && t < 200) ? 0 : 3;
                for (int d = 0; d < 2; d++) {
                    int m = (PT[l][d] + PT[l + 1][d]) / 2 + (r ? rng.range(2 * r + 1) - r : 0);
                    if (t >= 300) m = rng.range(N);
                    tk[k][d] = clampi(m, 0, N - 1);
                }
            }
            if (!seen.insert(tokkey(tk)).second) continue;
            for (int k = 0; k < K; k++) { st.tk[k][0] = tk[k][0]; st.tk[k][1] = tk[k][1]; }
            L0.push_back(st);
        }
    }
    double budget = 1.80;
    int W = 150;
    vector<Cand> cands;
    outC = &cands;
    for (int i = 0; i < M; i++) {
        double t0 = TM.real_sec();
        cands.clear();
        auto& cur = layers[i];
        curG[0] = G[i][0]; curG[1] = G[i][1];
        curLeg = i;
        setTargets(i);
        const int* x = PT[i];
        for (int si = 0; si < (int)cur.size(); si++) {
            const State& st = cur[si];
            curParent = si; curCost = st.cost;
            int tk[K][2];
            for (int k = 0; k < K; k++) { tk[k][0] = st.tk[k][0]; tk[k][1] = st.tk[k][1]; }
            {
                Cand cd; cd.cost = st.cost + abs(x[0] - curG[0]) + abs(x[1] - curG[1]);
                cd.ev = cd.cost + LAMBDA * heur(tk);
                cd.parent = si; cd.depth = 0; cd.seq = 0; cd.w[0] = cd.w[1] = 0;
                cands.push_back(cd);
            }
            Aff P; P.a[0] = x[0]; P.a[1] = x[1]; P.b = 1;
            Aff tok[K];
            for (int k = 0; k < K; k++) { tok[k].a[0] = tk[k][0]; tok[k].a[1] = tk[k][1]; tok[k].b = 0; }
            int lo[2] = {-x[0], -x[1]}, hi[2] = {N - 1 - x[0], N - 1 - x[1]};
            dfs(0, 0, 1, P, tok, lo, hi);
        }
        sort(cands.begin(), cands.end(), [](const Cand& a, const Cand& b) { return a.ev < b.ev; });
        auto& nxt = layers[i + 1];
        nxt.clear();
        unordered_set<uint64_t> seen;
        seen.reserve(W * 4);
        for (auto& cd : cands) {
            if ((int)nxt.size() >= W) break;
            const State& ps = cur[cd.parent];
            int tk[K][2];
            for (int k = 0; k < K; k++) { tk[k][0] = ps.tk[k][0]; tk[k][1] = ps.tk[k][1]; }
            apply_leg(x, tk, cd.depth, cd.seq, cd.w, G[i], nullptr);
            if (!seen.insert(tokkey(tk)).second) continue;
            State ns;
            ns.cost = cd.cost; ns.parent = cd.parent; ns.depth = cd.depth; ns.seq = cd.seq;
            ns.w[0] = cd.w[0]; ns.w[1] = cd.w[1];
            for (int k = 0; k < K; k++) { ns.tk[k][0] = tk[k][0]; ns.tk[k][1] = tk[k][1]; }
            nxt.push_back(ns);
        }
        double t1 = TM.real_sec();
        double per = (t1 - t0) / max<size_t>(1, cur.size());
        double remain = budget - t1;
        int legs = M - 1 - i;
        if (legs > 0 && per > 0) W = (int)clamp(remain / legs / per, 5.0, 20000.0);
    }
    int bi = 0;
    auto& last = layers[M];
    for (int s = 0; s < (int)last.size(); s++) if (last[s].cost < last[bi].cost) bi = s;
    vector<int> idx(M + 1);
    idx[M] = bi;
    for (int i = M; i >= 1; i--) idx[i - 1] = layers[i][idx[i]].parent;
    const State& init = layers[0][idx[0]];
    string out;
    int tk[K][2];
    for (int k = 0; k < K; k++) {
        tk[k][0] = init.tk[k][0]; tk[k][1] = init.tk[k][1];
        out += to_string(tk[k][0]) + " " + to_string(tk[k][1]) + "\n";
    }
    string ops;
    for (int i = 0; i < M; i++) {
        const State& st = layers[i + 1][idx[i + 1]];
        apply_leg(PT[i], tk, st.depth, st.seq, st.w, G[i], &ops);
    }
    out += ops;
    fwrite(out.data(), 1, out.size(), stdout);
    LOG("cost=%d T=%d W=%d elapsed=%.3f\n", last[bi].cost, T_in, W, TM.real_sec());
    return 0;
}
