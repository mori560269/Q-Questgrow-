#!/usr/bin/env python3
"""ahc - AHC（長期）With AI 部門向けの自作ハーネス。

標準ライブラリだけで動く。主な機能:
  評価      eval / compare / promote（SQLite に記録、同一ソースは再利用、交互測定）
  観察      runs / cases / stats / report（AI が読めるテキストのビジュアライザ）
  担当管理  lane new/start/list/stop/rm、pump（止まった担当へ続行の指示）
  共有黒板  idea / reject / decide / notify / status
  提出準備  pack（機械的な縮小とサイズ確認。提出そのものは人間が手で行う）

使い方は `ahc -h`、`ahc <command> -h`、README.md を参照。
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime as dt
import hashlib
import html
import json
import math
import os
import re
import shlex
import shutil
import sqlite3
import statistics
import subprocess
import sys
import time
import tomllib
from pathlib import Path

# ---------------------------------------------------------------- 基本


def die(msg: str, code: int = 1):
    print(f"ahc: {msg}", file=sys.stderr)
    sys.exit(code)


def now_iso() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def find_home() -> Path:
    """ハーネスのホーム（メインの作業ツリー）を探す。担当の worktree から呼んでも同じ場所になる。"""
    env = os.environ.get("AHC_HOME")
    if env:
        return Path(env).resolve()
    try:
        common = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
                                capture_output=True, text=True, check=True).stdout.strip()
        cand = Path(common).parent
        if (cand / "ahc.toml").exists():
            return cand
    except Exception:
        pass
    p = Path.cwd().resolve()
    for d in [p, *p.parents]:
        if (d / "ahc.toml").exists():
            return d
    die("ahc.toml が見つかりません（ホームで実行するか AHC_HOME を設定してください）")


HOME = None  # type: Path
CFG: dict = {}


def load():
    global HOME, CFG
    HOME = find_home()
    with open(HOME / "ahc.toml", "rb") as f:
        CFG = tomllib.load(f)
    (HOME / ".ahc").mkdir(exist_ok=True)
    (HOME / "board").mkdir(exist_ok=True)


def cfg(path: str, default=None):
    cur = CFG
    for k in path.split("."):
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur


def state(*parts) -> Path:
    p = HOME / ".ahc"
    for x in parts:
        p = p / x
    return p


def board(name: str) -> Path:
    return HOME / "board" / name


def maximize() -> bool:
    return cfg("problem.objective", "max") == "max"


# ---------------------------------------------------------------- 記録（SQLite / events）


def db() -> sqlite3.Connection:
    con = sqlite3.connect(state("db.sqlite"), timeout=60)
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript("""
    CREATE TABLE IF NOT EXISTS results(
        src_hash TEXT, seed TEXT, score REAL, time_ms REAL, status TEXT, created REAL,
        PRIMARY KEY(src_hash, seed));
    CREATE TABLE IF NOT EXISTS runs(
        run_id INTEGER PRIMARY KEY AUTOINCREMENT, label TEXT, src_hash TEXT, set_name TEXT,
        seeds TEXT, created REAL, note TEXT, lane TEXT, kind TEXT);
    CREATE TABLE IF NOT EXISTS sources(
        src_hash TEXT PRIMARY KEY, label TEXT, path TEXT, created REAL);
    """)
    return con


def event(kind: str, **kw):
    rec = {"t": now_iso(), "kind": kind, **kw}
    with open(board("events.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def notify(message: str):
    with open(board("NOTIFY.log"), "a", encoding="utf-8") as f:
        f.write(f"[{now_iso()}] {message}\n")
    cmd = cfg("notify.cmd", "")
    if cmd:
        subprocess.run(cmd.replace("{message}", shlex.quote(message)), shell=True, cwd=HOME)
    print(f"[notify] {message}")


def append(path: Path, text: str):
    with open(path, "a", encoding="utf-8") as f:
        f.write(text)


# ---------------------------------------------------------------- 解とビルド


def current_lane() -> str:
    cwd = Path.cwd().resolve()
    lanes_dir = (HOME / ".lanes").resolve()
    try:
        rel = cwd.relative_to(lanes_dir)
        return rel.parts[0]
    except ValueError:
        return ""


def resolve_solution(arg: str) -> tuple[str, Path]:
    """名前（solutions/<name>）、ディレクトリ、または .cpp のパスから (ラベル, ソースパス) を得る。"""
    if arg.upper() == "BEST":
        best = read_best()
        if not best:
            die("BEST が未設定です（ahc promote <解> --init）")
        arg = best
    p = Path(arg)
    if p.suffix in (".cpp", ".cc", ".rs", ".py") and p.exists():
        return (p.parent.name if p.name.startswith("main") else p.stem), p.resolve()
    if p.is_dir() and (p / "main.cpp").exists():
        return p.resolve().name, (p / "main.cpp").resolve()
    for base in [Path.cwd() / "solutions", HOME / "solutions"]:
        d = base / arg
        if (d / "main.cpp").exists():
            return arg, (d / "main.cpp").resolve()
    die(f"解が見つかりません: {arg}")


INCLUDE_RE = re.compile(r'^\s*#\s*include\s*"([^"]+)"', re.M)


def source_bundle(src: Path, seen=None) -> bytes:
    """ソースと、そこから #include "..." される手元のヘッダをまとめたバイト列（ハッシュ用）。"""
    seen = seen if seen is not None else set()
    if src in seen:
        return b""
    seen.add(src)
    data = src.read_bytes()
    out = data
    for m in INCLUDE_RE.finditer(data.decode("utf-8", "replace")):
        for cand in [src.parent / m.group(1), HOME / "templates" / m.group(1)]:
            if cand.exists():
                out += b"\0" + source_bundle(cand.resolve(), seen)
                break
    return out


def build_cmd(virtual: bool) -> str:
    cmd = cfg("build.cmd")
    if virtual:
        cmd += " " + cfg("build.virtual_flags", "")
    return cmd


def src_hash(src: Path, virtual: bool = False) -> str:
    h = hashlib.sha256()
    h.update(source_bundle(src))
    h.update(build_cmd(virtual).encode())
    return h.hexdigest()[:16]


