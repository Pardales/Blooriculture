"""Parallel local benchmark for Kaggriculture agents.

Runs N seeds of A-vs-B, playing every seed in BOTH seat orders so seat bias
cancels out, and reports win rate plus the absolute money distribution.

    python tools/bench.py main.py starter -n 20
    python tools/bench.py main.py variants/v4.py -n 30
    python tools/bench.py main.py --self -n 20

Agents are file paths, or one of the built-ins: pass, random, starter.
"""
import argparse
import json
import os
import statistics
import sys
import time
import warnings
from concurrent.futures import ProcessPoolExecutor

warnings.filterwarnings("ignore")

BUILTINS = {"pass", "random", "starter"}


def _run_one(job):
    """Run a single episode. Returns (seed, order, reward_a, reward_b, err)."""
    import warnings as _w
    _w.filterwarnings("ignore")
    seed, order, agent_a, agent_b, steps = job
    try:
        # Silence the env's import-time env listing.
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            from kaggle_environments import make
            cfg = {"episodeSteps": steps}
            if seed is not None:
                cfg["seed"] = seed
            env = make("kaggriculture", configuration=cfg, debug=False)
            pair = [agent_a, agent_b] if order == 0 else [agent_b, agent_a]
            env.run(pair)
        final = env.steps[-1]
        r0 = final[0]["reward"]
        r1 = final[1]["reward"]
        s0 = final[0]["status"]
        s1 = final[1]["status"]
        # Map back to A/B regardless of seat.
        if order == 0:
            ra, rb, sa, sb = r0, r1, s0, s1
        else:
            ra, rb, sa, sb = r1, r0, s1, s0
        err = None
        if sa != "DONE" or sb != "DONE":
            err = f"status A={sa} B={sb}"
        return (seed, order, ra, rb, err)
    except Exception as exc:  # noqa: BLE001
        return (seed, order, None, None, f"{type(exc).__name__}: {exc}")


def resolve(a):
    if a in BUILTINS:
        return a
    p = os.path.abspath(a)
    if not os.path.exists(p):
        sys.exit(f"agent not found: {a}")
    return p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("agent_a")
    ap.add_argument("agent_b", nargs="?", default="starter")
    ap.add_argument("-n", "--seeds", type=int, default=10, help="distinct seeds (each played twice)")
    ap.add_argument("--steps", type=int, default=720)
    ap.add_argument("--seed0", type=int, default=1000, help="first seed value")
    ap.add_argument("-w", "--workers", type=int, default=max(1, (os.cpu_count() or 4) - 2))
    ap.add_argument("--self", action="store_true", help="agent_b = agent_a")
    ap.add_argument("--json", default=None, help="write raw results to this path")
    ap.add_argument("--label", default=None, help="label for the results file")
    args = ap.parse_args()

    a = resolve(args.agent_a)
    b = resolve(args.agent_a if args.self else args.agent_b)

    jobs = []
    for i in range(args.seeds):
        seed = args.seed0 + i
        jobs.append((seed, 0, a, b, args.steps))
        jobs.append((seed, 1, a, b, args.steps))

    name_a = os.path.basename(args.agent_a)
    name_b = os.path.basename(args.agent_a if args.self else args.agent_b)
    print(f"A = {name_a}")
    print(f"B = {name_b}")
    print(f"{len(jobs)} episodes ({args.seeds} seeds x 2 seat orders), {args.workers} workers\n")

    t0 = time.time()
    results = []
    done = 0
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        for res in ex.map(_run_one, jobs):
            results.append(res)
            done += 1
            if done % 5 == 0 or done == len(jobs):
                el = time.time() - t0
                rate = done / el if el else 0
                eta = (len(jobs) - done) / rate if rate else 0
                print(f"  {done}/{len(jobs)}  {el:5.1f}s elapsed  ~{eta:4.0f}s left", end="\r", flush=True)
    print()
    elapsed = time.time() - t0

    ok = [r for r in results if r[2] is not None and r[4] is None]
    bad = [r for r in results if r[2] is None or r[4] is not None]

    if bad:
        print(f"\n!! {len(bad)} episodes had problems:")
        seen = set()
        for seed, order, ra, rb, err in bad[:10]:
            if err not in seen:
                print(f"   seed={seed} order={order}: {err}")
                seen.add(err)

    if not ok:
        sys.exit("no clean episodes")

    wins = sum(1 for _, _, ra, rb, _ in ok if ra > rb)
    losses = sum(1 for _, _, ra, rb, _ in ok if ra < rb)
    ties = sum(1 for _, _, ra, rb, _ in ok if ra == rb)
    n = len(ok)
    ra_all = [r[2] for r in ok]
    rb_all = [r[3] for r in ok]
    margins = [r[2] - r[3] for r in ok]

    print("\n" + "=" * 70)
    print(f"RESULT  {name_a}  vs  {name_b}")
    print("=" * 70)
    print(f"  Episodes   : {n} clean / {len(results)} run   ({elapsed:.0f}s, {elapsed/len(results):.1f}s per ep)")
    wr = 100.0 * wins / n
    # Wald 95% interval on the win rate; good enough to see if a delta is real.
    se = (wr * (100 - wr) / n) ** 0.5
    print(f"  Record     : {wins}W - {losses}L - {ties}T   win rate {wr:.1f}% +/- {1.96*se:.1f}")
    print(f"  A money    : mean {statistics.mean(ra_all):>10,.0f}   median {statistics.median(ra_all):>10,.0f}"
          f"   min {min(ra_all):>9,.0f}  max {max(ra_all):>9,.0f}")
    print(f"  B money    : mean {statistics.mean(rb_all):>10,.0f}   median {statistics.median(rb_all):>10,.0f}"
          f"   min {min(rb_all):>9,.0f}  max {max(rb_all):>9,.0f}")
    print(f"  Margin     : mean {statistics.mean(margins):>10,.0f}   median {statistics.median(margins):>10,.0f}")
    if n > 1:
        print(f"  A stdev    : {statistics.stdev(ra_all):,.0f}")

    # Seat split — exposes any first/second-player advantage.
    for order, lbl in ((0, "A seated P0"), (1, "A seated P1")):
        sub = [r for r in ok if r[1] == order]
        if sub:
            w = sum(1 for _, _, x, y, _ in sub if x > y)
            print(f"  {lbl}: {w}/{len(sub)} wins, A mean {statistics.mean([r[2] for r in sub]):,.0f}")

    out = args.json
    if args.label and not out:
        out = os.path.join("bench-results", f"{args.label}.json")
    if out:
        os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            json.dump({
                "agent_a": name_a, "agent_b": name_b, "seeds": args.seeds, "steps": args.steps,
                "wins": wins, "losses": losses, "ties": ties,
                "a_mean": statistics.mean(ra_all), "b_mean": statistics.mean(rb_all),
                "margin_mean": statistics.mean(margins),
                "episodes": [{"seed": s, "order": o, "a": x, "b": y} for s, o, x, y, _ in ok],
            }, f, indent=2)
        print(f"\n  wrote {out}")


if __name__ == "__main__":
    main()
