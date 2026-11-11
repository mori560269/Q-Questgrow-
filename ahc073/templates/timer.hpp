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
#pragma once
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
