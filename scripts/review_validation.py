#!/usr/bin/env python3
"""Reproducible, read-only checks used by the 2026-07 Codex deep review.

This script intentionally does not assert that the current behaviour is
correct.  It records the behaviour that the review discusses, plus small
seed/budget convergence samples.  Run from the repository root:

    python3 scripts/review_validation.py
"""

from __future__ import annotations

import json
import random
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from server.api import ScoreRequest, score_endpoint
from taimahjong.calibration import Calibration
from taimahjong.ev import TileAccounting, ev_rank, remaining_draws
from taimahjong.scoring import SCHEME_3_1, SCHEME_5_2, WinContext, score_hand
from taimahjong.shanten import shanten
from taimahjong.simulate import _greedy_discard, win_probability
from taimahjong.tiles import format_tiles, parse_tiles
from taimahjong.ukeire import discard_analysis


def _tile(text: str) -> int:
    return next(index for index, count in enumerate(parse_tiles(text)) if count)


def score_scheme_check() -> dict:
    hand_text = "123m111555666777z22z"
    hand = parse_tiles(hand_text)
    result = score_hand(hand, (), WinContext(winning_tile=_tile("2z"), self_draw=True))
    request = {"hand": hand_text, "win_tile": "2z", "self_draw": True}
    default_payload = score_endpoint(ScoreRequest(**request))
    alternate_payload = score_endpoint(
        ScoreRequest(**request, base_units=5, tai_units=2)
    )
    return {
        "total_tai": result.total_tai,
        "engine_3_1": result.value_in(SCHEME_3_1),
        "engine_5_2": result.value_in(SCHEME_5_2),
        "api_default": default_payload,
        "api_with_5_2_fields": alternate_payload,
        "api_ignored_5_2_fields": default_payload == alternate_payload,
    }


def remaining_draws_meld_check() -> dict:
    hand = parse_tiles("123m123p123s11122233z")
    one_discard = parse_tiles("9m")
    discard_and_open_meld = parse_tiles("9m111p")
    # A declared opponent meld is part of that opponent's 16-tile holding,
    # already represented by the fixed 3 * 16 deduction in remaining_draws.
    physical_live_wall = 136 - 16 - sum(hand) - (3 * 16) - 1
    physically_expected_turns = (physical_live_wall + 3) // 4
    return {
        "hand_tiles": sum(hand),
        "with_one_opponent_discard": remaining_draws(hand, TileAccounting(one_discard)),
        "with_same_discard_plus_open_meld": remaining_draws(
            hand, TileAccounting(one_discard, parse_tiles("111p"))
        ),
        "expected_when_meld_is_already_in_opponent_holdings": physically_expected_turns,
    }


def _visible_policy_divergence() -> dict:
    """Find a production-path state where cumulative own discards alter choice."""
    initial = parse_tiles("123456789m1123p567s")
    initial_visible = (0,) * 34
    pool = [
        tile
        for tile in range(34)
        for _ in range(4 - initial[tile] - initial_visible[tile])
    ]
    for seed in range(500):
        draws = pool[:]
        random.Random(seed).shuffle(draws)
        current = initial
        cumulative_visible = list(initial_visible)
        remaining = [4 - initial[tile] - initial_visible[tile] for tile in range(34)]
        prior_discards: list[int] = []
        for turn, draw in enumerate(draws[:12], start=1):
            remaining[draw] -= 1
            drawn = list(current)
            drawn[draw] += 1
            current = tuple(drawn)
            if shanten(current) == -1:
                break
            static = discard_analysis(current, visible=initial_visible)[0]
            dynamic = discard_analysis(current, visible=tuple(cumulative_visible))[0]
            if static.discard != dynamic.discard:
                production, _ = _greedy_discard(current, tuple(remaining), 0)
                return {
                    "found": True,
                    "seed": seed,
                    "turn": turn,
                    "state": format_tiles(current),
                    "prior_discards": [
                        format_tiles(tuple(1 if i == tile else 0 for i in range(34)))
                        for tile in prior_discards
                    ],
                    "static_choice": format_tiles(
                        tuple(1 if i == static.discard else 0 for i in range(34))
                    ),
                    "static_ukeire": static.total,
                    "dynamic_choice": format_tiles(
                        tuple(1 if i == dynamic.discard else 0 for i in range(34))
                    ),
                    "dynamic_ukeire": dynamic.total,
                    "production_choice": format_tiles(
                        tuple(1 if i == production else 0 for i in range(34))
                    ),
                    "production_matches_dynamic": production == dynamic.discard,
                }
            discard = static.discard
            reduced = list(current)
            reduced[discard] -= 1
            current = tuple(reduced)
            cumulative_visible[discard] += 1
            prior_discards.append(discard)
    return {"found": False, "seeds_checked": 500, "turns_per_seed": 12}


