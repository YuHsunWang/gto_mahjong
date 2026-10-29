"""Actor-only exit decisions against three attacking opponents."""

from __future__ import annotations

from .danger import tenpai_score
from .midgame_corpus import MidgameCase, stage_for
from .midgame_game import choose_discard, discard_risks, finish_case
from .selfplay import DecisionSnapshot, _cached_analysis, _decision_snapshot


# *_once: that strategy at the stored decision only, then attack; *_rest: to the end.
ACTOR_PROFILES = ("attack", "dodge_once", "fold_rest", "keep_safe_once", "keep_safe_rest")


def finish_actor_case(case: MidgameCase, strategy: str, *, wall=None):
    """Only role 0 deviates; dodge applies fold at the pending decision only."""
    if strategy not in ACTOR_PROFILES:
        raise ValueError(f"unknown actor strategy: {strategy}")
    actor = {"fold_rest": "fold", "keep_safe_rest": "keep_safe"}.get(strategy, "attack")
    first = {"dodge_once": "fold", "keep_safe_once": "keep_safe"}.get(strategy)
    return finish_case(case, (actor, "attack", "attack", "attack"), wall=wall, first_discard_strategy=first)


def case_observation(case: MidgameCase) -> DecisionSnapshot:
    """Engine adapter copies own hand and public table, never hidden contents."""
    state = case.state
    return _decision_snapshot(state.current, state.drawn_tile, state.players, len(state.wall))


def decision_features(observation: DecisionSnapshot) -> dict:
    """Accept only the public snapshot: no GameState, hidden hands or wall.

    Danger rank is ascending competition rank (1 = safest); equal scores get
    equal ranks. Opponent meld count sums public sets across all three seats,
    including kongs exposed as triplets by the engine observation adapter.
    """
    assert isinstance(observation, DecisionSnapshot), "features require an actor observation"
    attack, _ = choose_discard(observation, "attack")
    safest, _ = choose_discard(observation, "fold")
    keep_safe, _ = choose_discard(observation, "keep_safe")
    risks = {tile: risk for risk, _, tile in discard_risks(observation)}
    analyses = _cached_analysis(observation.hand, len(observation.melds) + len(observation.kongs), observation.public_counts)
    return {
        "wall_remaining": observation.wall_remaining,
        "stage": stage_for(observation.wall_remaining),
        "actor_shanten": analyses[0].shanten_after,
        "attack_tile": attack,
        "safest_tile": safest,
        "attack_danger": risks[attack],
        "safest_danger": risks[safest],
        "attack_danger_rank": 1 + sum(risk < risks[attack] for risk in risks.values()),
        "max_opponent_tenpai_score": max(tenpai_score(opponent).score for _, opponent in observation.opponents),
        "opponent_melds": sum(len(opponent.melds) for _, opponent in observation.opponents),
        "attack_is_drawn": attack == observation.drawn_tile,
        "attack_equals_safest": attack == safest,
        "keep_safe_tile": keep_safe,
        "keep_safe_danger": risks[keep_safe],
        "keep_safe_equals_attack": keep_safe == attack,
    }
