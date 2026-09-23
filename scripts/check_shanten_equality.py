"""Check every distinct production shanten request against the frozen evaluator.

    python scripts/check_shanten_equality.py CORPUS CHECKPOINT OUTPUT [--max-cases N]

The checkpoint is written after each case. Repeating the command resumes at
the next case; omit --max-cases to finish the corpus.
"""

from __future__ import annotations

import argparse
from dataclasses import astuple
from functools import lru_cache
import json
import os
import pickle
from pathlib import Path

from profile_shanten import calibration_context
from taimahjong import ev, quiz
from taimahjong.shanten import _shanten_unchecked_reference


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("corpus", type=Path)
    parser.add_argument("checkpoint", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--max-cases", type=int)
    parser.add_argument("--reference", action="store_true",
                        help="write full EV entry tuples using the frozen evaluator")
    args = parser.parse_args()
    cases = pickle.loads(args.corpus.read_bytes())
    state = (pickle.loads(args.checkpoint.read_bytes()) if args.checkpoint.exists()
             else {"next_case": 0, "keys": set(), "mismatches": [],
                   "results": [], "reference": args.reference})
    if state["reference"] != args.reference:
        parser.error("checkpoint mode differs from --reference")
    seen = state["keys"]
    original = ev._production_shanten

    def ranked(case: dict, calibration: object) -> dict:
        entries = ev.ev_rank(
            case["hand"], case["opponents"], case["visible"],
            case["melds_declared"], case["turns"], quiz.REFINE_SIMS,
            case["seed"], case["context_template"], calibration=calibration,
            top_k=quiz.EV_TOP_K, scheme=case["scheme"],
        )
        return {"name": case["name"], "entries": [astuple(entry) for entry in entries]}

    def checked(hand: tuple[int, ...], melds: int) -> int:
        result = original(hand, melds)
        key = bytes(hand) + bytes((melds,))
        if key not in seen:
            seen.add(key)
            expected = _shanten_unchecked_reference(hand, melds)
            if result != expected:
                state["mismatches"].append((key.hex(), result, expected))
        return result

    if args.reference:
        ev._production_shanten = lru_cache(maxsize=200_000)(_shanten_unchecked_reference)
    else:
        ev._production_shanten = checked
    calibration = calibration_context().calibration.calibration
    stop = len(cases)
    if args.max_cases is not None:
        stop = min(stop, state["next_case"] + args.max_cases)
    try:
        for index in range(state["next_case"], stop):
            state["results"].append(ranked(cases[index], calibration))
            state["next_case"] = index + 1
            temporary = args.checkpoint.with_suffix(args.checkpoint.suffix + ".tmp")
            temporary.write_bytes(pickle.dumps(state, protocol=pickle.HIGHEST_PROTOCOL))
            os.replace(temporary, args.checkpoint)
            print(json.dumps({"case": cases[index]["name"], "distinct_keys": len(seen),
                              "mismatches": len(state["mismatches"])}), flush=True)
    finally:
        ev._production_shanten = original
    summary = {"completed_cases": state["next_case"], "total_cases": len(cases),
               "reference": args.reference,
               "distinct_keys": len(seen), "mismatches": state["mismatches"],
               "results": state["results"]}
    args.output.write_text(json.dumps(summary, indent=2))
    print(json.dumps({key: value for key, value in summary.items()
                      if key != "results"}))
    if state["mismatches"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
