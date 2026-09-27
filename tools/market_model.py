"""Quantify the Kaggriculture market: how much money each product can actually pay.

Two things decide what a farm is worth:
  1. the glut curve  -- dumping units crashes the price, hard for premium goods;
  2. the town drain  -- shops eat inventory for free, which pulls the price back
     up and *regenerates* selling capacity all season.

This prints, per product: the standing absorption before the price floors, the
expected season-long town drain, and the revenue of realistic sell schedules.

    python tools/market_model.py
"""
import math
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8")

I0 = 10000
PRICE_FLOOR = 1
HINGE_GAIN = 8.0

MARKET_PARAMS = {
    "WHEAT":      {"base":  25, "T": 400, "bf": "sqrt",   "bt": 0.80, "af": "log",    "at": 0.20},
    "CARROT":     {"base":  35, "T": 450, "bf": "hinge",  "bt": 1.00, "af": "sqrt",   "at": 0.70},
    "TOMATO":     {"base":  60, "T": 200, "bf": "hinge",  "bt": 0.40, "af": "sqrt",   "at": 0.60},
    "STRAWBERRY": {"base": 120, "T": 100, "bf": "sqrt",   "bt": 0.70, "af": "linear", "at": 1.60},
    "MELON":      {"base": 250, "T": 300, "bf": "log",    "bt": 0.20, "af": "sq",     "at": 3.60},
    "EGG":        {"base":  50, "T": 332, "bf": "hinge",  "bt": 0.40, "af": "log",    "at": 0.20},
    "MILK":       {"base": 160, "T": 122, "bf": "sqrt",   "bt": 0.60, "af": "linear", "at": 1.60},
    "WOOL":       {"base": 200, "T": 105, "bf": "log",    "bt": 0.20, "af": "sq",     "at": 3.20},
    "FERTILIZER": {"base": 100, "T": 200, "bf": "linear", "bt": 0.40, "af": "linear", "at": 0.40},
}

SHOPS = {
    "BAKERY":         ["EGG", "WHEAT"],
    "PIZZA_SHOP":     ["MILK", "TOMATO", "WHEAT"],
    "BRUNCH_SPOT":    ["EGG", "WHEAT", "STRAWBERRY"],
    "YARN_STORE":     ["WOOL"],
    "ICE_CREAM_SHOP": ["STRAWBERRY", "MILK", "WHEAT"],
    "PET_CAFE":       ["CARROT"],
    "SMOOTHIE_SHOP":  ["STRAWBERRY", "MILK"],
    "FARMERS_MARKET": ["WHEAT", "CARROT", "TOMATO", "STRAWBERRY"],
}
PRODUCTS = list(MARKET_PARAMS)
TOWN_CENTER = [p for p in PRODUCTS if p != "FERTILIZER"]

SEASON_DAYS = 30
TURNS_PER_DAY = 24
SHOP_UNLOCK_INTERVAL = 3
SHOP_SELL_INTERVAL = 4          # -> 6 consumption ticks per day
TICKS_PER_DAY = TURNS_PER_DAY // SHOP_SELL_INTERVAL
MAX_SHOP_INSTANCES = 8


def shape(func, x, T):
    x = max(0.0, x)
    if func == "linear": return x
    if func == "sq":     return x * x
    if func == "sqrt":   return math.sqrt(x)
    if func == "log":    return math.log(1.0 + x)
    if func == "hinge":
        u = x / T
        return u + HINGE_GAIN * max(0.0, u - 1.0) ** 2
    return x


def price_at(item, inv):
    p = MARKET_PARAMS[item]
    base, T = p["base"], p["T"]
    if inv < I0:
        amp = p["bt"] * base / shape(p["bf"], T, T)
        val = base + amp * shape(p["bf"], I0 - inv, T)
    else:
        amp = p["at"] * base / shape(p["af"], T, T)
        val = base - amp * shape(p["af"], inv - I0, T)
    return max(PRICE_FLOOR, int(round(val)))


def absorption(item, start_inv=I0):
    """Units sellable from start_inv before the price hits the floor, and the cash."""
    inv, units, cash = start_inv, 0, 0
    while units < 20000:
        p = price_at(item, inv)
        if p <= PRICE_FLOOR:
            break
        cash += p
        inv += 1
        units += 1
    return units, cash


def expected_daily_drain():
    """Units/day each product loses to shops, per unlocked shop instance, plus centre."""
    per_instance = Counter()
    for name, items in SHOPS.items():
        mult = 2 if len(items) == 1 else 1
        for it in items:
            per_instance[it] += mult
    # Expected pull of one randomly-drawn shop instance, per day.
    exp = {it: per_instance[it] / len(SHOPS) * TICKS_PER_DAY for it in PRODUCTS}
    return exp, per_instance


