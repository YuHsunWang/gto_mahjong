"""Does the regret interval narrow with more cases, or with more worlds?

``docs/equilibrium-plan.md`` blames the unresolved equilibrium on the case
count (26) rather than the world count (400), and its next item is "add cases".
That item is only worth doing if the cluster-bootstrap half-width really does
shrink like ``1/sqrt(cases)``.  This script measures both axes at once by
subsampling the corpus that already exists.

Why subsampling is legitimate on both axes.  Worlds are seeded per case
(``sample_worlds(observation, sims, seed + case.seed)`` in ``build_game``), so
dropping cases leaves every surviving case's worlds untouched, and a ``k``-case
subset of the per-case deviation gains is arithmetically the game built on
those ``k`` cases alone.  Worlds inside a case are IID draws from production's
belief model, rejection-sampled independently, so any ``s`` of the ``sims``
worlds is a valid ``s``-world sample.

Two things this cannot check.  Whether *new* cases would look like the old ones
-- the extrapolation assumes new cases share the current dispersion, and a
corpus extended into strata the current 26 avoid could be more dispersed, not
less.  And the summary must be the *mean* half-width over subsets, not the
median: the per-case gains are dominated by one or two extreme cases, so a
subset either contains the dominant case or does not, and the median tracks
whether the typical subset drew it -- a quantity that rises with subset size
for reasons that have nothing to do with resolution.
"""

from __future__ import annotations

import argparse
import json
import sys
from math import log, sqrt
from pathlib import Path
from random import Random
from statistics import mean, pstdev
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from taimahjong.empirical_game import build_game
from taimahjong.reference_ev import representative_reference_cases


DEFAULT_CASE_COUNTS = (8, 13, 20, 26)
DEFAULT_WORLD_COUNTS = (20, 100, 400)
DEFAULT_PROFILES = ("EEEE", "SESS", "SEES")

# (role, alternative) -> per-case, per-world paired deviation gain.
GainMatrix = dict[tuple[int, str], tuple[tuple[float, ...], ...]]


def _profile(code: str) -> tuple[str, ...]:
    names = {"E": "efficiency", "S": "safety"}
    if len(code) != 4 or any(letter not in names for letter in code):
        raise argparse.ArgumentTypeError(f"profile must be 4 of E/S: {code}")
    return tuple(names[letter] for letter in code)


def _code(profile: tuple[str, ...]) -> str:
    return "".join(name[0].upper() for name in profile)


def gain_matrices(game, profile: tuple[str, ...]) -> GainMatrix:
    """Paired gains kept per world, so worlds can be subsampled later.

    ``EmpiricalGame._deviation_gains`` averages the worlds away because that is
    the cluster the shipped interval resamples; here the world axis is the
    thing under test, so it has to survive.
    """
    base = game.units[profile]
    matrices: GainMatrix = {}
    for role in range(4):
        for name in game.strategies:
            if name == profile[role]:
                continue
            candidate = list(profile)
            candidate[role] = name
            other = game.units[tuple(candidate)]
            matrices[(role, name)] = tuple(
                tuple(
                    other[index][role] - base[index][role]
                    for index in range(case * game.sims, (case + 1) * game.sims)
                )
                for case in range(game.cases)
            )
    return matrices


def half_width(
    matrices: GainMatrix,
    cases: tuple[int, ...],
    worlds: tuple[tuple[int, ...], ...],
    *,
    resamples: int,
    seed: int,
    confidence: float = 0.95,
) -> float:
    """Cluster bootstrap over ``cases``, each averaged over its ``worlds``.

    The maximum over deviations is taken inside each resample, exactly as in
    :meth:`EmpiricalGame.regret_interval`, so the interval keeps covering the
    selection of which role's deviation looked best.
    """
    means = {
        key: [
            sum(matrix[case][world] for world in picks) / len(picks)
            for case, picks in zip(cases, worlds)
        ]
        for key, matrix in matrices.items()
    }
    keys = list(means)
    count = len(cases)
    rng = Random(seed)
    draws = []
    for _ in range(resamples):
        picks = [rng.randrange(count) for _ in range(count)]
        draws.append(max(
            sum(means[key][i] for i in picks) / count for key in keys
        ))
    draws.sort()
    tail = (1.0 - confidence) / 2.0
    low = draws[int(tail * resamples)]
    high = draws[min(resamples - 1, int((1.0 - tail) * resamples))]
    return (high - low) / 2.0


