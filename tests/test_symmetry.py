"""Seat-exchangeability probe for the production opponent model.

Real positions have no ground truth, so a bias in the opponent model can only
be argued about. This builds a position where the answer is known by symmetry
instead: the acting seat's hand is drawn from the very distribution the sampler
uses for opponents, every seat's public state is empty, and all four draw the
same number of times. Under those conditions the four seats are exchangeable,
so a correct model must pay the acting seat zero on average and let each seat
win equally often.

The engine currently fails this. That is the point of the file — see the
handbook's measurement discipline: a failing test is a motive, not a threshold
to tune away. Do not relax ``BIAS_TOLERANCE`` to make it pass.
"""

import random
import statistics

import pytest

from taimahjong.calibration import Calibration
from taimahjong.danger import OpponentView
from taimahjong.ev import (
    _calibrated_ron,
    _draw_pool_tiles,
    _production_discard_policy,
    _production_seats,
    _sample_production_world,
)
from taimahjong.rollout import resolve_terminal_distribution
from taimahjong.scoring import WinContext


# Exchangeability checks need large trial counts to have any power (~57s).
pytestmark = pytest.mark.slow

TRIALS = 1200
CONTROL_TRIALS = 400
TURNS = 14
SEED = 2026

# The acting seat's expected payment must be small *relative to the effect the
# engine is asked to rank*: candidate discards in a mid-game position differ by
# roughly 0.02-0.19 chip units. A bias of half a unit is already several times
# that spread, so this bound is generous, not tight. It is derived from what the
# ranking needs, never from what the model currently scores.
BIAS_TOLERANCE = 0.5

# Each seat should win about as often as any other. Sampling noise on ~250 wins
# per seat is a few percent, so requiring the acting seat to reach 70% of the
# average opponent's win count leaves ample room while still catching a seat
# that is structurally starved of winning chances.
MIN_ACTOR_WIN_SHARE = 0.70


def _exchangeable_trials(
    trials: int,
    *,
    seeded_tenpai: bool = True,
    calibrated: bool = True,
) -> tuple[list[float], dict[int, float], int]:
    """Play ``trials`` exchangeable hands and return payments and wins by seat.

    ``seeded_tenpai`` and ``calibrated`` switch off one opponent-model layer
    each, so a failure can be attributed rather than merely observed.

    Each hand contributes its conditional mean payment and its expected wins
    by seat, because the priced RON claims are integrated out rather than
    sampled.  Both quantities have the same expectation as the sampled ones
    the probe used to collect, so the tolerances below still mean what they
    meant when they were written -- they are simply measured with less noise.
    """
    calibration = Calibration.from_path("data/calibration.json")
    opponents = (OpponentView([], []), OpponentView([], []), OpponentView([], []))
    context = WinContext(winning_tile=0)
    acting, _, streak = _production_seats(opponents, context)
    # Quantile 1.0 can never fall below a tenpai score, so the latent tenpai
    # draw never fires; this is how the layer is switched off without touching
    # production code.
    quantiles = None if seeded_tenpai else (1.0, 1.0, 1.0)

    rng = random.Random(SEED)
    payments: list[float] = []
    wins: dict[int, float] = {seat: 0.0 for seat in range(4)}
    for _ in range(trials):
        hand = tuple(_draw_pool_tiles([4] * 34, 17, rng))
        world = _sample_production_world(
            hand, (0,) * 34, opponents, TURNS, context,
            rng.randrange(2**64), quantiles, calibrated,
        )
        discard = _production_discard_policy(
            hand, tuple(4 - hand[tile] for tile in range(34)), 0,
        )
        mixture = resolve_terminal_distribution(
            world.players, world.wall, acting, (acting + 1) % 4, discard,
            _production_discard_policy, random.Random(rng.randrange(2**64)),
            dealer_streak=streak,
            calibrated_ron=(
                _calibrated_ron(calibration, acting, world.ron_value_hands)
                if calibrated
                else None
            ),
            visible=(0,) * 34,
        )
        payments.append(mixture.expected_deltas[acting])
        for probability, terminal in mixture.outcomes:
            if terminal.winner is None:
                continue
            for winner in terminal.ron_winners or (terminal.winner,):
                wins[winner] += probability
    return payments, wins, acting


def _summary(payments: list[float]) -> str:
    mean = statistics.mean(payments)
    stdev = statistics.stdev(payments)
    return f"mean={mean:+.3f} (se={stdev / len(payments) ** 0.5:.3f}, n={len(payments)})"


def test_acting_seat_is_not_paid_differently_from_an_exchangeable_opponent():
    payments, wins, acting = _exchangeable_trials(TRIALS)
    mean = statistics.mean(payments)

    if abs(mean) > BIAS_TOLERANCE:
        control, _, _ = _exchangeable_trials(
            CONTROL_TRIALS, seeded_tenpai=False, calibrated=False,
        )
        pytest.fail(
            "acting seat is not exchangeable with its opponents.\n"
            f"  production      : {_summary(payments)}\n"
            f"  both layers off : {_summary(control)}\n"
            "  wins by seat    : "
            + str({seat: round(count, 1) for seat, count in sorted(wins.items())})
            + f" (acting={acting})\n"
            "The control isolates the terminal/settlement/aggregation layer. If "
            "it sits near zero while production does not, the bias lives in the "
            "opponent model: the seeded-tenpai prior (ev.py _sample_production_"
            "world) and the calibrated-ron channel (ev.py _calibrated_ron), "
            "which give opponents winning chances the acting seat cannot get."
        )


def test_every_seat_wins_about_as_often_in_an_exchangeable_game():
    _, wins, acting = _exchangeable_trials(TRIALS)
    opponent_wins = [count for seat, count in wins.items() if seat != acting]
    average_opponent = statistics.mean(opponent_wins)
    assert average_opponent > 0, "no opponent ever won; the probe is broken"

    share = wins[acting] / average_opponent
    assert share >= MIN_ACTOR_WIN_SHARE, (
        f"acting seat won {wins[acting]:.1f} times against an opponent average of "
        f"{average_opponent:.1f} (share {share:.2f}). Opponents can win by the "
        "calibrated-ron channel without holding a winning hand, while the "
        "acting seat's ron must be physically real."
    )
