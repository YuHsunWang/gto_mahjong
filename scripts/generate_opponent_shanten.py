"""Build the observed opponent shanten distribution from self-play (DEV-120).

The production world sampler filled every non-tenpai opponent by drawing
uniformly from the unseen pool, which put almost no mass on 1- and 2-shanten
hands.  This script measures where that mass actually sits, conditioned on the
public state a reader would have, and writes it to a document the sampler can
read.

It deliberately does not touch data/calibration.json: the deal-in table
describes risk pricing in the self-play ecology, this one describes the hidden
hands, and the two are regenerated on different occasions.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from multiprocessing import Pool
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from taimahjong.calibration import MIN_CELL_COUNT  # noqa: E402
from taimahjong.opponent_shanten import (  # noqa: E402
    OpponentShanten,
    cell_key,
    document,
)
from taimahjong.selfplay import play_game  # noqa: E402


POLICIES = ("attack", "cautious", "ev_aware", "ev_aware")
MAX_WORKERS = 4
HOLDOUT_MODULUS = 5
HOLDOUT_REMAINDER = 4


def _seed_cells(seed: int) -> tuple[int, dict[str, dict[str, int]]]:
    """Play one seeded game and tally its shanten observations."""
    game = play_game(seed, POLICIES)
    cells: dict[str, dict[str, int]] = {}
    for event in game.events:
        shanten = event["true_shanten"]
        if shanten < 0:
            continue
        key = cell_key(event["melds"], event["turn"], event["tsumogiri_run"])
        cell = cells.setdefault(key, {})
        label = str(shanten)
        cell[label] = cell.get(label, 0) + 1
    return seed, cells


def _merge(target: dict, source: dict) -> dict:
    for key, cell in source.items():
        merged = target.setdefault(key, {})
        for label, count in cell.items():
            merged[label] = merged.get(label, 0) + count
    return target


def _generate(seeds: list[int], workers: int) -> list[tuple[int, dict]]:
    if workers == 1:
        results = [_seed_cells(seed) for seed in seeds]
    else:
        with Pool(processes=workers) as pool:
            results = list(pool.imap_unordered(_seed_cells, seeds))
    # Order by seed so a merge is independent of completion order.
    return sorted(results, key=lambda item: item[0])


def _collect(results: list[tuple[int, dict]], seeds: set[int]) -> dict:
    counts: dict[str, dict[str, int]] = {}
    for seed, cells in results:
        if seed in seeds:
            _merge(counts, cells)
    return counts


def _total_variation(left: dict[str, int], right: dict[str, int]) -> float:
    """Half the L1 distance between two non-tenpai shanten distributions."""
    left_total = sum(count for label, count in left.items() if label != "0")
    right_total = sum(count for label, count in right.items() if label != "0")
    if not left_total or not right_total:
        return float("nan")
    labels = {label for label in (*left, *right) if label != "0"}
    return 0.5 * sum(
        abs(left.get(label, 0) / left_total - right.get(label, 0) / right_total)
        for label in labels
    )


def _quality(fit: dict, holdout: dict, min_cell_count: int) -> dict:
    """How far the fitted cells sit from untouched games, cell by cell."""
    comparable = []
    for key, holdout_cell in sorted(holdout.items()):
        fit_cell = fit.get(key)
        if fit_cell is None:
            continue
        non_tenpai = sum(
            count for label, count in holdout_cell.items() if label != "0"
        )
        if non_tenpai < min_cell_count:
            continue
        distance = _total_variation(fit_cell, holdout_cell)
        comparable.append(
            {
                "cell": key,
                "holdout_non_tenpai": non_tenpai,
                "total_variation": distance,
            }
        )
    distances = [entry["total_variation"] for entry in comparable]
    marginal = _total_variation(_flatten(fit), _flatten(holdout))
    return {
        "compared_cells": len(comparable),
        "min_cell_count": min_cell_count,
        "marginal_total_variation": marginal,
        "mean_cell_total_variation": (
            sum(distances) / len(distances) if distances else float("nan")
        ),
        "max_cell_total_variation": max(distances) if distances else float("nan"),
        "cells": comparable,
    }


def _flatten(cells: dict[str, dict[str, int]]) -> dict[str, int]:
    total: dict[str, int] = {}
    for cell in cells.values():
        for label, count in cell.items():
            total[label] = total.get(label, 0) + count
    return total


def _git_commit() -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True,
            cwd=Path(__file__).resolve().parents[1],
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--games", type=int, default=4000)
    parser.add_argument("--seed-start", type=int, default=60001)
    parser.add_argument("--workers", type=int, default=MAX_WORKERS)
    parser.add_argument("--verify-games", type=int, default=12)
    parser.add_argument("--out", type=Path, default=Path("data/opponent-shanten.json"))
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
    results = _generate(seeds, args.workers)

    if args.verify_games:
        verify_seeds = seeds[: args.verify_games]
        serial = _collect(_generate(verify_seeds, 1), set(verify_seeds))
        parallel = _collect(_generate(verify_seeds, args.workers), set(verify_seeds))
        if serial != parallel:
            raise RuntimeError("worker-count determinism check failed")
        print(
            f"determinism_check=passed games={args.verify_games} "
            f"workers=1,{args.workers}"
        )

    fit_counts = _collect(results, set(seeds) - holdout)
    holdout_counts = _collect(results, holdout)
    metadata = {
        "games": args.games,
        "fit_games": len(seeds) - len(holdout),
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
        "conditioning": "melds|turn_bucket|run_bucket, as the tenpai table",
        "observation": (
            "the discarding seat's own shanten after its discard, paired with "
            "the public state a reader would have had at that moment"
        ),
        "consumes_calibration_table": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": _git_commit(),
        "workers": args.workers,
    }
    built = document(fit_counts, metadata)
    built["quality"] = _quality(fit_counts, holdout_counts, MIN_CELL_COUNT)
    OpponentShanten(built)  # refuse to write a document the model cannot read

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as stream:
        json.dump(built, stream, indent=2, sort_keys=True)
        stream.write("\n")

    marginal = _flatten(fit_counts)
    total = sum(marginal.values())
    shape = " ".join(
        f"{label}:{marginal[label] / total:.3f}" for label in sorted(marginal, key=int)
    )
    print(
        f"cells={len(fit_counts)} fit_games={metadata['fit_games']} "
        f"held_out_games={metadata['held_out_games']} observations={total}"
    )
    print(f"marginal {shape}")
    print(
        f"holdout compared_cells={built['quality']['compared_cells']} "
        f"mean_tv={built['quality']['mean_cell_total_variation']:.4f} "
        f"max_tv={built['quality']['max_cell_total_variation']:.4f} "
        f"out={args.out}"
    )


if __name__ == "__main__":
    main()
