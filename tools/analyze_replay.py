"""Reverse-engineer what each player did in a Kaggriculture replay.

    python tools/analyze_replay.py replays/episode-113201739-replay.json
    python tools/analyze_replay.py replays/*.json --brief

Prints, per player: money curve, tile composition by day, land/hire timing,
market order totals, revenue by product, and an action histogram.
"""
import argparse
import glob
import json
import sys
from collections import Counter, defaultdict

sys.stdout.reconfigure(encoding="utf-8")

PRODUCTS = ["WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON", "EGG", "MILK", "WOOL", "FERTILIZER"]
TPD = 24


def tile_census(tiles):
    """Count what is growing / standing on a farm."""
    c = Counter()
    for row in tiles:
        for t in row:
            if t is None:
                c["EMPTY"] += 1
            elif t == "LOCKED":
                c["LOCKED"] += 1
            elif isinstance(t, dict):
                k = t.get("kind")
                if k == "PLANT":
                    c[t.get("crop", "PLANT?")] += 1
                elif k == "WEED":
                    c["WEED"] += 1
                elif k in ("COOP", "PASTURE"):
                    a = t.get("animal")
                    c[a if a else f"{k}_EMPTY"] += 1
    return c


def analyze(path, brief=False):
    with open(path, encoding="utf-8") as f:
        rep = json.load(f)

    names = rep.get("info", {}).get("TeamNames") or ["P0", "P1"]
    rewards = rep.get("rewards", [])
    steps = rep["steps"]
    cfg = rep.get("configuration", {})
    tpd = cfg.get("turnsPerDay", TPD)

    print("=" * 84)
    print(f"{path}")
    print(f"  {names[0]}  =  {rewards[0] if rewards else '?':,}"
          f"   |   {names[1]}  =  {rewards[1] if len(rewards) > 1 else '?':,}")
    print("=" * 84)

    # ---- per-player accumulators -------------------------------------------
    orders = [Counter(), Counter()]            # op -> count
    sold_units = [Counter(), Counter()]        # product -> units ordered
    bought_units = [Counter(), Counter()]
    acts = [Counter(), Counter()]              # farmer/hand op -> count
    hires = [Counter(), Counter()]             # day -> hires
    land_days = [[], []]
    money_by_day = [dict(), dict()]
    census_by_day = [dict(), dict()]
    hands_by_day = [defaultdict(int), defaultdict(int)]
    unit_actions = [0, 0]

    prev_money = [None, None]
    revenue_by_product = [Counter(), Counter()]  # inferred from sell orders x price

    for si, step in enumerate(steps):
        obs = step[0]["observation"]
        day = obs.get("day", si // tpd)
        farms = obs.get("farms") or []
        prices = (obs.get("market") or {}).get("prices") or {}

        for p in (0, 1):
            if p < len(farms) and farms[p]:
                farm = farms[p]
                money_by_day[p][day] = farm.get("money")
                census_by_day[p][day] = tile_census(farm.get("tiles") or [])
                hands_by_day[p][day] = max(hands_by_day[p][day], len(farm.get("hands") or []))

            act = step[p].get("action") or {}
            if not isinstance(act, dict):
                continue

            f = act.get("farmer")
            if isinstance(f, list) and f:
                acts[p][f[0]] += 1
                unit_actions[p] += 1
            for h in (act.get("hands") or []):
                if isinstance(h, list) and h:
                    acts[p][h[0]] += 1
                    unit_actions[p] += 1

            for o in (act.get("market") or [])[:cfg.get("maxMarketOrdersPerTurn", 10)]:
                if not isinstance(o, list) or not o:
                    continue
                op = o[0]
                orders[p][op] += 1
                if op == "SELL" and len(o) >= 3:
                    item, n = o[1], o[2]
                    try:
                        n = int(n)
                    except (TypeError, ValueError):
                        n = 1
                    sold_units[p][item] += n
                    # Approximate: quote the pre-sell price for the whole batch.
                    revenue_by_product[p][item] += n * prices.get(item, 0)
                elif op in ("BUY_SEED", "BUY_ANIMAL", "BUY_PRODUCT") and len(o) >= 3:
                    try:
                        bought_units[p][o[1]] += int(o[2])
                    except (TypeError, ValueError):
                        bought_units[p][o[1]] += 1
                elif op == "HIRE":
                    hires[p][day] += 1
                elif op == "BUY_LAND":
                    land_days[p].append((day, obs.get("hour", 0)))

    # ---- report -------------------------------------------------------------
    for p in (0, 1):
        print(f"\n--- P{p}  {names[p]}   final ${rewards[p]:,}" if rewards else f"\n--- P{p} {names[p]}")
        days = sorted(money_by_day[p])

        print("  Money by day:")
        line = "   "
        for d in days:
            if d % 2 == 0:
                line += f" d{d:02d}:{money_by_day[p][d]/1000:>6.1f}k"
            if len(line) > 92:
                print(line)
                line = "   "
        if line.strip():
            print(line)

        print(f"  Land bought : {land_days[p] if land_days[p] else 'never'}")
        tot_hires = sum(hires[p].values())
        peak = max(hands_by_day[p].values()) if hands_by_day[p] else 0
        print(f"  Hires       : {tot_hires} total, peak {peak} hands in a day, "
              f"{tot_hires / max(1, len(days)):.1f}/day avg")
        print(f"  Unit actions: {unit_actions[p]:,}")

        print("  Farm composition (day -> counts, every 3rd day):")
        for d in days:
            if d % 3 or d == 0:
                continue
            c = census_by_day[p][d]
            parts = [f"{k}={v}" for k, v in c.most_common() if k not in ("LOCKED",) and v]
            print(f"    d{d:02d}: {' '.join(parts)}")

        print("  Market orders:", dict(orders[p].most_common()))
        if sold_units[p]:
            print("  SELL units ordered:")
            tot = sum(revenue_by_product[p].values())
            for item, n in sold_units[p].most_common():
                rev = revenue_by_product[p][item]
                share = 100.0 * rev / tot if tot else 0
                print(f"    {item:<12s} {n:>6,} units   ~${rev:>9,}  ({share:4.1f}% of gross)")
            print(f"    {'TOTAL':<12s} {sum(sold_units[p].values()):>6,} units   ~${tot:>9,}")
        if bought_units[p]:
            print("  BUY units ordered:", dict(bought_units[p].most_common()))
        if not brief:
            print("  Unit action histogram:", dict(acts[p].most_common()))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--brief", action="store_true")
    args = ap.parse_args()
    files = []
    for pat in args.paths:
        files.extend(sorted(glob.glob(pat)) or [pat])
    for f in files:
        try:
            analyze(f, args.brief)
        except Exception as exc:  # noqa: BLE001
            print(f"FAILED {f}: {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    main()
