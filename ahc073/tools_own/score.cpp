// 公式 lib.rs の採点部分を自分で移植したもの。usage: score <input> <output>
#include <bits/stdc++.h>
using namespace std;
int main(int argc, char** argv) {
    if (argc < 3) { fprintf(stderr, "usage: score in out\n"); return 2; }
    ifstream fi(argv[1]), fo(argv[2]);
    int N, M, K; long long T; fi >> N >> M >> K >> T;
    int si, sj; fi >> si >> sj;
    vector<pair<int,int>> g(M);
    for (auto& p : g) fi >> p.first >> p.second;
    auto fail = [&](const string& m) { printf("%s\nScore = 0\n", m.c_str()); exit(0); };
    vector<pair<int,int>> c(K);
    for (auto& p : c) {
        if (!(fo >> p.first >> p.second)) fail("Unexpected EOF");
        if (p.first < 0 || p.first >= N || p.second < 0 || p.second >= N) fail("circle out of range");
    }
    int pi = si, pj = sj; long long steps = 0; int vis = 0; string tok;
    while (fo >> tok) {
        if (steps == T) fail("Too many operations");
        int ni = pi, nj = pj, ci = -1;
        if (tok == "U") ni--; else if (tok == "D") ni++; else if (tok == "L") nj--; else if (tok == "R") nj++;
        else if (tok == "J") {
            int a, b; if (!(fo >> a >> b)) fail("Unexpected EOF");
            if (a < 0 || a >= N || b < 0 || b >= N) fail("J out of range");
            for (int k = 0; k < K; k++) if (c[k] == make_pair(a, b)) { ci = k; break; }
            if (ci < 0) fail("no magic circle at op " + to_string(steps + 1));
            ni = 2 * a - pi; nj = 2 * b - pj;
        } else fail("Unknown operation: " + tok);
        if (ni < 0 || ni >= N || nj < 0 || nj >= N) fail("landing outside board at op " + to_string(steps + 1));
        if (ci >= 0) c[ci] = {pi, pj};
        pi = ni; pj = nj; steps++;
        if (vis < M && make_pair(pi, pj) == g[vis]) vis++;
    }
    long long sc = vis == M ? M + T - steps + 1 : vis + 1;
    printf("A = %lld V = %d T = %lld\nScore = %lld\n", steps, vis, T, sc);
}
