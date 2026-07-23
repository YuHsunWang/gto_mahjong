"""Composition-root analysis configuration and calibration provenance."""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path

from .calibration import Calibration
from .config import DEFAULT_GAME_CONFIG, GameConfig


@dataclass(frozen=True)
class CalibrationContext:
    """One immutable calibration identity plus its loaded lookup facade."""

    calibration_id: str
    calibration: Calibration | None = field(compare=False, hash=False, repr=False)
    domain: str = "bot"

    @property
    def fallback_used(self) -> bool:
        return self.calibration is None

    def payload(self) -> dict[str, str | bool]:
        return {
            "calibration_id": self.calibration_id,
            "domain": self.domain,
            "fallback_used": self.fallback_used,
        }


HEURISTIC_FALLBACK = CalibrationContext("heuristic-fallback", None)


@dataclass(frozen=True)
class AnalysisContext:
    """Game rules and model provenance shared by one analysis path."""

    game: GameConfig = DEFAULT_GAME_CONFIG
    calibration: CalibrationContext = HEURISTIC_FALLBACK

    def payload(self) -> dict[str, object]:
        return {
            "scheme": self.game.payload(),
            **self.calibration.payload(),
        }


DEFAULT_ANALYSIS_CONTEXT = AnalysisContext()


@dataclass(frozen=True)
class CalibrationProvider:
    """Load one table and identify it by its exact content hash."""

    path: Path

    def load(self) -> CalibrationContext:
        if not self.path.exists():
            return HEURISTIC_FALLBACK
        content = self.path.read_bytes()
        calibration_id = f"sha256:{sha256(content).hexdigest()}"
        return CalibrationContext(calibration_id, Calibration.from_path(self.path))
