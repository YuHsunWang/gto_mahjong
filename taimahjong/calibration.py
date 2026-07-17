"""Empirical calibration tables produced by :mod:`taimahjong.selfplay`."""

from __future__ import annotations

import json
from pathlib import Path

from .danger import MELD_FLUSH, MELD_FLUSH_HONOR, SUIT_SCARCE, SUIT_VOID


MIN_CELL_COUNT = 30
TURN_BUCKETS = ("1-6", "7-12", "13+")
RUN_BUCKETS = ("0", "1-2", "3+")
DANGER_EDGES = (0.0, 1.0, 2.0, 4.0, 6.0, 9.0, 13.0)
DANGER_BUCKETS = ("0-1", "1-2", "2-4", "4-6", "6-9", "9-13", "13+")
DANGER_REFERENCE = "per_opponent"
DANGER_MODIFIERS = {
    "SUIT_VOID": SUIT_VOID,
    "SUIT_SCARCE": SUIT_SCARCE,
    "MELD_FLUSH": MELD_FLUSH,
    "MELD_FLUSH_HONOR": MELD_FLUSH_HONOR,
}


def turn_bucket(turn: int) -> str:
    return "1-6" if turn <= 6 else "7-12" if turn <= 12 else "13+"


def run_bucket(run: int) -> str:
    return "0" if run == 0 else "1-2" if run <= 2 else "3+"


def danger_bucket(score: float) -> str:
    for index, edge in enumerate(DANGER_EDGES[1:]):
        if score < edge:
            return DANGER_BUCKETS[index]
    return DANGER_BUCKETS[-1]


def empty_counts() -> dict:
    return {
        "games": 0,
        "tenpai": {},
        "deal_in": {bucket: {"observations": 0, "deal_ins": 0} for bucket in DANGER_BUCKETS},
        "fold": {
            "attack": {"windows": 0, "score_sum": 0.0},
            "cautious": {"windows": 0, "score_sum": 0.0},
        },
    }


def add_observation(counts: dict, event: dict) -> None:
    """Add one simulator discard event to mergeable raw counts.

    Danger exposure is measured against each live opponent separately.  A ron
    credits only the actual winner's row, so the numerator and denominator
    use the same opponent-specific score.  The scalar fallback retains
    compatibility with pre-M8 in-memory events only; those data must not be
    merged with a per-opponent calibration table.
    """
    key = f"{event['melds']}|{turn_bucket(event['turn'])}|{run_bucket(event['tsumogiri_run'])}"
    cell = counts["tenpai"].setdefault(key, {"observations": 0, "tenpai": 0})
    cell["observations"] += 1
    cell["tenpai"] += int(event["true_tenpai"])
    dangers = event.get("danger_by_opponent")
    if dangers is None:
        danger_rows = ((event["danger_score"], bool(event["dealt_in"])),)
    else:
        winner = event.get("deal_in_winner")
        danger_rows = ((score, bool(event["dealt_in"]) and opponent == winner) for opponent, score in dangers.items())
    for score, dealt_in in danger_rows:
        bucket = danger_bucket(score)
        counts["deal_in"][bucket]["observations"] += 1
        counts["deal_in"][bucket]["deal_ins"] += int(dealt_in)
    if event.get("fold_window"):
        policy = event["policy"]
        fold = counts["fold"][policy]
        fold["windows"] += 1
        fold["score_sum"] += event["fold_score"]


def counts_from_games(games: list) -> dict:
    counts = empty_counts()
    counts["games"] = len(games)
    for game in games:
        for event in game.events:
            add_observation(counts, event)
    return counts