def build(label: str, src: Path, virtual: bool = False) -> tuple[str, Path]:
    hsh = src_hash(src, virtual)
    out = state("bin", hsh)
    out.parent.mkdir(parents=True, exist_ok=True)
    if not out.exists():
        cmd = build_cmd(virtual).replace("{src}", shlex.quote(str(src))).replace("{out}", shlex.quote(str(out)))
        cmd += f" -I{shlex.quote(str(HOME / 'templates'))}"
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=src.parent)
        if r.returncode != 0:
            print(r.stdout + r.stderr, file=sys.stderr)
            die(f"ビルド失敗: {label}")
        keep = state("src", hsh + src.suffix)
        keep.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(src, keep)
        con = db()
        con.execute("INSERT OR IGNORE INTO sources VALUES(?,?,?,?)", (hsh, label, str(src), time.time()))
        con.commit()
    return hsh, out


# ---------------------------------------------------------------- 入力集合


def all_inputs() -> list[Path]:
    d = HOME / cfg("tools.input_dir")
    if not d.exists():
        die(f"入力ディレクトリがありません: {d}（ahc gen で作るか公式の in/ を置いてください）")
    return sorted(p for p in d.iterdir() if p.is_file())


def parse_range(spec: str, n: int) -> list[int]:
    idx = []
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-")
            idx += list(range(int(a), int(b) + 1))
        elif part:
            idx.append(int(part))
    return [i for i in idx if 0 <= i < n]


def select_inputs(set_name: str | None, seeds: str | None) -> tuple[str, list[Path]]:
    ins = all_inputs()
    if seeds:
        return f"seeds:{seeds}", [ins[i] for i in parse_range(seeds, len(ins))]
    set_name = set_name or "smoke"
    spec = cfg(f"eval.sets.{set_name}")
    if spec is None:
        die(f"未定義のテスト集合: {set_name}")
    chosen = [ins[i] for i in parse_range(spec, len(ins))]
    if len(chosen) < len(parse_range(spec, 10**9)):
        print(f"ahc: 注意: 集合 {set_name} は {len(parse_range(spec, 10**9))} 件の定義ですが入力は {len(chosen)} 件です", file=sys.stderr)
    return set_name, chosen


def features_of(inp: Path) -> dict:
    names = cfg("features.header", []) or []
    try:
        first = inp.open().readline().split()
    except Exception:
        return {}
    out = {}
    for k, v in zip(names, first):
        try:
            out[k] = float(v)
        except ValueError:
            pass
    return out


# ---------------------------------------------------------------- 実行と採点


def run_case(binpath: Path, hsh: str, inp: Path) -> dict:
    tl = float(cfg("problem.time_limit_sec", 2.0))
    hard = tl * float(cfg("eval.timeout_factor", 3.0))
    odir = state("out", hsh)
    odir.mkdir(parents=True, exist_ok=True)
    outp = odir / (inp.stem + ".out")
    errp = odir / (inp.stem + ".err")
    interactive = cfg("problem.interactive", False)
    if interactive:
        cmd = cfg("tools.tester_cmd").replace("{bin}", shlex.quote(str(binpath)))
    else:
        cmd = shlex.quote(str(binpath))
    status = "OK"
    t0 = time.perf_counter()
    with open(inp, "rb") as fi, open(outp, "wb") as fo, open(errp, "wb") as fe:
        try:
            p = subprocess.run(cmd, shell=True, stdin=fi, stdout=fo, stderr=fe, timeout=hard, cwd=HOME)
            rc = p.returncode
        except subprocess.TimeoutExpired:
            rc = None
            status = "TIMEOUT"
    ms = (time.perf_counter() - t0) * 1000
    # stderr は末尾だけ残す
    err = errp.read_bytes()
    if len(err) > 200_000:
        errp.write_bytes(err[-200_000:])
    score = None
    if status == "OK" and rc != 0:
        status = "RE"
    if status == "OK":
        rx = re.compile(cfg("tools.score_regex", r"Score\s*=\s*(-?\d+)"))
        if interactive:
            text = err.decode("utf-8", "replace")
        else:
            sc = cfg("tools.score_cmd").replace("{input}", shlex.quote(str(inp))).replace("{output}", shlex.quote(str(outp)))
            r = subprocess.run(sc, shell=True, capture_output=True, text=True, cwd=HOME)
            text = r.stdout + "\n" + r.stderr
        ms_found = rx.findall(text)
        if ms_found:
            score = float(ms_found[-1])
            if score == 0 and maximize():
                status = "ZERO"
        else:
            status = "NOSCORE"
    if status == "OK" and ms > tl * 1000:
        status = "TLE"
    return {"seed": inp.stem, "score": score, "time_ms": ms, "status": status}


def nworkers() -> int:
    n = int(cfg("eval.parallel", 0) or 0)
    return n if n > 0 else max(1, (os.cpu_count() or 2) - 1)


def measure(jobs: list[tuple[str, Path, Path]], force: bool, label_of: dict) -> None:
    """jobs = [(hash, bin, input)] を並列に流して results に保存。force でなければ既存結果は再利用。"""
    con = db()
    todo = []
    for hsh, binp, inp in jobs:
        if not force:
            row = con.execute("SELECT 1 FROM results WHERE src_hash=? AND seed=?", (hsh, inp.stem)).fetchone()
            if row:
                continue
        todo.append((hsh, binp, inp))
    if not todo:
        return
    done = 0
    t0 = time.time()
    with cf.ThreadPoolExecutor(nworkers()) as ex:
        futs = {ex.submit(run_case, b, h, i): h for h, b, i in todo}
        for fu in cf.as_completed(futs):
            h = futs[fu]
            r = fu.result()
            con.execute("INSERT OR REPLACE INTO results VALUES(?,?,?,?,?,?)",
                        (h, r["seed"], r["score"], r["time_ms"], r["status"], time.time()))
            done += 1
            if done % 20 == 0 or done == len(todo):
                con.commit()
                el = time.time() - t0
                print(f"\r  {done}/{len(todo)}  {el:.0f}s", end="", file=sys.stderr, flush=True)
    con.commit()
    print(file=sys.stderr)


def fetch(hsh: str, seeds: list[str]) -> dict[str, dict]:
    con = db()
    out = {}
    q = "SELECT seed, score, time_ms, status FROM results WHERE src_hash=? AND seed=?"
    for s in seeds:
        r = con.execute(q, (hsh, s)).fetchone()
        if r:
            out[s] = {"seed": r[0], "score": r[1], "time_ms": r[2], "status": r[3]}
    return out


def best_known(seeds: list[str]) -> dict[str, float]:
    con = db()
    agg = "MAX" if maximize() else "MIN"
    out = {}
    for s in seeds:
        r = con.execute(f"SELECT {agg}(score) FROM results WHERE seed=? AND status='OK' AND score IS NOT NULL", (s,)).fetchone()
        if r and r[0] is not None:
            out[s] = r[0]
    return out


