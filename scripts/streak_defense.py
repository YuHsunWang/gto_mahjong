"""Measure seat-relative defense against a (streaking) dealer.

The dealer (seat 0) plays attack and pushes; seats 1-3 all play cautious, so any
difference between them comes purely from their turn-order position relative to
the dealer:

    seat 1 = 莊的下家 (draws right after the dealer)
    seat 2 = 莊的對家
    seat 3 = 莊的上家 (draws right before the dealer)

The dealer-aware toggle zeroes the defensive dealer premium (ev's opponent
dealer tai and the cautious dealer weight), leaving the seat-blind baseline, so
the on/off contrast isolates what dealer-awareness buys. Walls are seed-paired
across every (streak, aware) cell — the same seed is the same shuffle — so
differences are the defensive response, not luck.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import taimahjong.ev as ev
import taimahjong.selfplay as selfplay
from taimahjong.selfplay import play_game
from taimahjong.moments import SampleMoments

SEAT_LABEL = {1: "downstream", 2: "across", 3: "upstream"}
# The dealer (seat 0) always pushes; seats 1-3 share a defender policy. cautious
# defends via a fold-gated dealer weight; ev_aware prices the dealer on every
# discard through opponent_value_estimate — the two channels respond differently
# to the dealer-aware toggle.
DEFENDERS = {"cautious", "ev_aware"}


@contextlib.contextmanager
def dealer_awareness(enabled: bool):
    """Temporarily zero the defensive dealer premium when disabled."""
    saved = (ev.OPPONENT_DEALER_TAI, ev.OPPONENT_STREAK_TAI_PER_WIN, selfplay.CAUTIOUS_DEALER_BONUS)
    if not enabled:
        ev.OPPONENT_DEALER_TAI = 0
        ev.OPPONENT_STREAK_TAI_PER_WIN = 0
        selfplay.CAUTIOUS_DEALER_BONUS = 0.0
    try:
        yield
    finally:
        ev.OPPONENT_DEALER_TAI, ev.OPPONENT_STREAK_TAI_PER_WIN, selfplay.CAUTIOUS_DEALER_BONUS = saved


def _run(games: int, seed: int, streak: int, aware: bool, defenders: str) -> dict:
    policies = ("attack", defenders, defenders, defenders)
    points = [0, 0, 0, 0]
    point_differences: list[list[float]] = [[], [], [], []]
    deal_in_to_dealer = {1: 0, 2: 0, 3: 0}
    dealer_wins = 0
    with dealer_awareness(aware):
        for offset in range(games):
            game = play_game(seed + offset, policies, dealer_streak=streak)
            for seat in range(4):
                points[seat] += game.point_deltas[seat]
                point_differences[seat].append(float(game.point_deltas[seat]))
            if game.outcome == "ron" and game.winner == 0 and game.discarder in deal_in_to_dealer:
                deal_in_to_dealer[game.discarder] += 1
            dealer_wins += int(game.winner == 0)
    return {
        "streak": streak,
        "dealer_aware": aware,
        "defenders": defenders,
        "games": games,
        "dealer_point_ev": points[0] / games,
        "dealer_point_moments": SampleMoments.from_values(point_differences[0]).payload(0.10),
        "dealer_win_rate": dealer_wins / games,
        "deal_in_to_dealer_rate": {
            SEAT_LABEL[seat]: deal_in_to_dealer[seat] / games for seat in (1, 2, 3)
        },
        "defender_point_ev": {
            SEAT_LABEL[seat]: points[seat] / games for seat in (1, 2, 3)
        },
        "defender_point_moments": {
            SEAT_LABEL[seat]: SampleMoments.from_values(point_differences[seat]).payload(0.10)
            for seat in (1, 2, 3)
        },
    }


def _paired_awareness(
    games: int,
    seed: int,
    streak: int,
    defenders: str,
) -> dict:
    policies = ("attack", defenders, defenders, defenders)
    dealer_differences: list[float] = []
    defender_differences: dict[int, list[float]] = {1: [], 2: [], 3: []}
    for offset in range(games):
        with dealer_awareness(False):
            baseline = play_game(
                seed + offset, policies, dealer_streak=streak,
            )
        with dealer_awareness(True):
            aware = play_game(
                seed + offset, policies, dealer_streak=streak,
            )
        dealer_differences.append(
            float(aware.point_deltas[0] - baseline.point_deltas[0])
        )
        for seat in (1, 2, 3):
            defender_differences[seat].append(
                float(aware.point_deltas[seat] - baseline.point_deltas[seat])
            )
    return {
        "streak": streak,
        "defenders": defenders,
        "games": games,
        "seed": seed,
        "dealer_aware_minus_off_moments": SampleMoments.from_values(
            dealer_differences,
        ).payload(0.10),
        "defender_aware_minus_off_moments": {
            SEAT_LABEL[seat]: SampleMoments.from_values(
                defender_differences[seat],
            ).payload(0.10)
            for seat in (1, 2, 3)
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--games", type=int, required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--streak", type=int, required=True)
    parser.add_argument("--dealer-aware", choices=("on", "off"), required=True)
    parser.add_argument("--defenders", choices=sorted(DEFENDERS), default="cautious")
    parser.add_argument("--paired-aware-contrast", action="store_true")
    args = parser.parse_args()
    result = (
        _paired_awareness(
            args.games, args.seed, args.streak, args.defenders,
        )
        if args.paired_aware_contrast
        else _run(
            args.games,
            args.seed,
            args.streak,
            args.dealer_aware == "on",
            args.defenders,
        )
    )
    print(json.dumps(result))


if __name__ == "__main__":
    main()
