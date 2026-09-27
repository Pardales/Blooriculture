"""Regression check: play a candidate against every variant we have kept.

    python tools/roundrobin.py                    # main.py vs all of variants/*.py
    python tools/roundrobin.py -n 5               # 5 seeds each (10 episodes per pair)
    python tools/roundrobin.py --cand variants/x.py

Every pair runs each seed in both seat orders, so seat bias cancels. Five seeds
is a smoke test, not an acceptance test: with per-episode sigma around $15k the
95% interval on a 10-episode margin is roughly +/- $9k, so treat anything inside
that as "no signal" and re-run the promising ones through sweep.py at n>=80.
"""
import argparse
import glob
import os
import statistics
import sys
import warnings
from concurrent.futures import ProcessPoolExecutor

warnings.filterwarnings("ignore")
sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bench import _run_one  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cand", default="main.py", help="agent under test")
    ap.add_argument("--others", default="variants/*.py", help="glob of opponents")
    ap.add_argument("-n", "--seeds", type=int, default=5)
    ap.add_argument("--seed0", type=int, default=2000)
    ap.add_argument("--steps", type=int, default=720)
    ap.add_argument("-w", "--workers", type=int, default=max(1, (os.cpu_count() or 4) - 2))
    ap.add_argument("--extra", nargs="*", default=["starter"],
                    help="builtin agents to also play (pass/random/starter)")
    args = ap.parse_args()

    cand = os.path.abspath(args.cand)
    opponents = []
    for p in sorted(glob.glob(args.others)):
        ap_ = os.path.abspath(p)
        if ap_ != cand and "/sweep/" not in p.replace("\\", "/"):
            opponents.append(ap_)
    opponents.extend(args.extra or [])

    if not opponents:
        sys.exit("no opponents found")

    jobs = []
    for opp in opponents:
        for i in range(args.seeds):
            seed = args.seed0 + i
            jobs.append((seed, 0, cand, opp, args.steps))
            jobs.append((seed, 1, cand, opp, args.steps))

    print(f"candidate : {os.path.basename(args.cand)}")
    print(f"opponents : {', '.join(os.path.basename(str(o)) for o in opponents)}")
    print(f"{len(jobs)} episodes ({args.seeds} seeds x 2 orders x {len(opponents)} opponents)\n")

    results = {}
    done = 0
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        for job, res in zip(jobs, ex.map(_run_one, jobs)):
            results.setdefault(job[3], []).append(res)
            done += 1
            if done % 5 == 0 or done == len(jobs):
                print(f"  {done}/{len(jobs)}", end="\r", flush=True)
    print()

    print(f"{'OPPONENT':<26} {'W-L-T':>9} {'win%':>6} {'margin':>10} {'+/-95%':>9} {'our mean':>10}")
    print("-" * 76)
    all_margins = []
    all_mine = []
    total_w = total_n = 0
    for opp in opponents:
        rs = [r for r in results.get(opp, []) if r[2] is not None and r[4] is None]
        name = os.path.basename(str(opp))
        if not rs:
            print(f"{name:<26} {'FAILED':>9}")
            continue
        margins = [r[2] - r[3] for r in rs]
        mine = [r[2] for r in rs]
        w = sum(1 for m in margins if m > 0)
        l = sum(1 for m in margins if m < 0)
        t = len(margins) - w - l
        se = statistics.stdev(margins) / len(margins) ** 0.5 if len(margins) > 1 else 0.0
        all_margins.extend(margins)
        all_mine.extend(mine)
        total_w += w
        total_n += len(margins)
        print(f"{name:<26} {f'{w}-{l}-{t}':>9} {100.0*w/len(rs):>5.0f}% "
              f"{statistics.mean(margins):>10,.0f} {1.96*se:>9,.0f} {statistics.mean(mine):>10,.0f}")

    if all_margins:
        se = statistics.stdev(all_margins) / len(all_margins) ** 0.5
        print("-" * 76)
        print(f"{'OVERALL':<26} {'':>9} {100.0*total_w/total_n:>5.0f}% "
              f"{statistics.mean(all_margins):>10,.0f} {1.96*se:>9,.0f} "
              f"{statistics.mean(all_mine):>10,.0f}")
        print(f"\n  n={len(all_margins)} episodes. Anything inside +/-95% is noise -- "
              f"confirm with sweep.py at n>=80.")


if __name__ == "__main__":
    main()