def rel(score, best) -> float:
    if score is None or best is None or score <= 0 or best <= 0:
        return 0.0
    return score / best if maximize() else best / score


def summarize(res: dict[str, dict], seeds: list[str]) -> dict:
    bk = best_known(seeds)
    oks = [res[s] for s in seeds if s in res]
    scores = [r["score"] for r in oks if r["score"] is not None]
    times = [r["time_ms"] for r in oks]
    stat = {}
    for r in oks:
        stat[r["status"]] = stat.get(r["status"], 0) + 1
    rels = [rel(res[s]["score"] if res.get(s, {}).get("status") in ("OK", "TLE") else None, bk.get(s)) for s in seeds if s in res]
    return {
        "n": len(oks),
        "total": len(seeds),
        "sum": sum(scores) if scores else 0,
        "mean": statistics.fmean(scores) if scores else 0,
        "rel": statistics.fmean(rels) if rels else 0,
        "status": stat,
        "max_ms": max(times) if times else 0,
        "mean_ms": statistics.fmean(times) if times else 0,
    }


def record_run(label, hsh, set_name, seeds, note="", kind="eval") -> int:
    con = db()
    cur = con.execute("INSERT INTO runs(label, src_hash, set_name, seeds, created, note, lane, kind) VALUES(?,?,?,?,?,?,?,?)",
                      (label, hsh, set_name, json.dumps(seeds), time.time(), note, current_lane(), kind))
    con.commit()
    return cur.lastrowid


def fmt_summary(label, s) -> str:
    st = " ".join(f"{k}:{v}" for k, v in sorted(s["status"].items()))
    return (f"{label:<24} n={s['n']}/{s.get('total', s['n']):<5} rel={s['rel']*100:8.4f}%  mean={s['mean']:.6g}  sum={s['sum']:.6g}"
            f"  time(mean/max)={s['mean_ms']:.0f}/{s['max_ms']:.0f}ms  [{st}]")


# ---------------------------------------------------------------- 比較の統計


def paired(base: dict, cand: dict, seeds: list[str]) -> dict:
    """対応のある比較。d = log(cand/base)（min 問題は符号反転）。エラーは別に数える。"""
    ds, win, lose, tie, err = [], 0, 0, 0, 0
    for s in seeds:
        b, c = base.get(s), cand.get(s)
        if not b or not c:
            continue
        good = ("OK", "TLE")
        if c["status"] not in good or b["status"] not in good or not c["score"] or not b["score"] or c["score"] <= 0 or b["score"] <= 0:
            if c["status"] not in good:
                err += 1
            continue
        d = math.log(c["score"] / b["score"])
        if not maximize():
            d = -d
        ds.append(d)
        if d > 1e-12:
            win += 1
        elif d < -1e-12:
            lose += 1
        else:
            tie += 1
    if len(ds) >= 2:
        m = statistics.fmean(ds)
        sd = statistics.stdev(ds)
        se = sd / math.sqrt(len(ds)) if sd > 0 else 0.0
        z = m / se if se > 0 else (math.inf if m > 0 else (-math.inf if m < 0 else 0.0))
    else:
        m, se, z = (ds[0] if ds else 0.0), 0.0, 0.0
    return {"n": len(ds), "gain": math.exp(m) - 1, "se": se, "z": z, "win": win, "lose": lose, "tie": tie, "cand_err": err}


def fmt_paired(p) -> str:
    return (f"gain={p['gain']*100:+.4f}% ±{p['se']*100:.4f}%  z={p['z']:+.2f}  "
            f"win/lose/tie={p['win']}/{p['lose']}/{p['tie']}  cand_err={p['cand_err']}  (n={p['n']})")


# ---------------------------------------------------------------- コマンド: 評価


def cmd_eval(a):
    label, src = resolve_solution(a.solution)
    set_name, ins = select_inputs(a.set, a.seeds)
    hsh, binp = build(label, src, a.virtual)
    print(f"eval {label} ({hsh}) on {set_name} [{len(ins)}件, 並列{nworkers()}]", file=sys.stderr)
    measure([(hsh, binp, i) for i in ins], a.force, {})
    seeds = [i.stem for i in ins]
    res = fetch(hsh, seeds)
    s = summarize(res, seeds)
    rid = record_run(label, hsh, set_name, seeds, a.note or "")
    print(f"run #{rid}  " + fmt_summary(label, s))
    event("eval", run=rid, label=label, hash=hsh, set=set_name, rel=s["rel"], status=s["status"], lane=current_lane())
    write_report()
    return s


def interleaved_jobs(entries, ins):
    """候補と基準をケースごとに交互に並べる（順番も seed ごとに入れ替える）。"""
    jobs = []
    for k, inp in enumerate(ins):
        order = entries if k % 2 == 0 else list(reversed(entries))
        for hsh, binp in order:
            jobs.append((hsh, binp, inp))
    return jobs


def cmd_compare(a):
    set_name, ins = select_inputs(a.set, a.seeds)
    seeds = [i.stem for i in ins]
    built = []
    for sol in [a.base, *a.cands]:
        label, src = resolve_solution(sol)
        hsh, binp = build(label, src, a.virtual)
        built.append((label, hsh, binp))
    print(f"compare on {set_name} [{len(ins)}件, 並列{nworkers()}, {'交互・再測定' if a.fresh else 'キャッシュ再利用'}]", file=sys.stderr)
    measure(interleaved_jobs([(h, b) for _, h, b in built], ins), a.fresh, {})
    base = fetch(built[0][1], seeds)
    print(fmt_summary(built[0][0] + " (基準)", summarize(base, seeds)))
    out = []
    for label, hsh, _ in built[1:]:
        res = fetch(hsh, seeds)
        p = paired(base, res, seeds)
        print(fmt_summary(label, summarize(res, seeds)))
        print("    vs 基準: " + fmt_paired(p))
        rid = record_run(label, hsh, set_name, seeds, f"compare vs {built[0][0]}", kind="compare")
        event("compare", run=rid, base=built[0][0], cand=label, set=set_name, **{k: p[k] for k in ("gain", "z", "win", "lose", "cand_err")})
        out.append((label, hsh, p, res))
    write_report()
    return built, out


# ---------------------------------------------------------------- コマンド: 昇格・提出


def read_best() -> str:
    p = board("BEST")
    return p.read_text().strip() if p.exists() else ""


