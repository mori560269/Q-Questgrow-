// 解のひな形。solutions/<name>/main.cpp にコピーして使う。
// 手元のヘッダ（timer.hpp）は ahc pack が提出用に1ファイルへ展開する。
#include <bits/stdc++.h>
#include "timer.hpp"
using namespace std;

struct RNG {
    uint64_t x = 88172645463325252ULL;
    inline uint64_t next() { x ^= x << 7; x ^= x >> 9; return x; }
    inline int range(int n) { return (int)(next() % (uint64_t)n); }
    inline double uniform() { return (next() >> 11) * (1.0 / 9007199254740992.0); }
};

int main() {
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
    Timer T(1.85);  // problem.time_limit_sec より少し短く
    RNG rng;

    // 入力
    // int N; cin >> N;

    // 初期解（貪欲）

    // 改善（山登り / 焼きなまし）
    // while (!T.over(1.80)) { T.tick(1); ... }

    // 出力

    LOG("elapsed=%.3f\n", T.real_sec());
    return 0;
}