def merge_counts(left: dict, right: dict) -> dict:
    """Merge two raw-count objects without retaining raw game logs."""
    result = empty_counts()
    result["games"] = left.get("games", 0) + right.get("games", 0)
    for source in (left, right):
        for key, cell in source.get("tenpai", {}).items():
            target = result["tenpai"].setdefault(key, {"observations": 0, "tenpai": 0})
            target["observations"] += cell["observations"]
            target["tenpai"] += cell["tenpai"]
        for bucket in DANGER_BUCKETS:
            cell = source.get("deal_in", {}).get(bucket, {})
            result["deal_in"][bucket]["observations"] += cell.get("observations", 0)
            result["deal_in"][bucket]["deal_ins"] += cell.get("deal_ins", 0)
        for policy in ("attack", "cautious"):
            cell = source.get("fold", {}).get(policy, {})
            result["fold"][policy]["windows"] += cell.get("windows", 0)
            result["fold"][policy]["score_sum"] += cell.get("score_sum", 0.0)
    return result


def _isotonic_probabilities(cells: list[dict]) -> list[float | None]:
    """Weighted pool-adjacent-violators calibration for ordered danger bins."""
    blocks: list[dict] = []
    for index, cell in enumerate(cells):
        observations = cell["observations"]
        if not observations:
            blocks.append({"indexes": [index], "weight": 0, "successes": 0})
            continue
        blocks.append({"indexes": [index], "weight": observations, "successes": cell["deal_ins"]})
        while len(blocks) >= 2 and blocks[-2]["weight"] and blocks[-1]["weight"] and (
            blocks[-2]["successes"] / blocks[-2]["weight"] > blocks[-1]["successes"] / blocks[-1]["weight"]
        ):
            right = blocks.pop()
            left = blocks.pop()
            blocks.append(
                {
                    "indexes": left["indexes"] + right["indexes"],
                    "weight": left["weight"] + right["weight"],
                    "successes": left["successes"] + right["successes"],
                }
            )
    result: list[float | None] = [None] * len(cells)
    for block in blocks:
        probability = block["successes"] / block["weight"] if block["weight"] else None
        for index in block["indexes"]:
            result[index] = probability
    return result


def derive_tables(counts: dict) -> dict:
    tenpai: dict[str, dict] = {}
    for melds in range(6):
        for turn in TURN_BUCKETS:
            for run in RUN_BUCKETS:
                key = f"{melds}|{turn}|{run}"
                cell = counts.get("tenpai", {}).get(key, {"observations": 0, "tenpai": 0})
                observations = cell["observations"]
                tenpai[key] = {
                    "observations": observations,
                    "tenpai": cell["tenpai"],
                    "probability": cell["tenpai"] / observations if observations else None,
                }
    raw_deal_in = [counts.get("deal_in", {}).get(bucket, {"observations": 0, "deal_ins": 0}) for bucket in DANGER_BUCKETS]
    fitted_deal_in = _isotonic_probabilities(raw_deal_in)
    deal_in: dict[str, dict] = {}
    for bucket, cell, fitted in zip(DANGER_BUCKETS, raw_deal_in, fitted_deal_in):
        observations = cell["observations"]
        deal_in[bucket] = {
            "observations": observations,
            "deal_ins": cell["deal_ins"],
            "empirical_probability": cell["deal_ins"] / observations if observations else None,
            "probability": fitted,
        }
    fold = {}
    for policy in ("attack", "cautious"):
        cell = counts.get("fold", {}).get(policy, {"windows": 0, "score_sum": 0.0})
        fold[policy] = {
            "windows": cell["windows"],
            "mean_fold_score": cell["score_sum"] / cell["windows"] if cell["windows"] else None,
        }
    return {"tenpai": tenpai, "deal_in": deal_in, "fold": fold}


def table_document(counts: dict, metadata: dict | None = None) -> dict:
    return {"version": 2, "metadata": metadata or {}, "counts": counts, "tables": derive_tables(counts)}


def load_table(path: str | Path) -> dict:
    with Path(path).open(encoding="utf-8") as stream:
        return json.load(stream)


