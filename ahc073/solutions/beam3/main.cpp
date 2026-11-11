#include <bits/stdc++.h>
#include "timer.hpp"
using namespace std;

struct RNG {
    uint64_t x = 88172645463325252ULL;
    inline uint64_t next() { x ^= x << 7; x ^= x >> 9; return x; }
    inline int range(int n) { return (int)(next() % (uint64_t)n); }
};

constexpr int N = 128, M = 150, K = 3;
int T_in;
int S[2];
int G[M][2];


constexpr int MAXD = 8;
#ifndef REFINE
#define REFINE 2
#endif
#ifndef LAMBDA
#define LAMBDA 0.0
#endif
#ifndef DEPTH
#define DEPTH 5
#endif
struct Sym { int a[2]; int b[MAXD]; };

struct Cand {
    int cost;
    int parent;
    int depth;
    int seq;  // base-3 digits, first jump is least significant
    int8_t w[MAXD][2];
};

struct State {
    int cost;
    int parent;
    int depth, seq;
    int8_t w[MAXD][2];
    int tk[K][2];
};

static int curG[2];
static int curX[2];
static int curTk[K][2];
static int curParent;
static int curCost;
static int maxDepth;
static vector<Cand>* outC;

static inline int roundiv(int a, int b) {  // nearest integer of a/b
    double r = (double)a / b;
    return (int)lround(r);
}

// 具体値で検証。歩行量合計を返す（不正なら -1）
static int verify(int depth, int seq, int w[][2]) {
    int p0 = curX[0], p1 = curX[1];
    int tk[K][2];
    memcpy(tk, curTk, sizeof(tk));
    int walk = 0;
    for (int s = 0; s < depth; s++) {
        p0 += w[s][0]; p1 += w[s][1];
        if ((unsigned)p0 >= (unsigned)N || (unsigned)p1 >= (unsigned)N) return -1;
        walk += abs(w[s][0]) + abs(w[s][1]);
        int k = seq % 3; seq /= 3;
        int a = tk[k][0], b = tk[k][1];
        tk[k][0] = p0; tk[k][1] = p1;
        p0 = 2 * a - p0; p1 = 2 * b - p1;
        if ((unsigned)p0 >= (unsigned)N || (unsigned)p1 >= (unsigned)N) return -1;
    }
    walk += abs(curG[0] - p0) + abs(curG[1] - p1);
    return walk;
}

static void evaluate(int depth, int seq, const Sym& L) {
    int best = INT_MAX;
    int bw[MAXD][2];
    int w[MAXD][2];
    int ord[MAXD];
    for (int s = 0; s < depth; s++) ord[s] = s;
    sort(ord, ord + depth, [&](int x, int y) { return abs(L.b[x]) > abs(L.b[y]); });
    for (int var = 0; var < 3; var++) {
        for (int d = 0; d < 2; d++) {
            int D = curG[d] - L.a[d];
            for (int s = 0; s < depth; s++) w[s][d] = 0;
            if (var == 2) continue;
            for (int ii = 0; ii < depth; ii++) {
                int s = ord[ii];
                int B = L.b[s];
                if (B == 0) continue;
                if (var == 1 && s != 0) continue;
                int v = roundiv(D, B);
                if (abs(B) == 1 && ii + 1 < depth) v = 0;  // 係数1は最後の歩きと同じ
                w[s][d] = v;
                D -= B * v;
            }
        }
        bool fit = true;
        for (int s = 0; s < depth; s++) if (abs(w[s][0]) > 127 || abs(w[s][1]) > 127) fit = false;
        if (!fit) continue;
        int c = verify(depth, seq, w);
        if (c >= 0 && c < best) { best = c; memcpy(bw, w, sizeof(int) * 2 * depth); }
    }
    if (best == INT_MAX) { for (int s = 0; s < depth; s++) bw[s][0] = bw[s][1] = 0; best = verify(depth, seq, bw); if (best < 0) best = INT_MAX; }
    if (best != INT_MAX && REFINE) {
        bool imp = true;
        while (imp) {
            imp = false;
            for (int s = 0; s < depth; s++) for (int d = 0; d < 2; d++) for (int dl = -REFINE; dl <= REFINE; dl++) {
                if (!dl) continue;
                bw[s][d] += dl;
                int c = verify(depth, seq, bw);
                if (c >= 0 && c < best) { best = c; imp = true; }
                else bw[s][d] -= dl;
            }
        }
    }
    if (best == INT_MAX) return;
    Cand cd;
    cd.cost = curCost + depth + best;
    cd.parent = curParent;
    cd.depth = depth;
    cd.seq = seq;
    for (int s = 0; s < depth; s++) { cd.w[s][0] = bw[s][0]; cd.w[s][1] = bw[s][1]; }
    outC->push_back(cd);
}