def ensure_in_home(label: str, src: Path) -> str:
    """解がホームの solutions/ になければ（担当の worktree にあれば）コピーする。"""
    dst = HOME / "solutions" / label
    if src.parent.resolve() == dst.resolve():
        return label
    if dst.exists():
        if (dst / "main.cpp").read_bytes() == src.read_bytes():
            return label
        label = f"{label}-{dt.datetime.now().strftime('%m%d%H%M%S')}"
        dst = HOME / "solutions" / label
    shutil.copytree(src.parent, dst, ignore=shutil.ignore_patterns("*.out", "a.out", "*.o"))
    return label


def cmd_promote(a):
    label, src = resolve_solution(a.solution)
    if a.init or not read_best():
        label = ensure_in_home(label, src)
        board("BEST").write_text(label + "\n")
        append(board("ONE_PAGE.md"), f"- {now_iso()} 初期 BEST = `{label}`\n")
        event("promote", label=label, init=True)
        notify(f"BEST を初期化: {label}")
        return
    best = read_best()
    set_name = a.set or cfg("promote.set", "dev")
    pa = argparse.Namespace(base=best, cands=[a.solution], set=set_name, seeds=None, fresh=not a.cached, virtual=a.virtual)
    built, out = cmd_compare(pa)
    _, hsh, p, res = out[0]
    s = summarize(res, [k for k in res])
    tle = s["status"].get("TLE", 0)
    errs = sum(v for k, v in s["status"].items() if k not in ("OK", "TLE"))
    line = {
        "min_rel_gain": float(cfg("promote.min_rel_gain", 0.0)),
        "min_z": float(cfg("promote.min_z", 2.0)),
        "max_errors": int(cfg("promote.max_errors", 0)),
        "max_tle": int(cfg("promote.max_tle", 0)),
    }
    checks = {
        "gain": p["gain"] >= line["min_rel_gain"],
        "z": p["z"] >= line["min_z"],
        "errors": errs <= line["max_errors"],
        "tle": tle <= line["max_tle"],
    }
    ok = all(checks.values())
    verdict = "昇格" if ok else "見送り"
    detail = ", ".join(f"{k}:{'○' if v else '×'}" for k, v in checks.items())
    print(f"\n判定: {verdict}  ({detail})  線={line}")
    event("promote_check", cand=label, base=best, ok=ok, checks=checks, line=line, gain=p["gain"], z=p["z"], errors=errs, tle=tle)
    if ok and not a.dry_run:
        newlabel = ensure_in_home(label, src)
        board("BEST").write_text(newlabel + "\n")
        msg = f"- {now_iso()} `{best}` → `{newlabel}`  {fmt_paired(p)}  set={set_name}"
        if a.why:
            msg += f"  理由: {a.why}"
        append(board("ONE_PAGE.md"), msg + "\n")
        event("promote", label=newlabel, prev=best, gain=p["gain"], z=p["z"])
        notify(f"昇格: {best} → {newlabel} ({p['gain']*100:+.3f}%, z={p['z']:.1f})")


def cmd_handoff(a):
    label, src = resolve_solution(a.solution)
    if a.name:
        label = a.name
    readme = src.parent / "README.md"
    if not readme.exists():
        die(f"{readme} がありません。解の内容か、改良元との差分を README.md に書いてから handoff してください")
    lane = current_lane()
    if lane and not label.startswith(lane):
        label = f"{lane}-{label}"
    newlabel = ensure_in_home(label, src)
    event("handoff", label=newlabel, lane=lane, summary=a.summary or "")
    append(board("QUEUE.md"), f"- [ ] {now_iso()} `{newlabel}` from {lane or 'home'}: {a.summary or ''}\n")
    notify(f"提出（handoff）: {newlabel} ({lane or 'home'}) {a.summary or ''}")
    if not a.no_eval:
        best = read_best()
        if best and best != newlabel:
            cmd_compare(argparse.Namespace(base=best, cands=[newlabel], set=a.set, seeds=None, fresh=False, virtual=False))
        else:
            cmd_eval(argparse.Namespace(solution=newlabel, set=a.set, seeds=None, force=False, virtual=False, note="handoff"))


CPP_TOKEN = re.compile(r'//[^\n]*|/\*.*?\*/|R"([^(\s]*)\(.*?\)\1"|"(?:\\.|[^"\\\n])*"|\'(?:\\.|[^\'\\\n])*\'', re.S)


def minify_cpp(text: str) -> str:
    """コメント除去と行頭空白・空行の削除だけを行う安全側の縮小（文字列・プリプロセッサ行は壊さない）。"""
    def repl(m):
        s = m.group(0)
        if s.startswith("//"):
            return ""
        if s.startswith("/*"):
            return " " if "\n" not in s else "\n"
        return s
    text = CPP_TOKEN.sub(repl, text)
    lines = []
    for ln in text.splitlines():
        t = ln.strip()
        if not t:
            continue
        lines.append(t)
    return "\n".join(lines) + "\n"


def cmd_pack(a):
    label, src = resolve_solution(a.solution)
    text = src.read_text(encoding="utf-8")
    # 手元のヘッダを展開（提出は1ファイル）
    def inline(t: str, base: Path, seen: set) -> str:
        def rep(m):
            name = m.group(1)
            for cand in [base / name, HOME / "templates" / name]:
                if cand.exists() and cand.resolve() not in seen:
                    seen.add(cand.resolve())
                    return inline(cand.read_text(encoding="utf-8"), cand.parent, seen)
            return m.group(0)
        return INCLUDE_RE.sub(rep, t)
    text = inline(text, src.parent, set())
    text = re.sub(r"^\s*#\s*pragma\s+once\s*$", "", text, flags=re.M)
    if a.minify:
        text = minify_cpp(text)
    out = Path(a.output) if a.output else state("submit", f"{label}.cpp")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    size = out.stat().st_size
    limit = int(cfg("problem.size_limit_kib", 512)) * 1024
    # 縮小後もビルドが通り、結果が同じか確認
    hsh, binp = build(label + "-packed", out)
    print(f"{out}  {size/1024:.1f} KiB / 上限 {limit/1024:.0f} KiB  {'OK' if size <= limit else '超過!'}")
    if a.check:
        _, ins = select_inputs("smoke", None)
        ins = ins[:10]
        h0, b0 = build(label, src)
        measure([(h0, b0, i) for i in ins] + [(hsh, binp, i) for i in ins], False, {})
        r0, r1 = fetch(h0, [i.stem for i in ins]), fetch(hsh, [i.stem for i in ins])
        same = all(r0[s]["score"] == r1[s]["score"] for s in r0 if s in r1)
        print("縮小前後のスコア一致（smoke 先頭10件）:", "一致" if same else "不一致（時間依存の解なら正常な場合あり）")
    event("pack", label=label, path=str(out), size=size)
    print("提出は人間が手で行ってください（ハーネスは提出しません）。")


