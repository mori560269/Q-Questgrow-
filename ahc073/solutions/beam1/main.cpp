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

struct Aff { int a[2]; int b; };

struct Cand {
    int cost;
    int parent;
    int depth;
    int seq;  // base-3 digits, first jump is least significant
    int w[2];
    uint64_t key;
};

struct State {
    int cost;
    int parent;
    int depth, seq, w[2];
    int tk[K][2];
};

// 探索中の状態（DFS用）
static int curG[2];
static int curX[2];
static int curParent;
static int curCost;
static int maxDepth;
static vector<Cand>* outC;

static inline int clampi(int v, int lo, int hi) { return v < lo ? lo : (v > hi ? hi : v); }

static inline int floordiv(int a, int b) {
    int q = a / b;
    if ((a % b != 0) && ((a < 0) != (b < 0))) q--;
    return q;
}

static inline void bestW(int A, int B, int g, int lo, int hi, int& bw, int& bc) {
    bc = INT_MAX; bw = 0;
    auto ev = [&](int w) {
        w = clampi(w, lo, hi);
        int c = abs(w) + abs(g - A - B * w);
        if (c < bc || (c == bc && abs(w) < abs(bw))) { bc = c; bw = w; }
    };
    ev(0);
    if (B != 0) {
        int t = floordiv(g - A, B);
        ev(t); ev(t + 1);
    }
}

static void dfs(int depth, int seq, int pw3, const Aff& P, const Aff* tok, const int* lo, const int* hi) {
    if (depth >= 1) {
        int w[2], c[2];
        bool ok = true;
        for (int d = 0; d < 2; d++) {
            if (lo[d] > hi[d]) { ok = false; break; }
            bestW(P.a[d], P.b, curG[d], lo[d], hi[d], w[d], c[d]);
        }
        if (ok) {
            Cand cd;
            cd.cost = curCost + depth + c[0] + c[1];
            cd.parent = curParent;
            cd.depth = depth;
            cd.seq = seq;
            cd.w[0] = w[0]; cd.w[1] = w[1];
            outC->push_back(cd);
        }
    }
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
            // 0 <= a + b w <= N-1
            if (np.b == 0) {
                if (np.a[d] < 0 || np.a[d] >= N) { ok = false; break; }
            } else if (np.b > 0) {
                nlo[d] = max(nlo[d], -floordiv(np.a[d], np.b));  // ceil(-a/b)
                nhi[d] = min(nhi[d], floordiv(N - 1 - np.a[d], np.b));
            } else {
                int nb = -np.b;
                // a - nb w >= 0 -> w <= a/nb ; a - nb w <= N-1 -> w >= (a-N+1)/nb
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

// 具体的な w で脚を実行し、トークンと操作列を得る
static void apply_leg(const int* x, int tk[K][2], int depth, int seq, const int* w, const int* g, string* ops) {
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

    maxDepth = 5;
    vector<vector<State>> layers(M + 1);
    // 初期配置の候補
    {
        vector<State>& L0 = layers[0];
        unordered_set<uint64_t> seen;
        int W0 = 300;
        for (int t = 0; t < W0; t++) {
            State st{};
            st.cost = 0; st.parent = -1; st.depth = 0; st.seq = 0; st.w[0] = st.w[1] = 0;
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
            curParent = si; curCost = st.cost;
            // 歩くだけ
            {
                Cand cd; cd.cost = st.cost + abs(x[0] - curG[0]) + abs(x[1] - curG[1]);
                cd.parent = si; cd.depth = 0; cd.seq = 0; cd.w[0] = cd.w[1] = 0;
                cands.push_back(cd);
            }
            Aff P; P.a[0] = x[0]; P.a[1] = x[1]; P.b = 1;
            Aff tok[K];
            for (int k = 0; k < K; k++) { tok[k].a[0] = st.tk[k][0]; tok[k].a[1] = st.tk[k][1]; tok[k].b = 0; }
            int lo[2] = {-x[0], -x[1]}, hi[2] = {N - 1 - x[0], N - 1 - x[1]};
            dfs(0, 0, 1, P, tok, lo, hi);
        }
        // 選抜
        sort(cands.begin(), cands.end(), [](const Cand& a, const Cand& b) { return a.cost < b.cost; });
        auto& nxt = layers[i + 1];
        nxt.clear();
        unordered_set<uint64_t> seen;
        seen.reserve(W * 4);
        const int* x = (i == 0) ? S : G[i - 1];
        for (auto& cd : cands) {
            if ((int)nxt.size() >= W) break;
            State ns;
            const State& ps = cur[cd.parent];
            memcpy(ns.tk, ps.tk, sizeof(ns.tk));
            apply_leg(x, ns.tk, cd.depth, cd.seq, cd.w, G[i], nullptr);
            uint64_t key = tokkey(ns.tk);
            if (!seen.insert(key).second) continue;
            ns.cost = cd.cost; ns.parent = cd.parent; ns.depth = cd.depth; ns.seq = cd.seq;
            ns.w[0] = cd.w[0]; ns.w[1] = cd.w[1];
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