def check_against_regret_interval(game, matrices: GainMatrix, profile) -> None:
    """The subsampling machinery must reproduce the shipped interval."""
    full_cases = tuple(range(game.cases))
    full_worlds = (tuple(range(game.sims)),) * game.cases
    measured = half_width(
        matrices, full_cases, full_worlds, resamples=2000, seed=7,
    )
    reference = game.regret_interval(profile, resamples=2000, seed=7)
    expected = (reference.high - reference.low) / 2.0
    if abs(measured - expected) > 1e-12:
        raise AssertionError(
            f"subsampled half-width {measured} != regret_interval {expected}"
        )


def report_variance_split(matrices: GainMatrix, sims: int) -> tuple[int, str]:
    """Split the case-level spread into real heterogeneity and world noise.

    The cluster bootstrap resamples case means, so it cannot tell the two
    apart: a case mean that differs from its neighbours because the hand is
    genuinely different and one that differs because 400 worlds were not
    enough for *that* case both widen the interval.  Which one dominates
    decides whether cases or worlds are the binding budget.
    """
    best = max(
        matrices, key=lambda key: mean(mean(row) for row in matrices[key]),
    )
    rows = matrices[best]
    case_means = [mean(row) for row in rows]
    observed = pstdev(case_means) ** 2
    within = mean(pstdev(row) ** 2 / sims for row in rows)
    print(
        f"  worst deviation role {best[0]} -> {best[1]}:"
        f" gain {mean(case_means):+.4f} tai"
    )
    print(
        f"  spread across the {len(rows)} case means: variance {observed:.4f}"
        f" (sd {sqrt(observed):.3f} tai)"
    )
    print(
        f"  of which world sampling noise: {within:.4f}"
        f" ({within / observed:.0%});"
        f" real case-to-case heterogeneity: {max(observed - within, 0.0):.4f}"
    )
    squares = sorted(
        ((value - mean(case_means)) ** 2 for value in case_means), reverse=True,
    )
    print(
        f"  largest single case holds {squares[0] / sum(squares):.0%}"
        f" of the spread, top 2 hold"
        f" {(squares[0] + squares[1]) / sum(squares):.0%}"
    )
    return best


def fit_exponent(sizes: list[int], widths: list[float]) -> float:
    """Least-squares slope of log(half-width) against log(size).

    ``-0.5`` is the square-root rule the plan assumes; much flatter means the
    axis does not buy what the plan expects.
    """
    xs = [log(size) for size in sizes]
    ys = [log(width) for width in widths]
    mean_x, mean_y = sum(xs) / len(xs), sum(ys) / len(ys)
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    return numerator / sum((x - mean_x) ** 2 for x in xs)


