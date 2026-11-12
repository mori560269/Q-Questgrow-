// 公式 lib.rs の対話判定を自分で移植したローカルテスター。
// usage: tester <解のバイナリ>  （入力ファイルを標準入力から読む。Score を標準エラーに出す）
#include <bits/stdc++.h>
#include <unistd.h>
#include <sys/wait.h>
#include <signal.h>
using namespace std;
typedef unsigned long long u64;
int main(int argc, char** argv) {
    signal(SIGPIPE, SIG_IGN);
    int N, K, P, R; cin >> N >> K >> P >> R;
    vector<string> A(P); for (auto& a : A) cin >> a;
    vector<int> req(R); for (auto& x : req) cin >> x;
    int to[2], from[2]; pipe(to); pipe(from);
    pid_t pid = fork();
    if (pid == 0) { dup2(to[0], 0); dup2(from[1], 1); close(to[1]); close(from[0]); execl(argv[1], argv[1], (char*)0); _exit(127); }
    close(to[0]); close(from[1]);
    FILE* w = fdopen(to[1], "w"); FILE* r = fdopen(from[0], "r");
    auto mask = [&](const string& s, char c) { u64 m = 0; for (int j = 0; j < N; j++) if (s[j] == c) m |= 1ULL << j; return m; };
    auto fail = [&](const string& msg) { fprintf(w, "-1\n"); fflush(w); fprintf(stderr, "ERROR: %s\n", msg.c_str()); kill(pid, SIGKILL); waitpid(pid, 0, 0); exit(0); };
    fprintf(w, "%d %d %d %d\n", N, K, P, R); for (auto& a : A) fprintf(w, "%s\n", a.c_str()); fflush(w);
    auto tok = [&]() -> string { char buf[256]; if (fscanf(r, "%255s", buf) != 1) fail("Unexpected EOF"); return buf; };
    auto num = [&](long lo, long hi) -> long { string t = tok(); char* e; long v = strtol(t.c_str(), &e, 10); if (*e || t.empty()) fail("Parse error: " + t); if (v < lo || v > hi) fail("Out of range: " + t); return v; };
    vector<u64> op(K), bl(K);
    for (int k = 0; k < K; k++) {
        string p = tok();
        if ((int)p.size() != N) fail("bad pattern length");
        for (char c : p) if (c != '0' && c != '1' && c != '.') fail("bad pattern char");
        op[k] = mask(p, '0') | mask(p, '1'); bl[k] = mask(p, '1');
    }
    vector<int> ord(K); iota(ord.begin(), ord.end(), 0);
    u64 full = N == 64 ? ~0ULL : ((1ULL << N) - 1);
    long moves = 0, mist = 0;
    for (int q = 0; q < R; q++) {
        fprintf(w, "%d\n", req[q]); fflush(w);
        long m = num(0, 2 * K);
        for (long i = 0; i < m; i++) {
            int k = num(0, K - 1), d = num(0, K - 1);
            u64 ex = op[k]; int pos = 0;
            while (ex && ord[pos] != k) { ex &= ~op[ord[pos]]; pos++; }
            if (!ex) fail("Paper " + to_string(k) + " is not visible");
            if (pos < d) rotate(ord.begin() + pos, ord.begin() + pos + 1, ord.begin() + d + 1);
            else rotate(ord.begin() + d, ord.begin() + pos, ord.begin() + pos + 1);
            moves++;
        }
        u64 cov = 0, b = 0;
        for (int k : ord) { b |= bl[k] & ~cov; cov |= op[k]; if (cov == full) break; }
        if (b != mask(A[req[q]], '1')) mist++;
    }
    fclose(w); waitpid(pid, 0, 0);
    fprintf(stderr, "E = %ld T = %ld\nScore = %ld\n", mist, moves, 2L * K * mist + moves);
}
