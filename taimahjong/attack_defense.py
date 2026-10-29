"""Independent attack/defense grading using only an actor's public snapshot."""

from .midgame_game import choose_discard, discard_risks
from .selfplay import DecisionSnapshot
from .ukeire import discard_analysis


def risk_levels(risks: dict[int, float]) -> dict[int, str]:
    """Relative thirds over distinct legal tile types, not physical copies.

    For n legal tile types, r = number with strictly lower risk (zero-based
    competition rank). Level = floor(3*r/n): 0 safe, 1 normal, 2 dangerous.
    Ties share their lowest rank and never split; all-equal hands are safe.
    These are within-hand ranks, not calibrated deal-in probabilities.
    """
    labels = ("安全", "普通", "危險")
    return {
        tile: labels[3 * sum(other < risk for other in risks.values()) // len(risks)]
        for tile, risk in risks.items()
    }


def recommendation(observation: DecisionSnapshot, shanten_after: int) -> dict:
    """Fourth-round table in docs/midgame-attack-defense.md."""
    wall = observation.wall_remaining
    if wall >= 20 or wall >= 10 and shanten_after == 0:
        verdict, strategy = "該進攻", "attack"
    elif wall >= 10 and shanten_after == 1:
        verdict, strategy = "不拆一向聽，挑安全的打", "keep_safe"
    elif wall <= 9 and shanten_after == 0:
        verdict, strategy = "已經聽牌：不要拆聽，能聽的牌裡打最安全的", "keep_safe"
    else:
        verdict, strategy = "該下車，之後一路打安全牌", "fold"
    return {
        "verdict": verdict,
        "strategy": strategy,
        "tile": choose_discard(observation, strategy)[0],
    }


def grade(observation: DecisionSnapshot, attack_tile: int, defense_tile: int) -> dict:
    # Public analysis: unlike the self-play cache, it no longer counts the discarded copy as drawable.
    analyses = discard_analysis(
        observation.hand, len(observation.melds) + len(observation.kongs), observation.public_counts,
    )
    by_tile = {item.discard: item for item in analyses}
    if attack_tile not in by_tile or defense_tile not in by_tile:
        raise ValueError("both choices must be legal discards from your hand")
    best_shanten = min(item.shanten_after for item in analyses)
    best_ukeire = max(item.total for item in analyses if item.shanten_after == best_shanten)
    attack_correct = sorted(
        item.discard for item in analyses
        if item.shanten_after == best_shanten and item.total == best_ukeire
    )
    risks = {tile: risk for risk, _, tile in discard_risks(observation)}
    minimum = min(risks.values())
    defense_correct = sorted(tile for tile, risk in risks.items() if risk == minimum)
    levels = risk_levels(risks)
    return {
        "attack": {
            "tile": attack_tile, "correct": attack_tile in attack_correct,
            "correct_tiles": attack_correct, "ukeire": by_tile[attack_tile].total,
            "best_ukeire": best_ukeire, "risk_level": levels[attack_tile],
        },
        "defense": {
            "tile": defense_tile, "correct": defense_tile in defense_correct,
            "correct_tiles": defense_correct, "risk_level": levels[defense_tile],
        },
        "shared_tiles": sorted(set(attack_correct) & set(defense_correct)),
        "shanten_after": best_shanten,
        "recommendation": recommendation(observation, best_shanten),
    }
