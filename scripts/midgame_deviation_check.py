"""Measure undeclared whole-hand unilateral deviations with paired walls.

Example (cost pilot only):
    python scripts/midgame_deviation_check.py --cases 40 --sims 10 --seed 1 \
        --checkpoint /tmp/midgame-pilot.json --output /tmp/midgame-report.json
Restart with identical options plus --resume. Checkpoints are atomic after
each completed world (all 13 profiles); an interrupted world is replayed.
No production belief sampler or shallow-endgame engine is used.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from random import Random
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from taimahjong.midgame_corpus import build_corpus, case_document, case_from_document
from taimahjong.midgame_game import (
    BASE_PROFILE, STRATEGIES, actor_shanten, bootstrap_interval, finish_case,
    paired_case_gains, profiles, reshuffled_wall,
)


def source_digest() -> str:
    """Refuse to mix worlds computed under different engine/policy code."""
    names = ("midgame_corpus.py", "midgame_game.py", "selfplay.py", "danger.py", "shanten.py", "scoring.py", "config.py", "ukeire.py", "ev.py", "tiles.py")
    digest = hashlib.sha256()
    for name in names:
        digest.update((ROOT / "taimahjong" / name).read_bytes())
    digest.update(Path(__file__).read_bytes())
    return digest.hexdigest()


def save_checkpoint(path: Path | None, document: dict) -> None:
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(json.dumps(document, separators=(",", ":")) + "\n")
        temporary.replace(path)


def report(document: dict, cases: tuple) -> dict:
    rows = document["worlds"]
    profile_list = profiles(document["parameters"].get("base", BASE_PROFILE[0]))
    tables = [[[world[index] for world in case] for case in rows] for index in range(len(profile_list))]
    base = tables[0]
    seed = document["parameters"]["seed"]
    deviations = []
    for index, profile in enumerate(profile_list[1:], 1):
        role = next(role for role in range(4) if profile[role] != profile_list[0][role])
        gains = paired_case_gains(base, tables[index], role)
        entry = {"role": role, "alternative": profile[role], **bootstrap_interval(gains, seed=seed)}
        if role == 0:
            entry["by_stage"] = {
                stage: bootstrap_interval(tuple(gain for gain, case in zip(gains, cases) if case.stage == stage), seed=seed)
                for stage in ("early", "mid", "late")
            }
            shanten = [actor_shanten(case) for case in cases]
            entry["by_actor_shanten"] = {
                label: bootstrap_interval(tuple(gain for gain, value in zip(gains, shanten) if (0 if value == 0 else 1 if value == 1 else 2) == bucket), seed=seed)
                for bucket, label in enumerate(("tenpai", "1-shanten", "2+-shanten"))
            }
        deviations.append(entry)
    timing = dict(document["timing"])
    timing["total_seconds"] = timing["corpus_seconds"] + timing["rollout_seconds"]
    scale = 416 * 100 / (len(cases) * document["parameters"]["sims"])
    # Corpus cost scales with games; rollout cost with case-world pairs.
    timing["extrapolated_416x100_seconds"] = timing["corpus_seconds"] * 416 / len(cases) + timing["rollout_seconds"] * scale
    return {
        "parameters": document["parameters"], "source_digest": document["source_digest"],
        "profiles": profile_list, "timing": timing,
        "units": "tai-equivalent payoff including base (3-base/1-tai)",
        "roles": "actor, then absolute seats +1, +2, +3 modulo 4",
        "stage_cut_points": {"late": [0, 19], "mid": [20, 38], "early": [39, 58]},
        "calls": "selfplay strict shanten-improving pon/chi; shanten-safe concealed/added kongs for all seats",
        "sampling": "one uniform eligible pre-discard decision per all-attack game; fixed concealed hands and dead wall; live-wall permutations only",
        "interval": "95% percentile bootstrap of case means; 2000 resamples; pointwise, not simultaneous",
        "extrapolation": "corpus seconds scale with games; rollout seconds scale with case-world pairs; reporting overhead excluded",
        "corpus_stage_counts": {stage: sum(case.stage == stage for case in cases) for stage in ("early", "mid", "late")},
        "base_self_gain_by_role": [list(paired_case_gains(base, base, role)) for role in range(4)],
        "deviations": deviations,
    }


def run(*, cases: int, sims: int, seed: int, base: str = BASE_PROFILE[0], checkpoint: Path | None = None, resume: bool = False) -> dict:
    if cases < 1 or sims < 1:
        raise ValueError("cases and sims must be positive")
    parameters = {"cases": cases, "sims": sims, "seed": seed}
    if base != BASE_PROFILE[0]:  # keeps tenpai_attack checkpoints and reports unchanged
        parameters["base"] = base
    return run_experiment(
        parameters=parameters, cases=cases, corpus_builder=lambda: build_corpus(cases, seed),
        profile_list=profiles(base), fingerprint=source_digest(), finish=finish_case,
        make_report=report, checkpoint=checkpoint, resume=resume,
    )


def run_experiment(*, parameters: dict, cases: int, corpus_builder, profile_list,
                   fingerprint: str, finish, make_report, checkpoint: Path | None = None,
                   resume: bool = False) -> dict:
    """Shared corpus storage, atomic world checkpoints, CRN and resume loop.

    Each finish callback receives the identical wall for a case-world pair and
    returns absolute-seat payoffs. Report callbacks receive actor-relative rows.
    """
    run_started = perf_counter()
    sims, seed = parameters["sims"], parameters["seed"]
    if resume:
        if checkpoint is None:
            raise ValueError("--resume requires --checkpoint")
        document = json.loads(checkpoint.read_text())
        if document["version"] != 1 or document["parameters"] != parameters or document["source_digest"] != fingerprint:
            raise ValueError("checkpoint parameters/version/source differ from this run")
        corpus = tuple(case_from_document(item) for item in document["corpus"])
        if len(corpus) != cases or len(document["worlds"]) != cases:
            raise ValueError("checkpoint corpus length mismatch")
    else:
        if checkpoint is not None and checkpoint.exists():
            raise ValueError("checkpoint exists; use --resume or a new path")
        started = perf_counter()
        corpus = corpus_builder()
        corpus_seconds = perf_counter() - started
        document = {
            "version": 1, "parameters": parameters, "source_digest": fingerprint,
            "corpus": [case_document(case) for case in corpus], "worlds": [[] for _ in corpus],
            "timing": {"corpus_seconds": corpus_seconds, "rollout_seconds": 0.0},
        }
        save_checkpoint(checkpoint, document)
    previous_elapsed = document["timing"]["corpus_seconds"] + document["timing"]["rollout_seconds"] if resume else 0.0
    started = perf_counter()
    previous_seconds = document["timing"]["rollout_seconds"]
    # Random-access world seeds: skipped completed work cannot shift the RNG.
    for case_index, case in enumerate(corpus):
        rows = document["worlds"][case_index]
        if len(rows) > sims:
            raise ValueError("checkpoint has too many worlds")
        for world_index in range(len(rows), sims):
            world_seed = Random(f"midgame:{seed}:{case_index}:{world_index}").getrandbits(64)
            wall = reshuffled_wall(case, world_seed)
            world = []
            for profile in profile_list:
                result = finish(case, profile, wall=wall)
                actor = case.state.current
                world.append([result.point_deltas[(actor + role) % 4] for role in range(4)])
            rows.append(world)
            document["timing"]["rollout_seconds"] = previous_seconds + perf_counter() - started
            save_checkpoint(checkpoint, document)
        print(f"case {case_index + 1}/{cases}: {len(rows)}/{sims} worlds", file=sys.stderr, flush=True)
    document["timing"]["rollout_seconds"] = previous_seconds + perf_counter() - started
    save_checkpoint(checkpoint, document)
    result = make_report(document, corpus)
    result["timing"]["total_seconds"] = previous_elapsed + perf_counter() - run_started
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=int, default=40)
    parser.add_argument("--sims", type=int, default=10)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--base", choices=STRATEGIES, default=BASE_PROFILE[0], help="strategy all four seats play in the base profile")
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        result = run(cases=args.cases, sims=args.sims, seed=args.seed, base=args.base, checkpoint=args.checkpoint, resume=args.resume)
    except (ValueError, FileNotFoundError) as error:
        parser.error(str(error))
    text = json.dumps(result, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text)
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