static void dfs(int depth, int seq, int pw3, const Sym& L, const Sym* tok) {
    if (depth >= 1) evaluate(depth, seq, L);
    if (depth == maxDepth) return;
    Sym P = L;
    P.b[depth] = 1;
    for (int k = 0; k < K; k++) {
        const Sym& t = tok[k];
        Sym nl;
        nl.a[0] = 2 * t.a[0] - P.a[0];
        nl.a[1] = 2 * t.a[1] - P.a[1];
        for (int s = 0; s <= depth; s++) nl.b[s] = 2 * t.b[s] - P.b[s];
        Sym ntok[K] = {tok[0], tok[1], tok[2]};
        ntok[k] = P;
        dfs(depth + 1, seq + k * pw3, pw3 * 3, nl, ntok);
    }
}

// 具体的な w で脚を実行し、トークンと操作列を得る
static void apply_leg(const int* x, int tk[K][2], int depth, int seq, const int8_t w[][2], const int* g, string* ops) {
    int p[2] = {x[0], x[1]};
    auto walk_to = [&](int ti, int tj) {
        while (p[0] < ti) { p[0]++; if (ops) *ops += "D\n"; }
        while (p[0] > ti) { p[0]--; if (ops) *ops += "U\n"; }
        while (p[1] < tj) { p[1]++; if (ops) *ops += "R\n"; }
        while (p[1] > tj) { p[1]--; if (ops) *ops += "L\n"; }
    };
    for (int s = 0; s < depth; s++) {
        walk_to(p[0] + w[s][0], p[1] + w[s][1]);
        int k = seq % 3; seq /= 3;
        int a = tk[k][0], b = tk[k][1];
        if (ops) *ops += "J " + to_string(a) + " " + to_string(b) + "\n";
        tk[k][0] = p[0]; tk[k][1] = p[1];
        p[0] = 2 * a - p[0]; p[1] = 2 * b - p[1];
    }
    walk_to(g[0], g[1]);
}