# ---------------------------------------------------------------- コマンド: 観察


def resolve_target(x: str, set_name, seeds_spec) -> tuple[str, str, list[str]]:
    if x.isdigit():
        r = db().execute("SELECT label, src_hash, seeds FROM runs WHERE run_id=?", (int(x),)).fetchone()
        if not r:
            die(f"run #{x} がありません")
        return r[0], r[1], json.loads(r[2])
    label, src = resolve_solution(x)
    _, ins = select_inputs(set_name, seeds_spec)
    return label, src_hash(src), [i.stem for i in ins]


def cmd_runs(a):
    rows = db().execute("SELECT run_id, label, src_hash, set_name, created, kind, lane, note FROM runs ORDER BY run_id DESC LIMIT ?", (a.limit,)).fetchall()
    for rid, label, hsh, sn, created, kind, lane, note in rows:
        seeds = json.loads(db().execute("SELECT seeds FROM runs WHERE run_id=?", (rid,)).fetchone()[0])
        s = summarize(fetch(hsh, seeds), seeds)
        t = dt.datetime.fromtimestamp(created).strftime("%m-%d %H:%M")
        print(f"#{rid:<5} {t} {kind:<7} {sn:<8} {(lane or '-'):<10} " + fmt_summary(label, s) + (f"  // {note}" if note else ""))


def cmd_cases(a):
    label, hsh, seeds = resolve_target(a.target, a.set, a.seeds)
    res = fetch(hsh, seeds)
    bk = best_known(seeds)
    ins = {p.stem: p for p in all_inputs()}
    vs = None
    if a.vs:
        vl, vh, _ = resolve_target(a.vs, a.set, a.seeds)
        vs = fetch(vh, seeds)
    rows = []
    for s in seeds:
        if s not in res:
            continue
        r = res[s]
        row = {"seed": s, "score": r["score"], "rel": rel(r["score"], bk.get(s)), "ms": r["time_ms"], "st": r["status"],
               **(features_of(ins[s]) if s in ins else {})}
        if vs and s in vs and vs[s]["score"] and r["score"]:
            d = math.log(r["score"] / vs[s]["score"])
            row["diff"] = d if maximize() else -d
        rows.append(row)
    key = {"diff": lambda r: r.get("diff", 0), "score": lambda r: r["score"] or 0, "time": lambda r: -r["ms"], "rel": lambda r: r["rel"]}[a.sort]
    rows.sort(key=key)
    if a.status:
        rows = [r for r in rows if r["st"] != "OK"]
    feats = cfg("features.header", []) or []
    head = f"{'seed':<6} {'status':<7} {'score':>14} {'rel%':>8} {'ms':>6} " + ("diff% " if vs else "") + " ".join(f"{f:>6}" for f in feats)
    print(f"{label} ({hsh})" + (f" vs {a.vs}" if vs else "") + f"  並び={a.sort}")
    print(head)
    for r in rows[: a.top]:
        print(f"{r['seed']:<6} {r['st']:<7} {r['score'] if r['score'] is not None else '-':>14} {r['rel']*100:8.3f} {r['ms']:6.0f} "
              + (f"{r.get('diff', 0)*100:+6.2f} " if vs else "")
              + " ".join(f"{r.get(f, ''):>6g}" if isinstance(r.get(f), float) else f"{'':>6}" for f in feats))


