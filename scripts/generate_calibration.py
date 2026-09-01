"""Generate a deterministic fit/holdout self-play calibration document."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import sys
from datetime import datetime, timezone
from multiprocessing import Pool
from pathlib import Path
from random import Random
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from taimahjong.calibration import (  # noqa: E402
    Calibration,
    DANGER_BUCKETS,
    DANGER_EDGES,
    DANGER_MODIFIERS,
    MIN_CELL_COUNT,
    counts_from_games,
    danger_bucket,
    empty_counts,
    merge_counts,
    table_document,
)
import taimahjong.selfplay as selfplay  # noqa: E402


POLICIES = ("attack", "cautious", "ev_aware", "ev_aware")
MAX_WORKERS = 4
HOLDOUT_MODULUS = 5
HOLDOUT_REMAINDER = 4
EV_MODEL_IDENTIFIER = "coherent-terminal-rollout-v1"
EV_MODEL_SOURCE_DATE = "2026-07-29"
CALIBRATION_INPUT = Path(__file__).resolve().parents[1] / "data" / "calibration.json"
TAIL_BOOTSTRAP_REPLICATES = 2000
TAIL_BOOTSTRAP_SEED = 20260806
TAIL_DIAGNOSTIC_EDGES = (9.0, 11.0, 13.0, 16.0, 20.0)
# DEV-119 promoted the split tail to the shipped binning: the open-ended 13+
# cell mixed a 0.659442% 13-16 population with a 1.586684% 16-20 one.  The
# pre-split calibration.DANGER_EDGES stays imported because legacy documents
# without metadata.danger_binning are still read under it.
STANDARD_DANGER_EDGES = DANGER_EDGES + (16.0,)
STANDARD_DANGER_BUCKETS = DANGER_BUCKETS[:-1] + ("13-16", "16+")


def _deal_in_trials(game) -> tuple[tuple[float, bool], ...]:
    trials: list[tuple[float, bool]] = []
    for event in game.events:
        dangers = event.get("danger_by_opponent")
        if dangers is None:
            trials.append((event["danger_score"], bool(event["dealt_in"])))
            continue
        winner = event.get("deal_in_winner")
        trials.extend(
            (score, bool(event["dealt_in"]) and opponent == winner)
            for opponent, score in dangers.items()
        )
    return tuple(trials)


def _play_seed(
    task: tuple[int, bool, bool, tuple[float, ...], tuple[str, ...]],
) -> tuple[int, dict, tuple[tuple[float, bool], ...]]:
    seed, retain_trials, consume_calibration, danger_edges, danger_buckets = task
    game = selfplay.play_game(
        seed,
        POLICIES,
        consume_calibration=consume_calibration,
    )
    counts = counts_from_games(
        [game],
        danger_edges=danger_edges,
        danger_buckets=danger_buckets,
    )
    return seed, counts, _deal_in_trials(game) if retain_trials else ()


def _generate(
    seeds: list[int],
    retained_trial_seeds: set[int],
    workers: int,
    consume_calibration: bool,
    danger_edges: tuple[float, ...],
    danger_buckets: tuple[str, ...],
) -> list[tuple[int, dict, tuple[tuple[float, bool], ...]]]:
    tasks = [
        (
            seed,
            seed in retained_trial_seeds,
            consume_calibration,
            danger_edges,
            danger_buckets,
        )
        for seed in seeds
    ]
    if workers == 1:
        results = [_play_seed(task) for task in tasks]
    else:
        with Pool(workers) as pool:
            results = list(pool.imap_unordered(_play_seed, tasks, chunksize=1))
    return sorted(results, key=lambda result: result[0])


def _merge_seed_counts(
    results,
    selected: set[int],
    danger_buckets: tuple[str, ...],
) -> dict:
    merged = empty_counts(danger_buckets)
    for seed, counts, _ in sorted(results, key=lambda result: result[0]):
        if seed in selected:
            merged = merge_counts(
                merged,
                counts,
                danger_buckets=danger_buckets,
            )
    return merged


def _unsmoothed_isotonic(cells: list[dict]) -> list[float | None]:
    blocks: list[dict] = []
    for index, cell in enumerate(cells):
        observations = cell["observations"]
        if not observations:
            blocks.append({"indexes": [index], "weight": 0, "successes": 0})
            continue
        blocks.append(
            {
                "indexes": [index],
                "weight": observations,
                "successes": cell["deal_ins"],
            }
        )
        while len(blocks) >= 2 and blocks[-2]["weight"] and blocks[-1]["weight"] and (
            blocks[-2]["successes"] / blocks[-2]["weight"]
            > blocks[-1]["successes"] / blocks[-1]["weight"]
        ):
            right = blocks.pop()
            left = blocks.pop()
            blocks.append(
                {
                    "indexes": left["indexes"] + right["indexes"],
                    "weight": left["weight"] + right["weight"],
                    "successes": left["successes"] + right["successes"],
                }
            )
    fitted: list[float | None] = [None] * len(cells)
    for block in blocks:
        probability = block["successes"] / block["weight"] if block["weight"] else None
        for index in block["indexes"]:
            fitted[index] = probability
    return fitted


def _prediction_quality(
    calibration: Calibration,
    trials: list[tuple[float, bool]],
) -> dict:
    reliability = {
        bucket: {"prediction_sum": 0.0, "observations": 0, "deal_ins": 0}
        for bucket in calibration.danger_buckets
    }
    squared_error = 0.0
    negative_log_likelihood = 0.0
    evaluated = 0
    deal_ins = 0
    for score, outcome in trials:
        probability = calibration.deal_in_probability(score)
        if probability is None:
            continue
        squared_error += (probability - int(outcome)) ** 2
        negative_log_likelihood -= math.log(probability if outcome else 1.0 - probability)
        evaluated += 1
        deal_ins += int(outcome)
        cell = reliability[
            danger_bucket(
                score,
                calibration.danger_edges,
                calibration.danger_buckets,
            )
        ]
        cell["prediction_sum"] += probability
        cell["observations"] += 1
        cell["deal_ins"] += int(outcome)

    curve = []
    for bucket in calibration.danger_buckets:
        cell = reliability[bucket]
        observations = cell["observations"]
        curve.append(
            {
                "bucket": bucket,
                "predicted_probability": (
                    cell["prediction_sum"] / observations if observations else None
                ),
                "observed_frequency": (
                    cell["deal_ins"] / observations if observations else None
                ),
                "observations": observations,
                "deal_ins": cell["deal_ins"],
            }
        )

    if not evaluated:
        raise ValueError("calibration did not cover any evaluation observations")
    brier_score = squared_error / evaluated
    log_loss = negative_log_likelihood / evaluated
    base_rate = deal_ins / evaluated
    brier_base = base_rate * (1.0 - base_rate)
    log_loss_base = -(
        (base_rate * math.log(base_rate) if base_rate else 0.0)
        + (
            (1.0 - base_rate) * math.log(1.0 - base_rate)
            if base_rate < 1.0 else 0.0
        )
    )
    return {
        "brier_score": brier_score,
        "brier_base": brier_base,
        "brier_skill_score": (
            1.0 - brier_score / brier_base if brier_base else None
        ),
        "log_loss": log_loss,
        "log_loss_base": log_loss_base,
        "log_loss_skill_score": (
            1.0 - log_loss / log_loss_base if log_loss_base else None
        ),
        "deal_ins": deal_ins,
        "base_rate": base_rate,
        "evaluated_observations": evaluated,
        "total_observations": len(trials),
        "reliability_curve": curve,
    }


def _quality_record(
    fit_counts: dict,
    trials: list[tuple[float, bool]],
    danger_edges: tuple[float, ...],
    danger_buckets: tuple[str, ...],
) -> dict:
    document = table_document(
        fit_counts,
        {
            "danger_binning": {
                "edges": list(danger_edges),
                "buckets": list(danger_buckets),
            },
        },
        danger_buckets=danger_buckets,
    )
    calibration = Calibration(document)
    quality = _prediction_quality(calibration, trials)

    raw_cells = [fit_counts["deal_in"][bucket] for bucket in danger_buckets]
    unsmoothed = _unsmoothed_isotonic(raw_cells)
    smoothed = [
        document["tables"]["deal_in"][bucket]["probability"]
        for bucket in danger_buckets
    ]
    well_populated_changes = [
        (bucket, abs(after - before))
        for bucket, cell, before, after in zip(
            danger_buckets, raw_cells, unsmoothed, smoothed
        )
        if cell["observations"] >= MIN_CELL_COUNT
        and before is not None
        and after is not None
    ]
    largest_bucket, largest_change = max(
        well_populated_changes, key=lambda item: item[1], default=(None, None)
    )
    old_calibration = Calibration(
        {
            **document,
            "tables": {
                **document["tables"],
                "deal_in": {
                    bucket: {
                        **document["tables"]["deal_in"][bucket],
                        "probability": probability,
                    }
                    for bucket, probability in zip(danger_buckets, unsmoothed)
                },
            },
        }
    )
    quality.update({
        "held_out_deal_ins": quality["deal_ins"],
        "held_out_base_rate": quality["base_rate"],
        "total_holdout_observations": quality["total_observations"],
        "smoothing": {
            "prior": "Jeffreys Beta(0.5, 0.5)",
            "counterexample_danger_score": 0.3,
            "counterexample_before_probability": old_calibration.deal_in_probability(0.3),
            "counterexample_after_probability": calibration.deal_in_probability(0.3),
            "largest_well_populated_absolute_change": largest_change,
            "largest_well_populated_change_bucket": largest_bucket,
            "well_populated_minimum_observations": MIN_CELL_COUNT,
        },
    })
    return quality


def _git_commit() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _write_document(path: Path, document: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        json.dump(document, stream, indent=2, sort_keys=True)
        stream.write("\n")


def _calibration_identity() -> str | None:
    if not CALIBRATION_INPUT.exists():
        return None
    return f"sha256:{hashlib.sha256(CALIBRATION_INPUT.read_bytes()).hexdigest()}"


def _previous_calibration_record(consumed: bool) -> dict:
    identity = _calibration_identity()
    if not consumed:
        return {
            "consumed_previous_calibration": False,
            "path": None,
            "calibration_id": None,
        }
    if not CALIBRATION_INPUT.exists():
        return {
            "consumed_previous_calibration": False,
            "path": "data/calibration.json",
            "calibration_id": None,
        }
    return {
        "consumed_previous_calibration": True,
        "path": "data/calibration.json",
        "calibration_id": identity,
    }


def _independent_policy_probe() -> dict:
    """Prove calibration-off skips the loader while calibration-on uses risk."""
    if selfplay.ATTACK_TOP_K != 5:
        raise RuntimeError("independent-policy audit must use production top_k=5")
    hand = (0, 0, 0, 0, 0, 0, 0, 0, 2, 1, 2, 0, 0, 1, 0, 1, 0, 0, 0, 1, 1, 1, 1, 0, 0, 1, 1, 0, 1, 0, 0, 1, 2, 0)
    players = [selfplay.Player("attack") for _ in range(4)]
    players[0].hand = list(hand)
    players[0].policy = "ev_aware"
    loads = 0

    class ScoreCalibration:
        def deal_in_probability(self, score: float) -> float:
            return min(0.99, score * 0.001)

    original_loader = selfplay._default_calibration

    def synthetic_loader() -> ScoreCalibration:
        nonlocal loads
        loads += 1
        return ScoreCalibration()

    selfplay._default_calibration = synthetic_loader
    try:
        off_choice = selfplay._choose_discard(
            0, 8, players, consume_calibration=False,
        )[0]
        off_loads = loads
        on_choice = selfplay._choose_discard(
            0, 8, players, consume_calibration=True,
        )[0]
        on_loads = loads - off_loads
    finally:
        selfplay._default_calibration = original_loader
    if (off_loads, on_loads, off_choice, on_choice) != (0, 1, 19, 28):
        raise RuntimeError(
            "independent-policy probe failed: "
            f"off_loads={off_loads} on_loads={on_loads} "
            f"off_choice={off_choice} on_choice={on_choice}"
        )
    return {
        "passed": True,
        "calibration_off_loads": off_loads,
        "calibration_on_loads": on_loads,
        "calibration_off_discard": off_choice,
        "calibration_on_discard": on_choice,
        "top_k": selfplay.ATTACK_TOP_K,
    }


def _rate_cell(observations: int, deal_ins: int) -> dict:
    return {
        "observations": observations,
        "deal_ins": deal_ins,
        "rate": deal_ins / observations if observations else None,
    }


def _tail_pair(trials: tuple[tuple[float, bool], ...] | list[tuple[float, bool]]) -> tuple[int, int, int, int]:
    lower_observations = lower_deal_ins = upper_observations = upper_deal_ins = 0
    for score, outcome in trials:
        bucket = danger_bucket(score)
        if bucket == "9-13":
            lower_observations += 1
            lower_deal_ins += int(outcome)
        elif bucket == "13+":
            upper_observations += 1
            upper_deal_ins += int(outcome)
    return lower_observations, lower_deal_ins, upper_observations, upper_deal_ins


def _tail_record(totals: tuple[int, int, int, int]) -> dict:
    lower_n, lower_k, upper_n, upper_k = totals
    lower = _rate_cell(lower_n, lower_k)
    upper = _rate_cell(upper_n, upper_k)
    difference = None
    if lower["rate"] is not None and upper["rate"] is not None:
        difference = upper["rate"] - lower["rate"]
    return {
        "9-13": lower,
        "13+": upper,
        "upper_minus_lower": difference,
    }


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    position = fraction * (len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _tail_diagnostics(
    results: list[tuple[int, dict, tuple[tuple[float, bool], ...]]],
) -> dict:
    ordered = sorted(results, key=lambda result: result[0])
    game_pairs = [_tail_pair(trials) for _, _, trials in ordered]
    prefix_targets = sorted({
        size for size in (500, 1000, 2000, 4000, 8000, len(ordered))
        if size <= len(ordered)
    })
    totals = [0, 0, 0, 0]
    prefixes = []
    for games, pair in enumerate(game_pairs, start=1):
        for index, value in enumerate(pair):
            totals[index] += value
        if games in prefix_targets:
            prefixes.append({"games": games, **_tail_record(tuple(totals))})

    fine_cells = [
        {"low": low, "high": high, "observations": 0, "deal_ins": 0}
        for low, high in zip(TAIL_DIAGNOSTIC_EDGES, (*TAIL_DIAGNOSTIC_EDGES[1:], None))
    ]
    for _, _, trials in ordered:
        for score, outcome in trials:
            if score < TAIL_DIAGNOSTIC_EDGES[0]:
                continue
            for cell in fine_cells:
                if cell["high"] is None or score < cell["high"]:
                    cell["observations"] += 1
                    cell["deal_ins"] += int(outcome)
                    break
    fine_tail = [
        {
            "band": f"{cell['low']:g}+" if cell["high"] is None else f"{cell['low']:g}-{cell['high']:g}",
            **_rate_cell(cell["observations"], cell["deal_ins"]),
        }
        for cell in fine_cells
    ]

    rng = Random(TAIL_BOOTSTRAP_SEED)
    differences = []
    for _ in range(TAIL_BOOTSTRAP_REPLICATES):
        sampled = [0, 0, 0, 0]
        for _ in game_pairs:
            pair = game_pairs[rng.randrange(len(game_pairs))]
            for index, value in enumerate(pair):
                sampled[index] += value
        record = _tail_record(tuple(sampled))
        if record["upper_minus_lower"] is not None:
            differences.append(record["upper_minus_lower"])
    return {
        "all_games": _tail_record(tuple(totals)),
        "prefix_scaling": prefixes,
        "fine_tail": fine_tail,
        "game_cluster_bootstrap": {
            "replicates": TAIL_BOOTSTRAP_REPLICATES,
            "seed": TAIL_BOOTSTRAP_SEED,
            "upper_minus_lower_95pct_interval": [
                _percentile(differences, 0.025),
                _percentile(differences, 0.975),
            ],
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--games", type=int, default=2000)
    parser.add_argument("--seed-start", type=int, default=40001)
    parser.add_argument("--workers", type=int, default=MAX_WORKERS)
    parser.add_argument("--verify-games", type=int, default=12)
    parser.add_argument("--out", type=Path, default=Path("data/calibration.json"))
    parser.add_argument("--benchmark-only", action="store_true")
    parser.add_argument(
        "--consume-calibration",
        action="store_true",
        help=(
            "reproduce a legacy feedback build: let ev_aware self-play read "
            "data/calibration.json, and fit under the pre-split binning"
        ),
    )
    parser.add_argument(
        "--audit",
        action="store_true",
        help=(
            "also score the shipped table on this run's trials and emit tail "
            "diagnostics; requires data/calibration.json to exist"
        ),
    )
    args = parser.parse_args()
    if args.games < 1:
        raise ValueError("--games must be positive")
    if not 1 <= args.workers <= MAX_WORKERS:
        raise ValueError(f"--workers must be between 1 and {MAX_WORKERS}")
    if not 0 <= args.verify_games <= args.games:
        raise ValueError("--verify-games must be between 0 and --games")

    consume_calibration = args.consume_calibration
    independent_policy = not consume_calibration
    if args.audit and consume_calibration:
        # The audit scores the shipped table against this run on a shared
        # holdout.  A feedback build reads that same shipped table while it
        # plays, so the comparison would not be between independent arms.
        raise ValueError("--audit cannot be combined with --consume-calibration")
    danger_edges = DANGER_EDGES if consume_calibration else STANDARD_DANGER_EDGES
    danger_buckets = (
        DANGER_BUCKETS if consume_calibration else STANDARD_DANGER_BUCKETS
    )
    policy_probe = _independent_policy_probe() if independent_policy else None
    if policy_probe:
        print(
            "independent_policy_probe=passed "
            f"off_loads={policy_probe['calibration_off_loads']} "
            f"on_loads={policy_probe['calibration_on_loads']} "
            f"off_discard={policy_probe['calibration_off_discard']} "
            f"on_discard={policy_probe['calibration_on_discard']} "
            f"top_k={policy_probe['top_k']}"
        )

    seeds = list(range(args.seed_start, args.seed_start + args.games))
    holdout = {
        seed
        for index, seed in enumerate(seeds)
        if index % HOLDOUT_MODULUS == HOLDOUT_REMAINDER
    }
    retained_trial_seeds = set(seeds) if args.audit else holdout
    previous_calibration = _previous_calibration_record(consume_calibration)
    started = perf_counter()
    results = _generate(
        seeds,
        retained_trial_seeds,
        args.workers,
        consume_calibration,
        danger_edges,
        danger_buckets,
    )
    elapsed = perf_counter() - started
    print(
        f"generated={args.games} workers={args.workers} "
        f"policy={'feedback' if consume_calibration else 'independent'} "
        f"elapsed_seconds={elapsed:.3f} "
        f"seconds_per_game={elapsed / args.games:.6f}"
    )
    if args.benchmark_only:
        return

    determinism = None
    if args.verify_games:
        verify_seeds = seeds[: args.verify_games]
        verify_retained = (
            set(verify_seeds)
            if args.audit
            else holdout.intersection(verify_seeds)
        )
        serial = _generate(
            verify_seeds,
            verify_retained,
            1,
            consume_calibration,
            danger_edges,
            danger_buckets,
        )
        parallel = _generate(
            verify_seeds,
            verify_retained,
            args.workers,
            consume_calibration,
            danger_edges,
            danger_buckets,
        )
        selected = set(verify_seeds)
        serial_counts = _merge_seed_counts(serial, selected, danger_buckets)
        parallel_counts = _merge_seed_counts(parallel, selected, danger_buckets)
        reverse_counts = _merge_seed_counts(
            list(reversed(parallel)), selected, danger_buckets,
        )
        determinism = serial_counts == parallel_counts == reverse_counts
        if not determinism:
            raise RuntimeError("worker-count/completion-order determinism check failed")
        print(
            f"determinism_check=passed games={args.verify_games} "
            f"workers=1,{args.workers} reversed_completion_order=true"
        )

    fit = set(seeds) - holdout
    fit_counts = _merge_seed_counts(results, fit, danger_buckets)
    holdout_trials = [
        trial
        for seed, _, trials in results
        if seed in holdout
        for trial in trials
    ]
    quality = _quality_record(
        fit_counts,
        holdout_trials,
        danger_edges,
        danger_buckets,
    )
    metadata = {
        "danger_reference": "per_opponent",
        "danger_modifiers": DANGER_MODIFIERS,
        "danger_binning": {
            "edges": list(danger_edges),
            "buckets": list(danger_buckets),
        },
        "games": args.games,
        "fit_games": len(fit),
        "held_out_games": len(holdout),
        "seed_range": {"start": seeds[0], "end": seeds[-1], "inclusive": True},
        "split": {
            "unit": "game_seed",
            "rule": (
                f"zero_based_seed_offset_mod_{HOLDOUT_MODULUS}"
                f"_equals_{HOLDOUT_REMAINDER}_is_holdout"
            ),
        },
        "policy_mix": list(POLICIES),
        "calibration_feedback": previous_calibration,
        "independent_policy": {
            "enabled": independent_policy,
            "instrument": (
                "same ev_aware top-5-plus-safest candidates and attack term; "
                "calibration-derived deal-in risk term disabled"
                if independent_policy else None
            ),
            "probe": policy_probe,
        },
        "ev_model": {
            "identifier": EV_MODEL_IDENTIFIER,
            "source_date": EV_MODEL_SOURCE_DATE,
            "git_commit": _git_commit(),
            "selfplay_entrypoint": "taimahjong.selfplay._ev_aware_discard",
            "selfplay_calls_production_ev_rank": False,
        },
        "generation": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "workers": args.workers,
            "max_workers": MAX_WORKERS,
            "wall_clock_seconds": elapsed,
            "worker_count_determinism_verified": determinism,
            "determinism_check_games": args.verify_games,
        },
    }
    document = table_document(
        fit_counts,
        metadata,
        danger_buckets=danger_buckets,
    )
    document["quality"] = quality
    if args.audit:
        if not CALIBRATION_INPUT.exists():
            raise FileNotFoundError("shipped calibration is required for the audit comparison")
        all_trials = [
            trial
            for _, _, trials in results
            for trial in trials
        ]
        shipped_calibration = Calibration.from_path(CALIBRATION_INPUT)
        document["audit"] = {
            "shipped_table": {
                "path": "data/calibration.json",
                "calibration_id": _calibration_identity(),
                "all_independent_games": _prediction_quality(
                    shipped_calibration, all_trials,
                ),
                "same_holdout_as_candidate": _prediction_quality(
                    shipped_calibration, holdout_trials,
                ),
            },
            "candidate_table": {
                "path": str(args.out),
                "same_holdout_as_shipped": quality,
            },
            "tail": _tail_diagnostics(results),
        }
    _write_document(args.out, document)
    print(
        f"fit_games={len(fit)} held_out_games={len(holdout)} "
        f"brier={quality['brier_score']:.9f} log_loss={quality['log_loss']:.9f} "
        f"out={args.out}"
    )


if __name__ == "__main__":
    main()
