"""Whole-hand continuations with public-information discard strategies.

All strategies share selfplay's strict shanten-improving pon/chi selection,
pon priority and next-seat chi, and shanten-safe concealed/added kongs (the
corpus setting). Declarations and forced discards follow the engine unchanged.
Payoffs use its default 3-base/1-tai settlement, in tai-equivalent units.
Only the live wall is randomized: this is conditional on fixed true concealed
hands and a fixed dead wall, not posterior sampling of hidden hands.
"""

from __future__ import annotations

from dataclasses import replace
from random import Random

from .danger import assess_validated_danger, tenpai_score
from .midgame_corpus import MidgameCase
from .selfplay import DecisionSnapshot, GameResult, _cached_analysis, _public_counts, play_game


STRATEGIES = ("tenpai_attack", "one_shanten_attack", "fold", "attack")
BASE_PROFILE = ("tenpai_attack",) * 4


def choose_discard(observation: DecisionSnapshot, strategy: str) -> tuple[int, bool]:
    """Own hand + public table only; safest = lowest worst expected danger.

    This is danger.rank_discards' river-aware danger * tenpai score, using
    its validated hot path and selfplay's cached efficiency ordering. Ties
    use minimum shanten, maximum ukeire, then tile index, exactly as attack.
    """
    if strategy not in STRATEGIES:
        raise ValueError(f"unknown strategy: {strategy}")
    analyses = _cached_analysis(observation.hand, len(observation.melds) + len(observation.kongs), observation.public_counts)
    threshold = {"tenpai_attack": 0, "one_shanten_attack": 1, "fold": -2, "attack": 99}[strategy]
    if analyses[0].shanten_after <= threshold:
        return analyses[0].discard, False
    return min(discard_risks(observation))[2], True


def discard_risks(observation: DecisionSnapshot) -> tuple[tuple[float, int, int], ...]:
    """(Worst expected danger, efficiency order, tile) for every legal discard.

    Shared with feature extraction so its scores are exactly fold's scores.
    """
    analyses = _cached_analysis(observation.hand, len(observation.melds) + len(observation.kongs), observation.public_counts)
    opponents = [(opponent, tenpai_score(opponent).score) for _, opponent in observation.opponents]
    ranked = []
    for order, analysis in enumerate(analyses):
        hand = list(observation.hand)
        hand[analysis.discard] -= 1
        risk = max(
            (assess_validated_danger(analysis.discard, opponent, observation.public_counts, tuple(hand)).score * tenpai
             for opponent, tenpai in opponents), default=0.0,
        )
        ranked.append((risk, order, analysis.discard))
    return tuple(ranked)


def profiles(base: str = BASE_PROFILE[0]) -> tuple[tuple[str, ...], ...]:
    """The symmetric base profile, then each role alone switched to every other strategy."""
    if base not in STRATEGIES:
        raise ValueError(f"unknown strategy: {base}")
    result = [(base,) * 4]
    for role in range(4):
        for alternative in STRATEGIES:
            if alternative != base:
                profile = [base] * 4
                profile[role] = alternative
                result.append(tuple(profile))
    return tuple(result)


def reshuffled_wall(case: MidgameCase, seed: int) -> tuple[int, ...]:
    wall = list(case.state.wall)
    Random(seed).shuffle(wall)
    return tuple(wall)


def finish_case(case: MidgameCase, profile: tuple[str, ...], *, wall: tuple[int, ...] | None = None, first_discard_strategy: str | None = None) -> GameResult:
    """Profile uses roles: actor first, then absolute seats in draw order.

    Omit wall to replay its real order; callers pass one shared permutation
    to every profile for common random numbers. Return absolute-seat payoffs.
    first_discard_strategy overrides only the stored pending discard; later
    discards use the profile, including any later actor discards after calls.
    """
    if len(profile) != 4 or any(name not in STRATEGIES for name in profile):
        raise ValueError("profile must contain four known strategies")
    if first_discard_strategy is not None and first_discard_strategy not in STRATEGIES:
        raise ValueError("unknown first discard strategy")
    state = case.state
    if wall is not None:
        if sorted(wall) != sorted(state.wall):
            raise ValueError("replacement wall must preserve the live tile multiset")
        state = replace(state, wall=list(wall))
    actor = state.current
    first = first_discard_strategy is not None

    def discard(observation: DecisionSnapshot) -> tuple[int, bool]:
        nonlocal first
        if first:
            first = False
            assert observation.seat == actor
            if first_discard_strategy is not None:
                return choose_discard(observation, first_discard_strategy)
        return choose_discard(observation, profile[(observation.seat - actor) % 4])

    return play_game(policies=("attack",) * 4, initial_state=state, discard_policy=discard)


def actor_shanten(case: MidgameCase) -> int:
    player = case.state.players[case.state.current]
    return _cached_analysis(tuple(player.hand), len(player.melds) + len(player.kongs), _public_counts(case.state.players))[0].shanten_after


def paired_case_gains(base: list, other: list, role: int) -> tuple[float, ...]:
    """Average paired worlds inside each case before bootstrapping cases."""
    if len(base) != len(other):
        raise ValueError("payoff tables must have matching cases")
    values = []
    for left, right in zip(base, other):
        if not left or len(left) != len(right):
            raise ValueError("each case must have matching nonempty worlds")
        values.append(sum(b[role] - a[role] for a, b in zip(left, right)) / len(left))
    return tuple(values)


def bootstrap_interval(values: tuple[float, ...], *, seed: int, resamples: int = 2000) -> dict:
    """Percentile 95% interval resampling whole cases, as empirical_game."""
    count = len(values)
    if not count:
        return {"cases": 0, "mean_gain": None, "ci95": None}
    rng = Random(seed)
    draws = sorted(sum(values[rng.randrange(count)] for _ in range(count)) / count for _ in range(resamples))
    return {"cases": count, "mean_gain": sum(values) / count, "ci95": [draws[int(.025 * resamples)], draws[min(resamples - 1, int(.975 * resamples))]]}
