// baseline: 窓ごとに白・黒の 1 マス紙を 2 枚。表示が違う窓だけ、上の紙を一番下へ回す。
#include <bits/stdc++.h>
#include "timer.hpp"
using namespace std;
int main() {
    int N, K, P, R;
    cin >> N >> K >> P >> R;
    vector<string> A(P);
    for (auto& a : A) cin >> a;
    string out;
    for (int k = 0; k < K; k++) {
        string s(N, '.');
        if (k < 2 * N) s[k / 2] = (k % 2) ? '1' : '0';
        out += s + "\n";
    }
    cout << out << flush;
    vector<int> topc(N, 0);  // 窓 j で上にある紙の色
    for (int r = 0; r < R; r++) {
        int a;
        if (!(cin >> a) || a < 0) return 0;
        string ops; int m = 0;
        for (int j = 0; j < N; j++) {
            int c = A[a][j] - '0';
            if (topc[j] != c) { ops += to_string(2 * j + topc[j]) + " " + to_string(K - 1) + "\n"; topc[j] = c; m++; }
        }
        cout << m << "\n" << ops << flush;
    }
}
