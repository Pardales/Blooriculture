"""Kaggriculture agent — melon opening, then whatever the town is starving for.

Why this strategy
-----------------
The market, not the farm, is the binding constraint. Every product has its own
glut curve, and the money you can pull out of one before the price collapses
varies by two orders of magnitude:

    MELON      sq / 3.60   -> collapses after ~155 units, but pays ~$26k for them
    FERTILIZER linear/0.40 -> collapses after ~500 units (~$25k), and is free
    EGG        log / 0.20  -> still ~$36 after 3,600 units sold
    WHEAT      log / 0.20  -> still ~$19 after 3,600 units sold
    CARROT/TOMATO/EGG      -> hinge curves: calm until the town runs them short,
                              then they run away upward
    STRAWBERRY/MILK/WOOL   -> a glut kills them inside 100 units, but the town
                              eats them faster than anyone farms them

That last line is the whole game. Shops unlock at random, each one eating its
products six times a day forever, and nothing refills the shelves unless a
player does. By the back half of the season a town with two yarn stores has
wool sitting at $240 with no supplier. So the agent never commits to a crop or
a species up front: every free tile is priced against the *live* curve, walking
`price_at` down unit by unit for the batch that tile would actually produce,
and land goes to whatever wins. Same farm code grows a goose battery when the
bakeries show up and a sheep ranch when the yarn stores do.

The parts that do not move:

1.  Days 0-10 the starting quadrant goes mostly to melons and strawberries.
    NOTE: this docstring used to claim the melon opening banks "roughly $20k of
    capital on day 10". It does not. Measured over 90 episodes, the bank sits at
    about $600 from day 0 to day 10 and $300 on day 16, because the seed bill is
    paid on day 0 and nothing melon or strawberry yields lands before day 10.
    The top of the leaderboard holds ~$19k on day 10 and compounds from there.
    That gap is the agent's single biggest known weakness -- see STRATEGY.md §6.
2.  Everything is costed in *actions*, not money. Hands are cheap (fib(n)) but
    a unit only gets 24 actions a day and walking burns them, so the planner
    spends a labour budget, keeps pens next to the shed and melons out on the
    rim, the auction charges every job for the distance walked to reach it, and
    we refuse to buy land we cannot staff.
3.  Sell everything, every turn -- but not for the reason originally given here.
    Price tracks *current* market inventory, not cumulative volume, and the town
    drains that inventory for free all season, so on paper metering sales out
    should pay far more. Measured, it does not: the shed caps at 100 items and
    end-of-day overflow is discarded, so a unit held back is usually a unit
    destroyed, and the opponent takes the top of the curve while we wait.
    Throttling sales costs $10-35k a game (STRATEGY.md §3.1).

Test locally:   python main.py
Benchmark:      python tools/bench.py main.py variants/v3_nopace.py -n 45
Submit:         kaggle competitions submit kaggriculture -f main.py -m "v3"

Strategy notes, measured experiment log, and refuted ideas: STRATEGY.md
"""

import math

# --------------------------------------------------------------------------
# Game constants (mirrored from the environment so the agent can plan ahead)
# --------------------------------------------------------------------------

CROPS = {
    "WHEAT":      {"seed": 10,  "first": 2,  "maxday": 4,  "interval": 0, "maxyield": 6, "ongoing": False},
    "CARROT":     {"seed": 20,  "first": 2,  "maxday": 3,  "interval": 0, "maxyield": 4, "ongoing": False},
    "TOMATO":     {"seed": 50,  "first": 8,  "maxday": 8,  "interval": 1, "maxyield": 4, "ongoing": True},
    "STRAWBERRY": {"seed": 100, "first": 10, "maxday": 10, "interval": 2, "maxyield": 4, "ongoing": True},
    "MELON":      {"seed": 80,  "first": 10, "maxday": 12, "interval": 0, "maxyield": 6, "ongoing": False},
}

# Rough upkeep of one tile of each crop, in unit-actions per day
# (plant + waterings + harvest, spread over the tile's occupancy).
CROP_LABOR = {"WHEAT": 1.2, "CARROT": 1.25, "TOMATO": 0.8, "STRAWBERRY": 0.75, "MELON": 0.95}

ANIMALS = {
    "GOOSE": {"cost": 300, "structure": "COOP",    "first": 4, "interval": 1, "max_held": 4, "product": "EGG"},
    "COW":   {"cost": 400, "structure": "PASTURE", "first": 8, "interval": 2, "max_held": 6, "product": "MILK"},
    "SHEEP": {"cost": 500, "structure": "PASTURE", "first": 6, "interval": 3, "max_held": 6, "product": "WOOL"},
}

PRODUCTS = ["WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON", "EGG", "MILK", "WOOL", "FERTILIZER"]

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
MAX_SHOP_INSTANCES = 8
SHOP_UNLOCK_INTERVAL = 3   # days; not exposed in the observation, so assume default
SHOP_SELL_INTERVAL = 4     # turns between consumption ticks, likewise

# Units of each product one not-yet-drawn shop is expected to pull per tick
# (shops are drawn uniformly with replacement; single-product shops pull 2x).
EXPECTED_SHOP_PULL = {}
for _product in PRODUCTS:
    _pull = 0.0
    for _items in SHOPS.values():
        if _product in _items:
            _pull += 2.0 if len(_items) == 1 else 1.0
    EXPECTED_SHOP_PULL[_product] = _pull / len(SHOPS)

MARKET_PARAMS = {
    "WHEAT":      {"base": 25,  "I0": 10000, "T": 400, "bf": "sqrt",   "bt": 0.80, "af": "log",    "at": 0.20},
    "CARROT":     {"base": 35,  "I0": 10000, "T": 450, "bf": "hinge",  "bt": 1.00, "af": "sqrt",   "at": 0.70},
    "TOMATO":     {"base": 60,  "I0": 10000, "T": 200, "bf": "hinge",  "bt": 0.40, "af": "sqrt",   "at": 0.60},
    "STRAWBERRY": {"base": 120, "I0": 10000, "T": 100, "bf": "sqrt",   "bt": 0.70, "af": "linear", "at": 1.60},
    "MELON":      {"base": 250, "I0": 10000, "T": 300, "bf": "log",    "bt": 0.20, "af": "sq",     "at": 3.60},
    "EGG":        {"base": 50,  "I0": 10000, "T": 332, "bf": "hinge",  "bt": 0.40, "af": "log",    "at": 0.20},
    "MILK":       {"base": 160, "I0": 10000, "T": 122, "bf": "sqrt",   "bt": 0.60, "af": "linear", "at": 1.60},
    "WOOL":       {"base": 200, "I0": 10000, "T": 105, "bf": "log",    "bt": 0.20, "af": "sq",     "at": 3.20},
    "FERTILIZER": {"base": 100, "I0": 10000, "T": 200, "bf": "linear", "bt": 0.40, "af": "linear", "at": 0.40},
}

HINGE_GAIN = 8.0
PRICE_FLOOR = 1
LAND_PRICES = [1000, 2000, 4000]
FIB = [1, 1, 2, 3, 5, 8, 13, 21, 34, 55, 89, 144, 233, 377, 610, 987, 1597]
SHED_CAP = 100

# --------------------------------------------------------------------------
# Tunables
# --------------------------------------------------------------------------

