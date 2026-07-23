"""Immutable game-wide house configuration."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType

from .scoring import DEFAULT_SCHEME, SCHEME_3_1, SCHEME_5_2, ScoringScheme


SCHEME_PRESETS = MappingProxyType({
    "3-1": SCHEME_3_1,
    "5-2": SCHEME_5_2,
})


@dataclass(frozen=True)
class GameConfig:
    """Rules that must stay fixed for one game or teaching session.

    Batch A deliberately exposes only the two product-supported payout
    presets.  ``ScoringScheme`` remains the core value object; this boundary
    prevents an API, CLI, or session from inventing a third unit system.
    """

    scheme: ScoringScheme = DEFAULT_SCHEME

    def __post_init__(self) -> None:
        if self.scheme not in SCHEME_PRESETS.values():
            raise ValueError("scheme must be one of the 3-1 or 5-2 presets")

    @property
    def scheme_id(self) -> str:
        return next(key for key, preset in SCHEME_PRESETS.items() if preset == self.scheme)

    @classmethod
    def from_id(cls, scheme_id: str) -> "GameConfig":
        try:
            return cls(SCHEME_PRESETS[scheme_id])
        except KeyError:
            raise ValueError("scheme must be '3-1' or '5-2'") from None

    @classmethod
    def from_pair(cls, base_units: int, tai_units: int) -> "GameConfig":
        for preset in SCHEME_PRESETS.values():
            if (base_units, tai_units) == (preset.base_units, preset.tai_units):
                return cls(preset)
        raise ValueError("base_units/tai_units must be the 3/1 or 5/2 preset")

    def payload(self) -> dict[str, int | str]:
        return {
            "id": self.scheme_id,
            "base_units": self.scheme.base_units,
            "tai_units": self.scheme.tai_units,
        }


DEFAULT_GAME_CONFIG = GameConfig()
