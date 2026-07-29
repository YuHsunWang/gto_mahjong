"""Generate a deterministic fit/holdout self-play calibration document."""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from datetime import datetime, timezone
from multiprocessing import Pool
from pathlib import Path
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from taimahjong.calibration import (  # noqa: E402
    Calibration,
    DANGER_BUCKETS,
    DANGER_MODIFIERS,
    MIN_CELL_COUNT,
    counts_from_games,
    danger_bucket,
    empty_counts,
    merge_counts,
    table_document,
)
from taimahjong.selfplay import play_game  # noqa: E402


POLICIES = ("attack", "cautious", "ev_aware", "ev_aware")
MAX_WORKERS = 4
HOLDOUT_MODULUS = 5
HOLDOUT_REMAINDER = 4
EV_MODEL_IDENTIFIER = "coherent-terminal-rollout-v1"
EV_MODEL_SOURCE_DATE = "2026-07-29"


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


def _play_seed(task: tuple[int, bool]) -> tuple[int, dict, tuple[tuple[float, bool], ...]]:
    seed, retain_trials = task
    game = play_game(seed, POLICIES)
    return seed, counts_from_games([game]), _deal_in_trials(game) if retain_trials else ()


def _generate(
    seeds: list[int],
    holdout_seeds: set[int],
    workers: int,
) -> list[tuple[int, dict, tuple[tuple[float, bool], ...]]]:
    tasks = [(seed, seed in holdout_seeds) for seed in seeds]
    if workers == 1:
        results = [_play_seed(task) for task in tasks]
    else:
        with Pool(workers) as pool:
            results = list(pool.imap_unordered(_play_seed, tasks, chunksize=1))
    return sorted(results, key=lambda result: result[0])


def _merge_seed_counts(results, selected: set[int]) -> dict:
    merged = empty_counts()
    for seed, counts, _ in sorted(results, key=lambda result: result[0]):
        if seed in selected:
            merged = merge_counts(merged, counts)
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


def _quality_record(fit_counts: dict, trials: list[tuple[float, bool]]) -> dict:
    document = table_document(fit_counts)
    calibration = Calibration(document)
    reliability = {
        bucket: {"prediction_sum": 0.0, "observations": 0, "deal_ins": 0}
        for bucket in DANGER_BUCKETS
    }
    squared_error = 0.0
    negative_log_likelihood = 0.0
    evaluated = 0
    for score, outcome in trials:
        probability = calibration.deal_in_probability(score)
        if probability is None:
            continue
        squared_error += (probability - int(outcome)) ** 2
        negative_log_likelihood -= math.log(probability if outcome else 1.0 - probability)
        evaluated += 1
        cell = reliability[danger_bucket(score)]
        cell["prediction_sum"] += probability
        cell["observations"] += 1
        cell["deal_ins"] += int(outcome)

    curve = []
    for bucket in DANGER_BUCKETS:
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

    raw_cells = [fit_counts["deal_in"][bucket] for bucket in DANGER_BUCKETS]
    unsmoothed = _unsmoothed_isotonic(raw_cells)
    smoothed = [document["tables"]["deal_in"][bucket]["probability"] for bucket in DANGER_BUCKETS]
    well_populated_changes = [
        (bucket, abs(after - before))
        for bucket, cell, before, after in zip(
            DANGER_BUCKETS, raw_cells, unsmoothed, smoothed
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
                    for bucket, probability in zip(DANGER_BUCKETS, unsmoothed)
                },
            },
        }
    )
    return {
        "brier_score": squared_error / evaluated,
        "log_loss": negative_log_likelihood / evaluated,
        "evaluated_observations": evaluated,
        "total_holdout_observations": len(trials),
        "reliability_curve": curve,
        "smoothing": {
            "prior": "Jeffreys Beta(0.5, 0.5)",
            "counterexample_danger_score": 0.3,
            "counterexample_before_probability": old_calibration.deal_in_probability(0.3),
            "counterexample_after_probability": calibration.deal_in_probability(0.3),
            "largest_well_populated_absolute_change": largest_change,
            "largest_well_populated_change_bucket": largest_bucket,
            "well_populated_minimum_observations": MIN_CELL_COUNT,
        },
    }


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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--games", type=int, default=2000)
    parser.add_argument("--seed-start", type=int, default=40001)
    parser.add_argument("--workers", type=int, default=MAX_WORKERS)
    parser.add_argument("--verify-games", type=int, default=12)
    parser.add_argument("--out", type=Path, default=Path("data/calibration.json"))
    parser.add_argument("--benchmark-only", action="store_true")
    args = parser.parse_args()
    if args.games < 1:
        raise ValueError("--games must be positive")
    if not 1 <= args.workers <= MAX_WORKERS:
        raise ValueError(f"--workers must be between 1 and {MAX_WORKERS}")
    if not 0 <= args.verify_games <= args.games:
        raise ValueError("--verify-games must be between 0 and --games")

    seeds = list(range(args.seed_start, args.seed_start + args.games))
    holdout = {
        seed
        for index, seed in enumerate(seeds)
        if index % HOLDOUT_MODULUS == HOLDOUT_REMAINDER
    }
    started = perf_counter()
    results = _generate(seeds, holdout, args.workers)
    elapsed = perf_counter() - started
    print(
        f"generated={args.games} workers={args.workers} elapsed_seconds={elapsed:.3f} "
        f"seconds_per_game={elapsed / args.games:.6f}"
    )
    if args.benchmark_only:
        return

    determinism = None
    if args.verify_games:
        verify_seeds = seeds[: args.verify_games]
        verify_holdout = holdout.intersection(verify_seeds)
        serial = _generate(verify_seeds, verify_holdout, 1)
        parallel = _generate(verify_seeds, verify_holdout, args.workers)
        selected = set(verify_seeds)
        serial_counts = _merge_seed_counts(serial, selected)
        parallel_counts = _merge_seed_counts(parallel, selected)
        reverse_counts = _merge_seed_counts(list(reversed(parallel)), selected)
        determinism = serial_counts == parallel_counts == reverse_counts
        if not determinism:
            raise RuntimeError("worker-count/completion-order determinism check failed")
        print(
            f"determinism_check=passed games={args.verify_games} "
            f"workers=1,{args.workers} reversed_completion_order=true"
        )

    fit = set(seeds) - holdout
    fit_counts = _merge_seed_counts(results, fit)
    holdout_trials = [
        trial
        for seed, _, trials in results
        if seed in holdout
        for trial in trials
    ]
    quality = _quality_record(fit_counts, holdout_trials)
    metadata = {
        "danger_reference": "per_opponent",
        "danger_modifiers": DANGER_MODIFIERS,
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
    document = table_document(fit_counts, metadata)
    document["quality"] = quality
    _write_document(args.out, document)
    print(
        f"fit_games={len(fit)} held_out_games={len(holdout)} "
        f"brier={quality['brier_score']:.9f} log_loss={quality['log_loss']:.9f} "
        f"out={args.out}"
    )


if __name__ == "__main__":
    main()
