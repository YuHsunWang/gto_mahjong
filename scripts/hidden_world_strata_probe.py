"""Measure the hidden-world cap one configuration per fresh process.

The production sampler couples two mechanisms: reuse of a bounded hidden-world
pool and Latin-hypercube (LHS) tenpai quantiles.  ``--stratification iid``
turns off only the latter by replacing the already-generated LHS quantiles with
deterministic IID uniforms; the sampler's RNG consumption and every other input
stay unchanged.  Running the four pool/stratification combinations therefore
provides the requested 2x2 comparison.
"""

from __future__ import annotations

import argparse
import json
import random
import resource
import sys
from collections import Counter
from dataclasses import dataclass
from math import isclose
from pathlib import Path
from statistics import mean
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from taimahjong import ev
from taimahjong.calibration import Calibration
from taimahjong.danger import OpponentView, RiverEntry
from taimahjong.ev_benchmark import EVBenchmarkCase, benchmark_corpus
from taimahjong.moments import ClusteredSampleMoments
from taimahjong.scoring import DEFAULT_SCHEME
from taimahjong.tiles import parse_tiles
from taimahjong.ukeire import discard_analysis


DEFAULT_SIMS = 200
TOP_K = 5


@dataclass(frozen=True)
class ProbeCase:
    name: str
    hand: tuple[int, ...]
    opponents: tuple[OpponentView, ...]
    visible: tuple[int, ...]
    turns: int
    seed: int
    scheme: object = DEFAULT_SCHEME


def historical_case() -> ProbeCase:
    """The exact state used for the previously recorded 2.957/2.139 probe."""
    hand = parse_tiles("123m456m789m11223p345s")
    river_tiles = (6, 7, 8, 14, 15, 16, 18, 19, 20, 21, 22, 23, 24, 25)
    opponent = OpponentView(
        [RiverEntry(tile, "tsumogiri") for tile in river_tiles],
        [],
    )
    visible = [0] * 34
    for entry in opponent.river:
        visible[entry.tile] += 1
    return ProbeCase(
        "historical-threat",
        hand,
        (opponent,),
        tuple(visible),
        8,
        30,
    )


def study_cases(repeat: int) -> tuple[ProbeCase, ...]:
    """Committed MJ-008 states, with an independent seed batch per repeat."""
    offset = repeat * 1_000_003
    return tuple(
        ProbeCase(
            case.name,
            case.hand,
            case.opponents,
            case.visible,
            case.turns,
            case.seed + offset,
            case.scheme,
        )
        for case in benchmark_corpus()
    )


def _lhs_bins(records: list[tuple[tuple[float, ...], tuple[float, ...]]], index: int, pool: int, effective: bool) -> list[int]:
    column = 1 if effective else 0
    return sorted(int(record[column][index] * pool) for record in records)


