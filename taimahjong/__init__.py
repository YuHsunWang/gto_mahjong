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
from .ev import (
    DeclarationAdvice,
    EVRankEntry,
    WinValueContext,
    WinValueEstimate,
    deal_in_ev,
    declaration_ev,
    estimate_win_value,
    ev_rank,
    opponent_value_estimate,
)
from .scoring import BASE_UNITS, ScoreResult, WinContext, score_hand
from .shanten import shanten
from .simulate import SimResult, WinningTrial, win_probability, winning_trials
from .tiles import format_tiles, parse_tiles
from .ukeire import DiscardAnalysis, discard_analysis, ukeire

__all__ = [
    "BASE_UNITS",
    "DangerAssessment",
    "DangerDiscardAnalysis",
    "Calibration",
    "DeclarationAdvice",
    "DECLARED_TAI",
    "DiscardAnalysis",
    "EVRankEntry",
    "OpponentView",
    "RiverEntry",
    "SimResult",
    "WinningTrial",
    "WinValueContext",
    "WinValueEstimate",
    "MIN_CELL_COUNT",
    "TenpaiAssessment",
    "WaitShape",
    "danger_score",
    "deal_in_ev",
    "declaration_ev",
    "discard_analysis",
    "format_tiles",
    "format_river",
    "fold_score",
    "estimate_win_value",
    "ev_rank",
    "parse_river",
    "parse_tiles",
    "opponent_value_estimate",
    "rank_discards",
    "ScoreResult",
    "score_hand",
    "shanten",
    "WinContext",
    "tenpai_score",
    "ukeire",
    "win_probability",
    "winning_trials",
]
