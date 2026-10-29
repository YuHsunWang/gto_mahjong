"""Map actor exit gains in undeclared all-attack hands (cost pilot only).

    python scripts/midgame_exit_check.py --per-stage 30 --sims 10 --seed 1 \
        --checkpoint /tmp/exit-checkpoint.json --output /tmp/exit-report.json \
        --csv /tmp/exit-cases.csv

Add --resume with identical parameters after interruption. All three actor
profiles and all worlds of a case complete before each atomic checkpoint. No long run is started
automatically; the report only extrapolates to 300 cases/stage x 100 worlds.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.midgame_deviation_check import run_experiment, source_digest as engine_digest
from taimahjong.midgame_corpus import build_corpus, build_stratified_corpus
from taimahjong.midgame_exit import ACTOR_PROFILES, case_observation, decision_features, finish_actor_case
from taimahjong.midgame_game import bootstrap_interval, paired_case_gains


STAGES = ("early", "mid", "late")
TERCILES = ("low", "middle", "high")


def source_digest() -> str:
    digest = hashlib.sha256(engine_digest().encode())
    digest.update((ROOT / "taimahjong" / "midgame_exit.py").read_bytes())
    digest.update(Path(__file__).read_bytes())
    return digest.hexdigest()


def danger_terciles(values: list[float]) -> tuple[tuple[float, float], list[str]]:
    """Linear quantiles at (n-1)/3 and 2(n-1)/3; ties stay together."""
    ordered = sorted(values)
    cuts = []
    for numerator in (1, 2):
        position = (len(ordered) - 1) * numerator / 3
        lower = int(position)
        upper = min(lower + 1, len(ordered) - 1)
        cuts.append(ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower))
    return tuple(cuts), ["low" if value <= cuts[0] else "middle" if value <= cuts[1] else "high" for value in values]


def report(document: dict, cases: tuple) -> dict:
    features = [decision_features(case_observation(case)) for case in cases]
    cuts, buckets = danger_terciles([row["attack_danger"] for row in features])
    for row, bucket in zip(features, buckets):
        row["danger_tercile"] = bucket
        row["shanten_bucket"] = "tenpai" if row["actor_shanten"] == 0 else "1-shanten" if row["actor_shanten"] == 1 else "2+-shanten"
    tables = [[[world[index] for world in row] for row in document["worlds"]] for index in range(len(ACTOR_PROFILES))]
    seed = document["parameters"]["seed"]
    deviations = []
    for index, alternative in enumerate(ACTOR_PROFILES[1:], 1):
        gains = paired_case_gains(tables[0], tables[index], 0)

        def interval(predicate):
            return bootstrap_interval(tuple(gain for gain, row in zip(gains, features) if predicate(row)), seed=seed)

        entry = {"role": 0, "alternative": alternative, **bootstrap_interval(gains, seed=seed)}
        entry["by_stage"] = {stage: interval(lambda row: row["stage"] == stage) for stage in STAGES}
        entry["by_actor_shanten"] = {label: interval(lambda row: row["shanten_bucket"] == label) for label in ("tenpai", "1-shanten", "2+-shanten")}
        entry["by_attack_danger_tercile"] = {label: interval(lambda row: row["danger_tercile"] == label) for label in TERCILES}
        entry["by_stage_and_danger_tercile"] = {
            stage: {label: interval(lambda row: row["stage"] == stage and row["danger_tercile"] == label) for label in TERCILES}
            for stage in STAGES
        }
        deviations.append(entry)
        for row, gain in zip(features, gains):
            row[f"{alternative}_mean_gain"] = gain
    per_case = [{"case_index": index, "game_seed": case.game_seed, "decision_index": case.decision_index,
                 "actor_seat": case.state.current, **row} for index, (case, row) in enumerate(zip(cases, features))]
    timing = dict(document["timing"])
    timing["total_seconds"] = timing["corpus_seconds"] + timing["rollout_seconds"]
    timing["extrapolated_300_per_stage_x100_seconds"] = (
        timing["corpus_seconds"] * 900 / len(cases)
        + timing["rollout_seconds"] * 900 * 100 / (len(cases) * document["parameters"]["sims"])
    )
    return {
        "parameters": document["parameters"], "source_digest": document["source_digest"],
        "profiles": [[name, "attack", "attack", "attack"] for name in ACTOR_PROFILES],
        "units": "tai-equivalent payoff including base (3-base/1-tai)",
        "roles": "actor, then absolute seats +1, +2, +3 modulo 4; only actor deviates",
        "sampling": "one uniform eligible point from the union of still-needed stages per all-attack game; reject games with none; stages fixed before each game; no declarations or prior wins",
        "conditioning": "fixed concealed hands and dead wall; shared live-wall permutation per case/world; calls and kongs use the original engine rules",
        "overall_weighting": "equal cases per stage, not natural stage-frequency weighting",
        "stage_cut_points": {"early": [39, 58], "mid": [20, 38], "late": [0, 19]},
        "corpus_stage_counts": {stage: sum(case.stage == stage for case in cases) for stage in STAGES},
        "danger_terciles": {"cut_values": cuts, "rule": "linear quantiles at (n-1)/3 and 2(n-1)/3 of corpus attack danger; low <= q1, middle q1 < x <= q2, high > q2; ties stay together, so bins may be unequal or empty"},
        "feature_definitions": {"tiles": "0-based tile indices", "attack_danger_rank": "ascending competition rank, 1=safest; ties share rank", "opponent_melds": "sum of public sets across all opponents, including kongs", "danger": "fold's max over opponents of river-aware validated danger times tenpai_score; heuristic score, not calibrated probability"},
        "interval": "95% percentile case bootstrap, 2000 resamples, after averaging paired worlds inside each case; pointwise, not simultaneous",
        "timing": timing,
        "extrapolation": "corpus seconds scale with cases; rollout seconds with case-world pairs, including checkpoint writes; reporting overhead excluded; no long experiment executed",
        "deviations": deviations, "per_case": per_case,
    } | ({
        "sampling": f"one uniform undeclared, no-win decision with live wall <= {document['parameters']['max_wall']} per all-attack game; reject games with none",
        "overall_weighting": "natural frequency of decisions within the wall window",
    } if "max_wall" in document["parameters"] else {})


def run(*, per_stage: int, sims: int, seed: int, checkpoint: Path | None = None, resume: bool = False,
        max_wall: int | None = None) -> dict:
    if per_stage < 1 or sims < 1:
        raise ValueError("per_stage and sims must be positive")
    parameters = {"per_stage": per_stage, "sims": sims, "seed": seed}
    if max_wall is None:
        cases, builder = 3 * per_stage, lambda: build_stratified_corpus(per_stage, seed)
    else:
        # Endgame window: per_stage is the total case count, all from wall <= max_wall.
        if not 0 <= max_wall <= 58:
            raise ValueError("max_wall must be between 0 and 58")
        parameters["max_wall"] = max_wall
        cases, builder = per_stage, lambda: build_corpus(per_stage, seed, max_wall=max_wall)
    return run_experiment(
        parameters=parameters, cases=cases,
        corpus_builder=builder,
        profile_list=ACTOR_PROFILES, fingerprint=source_digest(), finish=finish_actor_case,
        make_report=report, checkpoint=checkpoint, resume=resume,
    )


def write_outputs(result: dict, output: Path | None, csv_path: Path | None) -> None:
    if csv_path is not None:
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        with csv_path.open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(result["per_case"][0]))
            writer.writeheader()
            writer.writerows(result["per_case"])
    text = json.dumps(result, indent=2) + "\n"
    if output is None:
        print(text, end="")
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--per-stage", type=int, default=30)
    parser.add_argument("--sims", type=int, default=10)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--csv", type=Path)
    parser.add_argument("--max-wall", type=int, help="only sample decisions with at most this many live-wall tiles; --per-stage is then the total case count")
    args = parser.parse_args()
    try:
        result = run(per_stage=args.per_stage, sims=args.sims, seed=args.seed, checkpoint=args.checkpoint, resume=args.resume, max_wall=args.max_wall)
        write_outputs(result, args.output, args.csv)
    except (ValueError, FileNotFoundError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
