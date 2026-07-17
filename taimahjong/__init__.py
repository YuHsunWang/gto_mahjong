"""Taiwanese (16-tile) mahjong hand analysis."""

from .danger import (
    DECLARED_TAI,
    DangerAssessment,
    DangerDiscardAnalysis,
    OpponentView,
    RiverEntry,
    TenpaiAssessment,
    WaitShape,
    danger_score,
    fold_score,
    format_river,
    parse_river,
    rank_discards,
    tenpai_score,
)
from .calibration import Calibration, MIN_CELL_COUNT
from .scoring import BASE_UNITS, ScoreResult, WinContext, score_hand
from .shanten import shanten
from .simulate import SimResult, win_probability
from .tiles import format_tiles, parse_tiles
from .ukeire import DiscardAnalysis, discard_analysis, ukeire

__all__ = [
    "BASE_UNITS",
    "DangerAssessment",
    "DangerDiscardAnalysis",
    "Calibration",
    "DECLARED_TAI",
    "DiscardAnalysis",
    "OpponentView",
    "RiverEntry",
    "SimResult",
    "MIN_CELL_COUNT",
    "TenpaiAssessment",
    "WaitShape",
    "danger_score",
    "discard_analysis",
    "format_tiles",
    "format_river",
    "fold_score",
    "parse_river",
    "parse_tiles",
    "rank_discards",
    "ScoreResult",
    "score_hand",
    "shanten",
    "WinContext",
    "tenpai_score",
    "ukeire",
    "win_probability",
]
