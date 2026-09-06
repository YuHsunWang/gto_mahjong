"""Measure whether the four-player continuation has any 台數 awareness on offense.

DEV-185 asks what ``_fold_choice`` does with the ``scheme`` it demonstrably
receives.  Reading the two continuation rules answers half of it:

* Push branch -- ``ev._production_discard_policy(hand17, remaining, melds)``.
  The signature has no ``scheme`` slot at all, so 台數 cannot reach it.
* Fold branch -- ``ev._fold_choice``.  Its ranking key is
  ``(genbutsu, deal-in loss, duplicate count, tile)``; ``scheme`` enters only
  through ``deal_in_ev`` -> ``opponent_value_estimate``, i.e. the *defensive*
  price of an opponent's hand.  There is no offense term in the key.

Reading is not measuring, so this script measures.  It harvests the
continuation decision states production actually visits while building a
displayed quiz rank, then replays each state through the rules with only one
thing changed at a time:

* ``_greedy_discard`` with ``scheme=None`` vs a scheme -- pure 台數 weighting,
  same function, same tie-breaks.  This isolates the offense-side effect the
  push branch is missing.
* ``_fold_choice`` under both schemes -- the defensive contrast, which is
  expected to move because its scheme path is real.

Depth matters and the 26-case reference corpus does not have it: 18 of its 26
walls hold four tiles, so the actor draws at most once and an offense-side
continuation rule is barely exercised.  Quiz positions are production's own
midgame states at ``REFINE_SIMS``, which is where this question lives.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from taimahjong import ev, quiz
from taimahjong.scoring import SCHEME_3_1, SCHEME_5_2
from taimahjong.simulate import _greedy_discard

SCHEMES = {"3-1": SCHEME_3_1, "5-2": SCHEME_5_2}


def _harvest(position, scheme_name: str, scheme) -> tuple[set, list]:
    """Run one displayed rank, recording every continuation decision state."""
    push: set[tuple[tuple[int, ...], tuple[int, ...], int]] = set()
    fold: list[tuple] = []
    real_push = ev._production_discard_policy
    real_fold = ev._fold_choice

    def spy_push(hand17, remaining, melds_declared):
        push.add((tuple(hand17), tuple(remaining), melds_declared))
        return real_push(hand17, remaining, melds_declared)

    def spy_fold(current, visible, opponents, calibration, sch):
        fold.append((tuple(current), tuple(visible), opponents, calibration))
        return real_fold(current, visible, opponents, calibration, sch)

    ev._production_discard_policy = spy_push
    ev._fold_choice = spy_fold
    try:
        quiz._full_rank(position, scheme=scheme)
    finally:
        ev._production_discard_policy = real_push
        ev._fold_choice = real_fold
    return push, fold


def _probe_push(states) -> dict:
    """Toggle only the 台數 weighting on the offense rule and count changes."""
    counts = Counter()
    weightable = 0
    for hand, remaining, melds in states:
        counts["states"] += 1
        ukeire = _greedy_discard(hand, remaining, melds, None, None)[0]
        tai31 = _greedy_discard(hand, remaining, melds, SCHEME_3_1, None)[0]
        tai52 = _greedy_discard(hand, remaining, melds, SCHEME_5_2, None)[0]
        prod = ev._production_discard_policy(hand, remaining, melds)
        # 台數 weighting only engages for a concealed post-discard tenpai hand.
        if melds == 0 and _greedy_discard(hand, remaining, melds, None, None)[1] == 0:
            weightable += 1
        counts["tai31_vs_ukeire"] += tai31 != ukeire
        counts["tai52_vs_ukeire"] += tai52 != ukeire
        counts["tai31_vs_tai52"] += tai31 != tai52
        counts["production_vs_ukeire"] += prod != ukeire
    counts["weightable_states"] = weightable
    return dict(counts)


def _probe_fold(states) -> dict:
    counts = Counter()
    seen: set[tuple[tuple[int, ...], tuple[int, ...], int]] = set()
    for current, visible, opponents, calibration in states:
        key = (current, visible, id(opponents))
        if key in seen:
            continue
        seen.add(key)
        counts["states"] += 1
        a = ev._fold_choice(current, visible, opponents, calibration, SCHEME_3_1)
        b = ev._fold_choice(current, visible, opponents, calibration, SCHEME_5_2)
        counts["differs_by_scheme"] += a != b
    return dict(counts)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--positions", type=int, default=6)
    parser.add_argument("--out", type=Path, default=ROOT / "data" / "dev185_attack_probe.json")
    args = parser.parse_args()

    report: list[dict] = []
    started = perf_counter()
    seed = args.seed
    for index in range(args.positions):
        position = quiz.generate_position(seed)
        seed = position.seed + 1
        record = {
            "quiz_seed": position.seed,
            "seat": position.seat,
            "turn": position.turn,
            "shanten": position.shanten,
            "draws_remaining": position.draws_remaining,
            "melds": len(position.own_melds) + len(position.own_kongs),
            "schemes": {},
        }
        for name, scheme in SCHEMES.items():
            push, fold = _harvest(position, name, scheme)
            record["schemes"][name] = {
                "push": _probe_push(push),
                "fold": _probe_fold(fold),
            }
        report.append(record)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8",
        )
        print(
            f"[{index + 1}/{args.positions}] seed={record['quiz_seed']} "
            f"shanten={record['shanten']} draws={record['draws_remaining']} "
            f"melds={record['melds']} "
            f"({perf_counter() - started:.0f}s)",
            flush=True,
        )

    totals = Counter()
    for record in report:
        for arm in record["schemes"].values():
            for key, value in arm["push"].items():
                totals[f"push.{key}"] += value
            for key, value in arm["fold"].items():
                totals[f"fold.{key}"] += value
    print("\n=== totals over all harvested decision states ===")
    for key in sorted(totals):
        print(f"{key:32s} {totals[key]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