def cmd_stats(a):
    label, hsh, seeds = resolve_target(a.target, a.set, a.seeds)
    res = fetch(hsh, seeds)
    bk = best_known(seeds)
    ins = {p.stem: p for p in all_inputs()}
    vs = None
    if a.vs:
        _, vh, _ = resolve_target(a.vs, a.set, a.seeds)
        vs = fetch(vh, seeds)
    feats = [a.by] if a.by else (cfg("features.header", []) or [])
    print(f"{label} ({hsh}) 全体: " + fmt_summary("", summarize(res, seeds)))
    if vs:
        print("  vs " + a.vs + ": " + fmt_paired(paired(vs, res, seeds)))
    for f in feats:
        vals = [(features_of(ins[s]).get(f), s) for s in seeds if s in res and s in ins]
        vals = [(v, s) for v, s in vals if v is not None]
        if not vals:
            continue
        vals.sort()
        q = a.buckets
        print(f"\n[{f}] {q}分位ごと")
        for b in range(q):
            part = vals[len(vals) * b // q: len(vals) * (b + 1) // q]
            if not part:
                continue
            ss = [s for _, s in part]
            rels = [rel(res[s]["score"], bk.get(s)) for s in ss]
            line = f"  {f}∈[{part[0][0]:g},{part[-1][0]:g}] n={len(ss):<4} rel={statistics.fmean(rels)*100:7.3f}%"
            if vs:
                p = paired(vs, res, ss)
                line += f"  vs: {p['gain']*100:+.3f}% z={p['z']:+.1f}"
            print(line)


def write_report():
    """全 run の一覧を .ahc/report.html に書く（人間が流し見る用）。"""
    try:
        con = db()
        rows = con.execute("SELECT run_id, label, src_hash, set_name, created, kind, lane, note, seeds FROM runs ORDER BY run_id DESC LIMIT 300").fetchall()
        trs = []
        best = read_best()
        for rid, label, hsh, sn, created, kind, lane, note, seeds in rows:
            seeds = json.loads(seeds)
            s = summarize(fetch(hsh, seeds), seeds)
            st = " ".join(f"{k}:{v}" for k, v in sorted(s["status"].items()))
            mark = " ★" if label == best else ""
            trs.append(f"<tr><td>{rid}</td><td>{dt.datetime.fromtimestamp(created):%m-%d %H:%M}</td><td>{html.escape(kind or '')}</td>"
                       f"<td>{html.escape(sn)}</td><td>{html.escape(lane or '')}</td><td>{html.escape(label)}{mark}</td>"
                       f"<td class=n>{s['rel']*100:.4f}</td><td class=n>{s['mean']:.6g}</td><td class=n>{s['max_ms']:.0f}</td>"
                       f"<td>{html.escape(st)}</td><td>{html.escape(note or '')}</td></tr>")
        page = f"""<!doctype html><meta charset=utf-8><title>ahc report</title>
<style>body{{font:13px system-ui;margin:16px}}table{{border-collapse:collapse}}td,th{{border-bottom:1px solid #ddd;padding:3px 8px}}
.n{{text-align:right;font-variant-numeric:tabular-nums}}th{{text-align:left;background:#f4f4f4}}</style>
<h2>{html.escape(cfg('problem.name', 'ahc'))} — BEST: {html.escape(best or '-')}</h2>
<p>更新 {now_iso()}。rel は各 seed の既知最良に対する相対スコアの平均（新しい run が増えると過去の値も動く）。</p>
<table><tr><th>#</th><th>時刻</th><th>種類</th><th>集合</th><th>担当</th><th>解</th><th>rel%</th><th>mean</th><th>max ms</th><th>状態</th><th>メモ</th></tr>
{''.join(trs)}</table>"""
        state("report.html").write_text(page, encoding="utf-8")
    except Exception as e:  # レポートの失敗で評価を止めない
        print(f"ahc: report 作成失敗: {e}", file=sys.stderr)


def cmd_report(a):
    write_report()
    print(state("report.html"))


# ---------------------------------------------------------------- コマンド: 担当（lane）


def lanes_db() -> dict:
    p = state("lanes.json")
    return json.loads(p.read_text()) if p.exists() else {}


def lanes_save(d: dict):
    state("lanes.json").write_text(json.dumps(d, ensure_ascii=False, indent=1))


def sh(cmd, **kw):
    return subprocess.run(cmd, shell=isinstance(cmd, str), capture_output=True, text=True, **kw)


def cmd_lane(a):
    lanes = lanes_db()
    if a.lane_cmd == "new":
        name = a.name
        if name in lanes:
            die(f"担当 {name} は既にあります")
        wt = HOME / ".lanes" / name
        r = sh(["git", "-C", str(HOME), "worktree", "add", "-b", f"lane/{name}", str(wt), "HEAD"])
        if r.returncode != 0:
            die("git worktree add 失敗:\n" + r.stderr + "\n（ホームで一度 git commit しておく必要があります）")
        # 共有黒板と公式ツールはホームのものを見せる（worktree 側の古い写しを読まないように）
        for rel_ in ("board", "problem/tools"):
            src_, dst_ = HOME / rel_, wt / rel_
            if src_.exists():
                if dst_.is_symlink() or dst_.is_file():
                    dst_.unlink()
                elif dst_.exists():
                    shutil.rmtree(dst_)
                dst_.parent.mkdir(parents=True, exist_ok=True)
                dst_.symlink_to(src_)
        origin = a.from_ or read_best()
        if origin:
            olabel, osrc = resolve_solution(origin)
            dst = wt / "solutions" / name
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(osrc.parent, dst)
            (dst / "README.md").write_text(f"# {name}\n\n起点: `{olabel}`\n\n## 起点からの差分\n\n（ここに書く）\n", encoding="utf-8")
        tpl = (HOME / "templates" / "STRATEGY.md").read_text(encoding="utf-8")
        strategy = (tpl.replace("{name}", name).replace("{role}", a.role).replace("{angle}", a.angle or "")
                    .replace("{origin}", origin or "(なし)").replace("{hypothesis}", a.hypothesis or "")
                    .replace("{experiment}", a.experiment or "").replace("{continue_if}", a.continue_if or "")
                    .replace("{created}", now_iso()))
        (wt / "STRATEGY.md").write_text(strategy, encoding="utf-8")
        (wt / "notes.md").write_text(f"# notes: {name}\n\n（実験ごとに: 何を変えたか / 測定コマンド / 結果 / 結論）\n", encoding="utf-8")
        lanes[name] = {"path": str(wt), "role": a.role, "angle": a.angle, "origin": origin, "created": now_iso(), "agent": None}
        lanes_save(lanes)
        event("lane_new", lane=name, role=a.role, angle=a.angle, origin=origin)
        print(f"担当 {name} を作成: {wt}")
    elif a.lane_cmd == "start":
        ln = lanes.get(a.name) or die(f"担当 {a.name} がありません")
        agent = a.agent
        cmdtpl = cfg(f"agents.{agent}") or die(f"agents.{agent} が ahc.toml にありません")
        prompt = (HOME / "templates" / "lane_prompt.md").read_text(encoding="utf-8").replace("{name}", a.name).replace("{role}", ln["role"])
        pf = state("prompts", f"{a.name}.md")
        pf.parent.mkdir(parents=True, exist_ok=True)
        pf.write_text(prompt, encoding="utf-8")
        session = cfg("agents.tmux_session", "ahc")
        if sh(["tmux", "has-session", "-t", session]).returncode != 0:
            sh(["tmux", "new-session", "-d", "-s", session, "-n", "home", "-c", str(HOME)])
        cmd = cmdtpl.replace("{prompt_file}", shlex.quote(str(pf)))
        env = f"AHC_HOME={shlex.quote(str(HOME))} AHC_LANE={shlex.quote(a.name)}"
        r = sh(["tmux", "new-window", "-t", session, "-n", a.name, "-c", ln["path"], f"{env} {cmd}; exec $SHELL"])
        if r.returncode != 0:
            die("tmux new-window 失敗: " + r.stderr)
        ln["agent"] = agent
        lanes_save(lanes)
        event("lane_start", lane=a.name, agent=agent)
        print(f"担当 {a.name} を {agent} で起動（tmux {session}:{a.name}）")
    elif a.lane_cmd == "list":
        best = read_best()
        for n, ln in lanes.items():
            notes = Path(ln["path"]) / "notes.md"
            age = ""
            if notes.exists():
                age = f"notes更新 {int((time.time() - notes.stat().st_mtime) / 60)}分前"
            print(f"{n:<14} {ln['role']:<9} {(ln.get('agent') or '-'):<7} 起点={ln.get('origin') or '-':<16} {age}  観点: {ln.get('angle') or ''}")
        print(f"(BEST = {best or '-'})")
    elif a.lane_cmd == "stop":
        session = cfg("agents.tmux_session", "ahc")
        sh(["tmux", "kill-window", "-t", f"{session}:{a.name}"])
        event("lane_stop", lane=a.name)
        print(f"担当 {a.name} を停止")
    elif a.lane_cmd == "rm":
        ln = lanes.pop(a.name, None) or die(f"担当 {a.name} がありません")
        session = cfg("agents.tmux_session", "ahc")
        sh(["tmux", "kill-window", "-t", f"{session}:{a.name}"])
        # notes と STRATEGY は消す前に保存しておく
        arch = HOME / "board" / "lanes" / a.name
        arch.mkdir(parents=True, exist_ok=True)
        for f in ("STRATEGY.md", "notes.md"):
            p = Path(ln["path"]) / f
            if p.exists():
                shutil.copy(p, arch / f)
        sh(["git", "-C", str(HOME), "worktree", "remove", "--force", ln["path"]])
        lanes_save(lanes)
        event("lane_rm", lane=a.name)
        print(f"担当 {a.name} を削除（notes は board/lanes/{a.name}/ に保存、ブランチ lane/{a.name} は残す）")


def cmd_pump(a):
    """返答が終わって止まっている担当に続行の文を送る。長く進まない担当は通知する。"""
    session = cfg("agents.tmux_session", "ahc")
    msg = a.message or cfg("agents.continue_message")
    idle_n = int(cfg("agents.idle_cycles", 2))
    stall_n = int(cfg("agents.stall_cycles", 10))
    sp = state("pump.json")
    seen: dict = json.loads(sp.read_text()) if sp.exists() else {}
    if not a.once:
        print(f"pump: session={session} interval={a.interval}s（Ctrl-C で終了）")
    while True:
        lanes = lanes_db()
        for name in lanes:
            r = sh(["tmux", "capture-pane", "-p", "-t", f"{session}:{name}"])
            if r.returncode != 0:
                continue
            h = hashlib.md5(r.stdout.encode()).hexdigest()
            prev, cnt = seen.get(name, ["", 0])
            cnt = cnt + 1 if h == prev else 0
            seen[name] = [h, cnt]
            if cnt == idle_n:
                sh(["tmux", "send-keys", "-t", f"{session}:{name}", "-l", msg])
                time.sleep(0.5)
                sh(["tmux", "send-keys", "-t", f"{session}:{name}", "Enter"])
                event("pump_continue", lane=name)
                print(f"[{now_iso()}] 続行を送信: {name}")
            elif cnt == stall_n:
                notify(f"担当 {name} が {stall_n * a.interval // 60} 分ほど画面が変わりません（確認待ち・停止の可能性）")
        sp.write_text(json.dumps(seen))
        if a.once:
            break
        time.sleep(a.interval)


# ---------------------------------------------------------------- コマンド: 黒板


def next_id(path: Path, prefix: str) -> str:
    n = 0
    if path.exists():
        for m in re.finditer(rf"\b{prefix}(\d+)\b", path.read_text(encoding="utf-8")):
            n = max(n, int(m.group(1)))
    return f"{prefix}{n + 1:03d}"


def cmd_idea(a):
    p = board("IDEA_STOCK.md")
    if a.idea_cmd == "add":
        i = next_id(p, "I")
        src = a.source or current_lane() or "home"
        append(p, f"- [ ] **{i}** ({now_iso()}, {src}) {a.text}\n")
        event("idea", id=i, text=a.text, source=src)
        print(i)
    elif a.idea_cmd == "list":
        if p.exists():
            for ln in p.read_text(encoding="utf-8").splitlines():
                if ln.startswith("- [ ]") or a.all:
                    print(ln)
    elif a.idea_cmd == "take":
        text = p.read_text(encoding="utf-8")
        new = re.sub(rf"^- \[ \] \*\*{a.id}\*\*(.*)$", rf"- [x] **{a.id}**\1 → {a.lane}", text, flags=re.M)
        p.write_text(new, encoding="utf-8")
        event("idea_take", id=a.id, lane=a.lane)


def cmd_reject(a):
    p = board("REJECTED.md")
    i = next_id(p, "R")
    src = current_lane() or "home"
    append(p, f"\n### {i} {a.text}\n- 日時/担当: {now_iso()} / {src}\n- 根拠: {a.reason}\n- 再開の条件: {a.reopen_if or '（未記入）'}\n")
    event("reject", id=i, text=a.text, reason=a.reason)
    print(i)


def cmd_decide(a):
    append(board("decisions.md"), f"\n## {now_iso()} ({current_lane() or 'conductor'})\n{a.text}\n")
    event("decision", text=a.text)


def cmd_notify(a):
    notify(" ".join(a.message))


def cmd_status(a):
    best = read_best()
    print(f"問題: {cfg('problem.name')}  目的: {cfg('problem.objective')}  BEST: {best or '-'}")
    if best:
        try:
            _, src = resolve_solution(best)
            hsh = src_hash(src)
            for sn in cfg("eval.sets", {}):
                _, ins = select_inputs(sn, None)
                seeds = [i.stem for i in ins]
                res = fetch(hsh, seeds)
                if res:
                    print("  " + fmt_summary(f"BEST@{sn}", summarize(res, seeds)))
        except SystemExit:
            pass
    q = board("QUEUE.md")
    if q.exists():
        pending = [l for l in q.read_text(encoding="utf-8").splitlines() if l.startswith("- [ ]")]
        print(f"未判定の提出: {len(pending)}")
        for l in pending[-5:]:
            print("  " + l)
    ip = board("IDEA_STOCK.md")
    if ip.exists():
        t = ip.read_text(encoding="utf-8")
        print(f"案の在庫: 未着手 {t.count('- [ ]')} / 着手済 {t.count('- [x]')}")
    print("担当:")
    a2 = argparse.Namespace(lane_cmd="list")
    cmd_lane(a2)
    print("最近の run:")
    cmd_runs(argparse.Namespace(limit=5))


def cmd_gen(a):
    out_dir = HOME / (a.out or cfg("tools.input_dir"))
    out_dir.mkdir(parents=True, exist_ok=True)
    seeds_file = state("seeds.txt")
    seeds_file.write_text("\n".join(str(s) for s in range(a.start, a.start + a.count)) + "\n")
    cmd = cfg("tools.gen_cmd").replace("{seeds}", shlex.quote(str(seeds_file))).replace("{out_dir}", shlex.quote(str(out_dir)))
    r = subprocess.run(cmd, shell=True, cwd=HOME)
    if r.returncode != 0:
        die("gen_cmd が失敗しました")
    print(f"{out_dir} に {a.count} 件生成")


def cmd_init(a):
    for name, body in {
        "BRIEF.md": "# BRIEF（全担当への方針）\n\n- 目標:\n- いまの BEST:\n- 優先する観点:\n",
        "CONSTRAINTS.md": "# CONSTRAINTS（共有の制約）\n\n- 時間制限・サイズ上限・使ってよい資源\n- 提出は人間のみ\n",
        "IDEA_STOCK.md": "# 案の在庫\n\n",
        "REJECTED.md": "# 否定のカード（棄却した案と再開の条件）\n",
        "decisions.md": "# 判断の記録\n",
        "ONE_PAGE.md": "# ONE PAGE（昇格の履歴）\n\n",
        "QUEUE.md": "# 未判定の提出\n\n",
    }.items():
        p = board(name)
        if not p.exists():
            p.write_text(body, encoding="utf-8")
    (HOME / "solutions").mkdir(exist_ok=True)
    if not (HOME / ".git").exists():
        sh(["git", "-C", str(HOME), "init", "-q"])
    print(f"初期化しました: {HOME}")


# ---------------------------------------------------------------- 引数


def main():
    ap = argparse.ArgumentParser(prog="ahc", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)

    def add_set(p):
        p.add_argument("--set", help="テスト集合名（ahc.toml の eval.sets）")
        p.add_argument("--seeds", help="入力インデックス範囲（例 0-99,200-249）。--set より優先")

    p = sp.add_parser("init", help="board/ などを作る")
    p.set_defaults(f=cmd_init)

    p = sp.add_parser("gen", help="公式 gen で入力を作る")
    p.add_argument("count", type=int)
    p.add_argument("--start", type=int, default=0)
    p.add_argument("--out")
    p.set_defaults(f=cmd_gen)

    p = sp.add_parser("eval", help="解を評価して記録")
    p.add_argument("solution")
    add_set(p)
    p.add_argument("--force", action="store_true", help="記録があっても再測定")
    p.add_argument("--virtual", action="store_true", help="仮想時計版でビルド")
    p.add_argument("--note")
    p.set_defaults(f=cmd_eval)

    p = sp.add_parser("compare", help="基準と候補をケースごとに交互に測って比べる")
    p.add_argument("base")
    p.add_argument("cands", nargs="+")
    add_set(p)
    p.add_argument("--fresh", action="store_true", help="同じ回の中で全部測り直す（時間依存の解はこれ）")
    p.add_argument("--virtual", action="store_true")
    p.set_defaults(f=cmd_compare)

    p = sp.add_parser("promote", help="登録済みの線で BEST への昇格を判定")
    p.add_argument("solution")
    p.add_argument("--set")
    p.add_argument("--init", action="store_true", help="判定せずに BEST にする（最初の1本）")
    p.add_argument("--cached", action="store_true", help="再測定せず記録を使う")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--virtual", action="store_true")
    p.add_argument("--why", help="昇格の理由（ONE_PAGE に残る）")
    p.set_defaults(f=cmd_promote)

    p = sp.add_parser("handoff", help="担当の改善版をホームへ提出（README.md 必須）")
    p.add_argument("solution")
    p.add_argument("--name")
    p.add_argument("--summary", "-m")
    p.add_argument("--set", default="select")
    p.add_argument("--no-eval", action="store_true")
    p.set_defaults(f=cmd_handoff)

    p = sp.add_parser("pack", help="提出用1ファイルを作る（ヘッダ展開・縮小・サイズ確認）")
    p.add_argument("solution")
    p.add_argument("-o", "--output")
    p.add_argument("--minify", action="store_true")
    p.add_argument("--check", action="store_true", help="縮小前後のスコア一致を確認")
    p.set_defaults(f=cmd_pack)

    p = sp.add_parser("runs", help="run の一覧")
    p.add_argument("--limit", type=int, default=20)
    p.set_defaults(f=cmd_runs)

    p = sp.add_parser("cases", help="ケースごとの結果（AI 向けのテキストのビジュアライザ）")
    p.add_argument("target", help="run 番号 または 解")
    p.add_argument("--vs")
    add_set(p)
    p.add_argument("--sort", choices=["diff", "score", "time", "rel"], default="rel")
    p.add_argument("--top", type=int, default=30)
    p.add_argument("--status", action="store_true", help="OK 以外だけ")
    p.set_defaults(f=cmd_cases)

    p = sp.add_parser("stats", help="入力の特徴量ごとの成績")
    p.add_argument("target")
    p.add_argument("--vs")
    add_set(p)
    p.add_argument("--by")
    p.add_argument("--buckets", type=int, default=4)
    p.set_defaults(f=cmd_stats)

    p = sp.add_parser("report", help=".ahc/report.html を作る")
    p.set_defaults(f=cmd_report)

    p = sp.add_parser("lane", help="担当（git worktree + tmux 窓）の管理")
    lsp = p.add_subparsers(dest="lane_cmd", required=True)
    q = lsp.add_parser("new")
    q.add_argument("name")
    q.add_argument("--role", default="worker", choices=["worker", "free", "merger", "analyst", "critic", "advisor"])
    q.add_argument("--angle", help="観点（gap / state / new / neighbor / speedup など）")
    q.add_argument("--from", dest="from_", help="起点の解（省略時 BEST）")
    q.add_argument("--hypothesis")
    q.add_argument("--experiment", help="最小の実験")
    q.add_argument("--continue-if", help="続ける条件")
    q = lsp.add_parser("start")
    q.add_argument("name")
    q.add_argument("--agent", default="claude", help="ahc.toml の agents.<名前>")
    lsp.add_parser("list")
    q = lsp.add_parser("stop")
    q.add_argument("name")
    q = lsp.add_parser("rm")
    q.add_argument("name")
    p.set_defaults(f=cmd_lane)

    p = sp.add_parser("pump", help="止まった担当に続行を送る（配送係）")
    p.add_argument("--interval", type=int, default=90)
    p.add_argument("--once", action="store_true")
    p.add_argument("--message")
    p.set_defaults(f=cmd_pump)

    p = sp.add_parser("idea", help="案の在庫")
    isp = p.add_subparsers(dest="idea_cmd", required=True)
    q = isp.add_parser("add")
    q.add_argument("text")
    q.add_argument("--source")
    q = isp.add_parser("list")
    q.add_argument("--all", action="store_true")
    q = isp.add_parser("take")
    q.add_argument("id")
    q.add_argument("--lane", required=True)
    p.set_defaults(f=cmd_idea)

    p = sp.add_parser("reject", help="否定のカードを書く")
    p.add_argument("text")
    p.add_argument("--reason", required=True)
    p.add_argument("--reopen-if")
    p.set_defaults(f=cmd_reject)

    p = sp.add_parser("decide", help="判断を decisions.md に残す")
    p.add_argument("text")
    p.set_defaults(f=cmd_decide)

    p = sp.add_parser("notify", help="人間へ通知")
    p.add_argument("message", nargs="+")
    p.set_defaults(f=cmd_notify)

    p = sp.add_parser("status", help="全体の状況")
    p.set_defaults(f=cmd_status)

    a = ap.parse_args()
    load()
    a.f(a)


if __name__ == "__main__":
    main()