MOVE_COST = 13.0        # a walked tile is a lost action; price it like one
MAX_HANDS = 13          # the fib hire cost eventually outruns what a hand reaches
# MEASURED (n=200, margin +$2,819 +/- 1,866 against the v3 baseline): the crew
# was under-funded. 0.40 performs the same as 0.28, so HIRE_BUDGET_CAP binds
# above this and there is nothing more to win by raising it further.
HIRE_BUDGET_SHARE = 0.28  # of current cash, per day
HIRE_BUDGET_CAP = 1700.0
INVEST_FLOOR_SHARE = 0.90  # never reserve more than this fraction of the bank
FLOOR_BASE = 700.0         # flat emergency cash held back
# MEASURED: the single biggest win found so far. Swept 0 / .02 / .06 / .10 / .13
# / .15 / .18 / .22 / .30 / .60 / 1.20 on two disjoint seed sets. Flat plateau at
# .15-.18 (+$19k margin, 91-93% win rate, our mean $50k -> $70k), falling away on
# both sides -- .10 is already negative and .60 is catastrophic. Taking the
# midpoint of the plateau. What it changes: the opening plants wheat and carrot,
# which pay on day 2, instead of strawberry, which pays nothing until day 10 --
# the same shape the 165-199k agents on the leaderboard open with.
CAPITAL_RATE = 0.165       # $/day charged per $ of seed money locked up
CAPITAL_TIGHT = 1500.0     # investable cash below which capital gets pricier
CAPITAL_SQUEEZE = 3.0      # how much dearer capital gets at zero cash
WAGE_RESERVE_DAYS = 3.0    # days of the *realistic* wage bill kept in reserve
WHEAT_RESERVE_PER_ANIMAL = 14.0  # feed money held back per head
LABOR_PRICE = 11.0      # marginal $/action of the last hand we hire
LABOR_EFFICIENCY = 0.65  # tile-planning: useful actions available per unit-turn
HIRE_EFFICIENCY = 0.45   # hiring: measured rate once walking is paid for
ANIMAL_ACTIONS = 3.6    # feed + care + part of a harvest + fertilizer pickup
CARE_RATE = 0.45        # share of days CARE actually wins a slot in the auction
# CARE banks +1 unit, paid out on the next production: a cared cow makes 1.5
# milk a day against 0.5, a cared sheep 1.33 wool against 0.33. Raising this bid
# looked worth +$4k at n=28 -- but at n=80 the whole effect vanished into the
# noise (see the log in STRATEGY.md), and pushing it high starves watering,
# because a $2,500 CARE bid outbids a dying strawberry's $120. Left at 1.15.
CARE_BID = 1.15         # CARE's auction bid, as a multiple of the product price
ANIMAL_TILE_SHARE = 0.46
WHEAT_PER_ANIMAL = 0.80  # wheat tiles that keep one animal fed every day
WHEAT_FEED_VALUE = 0.45  # fraction of a product unit that one day of feed buys
WHEAT_BUY_TIMES = 1      # feed top-ups per day (wheat in the shed crowds produce)
WHEAT_SELL_RESERVE = 3.0  # days of feed kept back before wheat counts as surplus
MIN_TILE_SCORE = 6.0    # $/tile/day below which a tile is not worth planting
DRAIN_CREDIT = 1.0      # share of the town's remaining appetite a tile can count on

# --- sell pacing -----------------------------------------------------------
# The price tracks *current* inventory, and the town keeps eating that
# inventory for free. So a unit held back is not a unit foregone: it is a unit
# sold later into a market the shops have quietly restocked us for. Dumping a
# premium good walks it straight into the $1 floor -- strawberry pays $3.8k if
# you empty the shed into it and $46k if you meter it out. These four knobs are
# the difference.
# MEASURED, 32 episodes each: throttling sales is a large loss, not a gain.
#   dump everything (SELL_PACED=False)  : $65.2k   <- best
#   price floor only                    : $51.3k
#   floor + daily quota                 : $29.8k
# The shed caps at 100 items and end-of-day overflow is *discarded*, so a unit
# held back is usually a unit destroyed -- and the opponent takes the top of the
# curve while we wait. Melon is an overproduction problem, fixed at the plough,
# not at the till. Keep the machinery (town_daily_drain sizes production below)
# but leave the throttle off.
SELL_PACED = False      # True re-enables the sell throttle (measured worse)
SELL_QUOTA = True       # False = keep the price floor but never throttle volume
SELL_PACE = 1.35        # multiple of the town's daily appetite we try to claim
SELL_PRICE_KEEP = 0.55  # never walk a unit below this fraction of its base price
SELL_WINDOWS = 6        # selling opportunities per day (town eats every 4 turns)
MIN_TRICKLE = 3.0       # daily allowance for goods no shop eats (melon, fertilizer)
LIQUIDATE_DAYS = 1      # days left at which unsold stock is worth more gone than held

# --- production sizing -----------------------------------------------------
# Melon looks unbeatable on an untouched curve, which is how the planner ended
# up filling the opening quadrant with 23 of them: 138 units into a market that
# absorbs 158 in total *across both players*, sold at $81 against Canon's $224
# on 12 tiles. Cap what we commit to each product instead.
# MEASURED: capping our own output to "our share" loses $3.7k a game and, worse,
# lifts the opponent's mean from $61.7k to $69.9k -- the curve we politely leave
# alone is the curve they sell into. In a two-player market, racing to produce
# and sell first beats leaving room. Set MARKET_SHARE back under ~1.0 to re-arm.
MARKET_SHARE = 10.0      # share of a product's curve we plan to claim
SHARE_PRICE_KEEP = 0.60  # stop producing once the marginal unit fetches under this x base

# --- opening -----------------------------------------------------------
HERD_PRIORITY_DAYS = -1  # days during which livestock may dip into the wage reserve
HERD_FLOOR_SHARE = 0.25  # fraction of invest_floor the herd must still leave behind
HERD_COMMIT_FULL = True  # credit the herd we own with the whole rest of the season
RIVAL_CREDIT = 1.0      # how much of the opponent's visible pipeline to expect
LAST_LAND_DAY = 22
LAND_LABOR_SLACK = 12.0  # spare unit-actions/day required before buying a quadrant
LAND_EMPTY_MAX = 4       # free tiles we tolerate before expanding is allowed
LAND_CASH_MARGIN = 800.0  # cash kept on top of cost + invest_floor to expand


# --------------------------------------------------------------------------
# Market model
# --------------------------------------------------------------------------

def _shape(func, x, T):
    x = max(0.0, x)
    if func == "linear":
        return x
    if func == "sq":
        return x * x
    if func == "sqrt":
        return math.sqrt(x)
    if func == "log":
        return math.log(1.0 + x)
    if func == "hinge":
        if not T or T <= 0:
            return x
        u = x / T
        return u + HINGE_GAIN * max(0.0, u - 1.0) ** 2
    return x


def price_at(item, inventory):
    """Replica of the environment's price curve, so we can look ahead."""
    p = MARKET_PARAMS[item]
    base, I0, T = p["base"], p["I0"], p["T"]
    if inventory < I0:
        amp = p["bt"] * base / _shape(p["bf"], T, T)
        val = base + amp * _shape(p["bf"], I0 - inventory, T)
    else:
        amp = p["at"] * base / _shape(p["af"], T, T)
        val = base - amp * _shape(p["af"], inventory - I0, T)
    return max(PRICE_FLOOR, int(round(val)))


def town_future_drain(product, shops, day, last_day, turns_per_day):
    """Units of `product` the town will eat between now and the final day.

    This is the term that makes premium goods worth farming: nothing restocks
    the shelves, so every unit the shops eat is one more unit we can sell near
    the top of the curve. It also grows over time, because shops keep unlocking
    and never close."""
    if product == "FERTILIZER":
        return 0.0
    ticks_per_day = float(turns_per_day) / SHOP_SELL_INTERVAL
    pull = 0.0
    for name in shops:
        items = SHOPS.get(name)
        if items and product in items:
            pull += 2.0 if len(items) == 1 else 1.0
    expected_new = EXPECTED_SHOP_PULL.get(product, 0.0)
    slots_left = max(0, MAX_SHOP_INSTANCES - len(shops))
    opened = 0
    total = 0.0
    for d in range(day + 1, last_day + 1):
        if d % SHOP_UNLOCK_INTERVAL == 0 and opened < slots_left:
            pull += expected_new
            opened += 1
        total += pull * ticks_per_day + 1.0   # +1/day for the town centre
    return total


