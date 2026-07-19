"""Measure the marginal EV of each kong type for the acting seat.

Seat 0 is given the tested kong policy while seats 1-3 never kong, so seat 0's
mean point delta is its kong lift against otherwise identical opponents. Walls
are seed-paired across policies (same seed -> same shuffle), so the EV delta
between policies isolates the kong decision with shared sampling noise. The
house rule scores 大明槓 at 0 tai with no 槓上開花, so "all" minus
"concealed_added" is expected to be <= 0 — the point of the experiment.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from taimahjong.selfplay import play_game

POLICIES = ("attack", "attack", "attack", "attack")


def _run(games: int, seed: int, kong_policy: str) -> dict:
    seat_policy = (kong_policy, "none", "none", "none")
    seat0_points = 0
    seat0_wins = 0
    kong_types: Counter[str] = Counter()
    bloom = robbed = 0
    seat0_kong_games = 0
    for offset in range(games):
        game = play_game(seed + offset, POLICIES, kong_policy=seat_policy)
        seat0_points += game.point_deltas[0]
        seat0_wins += int(game.winner == 0)
        seat0_kongs = [entry for entry in game.kong_log if entry[0] == 0]
        seat0_kong_games += int(bool(seat0_kongs))
        for _, _, concealed in seat0_kongs:
            kong_types["concealed" if concealed else "open"] += 1
        bloom += int(game.kong_bloom and game.winner == 0)
        robbed += int(game.robbed_kong)
    return {
        "kong_policy": kong_policy,
        "games": games,
        "seat0_point_ev": seat0_points / games,
        "seat0_win_rate": seat0_wins / games,
        "seat0_kong_game_rate": seat0_kong_games / games,
        "seat0_kong_types": dict(kong_types),
        "seat0_kong_bloom": bloom,
        "robbed_kong_events": robbed,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--games", type=int, required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--kong-policy", choices=("none", "concealed_added", "all"), required=True)
    args = parser.parse_args()
    print(json.dumps(_run(args.games, args.seed, args.kong_policy)))


if __name__ == "__main__":
    main()
