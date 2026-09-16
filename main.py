"""Kaggriculture starter agent.

Simple wheat loop: buy a wheat seed, plant it, water it during the bonus
window, harvest, and sell whatever ends up in the shed. See AGENTS.md /
README.md in this repo for the full rules and observation format.

Test locally with:

    from kaggle_environments import make
    env = make("kaggriculture", debug=True)
    env.run(["main.py", "random"])

Submit with:

    kaggle competitions submit kaggriculture -f main.py -m "Wheat loop v1"
"""


def agent(obs):
    player = obs["player"]
    me = obs["farms"][player]
    private = obs["private"]
    fx, fy = me["farmer"]
    tile = me["tiles"][fy][fx]

    market = []

    # Keep at least one wheat seed on hand.
    if private["seeds"].get("WHEAT", 0) == 0 and me["money"] >= 10:
        market.append(["BUY_SEED", "WHEAT", 1])

    # Sell any wheat sitting in the shed.
    wheat_in_shed = private["shed"].get("WHEAT", 0)
    if wheat_in_shed > 0:
        market.append(["SELL", "WHEAT", wheat_in_shed])

    if tile is None and private["seeds"].get("WHEAT", 0) > 0:
        return {"farmer": ["PLANT", "WHEAT"], "hands": [], "market": market}

    if isinstance(tile, dict) and tile.get("kind") == "PLANT":
        crop_age = obs["day"] - tile["planted_day"]
        if crop_age >= 2:  # WHEAT first_yield_day = 2; harvest as soon as possible
            return {"farmer": ["HARVEST"], "hands": [], "market": market}
        if not tile["watered_today"]:
            return {"farmer": ["WATER"], "hands": [], "market": market}

    return {"farmer": ["PASS"], "hands": [], "market": market}


if __name__ == "__main__":
    # Quick local smoke test against the built-in random agent.
    from kaggle_environments import make

    env = make("kaggriculture", configuration={"episodeSteps": 200}, debug=True)
    env.run([agent, "random"])

    final = env.steps[-1]
    for i, s in enumerate(final):
        print(f"Player {i}: reward={s.reward}, status={s.status}")