def season_drain(item, exp_per_shop_day):
    """Expected total town drain over the season: centre (flat) + shops (ramping)."""
    centre = SEASON_DAYS if item in TOWN_CENTER else 0
    total = 0.0
    for day in range(SEASON_DAYS):
        n_shops = min(MAX_SHOP_INSTANCES, day // SHOP_UNLOCK_INTERVAL)
        total += n_shops * exp_per_shop_day[item]
    return centre + total


def revenue_schedule(item, per_day, drain_per_day, start_day, end_day=SEASON_DAYS):
    """Revenue from selling `per_day` units/day while the town drains in parallel."""
    inv = float(I0)
    # Let the town run the market down from day 0 up to start_day.
    for day in range(start_day):
        n_shops = min(MAX_SHOP_INSTANCES, day // SHOP_UNLOCK_INTERVAL)
        inv -= n_shops * drain_per_day
        if item in TOWN_CENTER:
            inv -= 1
    cash, sold = 0.0, 0
    for day in range(start_day, end_day):
        n_shops = min(MAX_SHOP_INSTANCES, day // SHOP_UNLOCK_INTERVAL)
        for _ in range(per_day):
            cash += price_at(item, int(round(inv)))
            inv += 1
            sold += 1
        inv -= n_shops * drain_per_day
        if item in TOWN_CENTER:
            inv -= 1
    return sold, cash, (cash / sold if sold else 0)


def main():
    exp, per_instance = expected_daily_drain()

    print("=" * 96)
    print("1. STANDING ABSORPTION  —  dump units into an untouched market until the price floors")
    print("=" * 96)
    print(f"{'PRODUCT':<12} {'base':>5} {'units':>7} {'total $':>10} {'avg $/u':>8}   price after 25/50/100/200 units")
    for it in PRODUCTS:
        u, c = absorption(it)
        pts = " ".join(f"{price_at(it, I0 + n):>4}" for n in (25, 50, 100, 200))
        print(f"{it:<12} {MARKET_PARAMS[it]['base']:>5} {u:>7,} {c:>10,} {c/u:>8.0f}   {pts}")

    print("\n" + "=" * 96)
    print("2. TOWN DRAIN  —  free consumption that regenerates selling capacity")
    print("=" * 96)
    print(f"{'PRODUCT':<12} {'shops demanding':<44} {'u/day/shop':>10} {'season drain':>13}")
    for it in PRODUCTS:
        names = [n for n, v in SHOPS.items() if it in v]
        lbl = ",".join(n.replace("_SHOP", "").replace("_STORE", "").replace("_SPOT", "")[:8] for n in names) or "-"
        print(f"{it:<12} {lbl:<44} {exp[it]:>10.2f} {season_drain(it, exp):>13,.0f}")
    print("\n  (u/day/shop = expected units one random shop instance eats per day;")
    print("   season drain = town centre + expected shop consumption over 30 days.)")

    print("\n" + "=" * 96)
    print("3. SUSTAINED SELL RATE  —  revenue if you sell N units/day from day 10 to 30")
    print("=" * 96)
    print(f"{'PRODUCT':<12} " + " ".join(f"{n:>3}/day" for n in (2, 5, 10, 20, 30)))
    for it in PRODUCTS:
        row = []
        for n in (2, 5, 10, 20, 30):
            sold, cash, avg = revenue_schedule(it, n, exp[it], 10)
            row.append(f"{cash/1000:>5.0f}k")
        print(f"{it:<12} " + " ".join(f"{v:>6}" for v in row))
    print("\n  Revenue from a day-10 start, selling a flat N units every day to day 30.")
    print("  Where the columns stop growing, the product is saturated — extra output is worthless.")

    print("\n" + "=" * 96)
    print("4. MARGINAL VALUE  —  $/unit at a sustained rate (what one more tile is worth)")
    print("=" * 96)
    print(f"{'PRODUCT':<12} " + " ".join(f"{n:>3}/day" for n in (2, 5, 10, 20, 30)))
    for it in PRODUCTS:
        row = []
        for n in (2, 5, 10, 20, 30):
            sold, cash, avg = revenue_schedule(it, n, exp[it], 10)
            row.append(f"{avg:>6.0f}")
        print(f"{it:<12} " + " ".join(row))


if __name__ == "__main__":
    main()