def scaling_table(
    matrices: GainMatrix,
    cases: int,
    sims: int,
    *,
    case_counts: tuple[int, ...],
    world_counts: tuple[int, ...],
    subsets: int,
    resamples: int,
    seed: int,
) -> dict[tuple[int, int], float]:
    """Mean half-width over ``subsets`` fresh (case, world) subsamples."""
    table: dict[tuple[int, int], float] = {}
    for case_count in case_counts:
        for world_count in world_counts:
            rng = Random(seed + 31 * case_count + world_count)
            widths = []
            trials = 1 if case_count >= cases and world_count >= sims else subsets
            for trial in range(trials):
                picked = (
                    tuple(range(cases)) if case_count >= cases
                    else tuple(rng.sample(range(cases), case_count))
                )
                worlds = tuple(
                    tuple(range(sims)) if world_count >= sims
                    else tuple(rng.sample(range(sims), world_count))
                    for _ in picked
                )
                widths.append(half_width(
                    matrices, picked, worlds,
                    resamples=resamples, seed=seed + 1000 * trial,
                ))
            table[(case_count, world_count)] = sum(widths) / len(widths)
    return table


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sims", type=int, default=400)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--subsets", type=int, default=40)
    parser.add_argument("--resamples", type=int, default=800)
    parser.add_argument("--bootstrap-seed", type=int, default=7)
    parser.add_argument(
        "--case-counts", type=int, nargs="+", default=list(DEFAULT_CASE_COUNTS),
    )
    parser.add_argument(
        "--world-counts", type=int, nargs="+",
        default=list(DEFAULT_WORLD_COUNTS),
    )
    parser.add_argument(
        "--profiles", type=_profile, nargs="+",
        default=[_profile(code) for code in DEFAULT_PROFILES],
    )
    parser.add_argument(
        "--cache", type=Path, default=None,
        help="reuse (or write) the built gain matrices at this path",
    )
    args = parser.parse_args()

    case_counts = tuple(sorted(args.case_counts))
    world_counts = tuple(sorted(args.world_counts))
    cached = {}
    if args.cache and args.cache.exists():
        raw = json.loads(args.cache.read_text())
        if raw["sims"] != args.sims or raw["seed"] != args.seed:
            raise SystemExit("cache was built at a different sims/seed")
        cases_count, sims = raw["cases"], raw["sims"]
        cached = {
            code: {
                (int(role), name): tuple(tuple(row) for row in matrix)
                for key, matrix in entry.items()
                for role, name in [key.split(":", 1)]
            }
            for code, entry in raw["profiles"].items()
        }
        print(f"loaded {len(cached)} profiles from {args.cache}")
        game = None
    else:
        cases = representative_reference_cases()
        started = perf_counter()
        game = build_game(cases, sims=args.sims, seed=args.seed)
        cases_count, sims = game.cases, game.sims
        print(
            f"built {len(game.payoffs)} profiles over {cases_count} cases x"
            f" {sims} worlds in {perf_counter() - started:.0f}s"
        )

    store = {}
    for profile in args.profiles:
        code = _code(profile)
        if code in cached:
            matrices = cached[code]
        else:
            if game is None:
                raise SystemExit(f"{code} is not in the cache; rebuild")
            matrices = gain_matrices(game, profile)
            check_against_regret_interval(game, matrices, profile)
        store[code] = {
            f"{role}:{name}": [list(row) for row in matrix]
            for (role, name), matrix in matrices.items()
        }

        print(f"\n=== {code} (world seed {args.seed}) ===")
        report_variance_split(matrices, sims)
        table = scaling_table(
            matrices, cases_count, sims,
            case_counts=case_counts, world_counts=world_counts,
            subsets=args.subsets, resamples=args.resamples,
            seed=args.bootstrap_seed,
        )
        header = "".join(f"{count:>10}" for count in world_counts)
        print(f"\n  mean half-width, tai (worlds across, cases down)")
        print(f"  {'cases':>5}{header}   exponent")
        for case_count in case_counts:
            row = [table[(case_count, count)] for count in world_counts]
            cells = "".join(f"{value:>10.4f}" for value in row)
            slope = fit_exponent(list(world_counts), row)
            print(f"  {case_count:>5}{cells}   {slope:+.3f} (worlds)")
        print(f"  {'exp.':>5}", end="")
        for world_count in world_counts:
            column = [table[(count, world_count)] for count in case_counts]
            print(f"{fit_exponent(list(case_counts), column):>+10.3f}", end="")
        print("   (cases)")

    if args.cache and not args.cache.exists():
        args.cache.write_text(json.dumps({
            "cases": cases_count, "sims": sims, "seed": args.seed,
            "profiles": store,
        }))
        print(f"\ncached gain matrices to {args.cache}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
