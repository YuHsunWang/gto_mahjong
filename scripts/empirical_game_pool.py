"""Pool several world seeds into one empirical game (#39 Q3, step 3m).

``dump SEED`` builds the three-strategy game on one world seed and saves each
profile's per-case mean payoff.  ``pool SEED...`` averages those means over
the seeds -- every seed has the same number of worlds, so this is the per-case
mean over all of them -- and prints the ``empirical_game_table`` profile and
role tables on a game with one unit per case.  Every number those tables use
is a per-case mean, which is linear in the units, so collapsing the worlds
first changes only float rounding (measured 5.6e-17 on 52 cases x 81
profiles).  ``pool`` with a single seed reproduces that seed's table.

    python scripts/empirical_game_pool.py dump 1      # ... and 2..6
    python scripts/empirical_game_pool.py pool 1 2 3 4 5 6
"""

from __future__ import annotations

import argparse
import pickle
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from taimahjong.empirical_corpus import empirical_game_cases
from taimahjong.empirical_game import EmpiricalGame, build_game
import empirical_game_table as table


STRATEGIES = ("efficiency", "deal_in_risk", "threat")
SIMS = 100


def dump(seed: int, out: Path) -> None:
    game = build_game(
        empirical_game_cases(None), sims=SIMS, seed=seed, strategies=STRATEGIES,
    )
    means = {
        profile: [
            tuple(
                sum(rows[i][seat] for i in range(case * SIMS, (case + 1) * SIMS)) / SIMS
                for seat in range(4)
            )
            for case in range(game.cases)
        ]
        for profile, rows in game.units.items()
    }
    (out / f"means{seed}.pkl").write_bytes(pickle.dumps((game.cases, means)))


def pool(seeds: list[int], out: Path, resamples: int) -> None:
    loaded = [pickle.loads((out / f"means{seed}.pkl").read_bytes()) for seed in seeds]
    cases = loaded[0][0]
    if any(count != cases for count, _ in loaded):
        raise ValueError("seeds were dumped on different corpora")
    units = {
        profile: tuple(
            tuple(
                sum(means[profile][case][seat] for _, means in loaded) / len(loaded)
                for seat in range(4)
            )
            for case in range(cases)
        )
        for profile in loaded[0][1]
    }
    payoffs = {
        profile: tuple(sum(row[seat] for row in rows) / cases for seat in range(4))
        for profile, rows in units.items()
    }
    game = EmpiricalGame(STRATEGIES, payoffs, units, cases, 1)
    print(f"pooled world seeds {seeds}: {cases} cases x {SIMS * len(seeds)} worlds")
    table.check_against_regret_interval(game, resamples)
    table.profile_table(game, resamples)
    table.profile_table(game, resamples, roles=(0, 1))
    for reply in STRATEGIES[1:]:
        table.role_table(game, resamples, reply=reply)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("dump", "pool"))
    parser.add_argument("seeds", type=int, nargs="+")
    parser.add_argument("--out", type=Path, default=Path("."))
    parser.add_argument("--resamples", type=int, default=2000)
    args = parser.parse_args()
    if args.mode == "dump":
        for seed in args.seeds:
            dump(seed, args.out)
    else:
        pool(args.seeds, args.out, args.resamples)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