static uint64_t tokkey(int tk[K][2]) {
    int v[K];
    for (int k = 0; k < K; k++) v[k] = tk[k][0] * N + tk[k][1];
    sort(v, v + K);
    uint64_t h = 0;
    for (int k = 0; k < K; k++) h = h * 1000003ULL + v[k];
    return h;
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

    maxDepth = DEPTH;
    vector<vector<State>> layers(M + 1);
    // 初期配置の候補
    {
        vector<State>& L0 = layers[0];
        unordered_set<uint64_t> seen;
        int W0 = 300;
        for (int t = 0; t < W0; t++) {
            State st{};
            st.cost = 0; st.parent = -1; st.depth = 0; st.seq = 0;
            for (int k = 0; k < K; k++) {
                if (t == 0) { st.tk[k][0] = 64; st.tk[k][1] = 32 + 32 * k; }
                else { st.tk[k][0] = 16 + rng.range(96); st.tk[k][1] = 16 + rng.range(96); }
            }
            uint64_t key = tokkey(st.tk);
            if (seen.insert(key).second) L0.push_back(st);
        }
    }
    double budget = 1.80;
    int W = 200;
    vector<Cand> cands;
    outC = &cands;
    for (int i = 0; i < M; i++) {
        double t0 = TM.real_sec();
        cands.clear();
        auto& cur = layers[i];
        curG[0] = G[i][0]; curG[1] = G[i][1];
        for (int si = 0; si < (int)cur.size(); si++) {
            const State& st = cur[si];
            const int* x = (i == 0) ? S : G[i - 1];
            curX[0] = x[0]; curX[1] = x[1];
            memcpy(curTk, st.tk, sizeof(curTk));
            curParent = si; curCost = st.cost;
            // 歩くだけ
            {
                Cand cd; cd.cost = st.cost + abs(x[0] - curG[0]) + abs(x[1] - curG[1]);
                cd.parent = si; cd.depth = 0; cd.seq = 0;
                cands.push_back(cd);
            }
            Sym L{}; L.a[0] = x[0]; L.a[1] = x[1];
            Sym tok[K] = {};
            for (int k = 0; k < K; k++) { tok[k].a[0] = st.tk[k][0]; tok[k].a[1] = st.tk[k][1]; }
            dfs(0, 0, 1, L, tok);
        }
        // 選抜
        // まず cost で粗く絞ってから、トークン位置の評価込みで選ぶ
        size_t lim = min(cands.size(), (size_t)W * 6);
        if (cands.size() > lim) nth_element(cands.begin(), cands.begin() + lim, cands.end(), [](const Cand& a, const Cand& b) { return a.cost < b.cost; }), cands.resize(lim);
        vector<pair<double,int>> ev(cands.size());
        vector<array<array<int,2>,K>> ctk(cands.size());
        {
            const int* x0 = (i == 0) ? S : G[i - 1];
            for (size_t c = 0; c < cands.size(); c++) {
                int tk[K][2];
                memcpy(tk, cur[cands[c].parent].tk, sizeof(tk));
                apply_leg(x0, tk, cands[c].depth, cands[c].seq, cands[c].w, G[i], nullptr);
                double h = 0;
                for (int k = 0; k < K; k++) { h += abs(tk[k][0] - 63.5) + abs(tk[k][1] - 63.5); ctk[c][k] = {tk[k][0], tk[k][1]}; }
                ev[c] = {cands[c].cost + LAMBDA * h, (int)c};
            }
        }
        sort(ev.begin(), ev.end());
        auto& nxt = layers[i + 1];
        nxt.clear();
        unordered_set<uint64_t> seen;
        seen.reserve(W * 4);
        const int* x = (i == 0) ? S : G[i - 1];
        for (auto& e : ev) {
            if ((int)nxt.size() >= W) break;
            const Cand& cd = cands[e.second];
            State ns;
            for (int k = 0; k < K; k++) { ns.tk[k][0] = ctk[e.second][k][0]; ns.tk[k][1] = ctk[e.second][k][1]; }
            uint64_t key = tokkey(ns.tk);
            if (!seen.insert(key).second) continue;
            ns.cost = cd.cost; ns.parent = cd.parent; ns.depth = cd.depth; ns.seq = cd.seq;
            memcpy(ns.w, cd.w, sizeof(ns.w));
            nxt.push_back(ns);
        }
        double t1 = TM.real_sec();
        double per = (t1 - t0) / max<size_t>(1, cur.size());
        double remain = budget - t1;
        int legs = M - 1 - i;
        if (legs > 0 && per > 0) {
            W = (int)clamp(remain / legs / per, 10.0, 20000.0);
        }
    }
    // 復元
    int bi = 0;
    auto& last = layers[M];
    for (int s = 0; s < (int)last.size(); s++) if (last[s].cost < last[bi].cost) bi = s;
    vector<int> idx(M + 1);
    idx[M] = bi;
    for (int i = M; i >= 1; i--) idx[i - 1] = layers[i][idx[i]].parent;
    State init = layers[0][idx[0]];
    string out;
    for (int k = 0; k < K; k++) out += to_string(init.tk[k][0]) + " " + to_string(init.tk[k][1]) + "\n";
    int tk[K][2];
    memcpy(tk, init.tk, sizeof(tk));
    string ops;
    for (int i = 0; i < M; i++) {
        const State& st = layers[i + 1][idx[i + 1]];
        const int* x = (i == 0) ? S : G[i - 1];
        apply_leg(x, tk, st.depth, st.seq, st.w, G[i], &ops);
    }
    out += ops;
    fwrite(out.data(), 1, out.size(), stdout);
    LOG("cost=%d T=%d W=%d elapsed=%.3f\n", last[bi].cost, T_in, W, TM.real_sec());
    return 0;
}