def _validate_mechanisms(
    *,
    case: ProbeCase,
    ranked: list[ev.EVRankEntry],
    pool: int,
    sims: int,
    stratification: str,
    calibration_active: bool,
    quantile_records: list[tuple[tuple[float, ...], tuple[float, ...]]],
    world_batches: list[list[ev._TrialWorld]],
) -> dict[str, object]:
    if len(world_batches) != 1:
        raise AssertionError(f"expected one production-world batch, got {len(world_batches)}")
    worlds = world_batches[0]
    if len(worlds) != sims or len(quantile_records) != pool:
        raise AssertionError("configured hidden-world pool was not exercised")

    strata = tuple(world.hidden_stratum for world in worlds)
    if strata != tuple(trial % pool for trial in range(sims)):
        raise AssertionError("hidden-world strata were not reused in balanced trial order")
    cluster_sizes = sorted(Counter(strata).values())
    expected_sizes = sorted(
        sims // pool + int(index < sims % pool)
        for index in range(pool)
    )
    if cluster_sizes != expected_sizes:
        raise AssertionError("hidden-world cluster sizes are not balanced")

    terminal_seeds = [world.terminal_seed for world in worlds]
    if None in terminal_seeds or len(set(terminal_seeds)) != sims:
        raise AssertionError("terminal streams were not fresh per trial")
    if pool < sims:
        for trial in range(pool, sims):
            source = worlds[trial % pool]
            if worlds[trial].players is not source.players or worlds[trial].wall is not source.wall:
                raise AssertionError("capped trials did not reuse their hidden determinization")
    elif len({id(world.players) for world in worlds}) != sims:
        raise AssertionError("uncapped trials unexpectedly reused hidden determinizations")

    for opponent_index in range(3):
        if _lhs_bins(quantile_records, opponent_index, pool, False) != list(range(pool)):
            raise AssertionError("production LHS generation was not active")
    if stratification == "lhs":
        for opponent_index in range(3):
            if _lhs_bins(quantile_records, opponent_index, pool, True) != list(range(pool)):
                raise AssertionError("effective LHS quantiles do not cover every stratum")
    else:
        effective_is_lhs = all(
            _lhs_bins(quantile_records, opponent_index, pool, True) == list(range(pool))
            for opponent_index in range(3)
        )
        if effective_is_lhs or all(native == effective for native, effective in quantile_records):
            raise AssertionError("IID control failed to disable effective stratification")

    if calibration_active:
        if not all(all(item is not None for item in world.ron_value_hands) for world in worlds[:pool]):
            raise AssertionError("calibrated RON valuation was not active")
    elif not all(all(item is None for item in world.ron_value_hands) for world in worlds[:pool]):
        raise AssertionError("uncalibrated control unexpectedly built RON value hands")

    real = sorted(
        (entry for entry in ranked if not entry.is_fold),
        key=lambda entry: (-entry.net_ev, entry.discard),
    )
    legal_count = len(discard_analysis(case.hand, 0, case.visible))
    if not (TOP_K <= len(real) <= TOP_K + 1 < legal_count):
        raise AssertionError(
            f"confidence screening inactive: returned={len(real)} legal={legal_count}"
        )
    if any(entry.sample_count != sims for entry in real):
        raise AssertionError("a screened finalist did not receive the production budget")
    if any(entry.trial_strata != real[0].trial_strata for entry in real[1:]):
        raise AssertionError("discard candidates did not share common random worlds")
    for entry in real:
        recomputed = ClusteredSampleMoments.from_clustered_values(
            entry.trial_values,
            entry.trial_strata,
        ).standard_error
        if recomputed is None or entry.standard_error is None or not isclose(
            recomputed, entry.standard_error, rel_tol=0.0, abs_tol=1e-12,
        ):
            raise AssertionError("reported uncertainty was not cluster-robust")

    return {
        "pool_exercised": len(set(strata)),
        "cluster_size_min": min(cluster_sizes),
        "cluster_size_max": max(cluster_sizes),
        "fresh_terminal_seeds": len(set(terminal_seeds)),
        "lhs_generation_active": True,
        "effective_stratification": stratification,
        "screening_active": True,
        "legal_candidates": legal_count,
        "returned_candidates": len(real),
        "top_k": TOP_K,
        "cluster_robust_se": True,
        "calibration_active": calibration_active,
    }


