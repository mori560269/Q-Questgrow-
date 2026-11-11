# 入力生成器（公式と同じ分布: 128x128 から相異なる 151 点を順序付きで一様に選ぶ）。乱数は公式と別。
# usage: python3 gen.py <seeds_file> <out_dir>
import random, sys, os
seeds = [int(l) for l in open(sys.argv[1]) if l.strip()]
os.makedirs(sys.argv[2], exist_ok=True)
for s in seeds:
    rng = random.Random(s * 1000003 + 73)
    pts = [(x // 128, x % 128) for x in rng.sample(range(128 * 128), 151)]
    T = sum(abs(a[0] - b[0]) + abs(a[1] - b[1]) for a, b in zip(pts, pts[1:]))
    with open(os.path.join(sys.argv[2], f"{s:04d}.txt"), "w") as f:
        f.write(f"128 150 3 {T}\n")
        f.write("".join(f"{i} {j}\n" for i, j in pts))
