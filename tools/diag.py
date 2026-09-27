"""Run one local episode and dump a replay for analyze_replay.py.

    python tools/diag.py main.py variants/v3_nopace.py --seed 1003
"""
import argparse
import contextlib
import io
import json
import os
import sys
import warnings

warnings.filterwarnings("ignore")
sys.stdout.reconfigure(encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("agent_a")
    ap.add_argument("agent_b")
    ap.add_argument("--seed", type=int, default=1003)
    ap.add_argument("--steps", type=int, default=720)
    ap.add_argument("--out", default="local-replays")
    args = ap.parse_args()

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        from kaggle_environments import make
        env = make("kaggriculture",
                   configuration={"episodeSteps": args.steps, "seed": args.seed},
                   debug=True)
        env.run([os.path.abspath(args.agent_a), os.path.abspath(args.agent_b)])

    final = env.steps[-1]
    print(f"seed {args.seed}:  A={final[0]['reward']:,.0f}   B={final[1]['reward']:,.0f}")
    for i, s in enumerate(final):
        if s["status"] != "DONE":
            print(f"  !! player {i} status {s['status']}")

    os.makedirs(args.out, exist_ok=True)
    dest = os.path.join(args.out, f"local-{args.seed}-replay.json")
    data = env.toJSON()
    # analyze_replay.py expects team names in info.
    data.setdefault("info", {})["TeamNames"] = [
        os.path.basename(args.agent_a), os.path.basename(args.agent_b)]
    with open(dest, "w", encoding="utf-8") as f:
        json.dump(data, f)
    print(f"wrote {dest}")

    # Surface any agent-side errors the env swallowed.
    err = buf.getvalue()
    lines = [l for l in err.splitlines()
             if "Traceback" in l or "Error" in l or "error" in l.lower()]
    if lines:
        print("\n-- stderr highlights --")
        for l in lines[:25]:
            print("  " + l)


if __name__ == "__main__":
    main()