def rival_future_supply(obs, player, day, last_day):
    """Units each product the *opponent's* farm is already committed to ship.

    Their tiles are public, so there is no excuse for walking into a market
    they have twenty sheep pointed at. Without this the agent reads a market as
    scarce on day 10 simply because the rival has not harvested yet, piles in,
    and meets them at the bottom of a `sq` glut curve."""
    out = {}
    for pid, farm in enumerate(obs["farms"]):
        if pid == player:
            continue
        for row in farm["tiles"]:
            for t in row:
                if not isinstance(t, dict):
                    continue
                animal = t.get("animal")
                if animal and animal in ANIMALS:
                    a = ANIMALS[animal]
                    start = max(day, t.get("placed_day", day) + a["first"])
                    units = animal_rate(animal) * max(0, last_day - start)
                    units += t.get("yield_units", 0)
                    out[a["product"]] = out.get(a["product"], 0.0) + units
                elif t.get("kind") == "PLANT" and t.get("crop") in CROPS:
                    crop = t["crop"]
                    out[crop] = out.get(crop, 0.0) + crop_expected_yield(
                        crop, t.get("yield_units", 0), day - t.get("planted_day", day),
                        t.get("watered_today", False),
                        t.get("fertilized_until_day", -1) >= day)
    return out


def town_daily_drain(product, shops, turns_per_day):
    """Units of `product` the town eats per day, from the shops actually unlocked.

    Exact, not estimated: `unlocked_shops` is in the observation. This is the
    rate at which the market restocks our selling capacity for free, and so the
    rate we can sell at forever without moving the price against us.
    """
    ticks = max(1, turns_per_day // SHOP_SELL_INTERVAL)
    per_tick = 0
    for name in shops:
        items = SHOPS.get(name)
        if items and product in items:
            per_tick += 2 if len(items) == 1 else 1
    drain = per_tick * ticks
    if product != "FERTILIZER":
        drain += 1  # town centre, one of everything once a day
    return drain


def daily_sell_quota(item, inv, shops, days_left, turns_per_day):
    """Units of `item` we are willing to sell today.

    Two sources of room: the town's ongoing appetite (a flow), and whatever
    scarcity it has already built up below I0 (a stock, which we release over
    the days we have left rather than all at once).
    """
    if not SELL_QUOTA:
        return 1e9  # price floor alone decides
    drain = town_daily_drain(item, shops, turns_per_day)
    quota = SELL_PACE * drain
    if drain <= 1:
        # Nobody eats melon or fertilizer; that market never recovers, so the
        # standing absorption is all we will ever get. Meter it out.
        quota = max(quota, MIN_TRICKLE)
    I0 = MARKET_PARAMS[item]["I0"]
    if inv < I0:
        quota += (I0 - inv) / max(1.0, float(days_left))
    return max(1.0, quota)


def _inv_shape(func, v):
    """Inverse of _shape. Only the glut-side shapes occur here (no hinge)."""
    v = max(0.0, v)
    if func == "linear":
        return v
    if func == "sq":
        return math.sqrt(v)
    if func == "sqrt":
        return v * v
    if func == "log":
        return math.exp(min(30.0, v)) - 1.0
    return v


def units_until_price(item, inv, floor_price):
    """Units we can add to the market before the price falls below floor_price.

    Closed form -- walking the curve one unit at a time is far too slow to run
    every turn for every product.
    """
    p = MARKET_PARAMS[item]
    base, I0, T = p["base"], p["I0"], p["T"]
    if floor_price >= base:
        # Only the scarcity buffer qualifies: how far we can refill towards I0
        # while still clearing the asking price.
        amp = p["bt"] * base / _shape(p["bf"], T, T)
        if amp <= 0:
            return 0.0
        need = _shape_inverse_below(p["bf"], (floor_price - base) / amp, T)
        return max(0.0, (I0 - inv) - need)
    amp = p["at"] * base / _shape(p["af"], T, T)
    if amp <= 0:
        return 0.0
    glut = _inv_shape(p["af"], (base - floor_price) / amp)
    return max(0.0, (I0 - inv)) + glut


def _shape_inverse_below(func, v, T):
    """Inverse of _shape on the scarcity side, including hinge (numeric)."""
    v = max(0.0, v)
    if func == "hinge":
        # u + 8*max(0,u-1)^2 = v  -> solve for u, then x = u*T
        if v <= 1.0:
            u = v
        else:
            # 8u^2 - 15u + (8 - v) = 0
            disc = 225.0 - 32.0 * (8.0 - v)
            u = (15.0 + math.sqrt(max(0.0, disc))) / 16.0
        return u * T
    return _inv_shape(func, v)


def market_capacity(product, inv, shops, day, last_day, turns_per_day):
    """Units of `product` still worth producing, as our share of the curve.

    Standing room down to a price we would still accept, plus everything the
    town will eat between now and the end -- then split, because the opponent
    is selling into the very same curve. This is the number that stops the
    planner turning the whole opening quadrant into melons it cannot sell.
    """
    floor_price = SHARE_PRICE_KEEP * MARKET_PARAMS[product]["base"]
    room = units_until_price(product, inv, floor_price)
    drain = town_future_drain(product, shops, day, last_day, turns_per_day)
    return MARKET_SHARE * (room + DRAIN_CREDIT * drain)


def units_above_price(item, inv, floor_price, cap):
    """How many units we can add to the market before the price drops below floor."""
    n = 0
    while n < cap:
        if price_at(item, inv + n) < floor_price:
            break
        n += 1
    return n


def sell_allowance(item, inv, shops, day, days_left, turns_per_day, held):
    """Units of `item` to offer this turn, or 0."""
    if held <= 0:
        return 0
    # Last day: unsold stock scores nothing, so any price beats holding.
    if days_left <= 0:
        return held
    per_day = daily_sell_quota(item, inv, shops, days_left, turns_per_day)
    if days_left <= LIQUIDATE_DAYS:
        per_day = max(per_day, held)  # clear the shed while there is still a market
    allow = min(held, int(math.ceil(per_day / float(max(1, SELL_WINDOWS)))))
    floor_price = max(PRICE_FLOOR, SELL_PRICE_KEEP * MARKET_PARAMS[item]["base"])
    return max(0, units_above_price(item, inv, floor_price, allow))


def batch_revenue(item, inventory, n):
    """What `n` more units of `item` fetch, walking down the price curve."""
    if n <= 0:
        return 0.0
    total = 0.0
    for k in range(n):
        total += price_at(item, inventory + k)
    return total


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------

def manhattan(ax, ay, bx, by):
    return abs(ax - bx) + abs(ay - by)


def shed_tiles(board):
    h = board // 2
    return [(h - 1, h - 1), (h, h - 1), (h - 1, h), (h, h)]


def step_towards(x, y, tx, ty):
    dx, dy = tx - x, ty - y
    if abs(dx) >= abs(dy):
        if dx > 0:
            return "EAST"
        if dx < 0:
            return "WEST"
    if dy > 0:
        return "SOUTH"
    if dy < 0:
        return "NORTH"
    if dx > 0:
        return "EAST"
    if dx < 0:
        return "WEST"
    return "PASS"


def hire_cost(n_already):
    return FIB[min(n_already, len(FIB) - 1)]


def cumulative_hire_cost(n):
    return sum(FIB[min(i, len(FIB) - 1)] for i in range(n))


def hands_for_budget(budget):
    n = 0
    while n < MAX_HANDS and cumulative_hire_cost(n + 1) <= budget:
        n += 1
    return n


def crop_plan(crop, day, last_day):
    """(units harvested, tile-days occupied) for a tile planted today."""
    c = CROPS[crop]
    if c["ongoing"]:
        ages = [c["first"] + i * c["interval"] for i in range(c["maxyield"])]
        ages = [a for a in ages if day + a <= last_day]
        if not ages:
            return 0, 1
        return len(ages), ages[-1] + 1
    ws = (c["maxday"] + 1) // 2
    best_units, best_days = 0, 1
    for h in range(c["first"], c["maxday"] + 1):
        if day + h > last_day:
            break
        units = min(c["maxyield"], 1 + max(0, h - ws + 1))
        if units > best_units:
            best_units, best_days = units, h + 1
    return best_units, best_days


def crop_expected_yield(crop, yield_units, age, watered_today, fertilized):
    """Units a one-time crop can still reach if we keep watering it."""
    c = CROPS[crop]
    if c["ongoing"]:
        return c["maxyield"]
    ws = (c["maxday"] + 1) // 2
    lo = max(age, ws)
    days = max(0, c["maxday"] - lo + 1)
    if watered_today and age >= ws:
        days -= 1
    per_day = 2 if fertilized else 1
    return min(c["maxyield"], yield_units + max(0, days) * per_day)


# --------------------------------------------------------------------------
# Farm survey
# --------------------------------------------------------------------------

class Survey(object):
    __slots__ = ("empties", "weeds", "animals", "empty_structs", "plants",
                 "wheat_tiles", "structs", "n_unlocked", "growing", "labor",
                 "herd")

    def __init__(self):
        self.empties = []
        self.weeds = []
        self.animals = []        # (x, y, tile)
        self.empty_structs = []  # (x, y, tile)
        self.plants = []         # (x, y, tile)
        self.wheat_tiles = 0
        self.structs = 0         # every animal structure, occupied or not
        self.n_unlocked = 0
        self.growing = {}        # crop -> units still to come off the field
        self.labor = 0.0         # unit-actions/day the current farm already needs
        self.herd = {}           # animal -> head currently placed


def survey_farm(tiles, board, day):
    s = Survey()
    for y in range(board):
        row = tiles[y]
        for x in range(board):
            t = row[x]
            if t == "LOCKED":
                continue
            s.n_unlocked += 1
            if t is None:
                s.empties.append((x, y))
            elif isinstance(t, dict):
                kind = t.get("kind")
                if kind == "WEED":
                    s.weeds.append((x, y))
                elif kind == "PLANT":
                    crop = t["crop"]
                    s.plants.append((x, y, t))
                    s.labor += CROP_LABOR.get(crop, 1.0)
                    if crop == "WHEAT":
                        s.wheat_tiles += 1
                    age = day - t["planted_day"]
                    exp = crop_expected_yield(crop, t.get("yield_units", 0), age,
                                              t.get("watered_today", False),
                                              t.get("fertilized_until_day", -1) >= day)
                    s.growing[crop] = s.growing.get(crop, 0) + exp
                elif kind in ("COOP", "PASTURE"):
                    s.structs += 1
                    animal = t.get("animal")
                    if animal:
                        s.animals.append((x, y, t))
                        s.labor += ANIMAL_ACTIONS
                        s.herd[animal] = s.herd.get(animal, 0) + 1
                    else:
                        s.empty_structs.append((x, y, t))
    return s


def animal_rate(animal):
    """Realistic product units per head per day, allowing for imperfect CARE."""
    iv = ANIMALS[animal]["interval"]
    return (1.0 + iv * CARE_RATE) / iv


def last_useful_animal_day(animal, last_day):
    """Latest day a purchase still repays itself before the season ends."""
    a = ANIMALS[animal]
    # build + place + first_yield, then enough ticks to clear the price tag
    return last_day - a["first"] - 2


# --------------------------------------------------------------------------
# Tile role planning
#
# One pass over the free tiles.  At every step we compare the marginal
# $/tile/day of another goose against the best cash crop, both net of the
# labour they will consume, and stop when neither clears MIN_TILE_SCORE or the
# labour / cash budget runs out.  Coops land nearest the shed (3.6 actions a
# day each), melons out on the rim (under 1).
# --------------------------------------------------------------------------

def plan_roles(s, obs, money, day, last_day, board, target_hands,
               turns_per_day, invest_floor):
    minv = obs["market"]["inventory"]
    days_left = last_day - day

    labor_budget = (1 + target_hands) * turns_per_day * LABOR_EFFICIENCY
    labor_left = labor_budget - s.labor
    cash_left = money - invest_floor

    struct_room = max(0, int(ANIMAL_TILE_SHARE * s.n_unlocked) - s.structs)
    if days_left < 5:
        struct_room = 0

    # Fertilizer is produced by any surviving animal, so it is common to all
    # three species and priced at the margin.
    fert_marginal = max(0.0, price_at("FERTILIZER", minv["FERTILIZER"] + 40) - LABOR_PRICE)
    animal_labor = ((ANIMAL_ACTIONS + WHEAT_PER_ANIMAL * CROP_LABOR["WHEAT"])
                    / (1.0 + WHEAT_PER_ANIMAL))
    animal_tile_days = (days_left + 1) * (1.0 + WHEAT_PER_ANIMAL)

    planned = {}       # crop -> tiles planned this turn
    planned_head = {}  # animal -> head planned this turn
    counts = {"WHEAT": 0}
    cash_crops = ["MELON", "TOMATO", "CARROT", "STRAWBERRY", "WHEAT"]

    # Where each product's inventory will sit by the time this tile's output
    # reaches the market: today's level, less the town's appetite between now
    # and then (roughly half the remaining season, on average).
    shops = obs["town"].get("unlocked_shops", []) or []
    rival = rival_future_supply(obs, obs["player"], day, last_day)
    sale_inv = {}
    for product in PRODUCTS:
        drain = town_future_drain(product, shops, day, last_day, turns_per_day)
        sale_inv[product] = (minv[product] - DRAIN_CREDIT * drain
                             + RIVAL_CREDIT * rival.get(product, 0.0))

    # How many units of each product this farm should ever put on the market.
    # Computed once a turn: the inverse-curve form is O(1), but calling it per
    # tile per crop inside the planning loop would still be wasteful.
    capacity = {}
    for product in PRODUCTS:
        capacity[product] = market_capacity(product, minv[product], shops,
                                            day, last_day, turns_per_day)

    # Price of having capital tied up, per dollar per day. A strawberry seed is
    # $100 that returns nothing for ten days; a wheat seed is $10 back on day 2.
    # Scored purely on $/tile/day the strawberry wins easily and the planner
    # spends the whole opening bank on seed that cannot pay a wage or buy a cow
    # until day 10 -- which is how the bank sat at ~$600 for the first third of
    # the season. Charge for the wait, and charge more when cash is short.
    capital_rate = CAPITAL_RATE
    if cash_left < CAPITAL_TIGHT:
        # Scarce cash is worth more than plentiful cash.
        capital_rate *= 1.0 + CAPITAL_SQUEEZE * (1.0 - max(0.0, cash_left) / CAPITAL_TIGHT)

    def crop_score(crop):
        units, tdays = crop_plan(crop, day, last_day)
        if units <= 0:
            return -1.0
        already = s.growing.get(crop, 0) + planned.get(crop, 0) * units
        # Wheat is feed, not a cash crop; its curve is near-bottomless anyway.
        if crop != "WHEAT" and already + units > capacity.get(crop, 1e9):
            return -1.0
        rev = batch_revenue(crop, int(sale_inv[crop] + already), units)
        lab = CROP_LABOR.get(crop, 1.0)
        seed = CROPS[crop]["seed"]
        # Interest on the seed money over the wait until the first harvest.
        wait = max(0, CROPS[crop]["first"])
        carry = capital_rate * seed * wait / tdays
        return (rev - seed) / tdays - LABOR_PRICE * lab - carry

    def animal_score(animal):
        """$/tile/day of one more head, priced against the real curve.

        This is what lets the agent notice that a town full of yarn stores has
        left wool at $240 with nobody producing it."""
        a = ANIMALS[animal]
        if day > last_useful_animal_day(animal, last_day):
            return -1.0
        prod_days = days_left - a["first"] - 1
        if prod_days <= 0:
            return -1.0
        rate = animal_rate(animal)
        units = int(round(rate * prod_days))
        if units <= 0:
            return -1.0
        product = a["product"]
        # Output already committed to this product's curve before the new head
        # sells a thing. Animals we already own are past their first yield, so
        # they keep producing for the whole rest of the season -- crediting them
        # only with a newcomer's shorter window understates supply and talks the
        # planner into piling every tile onto one species.
        herd_days = max(0, days_left) if HERD_COMMIT_FULL else max(0, prod_days)
        committed = int(round(s.herd.get(animal, 0) * rate * herd_days
                              + planned_head.get(animal, 0) * rate * max(0, prod_days)))
        if committed + units > capacity.get(product, 1e9):
            return -1.0
        rev = batch_revenue(product, int(sale_inv[product] + committed), units)
        rev += fert_marginal * max(0, days_left - 1)
        return (rev - a["cost"]) / animal_tile_days - LABOR_PRICE * animal_labor

    # wheat we still owe the animals we already own
    wheat_debt = max(0.0, WHEAT_PER_ANIMAL * s.structs - s.wheat_tiles)
    if days_left < 4:
        wheat_debt = 0.0

    for _ in range(len(s.empties)):
        # feeding the herd comes before anything speculative
        if wheat_debt >= 1.0 and labor_left >= CROP_LABOR["WHEAT"] and days_left >= 4:
            counts["WHEAT"] += 1
            planned["WHEAT"] = planned.get("WHEAT", 0) + 1
            wheat_debt -= 1.0
            labor_left -= CROP_LABOR["WHEAT"]
            continue

        best_animal, animal_best = None, MIN_TILE_SCORE
        placed = sum(planned_head.values())
        if struct_room - placed > 0 and labor_left >= ANIMAL_ACTIONS:
            for animal in ANIMALS:
                if cash_left < ANIMALS[animal]["cost"]:
                    continue
                sc = animal_score(animal)
                if sc > animal_best:
                    best_animal, animal_best = animal, sc

        best_crop, crop_best = None, MIN_TILE_SCORE
        for crop in cash_crops:
            if labor_left < CROP_LABOR.get(crop, 1.0):
                continue
            sc = crop_score(crop)
            if sc > crop_best:
                best_crop, crop_best = crop, sc

        if best_animal is not None and animal_best >= crop_best:
            planned_head[best_animal] = planned_head.get(best_animal, 0) + 1
            cash_left -= ANIMALS[best_animal]["cost"]
            labor_left -= ANIMAL_ACTIONS
            wheat_debt += WHEAT_PER_ANIMAL
        elif best_crop is not None:
            planned[best_crop] = planned.get(best_crop, 0) + 1
            counts[best_crop] = counts.get(best_crop, 0) + 1
            labor_left -= CROP_LABOR.get(best_crop, 1.0)
        else:
            break

    labor_spare = labor_left

    # --- place the roles: structures hug the shed, melons take the rim
    sheds = shed_tiles(board)
    ordered = sorted(s.empties,
                     key=lambda p: (min(manhattan(p[0], p[1], sx, sy) for sx, sy in sheds),
                                    p[1], p[0]))
    roles = {}
    front = 0
    for animal, n in sorted(planned_head.items(), key=lambda kv: -kv[1]):
        for _ in range(n):
            roles[ordered[front]] = "A:" + animal
            front += 1
    for _ in range(counts.get("WHEAT", 0)):
        roles[ordered[front]] = "WHEAT"
        front += 1
    rim = [p for p in reversed(ordered) if p not in roles]
    ri = 0
    for crop in ("MELON", "STRAWBERRY", "TOMATO", "CARROT"):
        for _ in range(counts.get(crop, 0)):
            if ri >= len(rim):
                break
            roles[rim[ri]] = crop
            ri += 1
    return roles, planned_head, labor_spare


# --------------------------------------------------------------------------
# Job construction
# --------------------------------------------------------------------------

def build_jobs(s, roles, priv, day, last_day, prices, fert_for_wheat, held_animals,
               wheat_buy_price):
    jobs = []
    add = jobs.append
    endgame = (day >= last_day)
    fert = prices["FERTILIZER"]
    wheat_p = prices["WHEAT"]

    for (x, y, t) in s.animals:
        a = ANIMALS[t["animal"]]
        pprice = prices[a["product"]]
        held = t.get("yield_units", 0)
        if held > 0:
            v = held * pprice
            if held >= a["max_held"] - 1:
                v += 2.5 * pprice     # another night's laying would be wasted
            add({"x": x, "y": y, "op": ["HARVEST"], "v": v, "need": None})
        if t.get("fertilizer_available"):
            v = float(fert) if fert >= 10 else 0.0
            if fert_for_wheat:
                v = max(v, 1.8 * wheat_p)
            if v > LABOR_PRICE:
                add({"x": x, "y": y, "op": ["COLLECT_FERTILIZER"], "v": v, "need": None})
        if endgame:
            continue
        if not t.get("fed_today"):
            # Base production happens fed or not; feeding buys survival and the
            # banked CARE bonus, i.e. roughly one extra egg.
            v = 900.0 if t.get("consecutive_unfed", 0) >= 1 else 1.6 * pprice
            add({"x": x, "y": y, "op": ["FEED"], "v": v, "need": "WHEAT"})
        # CARE banks a bonus paid out at the *next* end-of-day, so caring on the
        # penultimate day buys a production tick the season never reaches.
        # CARE banks a bonus paid out at the *next* end-of-day, so caring on the
        # penultimate day buys a production tick the season never reaches. The
        # bonus is worth a whole extra unit of product -- a cared cow makes 1.5
        # milk a day against 0.5 -- but it is capped by max_held, so a full
        # animal has nowhere to put it.
        if not t.get("cared_today") and day < last_day - 1 \
                and held < a["max_held"]:
            add({"x": x, "y": y, "op": ["CARE"], "v": CARE_BID * pprice, "need": None})

    for (x, y, t) in s.plants:
        crop = t["crop"]
        c = CROPS[crop]
        price = prices[crop]
        age = day - t["planted_day"]
        held = t.get("yield_units", 0)
        watered = t.get("watered_today", False)
        fertilized = t.get("fertilized_until_day", -1) >= day
        ws = (c["maxday"] + 1) // 2

        if c["ongoing"]:
            last_prod_age = c["first"] + (c["maxyield"] - 1) * c["interval"]
            if held > 0 and age >= c["first"] and (held >= 2 or age >= last_prod_age or endgame):
                add({"x": x, "y": y, "op": ["HARVEST"], "v": held * price, "need": None})
            if not watered and not endgame:
                if t.get("consecutive_unwatered", 0) >= 1:
                    # MEASURED (n=90): bidding this plant's whole remaining life
                    # here -- 4 productions, ~$960 for a young strawberry --
                    # costs $5k a game. The auction is zero-sum over units, so
                    # overpaying to save a strawberry starves the harvests and
                    # animal jobs that were the better use of the same turn.
                    # Dropping the bid to a flat floor instead costs $40k, so
                    # this term is load-bearing; it is just already tuned.
                    add({"x": x, "y": y, "op": ["WATER"],
                         "v": max(60.0, (held + 1) * price), "need": None})
                elif fertilized:
                    add({"x": x, "y": y, "op": ["WATER"], "v": float(price), "need": None})
            continue

        expect = crop_expected_yield(crop, held, age, watered, fertilized)
        if age >= c["first"] and held > 0 and (expect <= held or endgame or age > c["maxday"]):
            add({"x": x, "y": y, "op": ["HARVEST"], "v": held * price + 8.0, "need": None})
        if not watered and not endgame:
            if t.get("consecutive_unwatered", 0) >= 1:
                add({"x": x, "y": y, "op": ["WATER"],
                     "v": max(45.0, expect * price * 0.9), "need": None})
            elif ws <= age <= c["maxday"] and held < c["maxyield"]:
                add({"x": x, "y": y, "op": ["WATER"],
                     "v": float((2 if fertilized else 1) * price), "need": None})
        if (fert_for_wheat and crop == "WHEAT" and not fertilized and not endgame
                and ws <= age <= c["maxday"] - 1 and held < c["maxyield"]):
            add({"x": x, "y": y, "op": ["FERTILIZE"], "v": 2.0 * wheat_p, "need": "FERTILIZER"})

    if not endgame:
        for (x, y, t) in s.empty_structs:
            kind = t.get("kind")
            for animal, a in ANIMALS.items():
                if a["structure"] == kind and held_animals.get(animal, 0) > 0:
                    add({"x": x, "y": y, "op": ["PLACE", animal],
                         "v": 1.6 * a["cost"], "need": animal})

        want_tiles = len(roles) > 0 or s.structs > 0
        weed_v = 90.0 if want_tiles else 30.0
        for (x, y) in s.weeds:
            add({"x": x, "y": y, "op": ["DIG"], "v": weed_v, "need": None})

        seeds = priv.get("seeds", {}) or {}
        for (x, y), role in roles.items():
            if role.startswith("A:"):
                structure = ANIMALS[role[2:]]["structure"]
                add({"x": x, "y": y, "op": ["BUILD_" + structure], "v": 190.0,
                     "need": None})
            elif role in CROPS and seeds.get(role, 0) > 0:
                units = crop_plan(role, day, last_day)[0]
                if units > 0:
                    unit_value = prices[role]
                    if role == "WHEAT" and s.structs > 0:
                        # Home-grown wheat replaces wheat we would otherwise buy
                        # at the (rising) scarcity price.
                        unit_value = max(unit_value, wheat_buy_price)
                    add({"x": x, "y": y, "op": ["PLANT", role],
                         "v": 0.45 * units * unit_value, "need": None, "seed": role})
    return jobs


# --------------------------------------------------------------------------
# Greedy auction over *sites*, not jobs.
#
# Bidding job-by-job sends a unit across the farm for one action and then sends
# it somewhere else. Bidding per tile fixes that: a fed-and-cared animal is four
# actions on one square (feed, care, harvest, collect fertilizer), so the walk
# amortises. A site is scored by its best job plus a discounted tail of the rest
# — discounted because the unit only does one per turn and may be called away.
# --------------------------------------------------------------------------

def assign(units, jobs):
    if not units or not jobs:
        return {}
    jobs = sorted(jobs, key=lambda j: -j["v"])[:170]
    taken = [False] * len(jobs)
    free = [u["idx"] for u in units]
    by_idx = dict((u["idx"], u) for u in units)
    result = {}
    for _ in range(len(units)):
        best = None
        for ui in free:
            u = by_idx[ui]
            ux, uy, uinv = u["x"], u["y"], u["inv"]
            for ji, j in enumerate(jobs):
                if taken[ji]:
                    continue
                only = j.get("only")
                if only is not None and only != ui:
                    continue
                need = j["need"]
                if need is not None and uinv.get(need, 0) <= 0:
                    continue
                d = abs(ux - j["x"]) + abs(uy - j["y"])
                score = j["v"] - MOVE_COST * d
                if best is None or score > best[0]:
                    best = (score, ui, ji)
        if best is None or best[0] <= 1.0:
            break
        _, ui, ji = best
        taken[ji] = True
        free.remove(ui)
        result[ui] = jobs[ji]
    return result


# --------------------------------------------------------------------------
# Main decision
# --------------------------------------------------------------------------

def _decide(obs, config):
    player = obs["player"]
    me = obs["farms"][player]
    priv = obs["private"]
    day = int(obs["day"])
    hour = int(obs["hour"])
    tiles = me["tiles"]
    board = len(tiles)
    money = float(me["money"])
    prices = obs["market"]["prices"]
    minv = obs["market"]["inventory"]

    turns_per_day, episode_steps = 24, 720
    if config is not None:
        for key, default in (("turnsPerDay", 24), ("episodeSteps", 720)):
            val = default
            try:
                val = int(config[key])
            except Exception:
                try:
                    val = int(getattr(config, key, default))
                except Exception:
                    val = default
            if key == "turnsPerDay":
                turns_per_day = max(1, val)
            else:
                episode_steps = val
    last_day = max(0, (episode_steps - 2) // turns_per_day)
    days_left = last_day - day
    endgame = (day >= last_day)

    shed = dict(priv.get("shed", {}) or {})
    seeds = dict(priv.get("seeds", {}) or {})
    inventories = priv.get("inventories", [{}]) or [{}]

    s = survey_farm(tiles, board, day)
    n_animals = len(s.animals)

    units = []
    positions = [me["farmer"]] + list(me.get("hands", []))
    for i, pos in enumerate(positions):
        inv = inventories[i] if i < len(inventories) else {}
        units.append({"idx": i, "x": int(pos[0]), "y": int(pos[1]), "inv": dict(inv or {})})

    carried = {}
    for u in units:
        for k, v in u["inv"].items():
            carried[k] = carried.get(k, 0) + v
    # livestock bought but not yet standing on a structure
    stock_held = dict((a, shed.get(a, 0) + carried.get(a, 0)) for a in ANIMALS)

    # How much labour can we sustain?  Hands are the cheapest thing we buy, so
    # the budget is generous, but it must survive the rest of the season.
    hire_budget = max(40.0, min(HIRE_BUDGET_SHARE * money, HIRE_BUDGET_CAP))
    target_hands = hands_for_budget(hire_budget)

    # Cash we refuse to invest: a few days of wages plus emergency wheat. Capped
    # as a share of the bank, so a bad patch cannot leave the floor above our
    # balance and freeze the farm out of buying anything at all.
    #
    # This used to reserve three days of `cumulative_hire_cost(target_hands)`,
    # i.e. of the *most* hands the budget could ever afford. On day 0 that is 13
    # hands, $609/day, so it locked away $2,527 of the $3,000 bank -- while the
    # hire loop, which sizes the crew by the work actually available, hires five
    # hands for $12. Reserving 200x the real wage bill is what left us with $473
    # of usable cash on day 0: not enough for a sheep, barely one cow. Hence no
    # herd until day 12, no land until day 10, and a bank flat at ~$600 through
    # the entire opening while the leaders were at $19k by day 10.
    #
    # Size it off the crew the work implies instead, using the same expression
    # the hire loop uses.
    est_work = s.labor + 2.0 * min(len(s.empties), 3 * (1 + target_hands)) + len(s.weeds) + 8
    est_hands = min(target_hands, max(0, int(math.ceil(
        est_work / (turns_per_day * HIRE_EFFICIENCY))) - 1))
    invest_floor = min(WAGE_RESERVE_DAYS * cumulative_hire_cost(est_hands)
                       + WHEAT_RESERVE_PER_ANIMAL * n_animals + FLOOR_BASE,
                       INVEST_FLOOR_SHARE * money)

    roles, planned_head, labor_spare = plan_roles(
        s, obs, money, day, last_day, board, target_hands,
        turns_per_day, invest_floor)

    # One fertilizer on a young wheat plant is two extra wheat, i.e. two more
    # fed days, i.e. two more CARE payouts -- worth far more than the fertilizer.
    fert_for_wheat = (s.wheat_tiles > 0 and n_animals > 0
                      and prices["FERTILIZER"] < 2.0 * prices["WHEAT"])

    wheat_buy_price = price_at("WHEAT", minv["WHEAT"] - 1)
    jobs = build_jobs(s, roles, priv, day, last_day, prices, fert_for_wheat,
                      stock_held, wheat_buy_price)

    # ---- shed logistics (unit-specific jobs)
    #
    # Shed round trips are the single most expensive thing a unit can do, so
    # they are rationed: only the few units nearest the shed are sent, and each
    # one carries a full load rather than shuttling one item at a time.
    sheds = shed_tiles(board)
    shed_count = sum(shed.values())
    shed_room = max(0, SHED_CAP - shed_count)
    unfed = sum(1 for (_, _, t) in s.animals if not t.get("fed_today"))
    wheat_in_shed = shed.get("WHEAT", 0)
    open_pens = len(s.empty_structs)

    def nearest_shed(ux, uy):
        return min(sheds, key=lambda p: manhattan(ux, uy, p[0], p[1]))

    def shed_dist(u):
        sx, sy = nearest_shed(u["x"], u["y"])
        return manhattan(u["x"], u["y"], sx, sy)

    # 1. deliver produce so the sell orders have something to sell
    for u in units:
        uinv = u["inv"]
        keep_wheat = (n_animals > 0 and not endgame and uinv.get("WHEAT", 0) > 0)
        load, value = 0, 0.0
        for k, v in uinv.items():
            if k in MARKET_PARAMS and v > 0:
                if k == "WHEAT" and n_animals > 0 and not endgame:
                    continue
                load += v
                value += v * prices.get(k, 1)
        if load <= 0 or shed_room <= 0:
            continue
        if not (load >= 7 or hour >= turns_per_day - 4 or endgame):
            continue
        sx, sy = nearest_shed(u["x"], u["y"])
        if keep_wheat:
            item, bestv = None, 0
            for k, v in uinv.items():
                if k in MARKET_PARAMS and k != "WHEAT" and v * prices.get(k, 1) > bestv:
                    item, bestv = k, v * prices.get(k, 1)
            if item is None:
                continue
            op = ["PLACE", item, min(uinv[item], shed_room)]
        else:
            op = ["DROP"]
        jobs.append({"x": sx, "y": sy, "op": op, "v": 0.5 * value,
                     "need": None, "only": u["idx"]})

    # 2. wheat runs: one runner per ~10 unfed animals, nearest units first
    if not endgame and unfed > 0 and wheat_in_shed > 0:
        candidates = [u for u in units if u["inv"].get("WHEAT", 0) <= 1]
        candidates.sort(key=shed_dist)
        runners = max(1, min(4, int(math.ceil(unfed / 10.0))))
        per_run = max(1, min(wheat_in_shed // max(1, runners), 12, unfed))
        for u in candidates[:runners]:
            sx, sy = nearest_shed(u["x"], u["y"])
            jobs.append({"x": sx, "y": sy, "op": ["PICKUP", "WHEAT", per_run],
                         "v": 1.7 * prices["EGG"] * min(3, unfed), "need": None,
                         "only": u["idx"]})

    # 3. livestock runs: fetch whichever species has an empty structure waiting
    if not endgame and open_pens > 0:
        open_kinds = {}
        for (_, _, t) in s.empty_structs:
            k = t.get("kind")
            open_kinds[k] = open_kinds.get(k, 0) + 1
        for animal, a in ANIMALS.items():
            waiting = open_kinds.get(a["structure"], 0)
            if waiting <= 0 or shed.get(animal, 0) <= 0:
                continue
            candidates = [u for u in units if u["inv"].get(animal, 0) <= 0]
            candidates.sort(key=shed_dist)
            for u in candidates[:2]:
                sx, sy = nearest_shed(u["x"], u["y"])
                take = min(shed[animal], waiting, 6)
                jobs.append({"x": sx, "y": sy, "op": ["PICKUP", animal, take],
                             "v": 1.5 * a["cost"], "need": None, "only": u["idx"]})

    # 4. fertilizer for the wheat field
    if fert_for_wheat and shed.get("FERTILIZER", 0) > 0 and not endgame:
        ws = (CROPS["WHEAT"]["maxday"] + 1) // 2
        ready = 0
        for (_, _, t) in s.plants:
            if t["crop"] == "WHEAT" and t.get("fertilized_until_day", -1) < day:
                a = day - t["planted_day"]
                if ws <= a <= CROPS["WHEAT"]["maxday"] - 1:
                    ready += 1
        if ready > 0:
            candidates = [u for u in units if u["inv"].get("FERTILIZER", 0) <= 0]
            candidates.sort(key=shed_dist)
            for u in candidates[:1]:
                sx, sy = nearest_shed(u["x"], u["y"])
                jobs.append({"x": sx, "y": sy,
                             "op": ["PICKUP", "FERTILIZER",
                                    min(shed["FERTILIZER"], ready, 5)],
                             "v": 1.5 * prices["WHEAT"], "need": None, "only": u["idx"]})

    assigned = assign(units, jobs)

    unit_actions = {}
    for u in units:
        j = assigned.get(u["idx"])
        if j is None:
            unit_actions[u["idx"]] = ["PASS"]
        elif u["x"] == j["x"] and u["y"] == j["y"]:
            unit_actions[u["idx"]] = list(j["op"])
        else:
            unit_actions[u["idx"]] = [step_towards(u["x"], u["y"], j["x"], j["y"])]

    # The interpreter drops *every* PLANT of a crop if the turn asks for more
    # seeds than we hold, so trim the surplus ourselves.
    demand = {}
    for act in unit_actions.values():
        if act and act[0] == "PLANT":
            demand[act[1]] = demand.get(act[1], 0) + 1
    for crop, n in demand.items():
        drop = n - seeds.get(crop, 0)
        for idx in list(unit_actions):
            if drop <= 0:
                break
            a = unit_actions[idx]
            if a and a[0] == "PLANT" and a[1] == crop:
                unit_actions[idx] = ["PASS"]
                drop -= 1

    market = build_market(s, me, money, day, hour, last_day, days_left, turns_per_day,
                          roles, n_animals, stock_held, planned_head, prices, minv,
                          shed, seeds, target_hands, invest_floor, endgame, labor_spare,
                          obs["town"].get("unlocked_shops", []) or [])

    return {"farmer": unit_actions.get(0, ["PASS"]),
            "hands": [unit_actions.get(i, ["PASS"]) for i in range(1, len(positions))],
            "market": market}


# --------------------------------------------------------------------------
# Market orders
# --------------------------------------------------------------------------

def build_market(s, me, money, day, hour, last_day, days_left, turns_per_day,
                 roles, n_animals, stock_held, planned_head, prices, minv, shed, seeds,
                 target_hands, invest_floor, endgame, labor_spare, shops):
    orders = []
    cash = money
    max_orders = 10

    # What a day of feed is worth: the priciest product the herd actually makes.
    herd_product_value = 0.0
    for animal, n in s.herd.items():
        if n > 0:
            herd_product_value = max(herd_product_value,
                                     float(prices[ANIMALS[animal]["product"]]))

    # ---- hire at the top of the day so the hands get a full shift
    hires_today = me.get("hires_today", 0)
    if hour <= 1 and not endgame:
        work = s.labor + 2.0 * len(roles) + len(s.weeds) + 8
        need_units = int(math.ceil(work / (turns_per_day * HIRE_EFFICIENCY)))
        want = max(0, min(target_hands, need_units - 1))
        todo = max(0, want - hires_today)
        for _ in range(min(todo, 8 if hour == 0 else 10)):
            c = hire_cost(hires_today)
            if cash < c + 20:
                break
            orders.append(["HIRE"])
            cash -= c
            hires_today += 1

    # ---- sell, but meter it.
    #
    # The old rule here was "sell everything, every turn", on the theory that
    # price depends only on cumulative volume. It does not: it depends on the
    # *current* inventory, and the town drains that inventory for free all
    # season. Emptying the shed into a premium curve is how strawberry turns
    # $46k of output into $3.8k. So each product gets a daily quota sized to
    # what the town will actually eat, spread over SELL_WINDOWS turns, and no
    # unit is ever sold below SELL_PRICE_KEEP of its base price.
    #
    # The wheat band is deliberately wide: buying and selling wheat in the same
    # day is pure leakage, so we only shed a genuine surplus.
    window = max(1, turns_per_day // max(1, SELL_WINDOWS))
    selling_now = (not SELL_PACED) or endgame or window == 1 or (hour % window == 1)
    if selling_now:
        wheat_reserve = 0
        if n_animals > 0 and not endgame:
            wheat_reserve = int(WHEAT_SELL_RESERVE * n_animals) + 12
        sells = []
        for item in PRODUCTS:
            q = shed.get(item, 0)
            if item == "WHEAT":
                q -= wheat_reserve
            elif item == "FERTILIZER" and not endgame and s.wheat_tiles > 0 \
                    and prices["FERTILIZER"] < 2.0 * prices["WHEAT"]:
                q -= min(6, s.wheat_tiles)
            if q <= 0:
                continue
            if SELL_PACED:
                q = sell_allowance(item, minv.get(item, MARKET_PARAMS[item]["I0"]),
                                   shops, day, days_left, turns_per_day, q)
            if q > 0:
                sells.append((q * prices.get(item, 1), item, q))
        sells.sort(reverse=True)
        for _, item, q in sells:
            if len(orders) >= max_orders:
                break
            orders.append(["SELL", item, q])
            cash += 0.8 * q * prices.get(item, 1)

    if endgame:
        return orders[:max_orders]

    # ---- seeds for the tiles we just planned
    plantable = max(2, 3 * (1 + max(target_hands, me.get("hires_today", 0))))
    want_seed = {}
    for role in roles.values():
        if role in CROPS:
            want_seed[role] = want_seed.get(role, 0) + 1
    for crop, n in sorted(want_seed.items(), key=lambda kv: -CROPS[kv[0]]["seed"]):
        if len(orders) >= max_orders:
            break
        need = n - seeds.get(crop, 0)
        if need <= 0:
            continue
        cost = CROPS[crop]["seed"]
        # Only stock what the crew can realistically get into the ground soon;
        # unplanted seed is dead money.
        buy = min(need, plantable, int(max(0.0, cash - invest_floor * 0.4) // cost))
        if buy > 0:
            orders.append(["BUY_SEED", crop, buy])
            cash -= buy * cost

    # ---- livestock, but only just ahead of the structures that can house it.
    #
    # MEASURED: buying the herd *before* seed, so it could not be crowded out of
    # the opening, cost $29k a game (40.6k vs 69.9k over 32 episodes). Animals
    # bought ahead of their pens just sit in the shed, they starve without wheat
    # to feed them, and the cash they consume is cash the crops needed to get
    # going at all. Seed first is correct.
    #
    # An animal still in the shed at the buzzer is its full price thrown away,
    # so we stay close to the pens that actually exist.
    open_kinds = {}
    for (_, _, t) in s.empty_structs:
        k = t.get("kind")
        open_kinds[k] = open_kinds.get(k, 0) + 1
    for animal, a in ANIMALS.items():
        if len(orders) >= max_orders:
            break
        if day > last_useful_animal_day(animal, last_day):
            continue
        # empty pens of this kind, plus a small lead on the ones we plan to build
        housing = open_kinds.get(a["structure"], 0) + min(3, planned_head.get(animal, 0))
        want = min(housing, 6) - stock_held.get(animal, 0)
        if want <= 0:
            continue
        room = SHED_CAP - sum(shed.values())
        # Early on the herd outranks the seed bill, so it is allowed to dig into
        # the wage reserve; later the reserve protects the payroll as intended.
        floor = invest_floor * (HERD_FLOOR_SHARE if day <= HERD_PRIORITY_DAYS else 1.0)
        afford = int(max(0.0, cash - floor) // a["cost"])
        buy = max(0, min(want, afford, room))
        if buy > 0:
            orders.append(["BUY_ANIMAL", animal, buy])
            cash -= buy * a["cost"]
            open_kinds[a["structure"]] = max(0, open_kinds.get(a["structure"], 0) - buy)

    # ---- land, but only when the crew has both filled what we own and has
    # labour left over. Unstaffed acres only make the farm longer to walk.
    if len(orders) < max_orders and day <= LAST_LAND_DAY:
        bought = len(me.get("unlocked_quadrants", ["NW"])) - 1
        if bought < len(LAND_PRICES):
            cost = LAND_PRICES[bought]
            if (cash >= cost + invest_floor + LAND_CASH_MARGIN
                    and len(s.empties) <= LAND_EMPTY_MAX
                    and labor_spare >= LAND_LABOR_SLACK):
                orders.append(["BUY_LAND"])
                cash -= cost

    # ---- feed wheat, twice a day, and only well below the sell band.
    # One wheat buys a fed day, and a fed day is what lets CARE pay out an
    # extra unit of product -- so the ceiling scales with what the herd makes.
    buy_hours = (3, 14) if WHEAT_BUY_TIMES >= 2 else (3,)
    if (len(orders) < max_orders and n_animals > 0 and days_left >= 1
            and hour in buy_hours):
        have = shed.get("WHEAT", 0)
        target = int(n_animals * 1.6) + 4
        if have < n_animals:
            buy_price = price_at("WHEAT", minv["WHEAT"] - 1)
            if buy_price <= max(42.0, WHEAT_FEED_VALUE * herd_product_value):
                room = SHED_CAP - sum(shed.values())
                afford = int(max(0.0, cash - invest_floor * 0.5) // max(1, buy_price))
                buy = max(0, min(target - have, afford, room))
                if buy > 0:
                    orders.append(["BUY_PRODUCT", "WHEAT", buy])

    return orders[:max_orders]


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

def agent(obs, config=None):
    try:
        return _decide(obs, config)
    except Exception:
        try:
            n = len(obs["farms"][obs["player"]].get("hands", []))
        except Exception:
            n = 0
        return {"farmer": ["PASS"], "hands": [["PASS"]] * n, "market": []}


if __name__ == "__main__":
    import time
    from kaggle_environments import make

    t0 = time.time()
    env = make("kaggriculture", configuration={"episodeSteps": 720}, debug=True)
    env.run([agent, "starter"])
    for i, st in enumerate(env.steps[-1]):
        print("Player %d: reward=%s status=%s" % (i, st.reward, st.status))
    print("elapsed %.1fs" % (time.time() - t0))
