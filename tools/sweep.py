"""Sweep one or more constants against a fixed reference agent.

    python tools/sweep.py --ref variants/v3_nopace.py -n 12 CARE_BID=1.15,2.0,3.0,5.0
    python tools/sweep.py --ref variants/v3_nopace.py -n 12 MAX_HANDS=13,16,20

Each value becomes a variant of main.py, benchmarked against the reference in
both seat orders on the same seeds. Prints a table sorted by mean margin.
"""
import argparse
import itertools
import os
import statistics
import subprocess
import sys
import warnings

warnings.filterwarnings("ignore")
sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bench import _run_one, resolve  # noqa: E402
from concurrent.futures import ProcessPoolExecutor  # noqa: E402

VAR_DIR = "variants/sweep"


def make_variant(path, assignments):
    cmd = [sys.executable, "tools/mkvariant.py", path] + [f"{k}={v}" for k, v in assignments]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"mkvariant failed: {r.stdout}{r.stderr}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("specs", nargs="+", help="NAME=v1,v2,v3")
    ap.add_argument("--ref", default="variants/v3_nopace.py")
    ap.add_argument("-n", "--seeds", type=int, default=12)
    ap.add_argument("--seed0", type=int, default=1000)
    ap.add_argument("--steps", type=int, default=720)
    ap.add_argument("-w", "--workers", type=int, default=max(1, (os.cpu_count() or 4) - 2))
    args = ap.parse_args()

    names, valsets = [], []
    for spec in args.specs:
        k, vs = spec.split("=", 1)
        names.append(k.strip())
        valsets.append([v.strip() for v in vs.split(",")])

    combos = list(itertools.product(*valsets))
    os.makedirs(VAR_DIR, exist_ok=True)
    ref = resolve(args.ref)

    jobs, tags = [], []
    for combo in combos:
        tag = "_".join(f"{n}{v}" for n, v in zip(names, combo)).replace(".", "p")
        path = os.path.join(VAR_DIR, f"{tag}.py")
        make_variant(path, list(zip(names, combo)))
        tags.append((tag, combo, os.path.abspath(path)))
        for i in range(args.seeds):
            seed = args.seed0 + i
            jobs.append((seed, 0, os.path.abspath(path), ref, args.steps))
            jobs.append((seed, 1, os.path.abspath(path), ref, args.steps))

    print(f"{len(combos)} configs x {args.seeds} seeds x 2 orders = {len(jobs)} episodes")
    print(f"reference: {os.path.basename(ref)}\n")

    results = {}
    done = 0
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        for job, res in zip(jobs, ex.map(_run_one, jobs)):
            key = job[2]
            results.setdefault(key, []).append(res)
            done += 1
            if done % 10 == 0 or done == len(jobs):
                print(f"  {done}/{len(jobs)}", end="\r", flush=True)
    print()

    rows = []
    for tag, combo, path in tags:
        rs = [r for r in results.get(path, []) if r[2] is not None and r[4] is None]
        if not rs:
            rows.append((tag, combo, None, None, None, 0))
            continue
        margins = [r[2] - r[3] for r in rs]
        mine = [r[2] for r in rs]
        wins = sum(1 for m in margins if m > 0)
        # Standard error of the mean margin. Episode-to-episode spread here is
        # huge (sigma ~15k), so without this it is very easy to read noise as a
        # result: at n=28 a "+4k improvement" is well inside one 95% interval.
        se = statistics.stdev(margins) / (len(margins) ** 0.5) if len(margins) > 1 else 0.0
        rows.append((tag, combo, statistics.mean(margins), statistics.mean(mine),
                     100.0 * wins / len(rs), len(rs), se))

    rows.sort(key=lambda r: (r[2] is None, -(r[2] or 0)))
    hdr = "  ".join(f"{n:>12}" for n in names)
    print(f"{hdr}  {'margin':>10} {'+/-95%':>9} {'our mean':>10} {'win%':>6} {'n':>4}  sig")
    print("-" * (len(hdr) + 52))
    for tag, combo, margin, mine, wr, n, se in rows:
        vals = "  ".join(f"{v:>12}" for v in combo)
        if margin is None:
            print(f"{vals}  {'FAILED':>10}")
            continue
        ci = 1.96 * se
        sig = "**" if abs(margin) > ci and ci > 0 else "  "
        print(f"{vals}  {margin:>10,.0f} {ci:>9,.0f} {mine:>10,.0f} {wr:>5.0f}% {n:>4}  {sig}")
    print("\n  ** = mean margin exceeds its own 95% interval (i.e. probably real).")


if __name__ == "__main__":
    main()
