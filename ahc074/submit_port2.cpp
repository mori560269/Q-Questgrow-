// port2: port1 の 1 マス紙を「黒の 1 マス紙 + 白の地紙 1 枚」に置き換え、浮いた紙を上掛けへ
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
#define NPORT 13
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

// 地紙より上の黒紙 = 黒。地紙を下げると間の黒紙がまとめて黒になる
void groundFix(u64 tgt) {
    int gp = posOf(GROUND);
    int deepest = -1;
    for (int i = gp + 1; i < (int)ord_.size(); i++) {
        int k = ord_[i];
        if (kind[k] == 0 && (tgt >> pixWin[k] & 1)) deepest = i;
    }
    if (deepest >= 0) mv(GROUND, deepest);  // 抜くと 1 つ前にずれる -> deepest の直後
    gp = posOf(GROUND);
    vector<int> wrong;
    for (int i = 0; i < gp; i++) { int k = ord_[i]; if (kind[k] == 0 && !(tgt >> pixWin[k] & 1)) wrong.push_back(k); }
    for (int k : wrong) { int g = posOf(GROUND); mv(k, g); }  // 抜くと地紙が 1 つ前 -> 地紙の直後
}

int main() {
    cin >> N >> K >> P >> R;
    A.resize(P); for (auto& a : A) cin >> a;
    // 窓 0..NPORT-1 をポートにする
    isPort.assign(N, 0);
    for (int j = 0; j < NPORT; j++) isPort[j] = 1;
    vector<string> S;
    // 黒の 1 マス紙（ポート以外の窓）と白の地紙
    for (int j = 0; j < N; j++) if (!isPort[j]) {
        string s(N, '.'); s[j] = '1'; S.push_back(s); kind.push_back(0); pixWin.push_back(j); pixCol.push_back(1); ovTarget.push_back(-1); ovPort.push_back(-1);
    }
    {
        string s(N, '.'); for (int j = 0; j < N; j++) if (!isPort[j]) s[j] = '0';
        GROUND = S.size(); S.push_back(s); kind.push_back(3); pixWin.push_back(-1); pixCol.push_back(-1); ovTarget.push_back(-1); ovPort.push_back(-1);
    }
    int npix = S.size();
    int nov = K - npix;
    // 上掛け: 各ポートに nov/NPORT 枚、ポートでの色が半々になるよう割り当て
    ovOf.assign(P, -1);
    vector<int> used(P, 0);
    int pairs = nov / 2;
    vector<vector<int>> plan(NPORT);
    for (int p = 0; p < NPORT; p++) {
        int per = 2 * (pairs / NPORT + (p < pairs % NPORT ? 1 : 0));
        int need[2] = {(per + 1) / 2, per / 2};
        for (int c = 0; c < 2; c++) {
            for (int t = 0; t < need[c]; t++) {
                int u = 0; while (used[u] || A[u][p] - '0' != c) u++;
                used[u] = 1; plan[p].push_back(u);
            }
        }
    }
    // 交互の色に並べる
    for (int p = 0; p < NPORT; p++) {
        vector<int> z, o; for (int u : plan[p]) (A[u][p] == '0' ? z : o).push_back(u);
        vector<int> seq; for (size_t i = 0; i < max(z.size(), o.size()); i++) { if (i < z.size()) seq.push_back(z[i]); if (i < o.size()) seq.push_back(o[i]); }
        plan[p] = seq;
    }
    for (int p = 0; p < NPORT; p++) for (int u : plan[p]) {
        string s = A[u];
        for (int j = 0; j < NPORT; j++) if (j != p) s[j] = '.';
        ovOf[u] = S.size();
        S.push_back(s); kind.push_back(1); pixWin.push_back(-1); pixCol.push_back(-1); ovTarget.push_back(u); ovPort.push_back(p);
    }
    while ((int)S.size() < K) { S.push_back(string(N, '.')); kind.push_back(2); pixWin.push_back(-1); pixCol.push_back(-1); ovTarget.push_back(-1); ovPort.push_back(-1); }
    string out; for (auto& s : S) out += s + "\n";
    cout << out << flush;
    OPQ.resize(K); BLK.resize(K);
    for (int k = 0; k < K; k++) { OPQ[k] = BLK[k] = 0; for (int j = 0; j < N; j++) { if (S[k][j] != '.') OPQ[k] |= 1ULL << j; if (S[k][j] == '1') BLK[k] |= 1ULL << j; } }
    ord_.resize(K); iota(ord_.begin(), ord_.end(), 0);

    for (int r = 0; r < R; r++) {
        int a; if (!(cin >> a) || a < 0) return 0;
        opsOut.clear(); opsCnt = 0;
        u64 tgt = 0; for (int j = 0; j < N; j++) if (A[a][j] == '1') tgt |= 1ULL << j;
        if (raised >= 0) { int x = raised; raised = -1; putBack(x); }
        // 案 Y: 1 マス紙とポートで直す
        u64 d = display() ^ tgt;
        int costY = __builtin_popcountll(d);
        // 案 X: 上掛け
        int costX = INT_MAX, depth = 0;
        int ov = ovOf[a];
        if (ov >= 0) {
            int p = ovPort[ov];
            vector<int> st = portStack(p);
            depth = find(st.begin(), st.end(), ov) - st.begin();
            int pf = 0;
            for (int q = 0; q < NPORT; q++) if (q != p) {
                vector<int> sq = portStack(q);
                if (colorAt(sq.front(), q) != (A[a][q] - '0')) pf++;
            }
            costX = depth + 1 + pf;
        }
        if (costX < costY) {
            int p = ovPort[ov];
            for (int t = 0; t < depth; t++) portFlip(p);
            mv(ov, 0); raised = ov;
            for (int q = 0; q < NPORT; q++) if (q != p) {
                vector<int> sq = portStack(q);
                if (colorAt(sq.front(), q) != (A[a][q] - '0')) portFlip(q);
            }
        } else {
            for (int j = 0; j < N; j++) if ((d >> j & 1) && isPort[j]) portFlip(j);
            groundFix(tgt);
        }
        if (display() != tgt) LOG("mismatch at %d\n", r);
        cout << opsCnt << "\n" << opsOut << flush;
    }
}
