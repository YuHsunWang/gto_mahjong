"""Profile production quiz EV rankings with isolated, reproducible processes.

    python scripts/profile_shanten.py prepare /tmp/shanten-corpus.pkl
    python scripts/profile_shanten.py run /tmp/shanten-corpus.pkl /tmp/shanten-run1.json
    python scripts/profile_shanten.py audit /tmp/shanten-corpus.pkl /tmp/shanten-audit.json

Each invocation of ``run`` or ``audit`` must be a new Python process. Corpus
generation, imports, and calibration loading are outside the timed region.
"""

from __future__ import annotations

import argparse
import cProfile
import json
import pickle
import sys
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from taimahjong import ev, quiz
from taimahjong.analysis import AnalysisContext, CalibrationProvider
from taimahjong.ev_benchmark import benchmark_corpus
from taimahjong.ukeire import discard_analysis

QUIZ_SEEDS = (1, 20)
CALIBRATION_PATH = ROOT / "data" / "calibration.json"


def calibration_context() -> AnalysisContext:
    context = AnalysisContext(calibration=CalibrationProvider(CALIBRATION_PATH).load())
    if context.calibration.calibration is None:
        raise RuntimeError("production calibration did not load")
    return context


def prepare(path: Path) -> None:
    analysis = calibration_context()
    cases = []
    for seed in QUIZ_SEEDS:
        position = quiz.generate_position(seed, analysis)
        cases.append({
            "name": f"quiz-request-{seed}",
            "source_seed": seed,
            "actual_seed": position.seed,
            "hand": position.hand,
            "opponents": tuple(opponent.view() for opponent in position.opponents),
            "visible": position.public_counts,
            "melds_declared": len(position.own_melds) + len(position.own_kongs),
            "turns": position.draws_remaining,
            "seed": quiz._evaluation_seed(position),
            "context_template": quiz._score_template(position),
            "scheme": analysis.game.scheme,
        })
    for case in benchmark_corpus():
        cases.append({
            "name": f"bench-{case.name}",
            "hand": case.hand,
            "opponents": case.opponents,
            "visible": case.visible,
            "melds_declared": 0,
            "turns": case.turns,
            "seed": case.seed,
            "context_template": None,
            "scheme": case.scheme,
        })
    for case in cases:
        case["legal"] = len(discard_analysis(
            case["hand"], case["melds_declared"], case["visible"],
        ))
    path.write_bytes(pickle.dumps(cases))
    print(json.dumps({"cases": [case["name"] for case in cases],
                      "actual_quiz_seeds": [case["actual_seed"] for case in cases[:len(QUIZ_SEEDS)]],
                      "calibration_id": analysis.calibration.calibration_id}))


def run_case(case: dict, calibration: object, *, exhaustive: bool = False) -> dict:
    ranked = ev.ev_rank(
        case["hand"], case["opponents"], case["visible"],
        case["melds_declared"], case["turns"], quiz.REFINE_SIMS,
        case["seed"], case["context_template"], calibration=calibration,
        top_k=quiz.EV_TOP_K, scheme=case["scheme"], exhaustive=exhaustive,
    )
    return {"name": case["name"], "legal": case["legal"],
            "real_survivors": sum(not entry.is_fold for entry in ranked),
            "fold_entries": sum(entry.is_fold for entry in ranked),
            "rank": [(entry.discard, entry.is_fold, entry.net_ev) for entry in ranked]}


def cache_info() -> dict:
    return {
        name: dict(zip(("hits", "misses", "maxsize", "currsize"),
                       getattr(ev, name).cache_info()))
        for name in ("_production_shanten", "_production_discard_analysis")
    }


