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

POLICIES = ("attack", "cautious", "cautious", "cautious")
SEAT_LABEL = {1: "downstream", 2: "across", 3: "upstream"}


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


def _run(games: int, seed: int, streak: int, aware: bool) -> dict:
    points = [0, 0, 0, 0]
    deal_in_to_dealer = {1: 0, 2: 0, 3: 0}
    dealer_wins = 0
    with dealer_awareness(aware):
        for offset in range(games):
            game = play_game(seed + offset, POLICIES, dealer_streak=streak)
            for seat in range(4):
                points[seat] += game.point_deltas[seat]
            if game.outcome == "ron" and game.winner == 0 and game.discarder in deal_in_to_dealer:
                deal_in_to_dealer[game.discarder] += 1
            dealer_wins += int(game.winner == 0)
    return {
        "streak": streak,
        "dealer_aware": aware,
        "games": games,
        "dealer_point_ev": points[0] / games,
        "dealer_win_rate": dealer_wins / games,
        "deal_in_to_dealer_rate": {
            SEAT_LABEL[seat]: deal_in_to_dealer[seat] / games for seat in (1, 2, 3)
        },
        "defender_point_ev": {
            SEAT_LABEL[seat]: points[seat] / games for seat in (1, 2, 3)
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--games", type=int, required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--streak", type=int, required=True)
    parser.add_argument("--dealer-aware", choices=("on", "off"), required=True)
    args = parser.parse_args()
    print(json.dumps(_run(args.games, args.seed, args.streak, args.dealer_aware == "on")))


if __name__ == "__main__":
    main()
