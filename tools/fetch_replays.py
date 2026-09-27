"""Download replay JSON for specific episode ids into ./replays.

Usage: python tools/fetch_replays.py 113579720 113648162 ...
       python tools/fetch_replays.py --top N   # N highest opponent-reward episodes
"""
import json
import os
import sys
import warnings

warnings.filterwarnings("ignore")
sys.stdout.reconfigure(encoding="utf-8")

from kaggle.api.kaggle_api_extended import KaggleApi  # noqa: E402

COMP = "kaggriculture"
MY_TEAM = "Blooriculture"
MY_SUB = 56496770
OUT = "replays"


def main():
    api = KaggleApi()
    api.authenticate()
    os.makedirs(OUT, exist_ok=True)

    args = sys.argv[1:]
    if args and args[0] == "--top":
        n = int(args[1]) if len(args) > 1 else 5
        eps = api.competition_list_episodes(submission_id=MY_SUB)
        scored = []
        for ep in eps:
            d = ep.to_dict() if hasattr(ep, "to_dict") else vars(ep)
            if d.get("state") != "COMPLETED":
                continue
            opp = next((a for a in d.get("agents", []) if a.get("teamName") != MY_TEAM), None)
            if opp and opp.get("reward") is not None:
                scored.append((opp["reward"], d["id"], opp.get("teamName")))
        scored.sort(reverse=True)
        ids = [(e, r, t) for r, e, t in scored[:n]]
        for eid, rew, team in ids:
            print(f"  target {eid}: opponent {team} scored {rew:,}")
        ids = [eid for eid, _, _ in ids]
    else:
        ids = [int(a) for a in args]

    for eid in ids:
        dest = os.path.join(OUT, f"episode-{eid}-replay.json")
        # A previous buggy run left 4-byte "null" stubs; treat those as missing.
        if os.path.exists(dest) and os.path.getsize(dest) > 1000:
            print(f"skip {eid} (exists, {os.path.getsize(dest):,} bytes)")
            continue
        try:
            # The API writes the file itself; it returns None.
            api.competition_episode_replay(eid, path=OUT, quiet=True)
            size = os.path.getsize(dest) if os.path.exists(dest) else 0
            print(f"saved {dest} ({size:,} bytes)")
        except Exception as exc:  # noqa: BLE001
            print(f"FAILED {eid}: {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    main()
