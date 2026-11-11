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
#define DEPTH 2
#endif
#ifndef LAMBDA
#define LAMBDA 1.0
#endif
#ifndef LOOK
#define LOOK 12
#endif
#ifndef MU
#define MU 0.0
#endif
#ifndef SPREAD0
#define SPREAD0 15.0
#endif
#ifndef SLACK
#define SLACK 4
#endif
#ifndef WMAX
#define WMAX 1000000
#endif
#ifndef WINIT
#define WINIT 1000
#endif
#ifndef BUDGET
#define BUDGET 1.75
#endif
#define FASTT
#ifndef QZ
#define QZ 1
#endif
#ifndef DECAY
#define DECAY 0.9
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
    uint8_t p[2][2];
};

struct State {
    int cost;
    int parent;
    int8_t depth;
    int16_t seq;
    uint8_t p[2][2];
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
static float tgtV[LOOK][2];
static int nTgt;
static float FT[N * N];
static void buildFT() {
    for (int a = 0; a < N; a++) for (int b = 0; b < N; b++) {
        float bs = 0, wt = 1;
        for (int j = 0; j < nTgt; j++) {
            float c = 2 * (fabsf(a - tgt[j][0]) + fabsf(b - tgt[j][1])) + 1;
            bs = max(bs, wt * (tgtD[j] - c));
            wt *= DECAY;
        }
        FT[a * N + b] = -bs;
    }
}
static inline float heur(const int tk[K][2]) {
#ifdef FASTT
    return FT[tk[0][0] * N + tk[0][1]] + FT[tk[1][0] * N + tk[1][1]] + FT[tk[2][0] * N + tk[2][1]];
#endif
#ifdef TOKWISE
    {
        float h = 0;
        for (int k = 0; k < K; k++) {
            float bs = 0, wt = 1;
            for (int j = 0; j < nTgt; j++) {
                float c = 2 * (fabsf(tk[k][0] - tgt[j][0]) + fabsf(tk[k][1] - tgt[j][1])) + 1;
                bs = max(bs, wt * (tgtD[j] - c));
                wt *= DECAY;
            }
            h -= bs;
        }
        return h;
    }
#endif
    float h = 0, wt = 1;
    for (int j = 0; j < nTgt; j++) {
        float best = tgtD[j];
        for (int k = 0; k < K; k++) {
            float c = 2 * (fabsf(tk[k][0] - tgt[j][0]) + fabsf(tk[k][1] - tgt[j][1])) + 1;
            best = min(best, c);
        }
#ifdef TRANS
        for (int a = 0; a < K; a++) for (int b = 0; b < K; b++) if (a != b) {
            float c = fabsf(tgtV[j][0] - 2 * (tk[b][0] - tk[a][0])) + fabsf(tgtV[j][1] - 2 * (tk[b][1] - tk[a][1])) + 2;
            best = min(best, c);
        }
#endif
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


#ifndef LP
#define LP 1
#endif
static int curX[2];
static int curTk[K][2];

static inline bool inb(int a, int b) { return (unsigned)a < (unsigned)N && (unsigned)b < (unsigned)N; }
static inline int md(const int* a, const int* b) { return abs(a[0] - b[0]) + abs(a[1] - b[1]); }
static inline void clampBox(const int* p, const int* a, const int* b, int* o) {
    for (int d = 0; d < 2; d++) o[d] = clampi(p[d], min(a[d], b[d]), max(a[d], b[d]));
}

// 経路: x -> p1 (歩) -> J k1 -> q1 -> p2 (歩) -> J k2 -> q2 -> g (歩)
static void evaluate1(int k1) {
    const int* x = curX; const int* g = curG;
    int t[2] = {curTk[k1][0], curTk[k1][1]};
    int land[2] = {2 * t[0] - g[0], 2 * t[1] - g[1]};  // ここから跳べば g に着く
    int cand[2 + 2 * LP][2]; int nc = 0;
    cand[nc][0] = x[0]; cand[nc][1] = x[1]; nc++;
    { int o[2] = {clampi(land[0], 0, N - 1), clampi(land[1], 0, N - 1)}; cand[nc][0] = o[0]; cand[nc][1] = o[1]; nc++; }
    for (int j = 0; j < min(LP, nTgt); j++) {
        int T2[2] = {(int)lround(tgt[j][0]), (int)lround(tgt[j][1])};
        cand[nc][0] = T2[0]; cand[nc][1] = T2[1]; nc++;
        int o[2]; clampBox(T2, x, cand[1], o); cand[nc][0] = o[0]; cand[nc][1] = o[1]; nc++;
    }
    float bestEv = 1e30f; int bc = 0, bi = -1, base = INT_MAX;
    int cs[2 + 2 * LP];
    for (int c = 0; c < nc; c++) {
        int* p = cand[c];
        int q[2] = {2 * t[0] - p[0], 2 * t[1] - p[1]};
        if (!inb(q[0], q[1]) || (p[0] == t[0] && p[1] == t[1])) { cs[c] = -1; continue; }
        cs[c] = curCost + md(x, p) + 1 + md(q, g);
        base = min(base, cs[c]);
    }
    for (int c = 0; c < nc; c++) {
        if (cs[c] < 0 || cs[c] > base + SLACK) continue;
        int tk[K][2]; memcpy(tk, curTk, sizeof(tk));
        tk[k1][0] = cand[c][0]; tk[k1][1] = cand[c][1];
        float e = cs[c] + LAMBDA * heur(tk);
        if (e < bestEv) { bestEv = e; bc = cs[c]; bi = c; }
    }
    if (bi < 0) return;
    Cand cd; cd.ev = bestEv; cd.cost = bc; cd.parent = curParent; cd.depth = 1; cd.seq = k1;
    cd.p[0][0] = cand[bi][0]; cd.p[0][1] = cand[bi][1];
    outC->push_back(cd);
}

static void evaluate2(int k1, int k2) {
    const int* x = curX; const int* g = curG;
    int t1[2] = {curTk[k1][0], curTk[k1][1]};
    // p1 の候補
    int c1[3 + 2 * LP][2]; int n1 = 0;
    c1[n1][0] = x[0]; c1[n1][1] = x[1]; n1++;
    for (int j = 0; j < min(LP, nTgt); j++) { c1[n1][0] = (int)lround(tgt[j][0]); c1[n1][1] = (int)lround(tgt[j][1]); n1++; }
    // k2 != k1 の並進: 最適は x + 2(t2-t1) 方向。p1 を g 側へ寄せる候補
    if (k2 != k1) {
        int t2[2] = {curTk[k2][0], curTk[k2][1]};
        int e[2] = {clampi(g[0] - 2 * (t2[0] - t1[0]), 0, N - 1), clampi(g[1] - 2 * (t2[1] - t1[1]), 0, N - 1)};
        c1[n1][0] = e[0]; c1[n1][1] = e[1]; n1++;
        for (int j = 0; j < min(LP, nTgt); j++) {
            int T2[2] = {(int)lround(tgt[j][0]), (int)lround(tgt[j][1])}, o[2];
            clampBox(T2, x, e, o); c1[n1][0] = o[0]; c1[n1][1] = o[1]; n1++;
        }
    }
    float bestEv = 1e30f; int bc = 0, bi = -1, bj = -1;
    int base = INT_MAX;
    struct E { int c, i, p2[2]; } es[64]; int ne = 0;
    for (int i = 0; i < n1; i++) {
        int* p1 = c1[i];
        if (p1[0] == t1[0] && p1[1] == t1[1]) continue;
        int q1[2] = {2 * t1[0] - p1[0], 2 * t1[1] - p1[1]};
        if (!inb(q1[0], q1[1])) continue;
        int t2[2];
        if (k2 == k1) { t2[0] = p1[0]; t2[1] = p1[1]; } else { t2[0] = curTk[k2][0]; t2[1] = curTk[k2][1]; }
        int land[2] = {clampi(2 * t2[0] - g[0], 0, N - 1), clampi(2 * t2[1] - g[1], 0, N - 1)};
        int c2[2 + 2 * LP][2]; int n2 = 0;
        c2[n2][0] = q1[0]; c2[n2][1] = q1[1]; n2++;
        c2[n2][0] = land[0]; c2[n2][1] = land[1]; n2++;
        for (int j = 0; j < min(LP, nTgt); j++) {
            int T2[2] = {(int)lround(tgt[j][0]), (int)lround(tgt[j][1])}, o[2];
            c2[n2][0] = T2[0]; c2[n2][1] = T2[1]; n2++;
            clampBox(T2, q1, land, o); c2[n2][0] = o[0]; c2[n2][1] = o[1]; n2++;
        }
        int w1 = md(x, p1);
        for (int jj = 0; jj < n2; jj++) {
            int* p2 = c2[jj];
            if (p2[0] == t2[0] && p2[1] == t2[1]) continue;
            int q2[2] = {2 * t2[0] - p2[0], 2 * t2[1] - p2[1]};
            if (!inb(q2[0], q2[1])) continue;
            int c = curCost + w1 + 1 + md(q1, p2) + 1 + md(q2, g);
            if (ne < 64) { es[ne].c = c; es[ne].i = i; es[ne].p2[0] = p2[0]; es[ne].p2[1] = p2[1]; ne++; }
            base = min(base, c);
        }
    }
    for (int e = 0; e < ne; e++) {
        if (es[e].c > base + SLACK) continue;
        int tk[K][2]; memcpy(tk, curTk, sizeof(tk));
        tk[k1][0] = c1[es[e].i][0]; tk[k1][1] = c1[es[e].i][1];
        // 2 回目: k2 のトークン（k2==k1 なら p1 に置いたもの）が p2 に置き換わる
        tk[k2][0] = es[e].p2[0]; tk[k2][1] = es[e].p2[1];
        float ev = es[e].c + LAMBDA * heur(tk);
        if (ev < bestEv) { bestEv = ev; bc = es[e].c; bi = es[e].i; bj = e; }
    }
    if (bi < 0) return;
    Cand cd; cd.ev = bestEv; cd.cost = bc; cd.parent = curParent; cd.depth = 2; cd.seq = k1 + 3 * k2;
    cd.p[0][0] = c1[bi][0]; cd.p[0][1] = c1[bi][1];
    cd.p[1][0] = es[bj].p2[0]; cd.p[1][1] = es[bj].p2[1];
    outC->push_back(cd);
}

static void apply_leg(const int* x, int tk[K][2], int depth, int seq, const uint8_t pp[][2], const int* g, string* ops) {
    int p[2] = {x[0], x[1]};
    auto walk_to = [&](int ti, int tj) {
        while (p[0] < ti) { p[0]++; if (ops) *ops += "D\n"; }
        while (p[0] > ti) { p[0]--; if (ops) *ops += "U\n"; }
        while (p[1] < tj) { p[1]++; if (ops) *ops += "R\n"; }
        while (p[1] > tj) { p[1]--; if (ops) *ops += "L\n"; }
    };
    for (int s = 0; s < depth; s++) {
        walk_to(pp[s][0], pp[s][1]);
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
    for (int k = 0; k < K; k++) v[k] = (tk[k][0] / QZ) * N + tk[k][1] / QZ;
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
        tgtV[nTgt][0] = PT[l + 1][0] - PT[l][0]; tgtV[nTgt][1] = PT[l + 1][1] - PT[l][1];
        nTgt++;
    }
}

int main() {
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
    Timer TM(BUDGET + 0.05);
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
    double budget = BUDGET;
    int W = WINIT;
    vector<Cand> cands;
    outC = &cands;
    for (int i = 0; i < M; i++) {
        double t0 = TM.real_sec();
        cands.clear();
        auto& cur = layers[i];
        curG[0] = G[i][0]; curG[1] = G[i][1];
        curLeg = i;
        setTargets(i);
#ifdef FASTT
        buildFT();
#endif
        const int* x = PT[i];
        for (int si = 0; si < (int)cur.size(); si++) {
            const State& st = cur[si];
            curParent = si; curCost = st.cost;
            int tk[K][2];
            for (int k = 0; k < K; k++) { tk[k][0] = st.tk[k][0]; tk[k][1] = st.tk[k][1]; }
            {
                Cand cd; cd.cost = st.cost + abs(x[0] - curG[0]) + abs(x[1] - curG[1]);
                cd.ev = cd.cost + LAMBDA * heur(tk);
                cd.parent = si; cd.depth = 0; cd.seq = 0;
                cands.push_back(cd);
            }
            curX[0] = x[0]; curX[1] = x[1];
            memcpy(curTk, tk, sizeof(tk));
            for (int k1 = 0; k1 < K; k1++) {
                evaluate1(k1);
                if (DEPTH >= 2) for (int k2 = 0; k2 < K; k2++) evaluate2(k1, k2);
            }
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
            apply_leg(x, tk, cd.depth, cd.seq, cd.p, G[i], nullptr);
            if (!seen.insert(tokkey(tk)).second) continue;
            State ns;
            ns.cost = cd.cost; ns.parent = cd.parent; ns.depth = cd.depth; ns.seq = cd.seq;
            memcpy(ns.p, cd.p, sizeof(ns.p));
            for (int k = 0; k < K; k++) { ns.tk[k][0] = tk[k][0]; ns.tk[k][1] = tk[k][1]; }
            nxt.push_back(ns);
        }
        double t1 = TM.real_sec();
        double per = (t1 - t0) / max<size_t>(1, cur.size());
        double remain = budget - t1;
        int legs = M - 1 - i;
        if (legs > 0 && per > 0) W = (int)clamp(remain / legs / per, 5.0, (double)WMAX);
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
        apply_leg(PT[i], tk, st.depth, st.seq, st.p, G[i], &ops);
    }
    out += ops;
    fwrite(out.data(), 1, out.size(), stdout);
    LOG("cost=%d T=%d W=%d elapsed=%.3f\n", last[bi].cost, T_in, W, TM.real_sec());
    return 0;
}
