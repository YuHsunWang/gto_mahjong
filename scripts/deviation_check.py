"""Score a candidate seat policy against the step 3k equilibrium ``TDDD``.

The equilibrium of step 3k holds only inside {efficiency, deal_in_risk,
threat}; the plan says a new strategy may change the answer.  This script asks
that question for one candidate: each role in turn plays the candidate while
the other three keep ``TDDD``, and the per-role gain is paired against
``TDDD`` on the same sampled worlds.

The candidate file must define ``policy(hand17, belief, opponent_declared)``
returning a tile index the hand holds -- the ``SeatPolicy`` signature in
``taimahjong/empirical_game.py``.  It runs in-process with no sandbox; only
point it at code you are willing to run.

Output is one JSON object on stdout.  ``regret`` is the cluster-bootstrap
interval of the best gain over the four roles (max taken inside each resample,
as ``EmpiricalGame.regret_interval`` does).  Only ``regret.low > 0`` says the
candidate breaks ``TDDD``; a straddling interval says the budget did not
answer, and a quick-mode hit must be re-run at the full corpus before it is
reported.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from random import Random
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from taimahjong.empirical_corpus import empirical_game_cases
from taimahjong.empirical_game import STRATEGIES, build_game


BASE = ("threat", "deal_in_risk", "deal_in_risk", "deal_in_risk")
CANDIDATE = "candidate"


def load_policy(path: Path):
    spec = importlib.util.spec_from_file_location("candidate_policy", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not callable(getattr(module, "policy", None)):
        raise ValueError(f"{path} defines no callable `policy`")
    return module.policy


def deviations(base: tuple[str, ...]) -> tuple[tuple[str, ...], ...]:
    return tuple(
        base[:role] + (CANDIDATE,) + base[role + 1:] for role in range(4)
    )


def mean_interval(
    values: tuple[float, ...], *, resamples: int, seed: int,
) -> tuple[float, float]:
    """Percentile bootstrap (95%) of the mean of one per-case series."""
    count = len(values)
    rng = Random(seed)
    draws = sorted(
        sum(values[rng.randrange(count)] for _ in range(count)) / count
        for _ in range(resamples)
    )
    return draws[int(0.025 * resamples)], draws[min(resamples - 1, int(0.975 * resamples))]


def score(policy, cases, *, sims: int, seed: int, resamples: int) -> dict:
    STRATEGIES[CANDIDATE] = policy
    try:
        started = perf_counter()
        game = build_game(
            cases, sims=sims, seed=seed, strategies=(CANDIDATE,),
            profiles=(BASE,) + deviations(BASE),
        )
        elapsed = perf_counter() - started
    finally:
        del STRATEGIES[CANDIDATE]
    gains = game._deviation_gains(BASE)
    roles = []
    for role in range(4):
        series = gains[(role, CANDIDATE)]
        low, high = mean_interval(series, resamples=resamples, seed=7)
        roles.append({
            "role": role, "gain": sum(series) / len(series),
            "low": low, "high": high,
        })
    regret = game.regret_interval(BASE, resamples=resamples)
    return {
        "valid": True,
        "base": "TDDD",
        "cases": game.cases,
        "sims": game.sims,
        "seed": seed,
        "seconds": round(elapsed, 1),
        "roles": roles,
        "regret": {
            "role": regret.role, "gain": regret.gain,
            "low": regret.low, "high": regret.high,
            "breaks_equilibrium": regret.low > 0.0,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--sims", type=int, default=100)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--resamples", type=int, default=2000)
    parser.add_argument(
        "--quick", action="store_true",
        help="screening budget: full 416-case corpus x 10 worlds (~35 s)",
    )
    args = parser.parse_args()
    # Screen on every case, not a prefix of templates.  Measured 2026-10-26 on
    # one candidate: full 416 x 100 gave +0.002 [-0.002, +0.008]; the first
    # 52 x 20 cases said +0.028 and the first 104 x 40 said +0.016 with the
    # interval above zero -- a fixed case subset is what a search overfits.
    # 416 x 10 gave -0.005 and -0.0005 under world seeds 1 and 2.
    templates, sims = (None, 10) if args.quick else (None, args.sims)
    try:
        policy = load_policy(args.candidate)
        result = score(
            policy, empirical_game_cases(templates), sims=sims,
            seed=args.seed, resamples=args.resamples,
        )
    except Exception as error:  # candidate code is arbitrary; report, don't crash
        print(json.dumps({"valid": False, "error": f"{type(error).__name__}: {error}"}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
