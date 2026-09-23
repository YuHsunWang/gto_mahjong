"""Price survivor rules for ev_rank's candidate screen (DEV-121).

Today ``top_k`` is both the floor and the cap of the screen, so exactly
min(top_k, legal) candidates survive whatever the pilot's intervals say.  This
probe compares that rule with adaptive and fixed alternatives against an
independent high-budget exhaustive reference.

Every step runs in its own process so no cache warmed by one rule speeds up
another:

    python scripts/screen_survivors_probe.py corpus  OUT/corpus.pkl
    python scripts/screen_survivors_probe.py truth   OUT/corpus.pkl OUT/truth.json
    python scripts/screen_survivors_probe.py rule S0 OUT/corpus.pkl OUT/S0.json
    python scripts/screen_survivors_probe.py report  OUT
"""

from __future__ import annotations

import argparse
import json
import pickle
import sys
from pathlib import Path
from statistics import mean
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from taimahjong.ev import ev_rank
from taimahjong.ev_benchmark import benchmark_corpus
from taimahjong.quiz import (
    DEFAULT_ANALYSIS_CONTEXT,
    EV_TOP_K,
    REFINE_SIMS,
    _evaluation_seed,
    _score_template,
    generate_position,
)

QUIZ_POSITIONS = 40
TRUTH_SIMS = 2000
# The reference must not share worlds with the rules it judges, or a rule's
# own noise would be graded as correct.
TRUTH_SEED_SALT = 0x5EED7157
UNBOUNDED = 34

# name -> (floor, cap); None means production's own top_k for both.
RULES = {
    "S0": (None, None),
    "S1": (1, UNBOUNDED),
    "S2": (2, UNBOUNDED),
    "S3": (3, 3),
    "S4": (8, 8),
    "EX": "exhaustive",
}


def build_corpus() -> list[dict]:
    calibration = DEFAULT_ANALYSIS_CONTEXT.calibration.calibration
    cases: list[dict] = []
    seen: set[tuple[int, int, int]] = set()
    seed = 1
    while len(cases) < QUIZ_POSITIONS:
        position = generate_position(seed)
        key = (position.seed, position.seat, position.turn)
        seed = position.seed + 1
        if key in seen:
            continue
        seen.add(key)
        cases.append({
            "name": f"quiz-{position.seed}",
            "args": (
                position.hand,
                [opponent.view() for opponent in position.opponents],
                position.public_counts,
                len(position.own_melds) + len(position.own_kongs),
                position.draws_remaining,
            ),
            "seed": _evaluation_seed(position),
            "kwargs": {
                "context_template": _score_template(position),
                "calibration": calibration,
                "scheme": DEFAULT_ANALYSIS_CONTEXT.game.scheme,
            },
        })
    for case in benchmark_corpus():
        cases.append({
            "name": f"bench-{case.name}",
            "args": (case.hand, list(case.opponents), case.visible),
            "seed": case.seed,
            "kwargs": {
                "turns": case.turns,
                "calibration": calibration,
                "scheme": case.scheme,
            },
        })
    return cases


def _rank(case: dict, sims: int, seed: int, **extra) -> tuple[list, float]:
    started = perf_counter()
    ranked = ev_rank(*case["args"], sims=sims, seed=seed, **case["kwargs"], **extra)
    elapsed = perf_counter() - started
    real = sorted(
        (entry for entry in ranked if not entry.is_fold),
        key=lambda entry: (-entry.net_ev, entry.discard),
    )
    return real, elapsed


def run_truth(cases: list[dict]) -> dict:
    out = {}
    for case in cases:
        real, elapsed = _rank(
            case, TRUTH_SIMS, case["seed"] ^ TRUTH_SEED_SALT,
            top_k=EV_TOP_K, exhaustive=True,
        )
        out[case["name"]] = {
            "ev": {str(entry.discard): entry.net_ev for entry in real},
            "se": {str(entry.discard): entry.standard_error for entry in real},
            "seconds": elapsed,
        }
        print(f"truth {case['name']} {elapsed:.1f}s", flush=True)
    return out


def run_rule(name: str, cases: list[dict]) -> dict:
    rule = RULES[name]
    extra: dict = {"top_k": EV_TOP_K}
    if rule == "exhaustive":
        extra["exhaustive"] = True
    else:
        floor, cap = rule
        if floor is not None:
            extra["_screen_floor"] = floor
            extra["_screen_cap"] = cap
    out = {}
    for case in cases:
        real, elapsed = _rank(case, REFINE_SIMS, case["seed"], **extra)
        out[case["name"]] = {
            "top": real[0].discard,
            "survivors": len(real),
            "seconds": elapsed,
        }
        print(f"{name} {case['name']} {elapsed:.1f}s survivors={len(real)}", flush=True)
    return out


def report(directory: Path) -> str:
    truth = json.loads((directory / "truth.json").read_text())
    unresolved = 0
    for record in truth.values():
        ordered = sorted(record["ev"].items(), key=lambda item: -item[1])
        (first, first_ev), (_, second_ev) = ordered[0], ordered[1]
        se = record["se"][first] or 0.0
        unresolved += int(first_ev - second_ev < 1.96 * se)
    lines = [
        f"reference: exhaustive, {TRUTH_SIMS} sims, independent seed; "
        f"{len(truth)} cases, {unresolved} with top-two gap inside 1.96 SE",
        "",
        "| rule | recall@1 | mean regret | worst regret | mean survivors | total seconds |",
        "|---|---|---|---|---|---|",
    ]
    for name in RULES:
        path = directory / f"{name}.json"
        if not path.exists():
            lines.append(f"| {name} | SKIPPED | | | | |")
            continue
        results = json.loads(path.read_text())
        regrets, hits = [], 0
        for case_name, result in results.items():
            ev = truth[case_name]["ev"]
            best = max(ev.values())
            regrets.append(best - ev[str(result["top"])])
            hits += int(ev[str(result["top"])] == best)
        lines.append(
            f"| {name} | {hits}/{len(results)} | {mean(regrets):.4f} | {max(regrets):.4f} "
            f"| {mean(r['survivors'] for r in results.values()):.2f} "
            f"| {sum(r['seconds'] for r in results.values()):.1f} |"
        )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("corpus").add_argument("out", type=Path)
    truth_parser = sub.add_parser("truth")
    truth_parser.add_argument("corpus", type=Path)
    truth_parser.add_argument("out", type=Path)
    truth_parser.add_argument("--limit", type=int)
    rule_parser = sub.add_parser("rule")
    rule_parser.add_argument("name", choices=sorted(RULES))
    rule_parser.add_argument("corpus", type=Path)
    rule_parser.add_argument("out", type=Path)
    sub.add_parser("report").add_argument("directory", type=Path)
    args = parser.parse_args()

    if args.command == "corpus":
        args.out.write_bytes(pickle.dumps(build_corpus()))
    elif args.command == "truth":
        cases = pickle.loads(args.corpus.read_bytes())[: args.limit]
        args.out.write_text(json.dumps(run_truth(cases), indent=1))
    elif args.command == "rule":
        cases = pickle.loads(args.corpus.read_bytes())
        args.out.write_text(json.dumps(run_rule(args.name, cases), indent=1))
    else:
        print(report(args.directory))


if __name__ == "__main__":
    main()
