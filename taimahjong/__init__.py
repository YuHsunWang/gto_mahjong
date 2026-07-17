"""Taiwanese (16-tile) mahjong hand analysis."""

from .danger import DangerAssessment, DangerDiscardAnalysis, OpponentView, WaitShape, danger_score, rank_discards
from .shanten import shanten
from .simulate import SimResult, win_probability
from .tiles import format_tiles, parse_tiles
from .ukeire import DiscardAnalysis, discard_analysis, ukeire

__all__ = [
    "DangerAssessment",
    "DangerDiscardAnalysis",
    "DiscardAnalysis",
    "OpponentView",
    "SimResult",
    "WaitShape",
    "danger_score",
    "discard_analysis",
    "format_tiles",
    "parse_tiles",
    "rank_discards",
    "shanten",
    "ukeire",
    "win_probability",
]
