"""Print the MJ-006 oracle comparison and MJ-008 pruning benchmark as JSON."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from taimahjong.ev_benchmark import measure_pruning
from taimahjong.reference_ev import (
    compare_reference_corpus,
    representative_reference_cases,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sims", type=int, default=24)
    args = parser.parse_args()
    print(json.dumps({
        "oracle_comparison": asdict(compare_reference_corpus(
            representative_reference_cases(),
            sims=args.sims,
        )),
        "pruning": asdict(measure_pruning(sims=args.sims)),
    }, indent=2))


if __name__ == "__main__":
    main()
