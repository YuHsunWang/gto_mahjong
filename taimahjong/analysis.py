"""Composition-root analysis configuration and calibration provenance."""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import json
import logging
from pathlib import Path
from typing import Literal

from .calibration import Calibration
from .config import DEFAULT_GAME_CONFIG, GameConfig
from .opponent_shanten import OpponentShanten


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CalibrationContext:
    """One immutable model identity plus both loaded lookup facades.

    ``default`` preserves default-table loading for callers without a provider;
    provider fallbacks explicitly carry ``None`` instead.
    """

    calibration_id: str
    calibration: Calibration | None = field(compare=False, hash=False, repr=False)
    domain: str = "bot"
    opponent_shanten: OpponentShanten | None | Literal["default"] = field(
        default="default", compare=False, hash=False, repr=False,
    )
    _default_opponent: bool = field(init=False, repr=False)

    def __post_init__(self) -> None:
        # Default-table analyses must not share cached ranks with explicit fallback.
        object.__setattr__(self, "_default_opponent", self.opponent_shanten == "default")

    @property
    def fallback_used(self) -> bool:
        return self.calibration is None

    def payload(self) -> dict[str, str | bool]:
        return {
            "calibration_id": self.calibration_id,
            "domain": self.domain,
            "fallback_used": self.fallback_used,
        }


HEURISTIC_FALLBACK = CalibrationContext(
    "heuristic-fallback", None, opponent_shanten=None,
)


@dataclass(frozen=True)
class AnalysisContext:
    """Game rules and model provenance shared by one analysis path."""

    game: GameConfig = DEFAULT_GAME_CONFIG
    calibration: CalibrationContext = CalibrationContext("heuristic-fallback", None)

    def payload(self) -> dict[str, object]:
        return {
            "scheme": self.game.payload(),
            **self.calibration.payload(),
        }


DEFAULT_ANALYSIS_CONTEXT = AnalysisContext()


def _load_opponent_shanten(path: Path) -> tuple[bytes, OpponentShanten] | None:
    """Read and validate the table shared by provenance and world sampling."""
    try:
        content = path.read_bytes()
        model = OpponentShanten(json.loads(content))
        for cell in model.tables.values():
            for label, count in cell.items():
                if int(label) < 0 or type(count) is not int or count < 0:
                    raise ValueError("invalid shanten count")
        if not any(
            int(label) > 0 and count > 0
            for label, count in model.tables["*|*|*"].items()
        ):
            raise ValueError("no non-tenpai observations")
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        logger.warning("ignoring unusable opponent-shanten table %s: %s", path, error)
        return None
    return content, model


@dataclass(frozen=True)
class CalibrationProvider:
    """Load both EV tables and identify their exact content by one hash."""

    path: Path

    def load(self) -> CalibrationContext:
        if not self.path.exists():
            return HEURISTIC_FALLBACK
        content = self.path.read_bytes()
        try:
            calibration = Calibration(json.loads(content))
        except (ValueError, KeyError, TypeError, AttributeError) as error:
            logger.warning("ignoring unusable calibration table %s: %s", self.path, error)
            return HEURISTIC_FALLBACK
        opponent = _load_opponent_shanten(self.path.with_name("opponent-shanten.json"))
        if opponent is None:
            return HEURISTIC_FALLBACK
        opponent_content, opponent_model = opponent
        # Frame the first table so different byte boundaries cannot share an ID.
        combined = len(content).to_bytes(8, "big") + content + opponent_content
        calibration_id = f"sha256:{sha256(combined).hexdigest()}"
        return CalibrationContext(
            calibration_id, calibration, opponent_shanten=opponent_model,
        )
