"""Step 3l: does role 0 attack because of its seat or because its hand is good?

Per case, the paired gain of role 0 playing ``threat`` instead of
``deal_in_risk`` while the other roles play ``deal_in_risk`` (TDDD - DDDD),
split by the actor's shanten stratum and by whether any opponent declared.
Intervals are a 95% percentile bootstrap over cases inside each cell.

    python scripts/role0_by_hand.py --seed 1
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from random import Random

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from taimahjong.empirical_corpus import empirical_game_cases
from taimahjong.empirical_game import build_game


TDDD = ("threat", "deal_in_risk", "deal_in_risk", "deal_in_risk")
DDDD = ("deal_in_risk",) * 4


def interval(values: list[float], resamples: int = 2000) -> tuple[float, float]:
    rng = Random(7)
    count = len(values)
    draws = sorted(
        sum(values[rng.randrange(count)] for _ in range(count)) / count
        for _ in range(resamples)
    )
    return draws[int(0.025 * resamples)], draws[int(0.975 * resamples) - 1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sims", type=int, default=100)
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args()

    cases = empirical_game_cases()
    game = build_game(
        cases, sims=args.sims, seed=args.seed, strategies=("threat",),
        profiles=(TDDD, DDDD),
    )
    attack, defend, sims = game.units[TDDD], game.units[DDDD], game.sims
    gains = [
        sum(attack[i][0] - defend[i][0] for i in range(c * sims, (c + 1) * sims)) / sims
        for c in range(len(cases))
    ]
    groups: dict[tuple[str, str], list[float]] = {}
    for case, gain in zip(cases, gains):
        threat = "none" if case.strata.threat_level == "none" else "declared"
        groups.setdefault((case.strata.hand_state, threat), []).append(gain)
        groups.setdefault((case.strata.hand_state, "all"), []).append(gain)
    for (hand, threat), values in sorted(groups.items()):
        low, high = interval(values)
        print(
            f"{hand:>10} {threat:>9} n={len(values):>3}"
            f" gain={sum(values) / len(values):+.4f} [{low:+.4f}, {high:+.4f}]"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
