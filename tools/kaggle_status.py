"""Kaggriculture competition status: leaderboard rank, submissions, episode record.

Usage:
    python tools/kaggle_status.py            # summary
    python tools/kaggle_status.py --episodes # per-episode detail
"""
import contextlib
import io
import sys
import warnings
from collections import defaultdict

warnings.filterwarnings("ignore")
sys.stdout.reconfigure(encoding="utf-8")

from kaggle.api.kaggle_api_extended import KaggleApi  # noqa: E402

COMP = "kaggriculture"
MY_TEAM = "Blooriculture"


def api_client():
    api = KaggleApi()
    api.authenticate()
    return api


def full_leaderboard(api, page_size=2000):
    """Fetch the whole leaderboard.

    The API pages at 20 by default and prints the next page token to stdout
    rather than returning it, so paging properly means scraping our own output.
    Asking for one big page avoids that entirely.
    """
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rows = api.competition_leaderboard_view(COMP, page_size=page_size)
    return [r for r in (rows or []) if r is not None]


def main():
    api = api_client()

    print("=" * 78)
    print("KAGGRICULTURE STATUS")
    print("=" * 78)

    comps = api.competitions_list(search=COMP).competitions
    for c in comps:
        print(f"Competition : {c.ref}")
        print(f"Deadline    : {getattr(c, 'deadline', None)}")

    subs = api.competition_submissions(COMP)
    print(f"\nSubmissions : {len(subs)}")
    sub_ids = []
    for s in subs:
        sub_ids.append(s.ref)
        print(f"  id={s.ref}  date={s.date}  status={s.status}  desc={s.description or '-'}")

    lb = full_leaderboard(api)
    print(f"\nLeaderboard : {len(lb)} teams fetched")
    my_rank = None
    for i, e in enumerate(lb, 1):
        if e.team_name == MY_TEAM:
            my_rank = i
            break
    print("  Top 10:")
    for i, e in enumerate(lb[:10], 1):
        print(f"   {i:3d}. {e.team_name:<28s} {e.score}")
    if my_rank:
        print(f"\n  >> {MY_TEAM}: rank {my_rank}/{len(lb)}  score={lb[my_rank - 1].score}")
        lo = max(0, my_rank - 4)
        for i, e in enumerate(lb[lo:my_rank + 3], lo + 1):
            mark = " <<< US" if e.team_name == MY_TEAM else ""
            print(f"   {i:3d}. {e.team_name:<28s} {e.score}{mark}")
    else:
        print(f"  >> {MY_TEAM} not found in the {len(lb)} rows fetched (pagination limit).")

    # Episodes across every submission we own.
    print("\n" + "=" * 78)
    print("EPISODE RECORD")
    print("=" * 78)
    detail = "--episodes" in sys.argv
    for sid in sub_ids:
        try:
            eps = api.competition_list_episodes(submission_id=sid)
        except Exception as exc:  # noqa: BLE001
            print(f"  submission {sid}: episode fetch failed: {exc}")
            continue

        wins = losses = ties = 0
        my_rewards, opp_rewards = [], []
        per_opp = defaultdict(lambda: [0, 0, 0])  # w, l, t
        rows = []
        for ep in eps:
            d = ep.to_dict() if hasattr(ep, "to_dict") else vars(ep)
            if d.get("state") != "COMPLETED":
                continue
            agents = d.get("agents", [])
            mine = next((a for a in agents if a.get("teamName") == MY_TEAM), None)
            opp = next((a for a in agents if a.get("teamName") != MY_TEAM), None)
            if not mine or not opp:
                continue
            mr, orw = mine.get("reward"), opp.get("reward")
            if mr is None or orw is None:
                continue
            my_rewards.append(mr)
            opp_rewards.append(orw)
            name = opp.get("teamName", "?")
            if mr > orw:
                wins += 1
                per_opp[name][0] += 1
                res = "W"
            elif mr < orw:
                losses += 1
                per_opp[name][1] += 1
                res = "L"
            else:
                ties += 1
                per_opp[name][2] += 1
                res = "T"
            rows.append((d.get("createTime", ""), d["id"], res, mr, orw, name))

        n = wins + losses + ties
        print(f"\nSubmission {sid}: {n} completed episodes")
        if n:
            print(f"  Record   : {wins}W - {losses}L - {ties}T   ({100.0 * wins / n:.1f}% win rate)")
            print(f"  Our $    : avg {sum(my_rewards) / n:>9,.0f}   min {min(my_rewards):>9,}   max {max(my_rewards):>9,}")
            print(f"  Opp $    : avg {sum(opp_rewards) / n:>9,.0f}   min {min(opp_rewards):>9,}   max {max(opp_rewards):>9,}")
            print("  Toughest opponents (by our losses):")
            for name, (w, l, t) in sorted(per_opp.items(), key=lambda kv: -kv[1][1])[:8]:
                print(f"    {name:<26s} {w}W-{l}L-{t}T")
        if detail:
            print("  Episodes (newest first):")
            for ct, eid, res, mr, orw, name in sorted(rows, reverse=True):
                print(f"    {ct[:19]}  {eid}  {res}  us={mr:>8,}  opp={orw:>8,}  vs {name}")


if __name__ == "__main__":
    main()
