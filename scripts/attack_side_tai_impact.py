"""Quantify what a 台數-aware push continuation would change (DEV-185 step 3).

``scripts/attack_side_tai_probe.py`` establishes the decision-level gap: the
push continuation cannot see ``scheme`` at all, and toggling 台數 weighting on
the same rule moves only a small fraction of the states production visits.  A
decision-count is not an impact, so this script prices it two ways.

``exploitability`` -- the sanctioned unbiased number.  ``measured_policy``
swaps the acting seat's rule only; the opponents inside ``_analyse_opening``
keep playing production's, so the two columns face the same environment and are
comparable.  ``holdout=True`` is the number to read (DEV-184); the in-sample
one is retained as the leakage sentinel.  Scope caveat: 18 of the 26 reference
walls hold four tiles, so this corpus is a shallow endgame.

``quiz`` -- the depth column.  Production's own midgame positions at
``REFINE_SIMS``, asking whether the displayed answer changes at all.  Here the
swap is *not* isolated: ``ev_rank``'s ``discard_policy`` is used by every seat,
so this column moves the opponent model too.  It is therefore a screen, not an
attribution: if the displayed choice never moves, no isolated version of the
change can matter either.

The weighting uses ``_greedy_discard(scheme=..., tai_estimator=None)``, whose
own docstring limits it to concealed post-discard tenpai and to shape-dependent
tai with no seat context.  A real fix would need a seat-aware estimator; this
measures the effect that is already implementable, which is the cheaper bound.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path
from statistics import mean
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from taimahjong import quiz
from taimahjong.best_response import exploitability
from taimahjong.ev import ev_rank
from taimahjong.quiz import EV_TOP_K, REFINE_SIMS
from taimahjong.reference_ev import representative_reference_cases
from taimahjong.scoring import SCHEME_3_1, SCHEME_5_2
from taimahjong.simulate import _greedy_discard

SCHEMES = {"3-1": SCHEME_3_1, "5-2": SCHEME_5_2}


def tai_aware_policy(scheme):
    """Production's offense rule with 台數 weighting switched on."""

    def choose(hand17, remaining, melds_declared) -> int:
        return _greedy_discard(
            tuple(hand17), tuple(remaining), melds_declared, scheme, None,
        )[0]

    return choose


def _exploitability_column(sims: int, seed: int) -> dict:
    rows = []
    for index, case in enumerate(representative_reference_cases()):
        base = exploitability(case, sims=sims, seed=seed, holdout=True)
        tai = exploitability(
            case,
            sims=sims,
            seed=seed,
            holdout=True,
            measured_policy=tai_aware_policy(case.state.scheme),
        )
        rows.append({
            "case": index,
            "scheme": f"{case.state.scheme.base_units}-{case.state.scheme.tai_units}",
            "wall": len(case.state.wall),
            "production_holdout": base.holdout_exploitability,
            "tai_aware_holdout": tai.holdout_exploitability,
            "production_in_sample": base.exploitability,
            "tai_aware_in_sample": tai.exploitability,
        })
        print(
            f"  case {index:2d} wall={rows[-1]['wall']} "
            f"prod={rows[-1]['production_holdout']:+.3f} "
            f"tai={rows[-1]['tai_aware_holdout']:+.3f}",
            flush=True,
        )
    return {
        "rows": rows,
        "mean_production_holdout": mean(r["production_holdout"] for r in rows),
        "mean_tai_aware_holdout": mean(r["tai_aware_holdout"] for r in rows),
        "mean_production_in_sample": mean(r["production_in_sample"] for r in rows),
        "mean_tai_aware_in_sample": mean(r["tai_aware_in_sample"] for r in rows),
        "changed_cases": sum(
            r["production_holdout"] != r["tai_aware_holdout"] for r in rows
        ),
    }


def _rank_with(position, scheme, policy):
    return tuple(ev_rank(
        position.hand,
        [opponent.view() for opponent in position.opponents],
        position.public_counts,
        len(position.own_melds) + len(position.own_kongs),
        position.draws_remaining,
        REFINE_SIMS,
        quiz._evaluation_seed(position),
        quiz._score_template(position),
        calibration=quiz.DEFAULT_ANALYSIS_CONTEXT.calibration.calibration,
        top_k=EV_TOP_K,
        scheme=scheme,
        discard_policy=policy,
    ))


def _quiz_column(positions: int, seed: int) -> dict:
    rows = []
    current = seed
    for _ in range(positions):
        position = quiz.generate_position(current)
        current = position.seed + 1
        keyed = replace(position, candidate_ev_gap=0.0)
        for name, scheme in SCHEMES.items():
            base = _rank_with(keyed, scheme, None)
            tai = _rank_with(keyed, scheme, tai_aware_policy(scheme))
            rows.append({
                "quiz_seed": position.seed,
                "scheme": name,
                "draws_remaining": position.draws_remaining,
                "shanten": position.shanten,
                "production_top": base[0].discard,
                "tai_aware_top": tai[0].discard,
                "production_top_ev": base[0].net_ev,
                "tai_aware_top_ev": tai[0].net_ev,
                "top_changed": base[0].discard != tai[0].discard,
            })
            print(
                f"  seed={position.seed} {name} "
                f"top {base[0].discard} -> {tai[0].discard} "
                f"ev {base[0].net_ev:+.3f} -> {tai[0].net_ev:+.3f}",
                flush=True,
            )
    return {
        "rows": rows,
        "changed": sum(r["top_changed"] for r in rows),
        "n": len(rows),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sims", type=int, default=60)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--positions", type=int, default=8)
    parser.add_argument("--skip-quiz", action="store_true")
    parser.add_argument(
        "--out", type=Path, default=ROOT / "data" / "dev185_attack_impact.json",
    )
    args = parser.parse_args()

    started = perf_counter()
    report: dict = {}
    print("=== exploitability column (26 reference cases) ===", flush=True)
    report["exploitability"] = _exploitability_column(args.sims, args.seed)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"({perf_counter() - started:.0f}s)", flush=True)

    if not args.skip_quiz:
        print("=== quiz depth column ===", flush=True)
        report["quiz"] = _quiz_column(args.positions, args.seed)
        args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"\nwrote {args.out} ({perf_counter() - started:.0f}s)")
    exploit = report["exploitability"]
    print(
        f"holdout mean: production {exploit['mean_production_holdout']:+.4f} "
        f"vs tai-aware {exploit['mean_tai_aware_holdout']:+.4f} "
        f"({exploit['changed_cases']}/26 cases moved)"
    )
    if "quiz" in report:
        print(f"quiz displayed top-1 changed: {report['quiz']['changed']}/{report['quiz']['n']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