def run_case(
    case: ProbeCase,
    *,
    pool: int,
    sims: int,
    stratification: str,
    calibration: Calibration | None,
) -> dict[str, object]:
    quantile_records: list[tuple[tuple[float, ...], tuple[float, ...]]] = []
    world_batches: list[list[ev._TrialWorld]] = []
    original_sample = ev._sample_production_world
    original_worlds = ev._production_worlds

    def sampled_world(
        hand,
        seen,
        views,
        turns,
        context_template,
        world_seed,
        tenpai_quantiles=None,
        calibrated_ron_values=False,
    ):
        if tenpai_quantiles is None:
            raise AssertionError("production sampler did not supply stratified quantiles")
        native = tuple(tenpai_quantiles)
        effective = native
        if stratification == "iid":
            iid_rng = random.Random(f"hidden-world-iid:{world_seed}")
            effective = tuple(iid_rng.random() for _ in range(3))
        quantile_records.append((native, effective))
        return original_sample(
            hand,
            seen,
            views,
            turns,
            context_template,
            world_seed,
            effective,
            calibrated_ron_values,
        )

    def production_worlds(*args, **kwargs):
        result = original_worlds(*args, **kwargs)
        world_batches.append(result[0])
        return result

    ev.PRODUCTION_HIDDEN_WORLD_STRATA = pool
    ev._sample_production_world = sampled_world
    ev._production_worlds = production_worlds
    try:
        started = perf_counter()
        ranked = ev.ev_rank(
            case.hand,
            case.opponents,
            case.visible,
            turns=case.turns,
            sims=sims,
            seed=case.seed,
            calibration=calibration,
            top_k=TOP_K,
            scheme=case.scheme,
        )
        elapsed = perf_counter() - started
    finally:
        ev._sample_production_world = original_sample
        ev._production_worlds = original_worlds

    checks = _validate_mechanisms(
        case=case,
        ranked=ranked,
        pool=pool,
        sims=sims,
        stratification=stratification,
        calibration_active=calibration is not None,
        quantile_records=quantile_records,
        world_batches=world_batches,
    )
    real = sorted(
        (entry for entry in ranked if not entry.is_fold),
        key=lambda entry: (-entry.net_ev, entry.discard),
    )
    widths = [entry.ci95_high - entry.ci95_low for entry in real]
    gap = ev.paired_delta_moments(real[0], real[1])
    if gap.ci95 is None:
        raise AssertionError("top-1/top-2 paired interval was unavailable")
    gap_low, gap_high = gap.ci95
    return {
        "name": case.name,
        "seed": case.seed,
        "seconds": elapsed,
        "mean_candidate_ci_width": mean(widths),
        "min_candidate_ci_width": min(widths),
        "max_candidate_ci_width": max(widths),
        "top_discard": real[0].discard,
        "runner_up_discard": real[1].discard,
        "paired_gap": gap.mean,
        "paired_gap_ci95": [gap_low, gap_high],
        "paired_gap_ci_width": gap_high - gap_low,
        "paired_gap_resolved": gap_low > 0.0,
        "paired_interval_post_selection": gap.post_selection,
        "checks": checks,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    # "32" and "full" are the original two arms; an explicit integer lets a
    # run target a specific cap, such as the committed production constant.
    parser.add_argument("--pool", required=True)
    parser.add_argument("--stratification", choices=("lhs", "iid"), required=True)
    parser.add_argument("--calibration", choices=("on", "off"), required=True)
    parser.add_argument("--corpus", choices=("historical", "study"), required=True)
    parser.add_argument("--repeat", type=int, default=0)
    parser.add_argument("--sims", type=int, default=DEFAULT_SIMS)
    args = parser.parse_args()
    if args.repeat < 0:
        raise ValueError("repeat must be non-negative")
    if args.sims < 2:
        raise ValueError("sims must be at least two")

    sims = args.sims
    if args.pool == "full":
        pool = sims
    else:
        pool = int(args.pool)
        if not 1 <= pool <= sims:
            raise ValueError("pool must be between one and sims")
    calibration = (
        Calibration.from_path(ROOT / "data" / "calibration.json")
        if args.calibration == "on"
        else None
    )
    cases = (
        (historical_case(),)
        if args.corpus == "historical"
        else study_cases(args.repeat)
    )
    results = [
        run_case(
            case,
            pool=pool,
            sims=sims,
            stratification=args.stratification,
            calibration=calibration,
        )
        for case in cases
    ]
    print(json.dumps({
        "configuration": {
            "pool": pool,
            "cap_enabled": pool < sims,
            "stratification": args.stratification,
            "calibration": args.calibration,
            "corpus": args.corpus,
            "repeat": args.repeat,
            "sims": sims,
            "top_k": TOP_K,
        },
        "total_seconds": sum(result["seconds"] for result in results),
        # Whole-process peak RSS.  Every configuration runs in a fresh process,
        # so this is the configuration's peak, not a running maximum.
        "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "cases": results,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