def profile(cases: list[dict], output: Path, *, exhaustive: bool = False) -> None:
    if quiz.REFINE_SIMS != 200 or quiz.EV_TOP_K != 5:
        raise RuntimeError("production ranking settings changed")
    calibration = calibration_context().calibration.calibration
    ev._production_shanten.cache_clear()
    ev._production_discard_analysis.cache_clear()
    before = cache_info()
    profiler = cProfile.Profile()
    start = perf_counter()
    profiler.enable()
    results = [run_case(case, calibration, exhaustive=exhaustive) for case in cases]
    profiler.disable()
    wall = perf_counter() - start
    after = cache_info()
    stats = profiler.getstats()
    rows = []
    for stat in stats:
        code = stat.code
        if isinstance(code, str):
            label = code
        else:
            label = f"{Path(code.co_filename).name}:{code.co_firstlineno}:{code.co_name}"
        rows.append({"function": label, "calls": stat.callcount,
                     "recursive_calls": stat.reccallcount,
                     "tottime": stat.inlinetime, "cumtime": stat.totaltime})
    rows.sort(key=lambda row: row["tottime"], reverse=True)
    interest = ("_production_shanten", "_shanten_unchecked",
                "_production_discard_analysis", "_production_discard_policy",
                "resolve_terminal_distribution", "_production_worlds",
                "_calibrated_ron", "ev_rank")
    selected = [row for row in rows if any(name in row["function"] for name in interest)]
    world_calls = next(row["calls"] for row in selected
                       if row["function"].endswith(":_production_worlds"))
    ron_calls = next(row["calls"] for row in selected
                     if row["function"].endswith(":_calibrated_ron"))
    expected_world_calls = len(cases) if exhaustive else 2 * len(cases)
    if world_calls != expected_world_calls or ron_calls == 0:
        raise RuntimeError("calibrated production world path was not profiled")
    if not exhaustive and not all(item["legal"] > item["real_survivors"]
                                  for item in results):
        raise RuntimeError("candidate screening did not reduce every case")
    deltas = {name: {key: after[name][key] - before[name][key]
                     for key in ("hits", "misses")}
              for name in after}
    data = {"wall_seconds": wall, "settings": {"sims": quiz.REFINE_SIMS,
            "top_k": quiz.EV_TOP_K, "calibration_active": calibration is not None,
            "exhaustive": exhaustive, "hidden_world_strata": ev.PRODUCTION_HIDDEN_WORLD_STRATA},
            "cache": after, "cache_delta": deltas, "cases": results,
            "top_tottime": rows[:10], "selected": selected}
    output.write_text(json.dumps(data, indent=2))
    print(json.dumps({"wall_seconds": wall, "cache": after,
                      "selected": selected, "cases": [
                          {key: item[key] for key in ("name", "legal", "real_survivors")}
                          for item in results]}))


def audit(cases: list[dict], output: Path) -> None:
    """Observe request keys without including instrumentation in timed runs."""
    calibration = calibration_context().calibration.calibration
    ev._production_shanten.cache_clear()
    ev._production_discard_analysis.cache_clear()
    original_shanten = ev._production_shanten
    original_analysis = ev._production_discard_analysis
    shanten_keys = set()
    analysis_keys = set()
    def shanten(hand, melds):
        shanten_keys.add(bytes(hand) + bytes((melds,)))
        return original_shanten(hand, melds)
    def analysis(hand, melds):
        analysis_keys.add(bytes(hand) + bytes((melds,)))
        return original_analysis(hand, melds)
    ev._production_shanten = shanten
    ev._production_discard_analysis = analysis
    try:
        results = [run_case(case, calibration) for case in cases]
    finally:
        ev._production_shanten = original_shanten
        ev._production_discard_analysis = original_analysis
    cache = cache_info()
    data = {"cache": cache, "distinct_keys": {
        "_production_shanten": len(shanten_keys),
        "_production_discard_analysis": len(analysis_keys)},
        "requests": {"_production_shanten": sum(cache["_production_shanten"][key]
            for key in ("hits", "misses")),
            "_production_discard_analysis": sum(cache["_production_discard_analysis"][key]
            for key in ("hits", "misses"))},
        "shanten_hand_only_keys": len({key[:-1] for key in shanten_keys}),
        "analysis_hand_only_keys": len({key[:-1] for key in analysis_keys}),
        "rank_digest": [[item["name"], item["rank"]] for item in results]}
    output.write_text(json.dumps(data, indent=2))
    print(json.dumps({key: value for key, value in data.items() if key != "rank_digest"}))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "run", "audit"))
    parser.add_argument("corpus", type=Path)
    parser.add_argument("output", type=Path, nargs="?")
    parser.add_argument("--exhaustive", action="store_true",
                        help="fresh-process top_k=5 comparison, not production")
    args = parser.parse_args()
    if args.command == "prepare":
        prepare(args.corpus)
        return
    if args.output is None:
        parser.error("run and audit require an output path")
    cases = pickle.loads(args.corpus.read_bytes())
    for case in cases:
        if "legal" not in case:
            case["legal"] = len(discard_analysis(
                case["hand"], case["melds_declared"], case["visible"],
            ))
    if args.command == "run":
        profile(cases, args.output, exhaustive=args.exhaustive)
    else:
        if args.exhaustive:
            parser.error("--exhaustive applies only to run")
        audit(cases, args.output)


if __name__ == "__main__":
    main()