def simulation_convergence() -> dict:
    hand = parse_tiles("123456789m1123p567s")
    budgets = (100, 400, 1600)
    seeds = (7, 17, 29)
    rows = []
    for sims in budgets:
        started = time.perf_counter()
        values = [
            win_probability(hand, turns=6, sims=sims, seed=seed).p_win
            for seed in seeds
        ]
        mean = statistics.fmean(values)
        binomial_se = (mean * (1.0 - mean) / (sims * len(seeds))) ** 0.5
        rows.append(
            {
                "sims_per_seed": sims,
                "seeds": list(seeds),
                "p_win": values,
                "mean": mean,
                "between_seed_sd": statistics.stdev(values),
                "pooled_binomial_se": binomial_se,
                "approx_95pct_ci": [
                    max(0.0, mean - 1.96 * binomial_se),
                    min(1.0, mean + 1.96 * binomial_se),
                ],
                "elapsed_seconds": time.perf_counter() - started,
            }
        )
    return {"hand": format_tiles(hand), "turns": 6, "rows": rows}


def ev_ranking_stability() -> dict:
    hand = parse_tiles("123456789m11234p567s")
    rows = []
    for sims in (24, 96):
        for seed in (3, 13, 23):
            started = time.perf_counter()
            entries = ev_rank(
                hand,
                (),
                (0,) * 34,
                turns=3,
                sims=sims,
                seed=seed,
                top_k=3,
            )
            real = [entry for entry in entries if not entry.is_fold]
            rows.append(
                {
                    "sims": sims,
                    "seed": seed,
                    "ranking": [
                        {
                            "discard": format_tiles(
                                tuple(1 if i == entry.discard else 0 for i in range(34))
                            ),
                            "net_ev": entry.net_ev,
                            "p_win": entry.p_win,
                        }
                        for entry in real
                    ],
                    "elapsed_seconds": time.perf_counter() - started,
                }
            )
    top_counts: dict[str, int] = {}
    for row in rows:
        top = row["ranking"][0]["discard"]
        top_counts[top] = top_counts.get(top, 0) + 1
    return {"hand": format_tiles(hand), "turns": 3, "top_choice_counts": top_counts, "rows": rows}


def calibration_zero_bucket_check() -> dict:
    calibration = Calibration.from_path(ROOT / "data" / "calibration.json")
    table = calibration.tables["deal_in"]["0-1"]
    return {
        "raw_bucket": table,
        "lookup_at_score_0": calibration.deal_in_probability(0.0),
        "lookup_at_score_0_5": calibration.deal_in_probability(0.5),
    }


def fold_action_check() -> dict:
    hand = parse_tiles("123456789m11234p567s")
    entries = ev_rank(hand, (), (0,) * 34, turns=2, sims=40, seed=5, top_k=3)
    fold = next(entry for entry in entries if entry.is_fold)
    real = [entry for entry in entries if not entry.is_fold]
    return {
        "fold_net_ev": fold.net_ev,
        "best_real_net_ev": max(entry.net_ev for entry in real),
        "minimum_real_risk_ev": min(entry.risk_ev for entry in real),
        "fold_risk_ev": fold.risk_ev,
        "fold_strictly_beats_best_real": fold.net_ev > max(entry.net_ev for entry in real),
    }


def main() -> None:
    output = {
        "score_scheme": score_scheme_check(),
        "remaining_draws_with_open_meld": remaining_draws_meld_check(),
        "static_visible_policy": _visible_policy_divergence(),
        "simulation_convergence": simulation_convergence(),
        "ev_ranking_stability": ev_ranking_stability(),
        "calibration_zero_bucket": calibration_zero_bucket_check(),
        "fold_pseudo_action": fold_action_check(),
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
