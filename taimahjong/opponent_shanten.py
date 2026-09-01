"""Observed shanten distribution for an opponent who is not tenpai.

`tenpai_score` answers one question — is this opponent waiting? — and the
production world sampler used to stop there: a hand that failed the tenpai
draw was filled by drawing uniformly from the unseen pool.  Uniform draws
almost never land on 1- or 2-shanten, so the sampled opponents were either
waiting or nearly hopeless, with the middle of the distribution empty
(DEV-120).

This module supplies that middle from self-play observation rather than from
an invented curve.  Self-play records every discarder's own shanten alongside
the public state a reader would have seen, and those counts are aggregated
under exactly the key the calibrated tenpai table already uses,
``melds|turn_bucket|run_bucket``.  The model reports the distribution
*conditional on not being tenpai*, so the tenpai rate itself stays where
`tenpai_score` put it and only the previously uniform remainder changes.
"""

from __future__ import annotations

import json
from pathlib import Path

from .calibration import MIN_CELL_COUNT, run_bucket, turn_bucket
from .danger import OpponentView, _trailing_tsumogiri_run


DOCUMENT_VERSION = 1


def cell_key(melds: int, turn: int, run: int) -> str:
    """The conditioning key, identical in shape to the tenpai table's."""
    return f"{melds}|{turn_bucket(turn)}|{run_bucket(run)}"


def view_key(opponent: OpponentView, turn: int) -> str:
    """The key for a public view, read the way `tenpai_score` reads it."""
    return cell_key(
        len(opponent.melds), turn, _trailing_tsumogiri_run(opponent.river),
    )


def counts_from_games(games: list) -> dict:
    """Tally observed shanten by conditioning cell across self-play games."""
    cells: dict[str, dict[str, int]] = {}
    for game in games:
        for event in game.events:
            shanten = event.get("true_shanten")
            if shanten is None:
                raise ValueError(
                    "self-play events lack true_shanten; regenerate with a "
                    "build that records it"
                )
            if shanten < 0:
                # A winning hand is not a state a live opponent is read in.
                continue
            key = cell_key(event["melds"], event["turn"], event["tsumogiri_run"])
            cell = cells.setdefault(key, {})
            label = str(shanten)
            cell[label] = cell.get(label, 0) + 1
    return cells


def _backoff_keys(key: str) -> tuple[str, ...]:
    """Progressively coarser keys, ending at the pooled marginal."""
    melds, turn, run = key.split("|")
    return (key, f"{melds}|{turn}|*", f"*|{turn}|*", "*|*|*")


def _pool(cells: dict[str, dict[str, int]]) -> dict[str, dict[str, int]]:
    """Add the coarser cells the back-off chain reads."""
    pooled: dict[str, dict[str, int]] = {key: dict(cell) for key, cell in cells.items()}
    for key, cell in cells.items():
        melds, turn, run = key.split("|")
        for coarse in (f"{melds}|{turn}|*", f"*|{turn}|*", "*|*|*"):
            target = pooled.setdefault(coarse, {})
            for label, count in cell.items():
                target[label] = target.get(label, 0) + count
    return pooled


def document(counts: dict, metadata: dict | None = None) -> dict:
    return {
        "version": DOCUMENT_VERSION,
        "metadata": metadata or {},
        "counts": counts,
        "tables": _pool(counts),
    }


class OpponentShanten:
    """Lookup for P(shanten = k | public state, not tenpai)."""

    def __init__(self, document: dict, min_cell_count: int = MIN_CELL_COUNT) -> None:
        if document.get("version") != DOCUMENT_VERSION:
            raise ValueError(
                f"unsupported opponent-shanten document version: "
                f"{document.get('version')!r}"
            )
        self.document = document
        self.tables = document["tables"]
        self.min_cell_count = min_cell_count
        if "*|*|*" not in self.tables:
            raise ValueError("document has no pooled marginal to fall back on")

    @classmethod
    def from_path(
        cls, path: str | Path, min_cell_count: int = MIN_CELL_COUNT,
    ) -> "OpponentShanten":
        with Path(path).open(encoding="utf-8") as stream:
            return cls(json.load(stream), min_cell_count)

    def _cell(self, key: str) -> dict[str, int]:
        """The finest cell on the back-off chain with enough non-tenpai mass."""
        for candidate in _backoff_keys(key):
            cell = self.tables.get(candidate)
            if cell is None:
                continue
            if sum(count for label, count in cell.items() if label != "0") >= self.min_cell_count:
                return cell
        return self.tables["*|*|*"]

    def distribution(self, opponent: OpponentView, turn: int) -> tuple[tuple[int, float], ...]:
        """(shanten, probability) over shanten >= 1, conditional on not tenpai.

        Returns an empty tuple when the backing cell holds no non-tenpai
        observation at all, which leaves the caller on its previous behaviour
        rather than inventing a shape.
        """
        cell = self._cell(view_key(opponent, turn))
        entries = sorted(
            (int(label), count)
            for label, count in cell.items()
            if label != "0" and count
        )
        total = sum(count for _, count in entries)
        if not total:
            return ()
        return tuple((shanten, count / total) for shanten, count in entries)

    def sample(self, opponent: OpponentView, turn: int, quantile: float) -> int | None:
        """Draw a shanten >= 1 by inverse transform on `quantile` in [0, 1)."""
        distribution = self.distribution(opponent, turn)
        if not distribution:
            return None
        cumulative = 0.0
        for shanten, probability in distribution:
            cumulative += probability
            if quantile < cumulative:
                return shanten
        return distribution[-1][0]