def write_merged_table(path: str | Path, new_counts: dict, metadata: dict | None = None) -> dict:
    destination = Path(path)
    if destination.exists():
        old = load_table(destination)
        if old.get("metadata", {}).get("danger_reference") != DANGER_REFERENCE:
            raise ValueError("existing calibration uses incompatible danger-reference semantics; rebuild from scratch")
        counts = merge_counts(old["counts"], new_counts)
        merged_metadata = dict(old.get("metadata", {}))
    else:
        counts = new_counts
        merged_metadata = {}
    if metadata:
        old_seeds = list(merged_metadata.get("seeds", []))
        merged_metadata.update({key: value for key, value in metadata.items() if key != "seeds"})
        for seed in metadata.get("seeds", []):
            if seed not in old_seeds:
                old_seeds.append(seed)
        merged_metadata["seeds"] = old_seeds
    merged_metadata.update({"danger_reference": DANGER_REFERENCE, "danger_modifiers": DANGER_MODIFIERS})
    merged_metadata["games"] = counts["games"]
    document = table_document(counts, merged_metadata)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8") as stream:
        json.dump(document, stream, indent=2, sort_keys=True)
        stream.write("\n")
    return document


class Calibration:
    """Lookup facade with low-sample fallbacks and danger interpolation."""

    def __init__(self, document: dict, min_cell_count: int = MIN_CELL_COUNT) -> None:
        self.document = document
        self.tables = document.get("tables", derive_tables(document["counts"]))
        self.min_cell_count = min_cell_count

    @classmethod
    def from_path(cls, path: str | Path, min_cell_count: int = MIN_CELL_COUNT) -> "Calibration":
        return cls(load_table(path), min_cell_count)

    def tenpai_probability(self, melds: int, turn: int, run: int) -> float | None:
        key = f"{max(0, min(5, melds))}|{turn_bucket(turn)}|{run_bucket(run)}"
        cell = self.tables["tenpai"].get(key)
        if not cell or cell["observations"] < self.min_cell_count:
            return None
        return cell["probability"]

    def deal_in_probability(self, danger_score: float) -> float | None:
        usable: list[tuple[float, float]] = []
        for index, bucket in enumerate(DANGER_BUCKETS):
            cell = self.tables["deal_in"].get(bucket, {})
            if cell.get("observations", 0) >= self.min_cell_count and cell.get("probability") is not None:
                low = DANGER_EDGES[index]
                high = DANGER_EDGES[index + 1] if index + 1 < len(DANGER_EDGES) else low + 4.0
                usable.append(((low + high) / 2.0, cell["probability"]))
        if not usable:
            return None
        usable.sort()
        if danger_score <= usable[0][0]:
            return usable[0][1]
        if danger_score >= usable[-1][0]:
            return usable[-1][1]
        for (left_x, left_y), (right_x, right_y) in zip(usable, usable[1:]):
            if left_x <= danger_score <= right_x:
                return left_y + (right_y - left_y) * (danger_score - left_x) / (right_x - left_x)
        return None


def format_report(document: dict) -> str:
    """Return a compact human-readable report for the CLI."""
    tables = document.get("tables", derive_tables(document["counts"]))
    lines = ["P(tenpai | melds, turn bucket, tsumogiri run bucket)", "melds  turn  run  probability  observations"]
    for melds in range(6):
        for turn in TURN_BUCKETS:
            for run in RUN_BUCKETS:
                cell = tables["tenpai"][f"{melds}|{turn}|{run}"]
                value = "-" if cell["probability"] is None else f"{cell['probability']:.3f}"
                lines.append(f"{melds:<5}  {turn:<4}  {run:<3}  {value:<11}  {cell['observations']}")
    lines.extend(["", "P(deal-in | M4a danger bucket; monotone calibrated)", "bucket  probability  raw deal-ins/observations"])
    for bucket in DANGER_BUCKETS:
        cell = tables["deal_in"][bucket]
        value = "-" if cell["probability"] is None else f"{cell['probability']:.4f}"
        lines.append(f"{bucket:<6}  {value:<11}  {cell['deal_ins']}/{cell['observations']}")
    lines.append("")
    for policy in ("cautious", "attack"):
        cell = tables["fold"][policy]
        value = "-" if cell["mean_fold_score"] is None else f"{cell['mean_fold_score']:.3f}"
        lines.append(f"{policy} fold windows: mean {value} ({cell['windows']} windows)")
    return "\n".join(lines)
