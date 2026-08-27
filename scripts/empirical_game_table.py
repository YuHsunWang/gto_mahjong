"""Re-issue the step 3b tables on the empirical game's own corpus.

Everything here is reported as a 95% cluster-bootstrap interval over cases,
never as a point estimate, and every verdict is re-checked under eight
bootstrap seeds.  The rule the plan fixed in step 3 stands: an interval wholly
above zero shows a profile is *not* an equilibrium, an interval wholly below
zero would show it is one, and an interval straddling zero shows only that the
budget did not answer the question.  A verdict that flips under any of the
eight seeds is downgraded to undecided -- step 3b had two cells sitting on zero
that changed answer with the seed.

The regret intervals come from ``EmpiricalGame.regret_interval``, which takes
the maximum over deviations inside each resample so the interval covers the
selection of which role looked best.  The per-role tables below do not select,
so they bootstrap a single deviation's mean directly; they are therefore *not*
comparable to the regret column and are labelled separately.

The script prints two games over the same numbers.  In the four-player game
every role may deviate.  In the restricted game roles 2 and 3 are held at
production's efficiency policy and become part of the environment, so only
roles 0 and 1 decide.  The two answer different questions and neither result
transfers to the other: a profile can be an equilibrium of the restricted game
while role 2 or 3 has a profitable deviation in the full one.

Which game is easier to *prove* something in follows from how regret is
defined.  Taking the maximum over more deviations can only push each resample
higher, so widening the set of strategic roles raises the whole interval: it
makes exclusion easier and proof harder.  The four-player table is the one
that excludes profiles; the restricted table is the one that can put an
interval below zero.

``--tilt`` picks which defensive policy plays against the efficiency
baseline.  ``safety`` is the original crude stand-in -- is any copy of this
tile still unseen?  ``deal_in_risk`` weights the standard wait shapes by the
chance an opponent holds what they need, which is the step-3 replacement the
plan asked for.  Profiles print as E/D either way, so the two runs are read
side by side; D means whichever tilt the run was given.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from random import Random
from statistics import mean
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from taimahjong.empirical_corpus import empirical_game_cases
from taimahjong.empirical_game import EmpiricalGame, build_game


SEEDS = (7, 8, 11, 13, 17, 19, 23, 29)
EFFICIENCY = ("efficiency",) * 4


def _code(profile: tuple[str, ...]) -> str:
    """E for the efficiency baseline, D for whichever defensive tilt is in use."""
    return "".join("E" if name == "efficiency" else "D" for name in profile)


def interval(
    values: list[float], *, resamples: int, seed: int, confidence: float = 0.95,
) -> tuple[float, float]:
    """Percentile bootstrap of the mean of one per-case series."""
    count = len(values)
    rng = Random(seed)
    draws = sorted(
        sum(values[rng.randrange(count)] for _ in range(count)) / count
        for _ in range(resamples)
    )
    tail = (1.0 - confidence) / 2.0
    return (
        draws[int(tail * resamples)],
        draws[min(resamples - 1, int((1.0 - tail) * resamples))],
    )


def verdict(low: float, high: float) -> str:
    if low > 0.0:
        return "not an equilibrium"
    if high < 0.0:
        return "IS an equilibrium"
    return "undecided"


def robust(intervals: list[tuple[float, float]]) -> tuple[bool, str]:
    """Does every bootstrap seed give the same verdict?"""
    verdicts = {verdict(low, high) for low, high in intervals}
    if len(verdicts) == 1:
        return True, ""
    lows = [low for low, _ in intervals]
    highs = [high for _, high in intervals]
    return False, f"low {min(lows):+.3f}..{max(lows):+.3f} high {min(highs):+.3f}..{max(highs):+.3f}"


def case_gains(
    game: EmpiricalGame, profile: tuple[str, ...], role: int, reply: str,
) -> list[float]:
    """Per-case mean paired gain from one role switching to ``reply``."""
    candidate = list(profile)
    candidate[role] = reply
    base, other = game.units[profile], game.units[tuple(candidate)]
    return [
        mean(
            other[index][role] - base[index][role]
            for index in range(case * game.sims, (case + 1) * game.sims)
        )
        for case in range(game.cases)
    ]


def restricted_regret(
    game: EmpiricalGame,
    profile: tuple[str, ...],
    roles: tuple[int, ...],
    *,
    resamples: int,
    seed: int,
) -> tuple[float, float, float]:
    """``regret_interval`` over ``roles`` only, everything else identical.

    With ``roles = (0, 1, 2, 3)`` this reproduces
    :meth:`EmpiricalGame.regret_interval` exactly, which is what
    ``check_against_regret_interval`` asserts.
    """
    gains = {
        (role, name): case_gains(game, profile, role, name)
        for role in roles
        for name in game.strategies
        if name != profile[role]
    }
    keys = list(gains)
    count = game.cases
    rng = Random(seed)
    draws = []
    for _ in range(resamples):
        picks = [rng.randrange(count) for _ in range(count)]
        draws.append(max(
            sum(gains[key][i] for i in picks) / count for key in keys
        ))
    draws.sort()
    point = max(sum(gains[key]) / count for key in keys)
    return (
        point,
        draws[int(0.025 * resamples)],
        draws[min(resamples - 1, int(0.975 * resamples))],
    )


def check_against_regret_interval(game: EmpiricalGame, resamples: int) -> None:
    """The restricted machinery must reproduce the shipped interval at full
    width, or the restricted table is measuring something else entirely."""
    profile = EFFICIENCY
    point, low, high = restricted_regret(
        game, profile, (0, 1, 2, 3), resamples=resamples, seed=SEEDS[0],
    )
    reference = game.regret_interval(profile, resamples=resamples, seed=SEEDS[0])
    for measured, expected in (
        (point, reference.gain), (low, reference.low), (high, reference.high),
    ):
        if abs(measured - expected) > 1e-12:
            raise AssertionError(
                f"restricted_regret disagrees with regret_interval:"
                f" {measured} vs {expected}"
            )


def profile_table(
    game: EmpiricalGame,
    resamples: int,
    *,
    roles: tuple[int, ...] = (0, 1, 2, 3),
) -> None:
    strategic = ", ".join(str(role) for role in roles)
    fixed = [role for role in range(4) if role not in roles]
    title = (
        f"roles {strategic} strategic"
        + (f" (roles {', '.join(map(str, fixed))} fixed at efficiency)" if fixed else "")
    )
    print(f"\n## Every profile: regret and whether it is an equilibrium -- {title}\n")
    print(f"{'profile':>8} {'regret':>9} {'95% CI':>20} {'verdict':>20}  seed-robust")
    profiles = sorted(
        (
            profile for profile in game.payoffs
            if all(profile[role] == "efficiency" for role in fixed)
        ),
        key=_code,
    )
    for profile in profiles:
        results = [
            restricted_regret(game, profile, roles, resamples=resamples, seed=seed)
            for seed in SEEDS
        ]
        point, low, high = results[0]
        stable, spread = robust([(l, h) for _, l, h in results])
        label = verdict(low, high) if stable else "undecided"
        print(
            f"{_code(profile):>8} {point:>+9.4f}"
            f" {f'[{low:+.3f}, {high:+.3f}]':>20} {label:>20}"
            f"  {'yes' if stable else 'NO  ' + spread}"
        )


def role_table(
    game: EmpiricalGame,
    resamples: int,
    *,
    tilt: str,
    baseline: str = "efficiency",
    depth_of: dict[int, int] | None = None,
) -> None:
    """One role at a time, deviating away from ``baseline``.

    The baseline matters more than it looks.  Deviating from all-efficiency
    measures the gradient at the profile production actually plays; deviating
    from the all-tilt profile measures it at the equilibrium.  A depth-by-role
    cell can pay at one and not the other, and only the second says anything
    about what an equilibrium-shaped policy should condition on.
    """
    profile = (baseline,) * 4
    reply = "efficiency" if baseline == tilt else tilt
    print(f"\n## Deviating from all-{baseline} to {reply}, one role at a time\n")
    header = f"{'role':>5} {'cases':>6} {'gain':>9} {'95% CI':>20} {'verdict':>20}  seed-robust"
    print(header)
    for role in range(4):
        gains = case_gains(game, profile, role, reply)
        _emit(role, gains, list(range(game.cases)), resamples, reply=reply)
    if depth_of is None:
        return
    print("\n## Same deviation, split by wall depth\n")
    print(f"{'depth':>5} " + header)
    for depth in sorted(set(depth_of.values())):
        picks = [case for case, value in depth_of.items() if value == depth]
        for role in range(4):
            gains = case_gains(game, profile, role, reply)
            print(f"{depth:>5} ", end="")
            _emit(role, gains, picks, resamples, reply=reply)


def _emit(
    role: int,
    gains: list[float],
    picks: list[int],
    resamples: int,
    *,
    reply: str,
) -> None:
    values = [gains[case] for case in picks]
    if all(value == 0.0 for value in values):
        print(
            f"{role:>5} {len(values):>6} {0.0:>+9.4f} {'exactly zero':>20}"
            f" {'wall never reaches':>20}  --"
        )
        return
    intervals = [
        interval(values, resamples=resamples, seed=seed) for seed in SEEDS
    ]
    low, high = intervals[0]
    stable, spread = robust(intervals)
    label = (
        f"{reply} gains" if low > 0
        else f"{reply} loses" if high < 0
        else "undecided"
    )
    if not stable:
        label = "undecided"
    print(
        f"{role:>5} {len(values):>6} {mean(values):>+9.4f}"
        f" {f'[{low:+.3f}, {high:+.3f}]':>20} {label:>20}"
        f"  {'yes' if stable else 'NO  ' + spread}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sims", type=int, default=100)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--resamples", type=int, default=2000)
    parser.add_argument(
        "--tilt", default="safety", choices=("safety", "deal_in_risk"),
        help="which defensive policy plays against the efficiency baseline",
    )
    parser.add_argument(
        "--baseline", default="efficiency", choices=("efficiency", "tilt"),
        help="which profile the per-role table deviates away from: the "
             "all-efficiency profile production plays, or the all-tilt one",
    )
    parser.add_argument(
        "--templates", type=int, default=None,
        help="truncate the corpus to this many hand templates (13 = the "
             "52-case corpus the step 3c tables used)",
    )
    args = parser.parse_args()

    cases = empirical_game_cases(args.templates)
    started = perf_counter()
    strategies = ("efficiency", args.tilt)
    game = build_game(cases, sims=args.sims, seed=args.seed, strategies=strategies)
    elapsed = perf_counter() - started
    residual = max(abs(sum(values)) for values in game.payoffs.values())
    print(
        f"{len(game.payoffs)} profiles over {game.cases} cases x {game.sims}"
        f" worlds (world seed {args.seed}) in {elapsed:.0f}s;"
        f" strategies {strategies}; zero-sum residual {residual:.1e}"
    )
    check_against_regret_interval(game, args.resamples)
    print("restricted_regret reproduces regret_interval at full width")
    profile_table(game, args.resamples)
    profile_table(game, args.resamples, roles=(0, 1))
    role_table(
        game,
        args.resamples,
        tilt=args.tilt,
        baseline=args.tilt if args.baseline == "tilt" else "efficiency",
        depth_of={
            index: len(case.state.wall) for index, case in enumerate(cases)
        },
    )
    print(f"\nbootstrap seeds checked: {SEEDS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
