# 入力生成器（公式と同じ分布、乱数は別）。usage: python3 gen.py <seeds_file> <out_dir>
import random, sys, os
seeds = [int(l) for l in open(sys.argv[1]) if l.strip()]
os.makedirs(sys.argv[2], exist_ok=True)
for s in seeds:
    rng = random.Random(s * 1000003 + 74)
    A = []; seen = set()
    while len(A) < 256:
        b = ['1'] * 32 + ['0'] * 32; rng.shuffle(b); x = ''.join(b)
        if x not in seen: seen.add(x); A.append(x)
    req = [rng.randrange(256)]
    for _ in range(1023):
        x = rng.randrange(255); req.append(x + (x >= req[-1]))
    with open(os.path.join(sys.argv[2], f"{s:04d}.txt"), "w") as f:
        f.write("64 192 256 1024\n" + "\n".join(A) + "\n" + "\n".join(map(str, req)) + "\n")
