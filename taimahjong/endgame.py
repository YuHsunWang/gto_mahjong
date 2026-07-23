"""Late-game filtered teaching positions for endgame push/fold drills.

A thin filter over the quiz machinery: the same seeded self-play snapshots,
restricted to late-wall high-pressure decisions, and tagged as an attack
(push) or defense (fold-pressure) drill from where the fold pseudo-action
ranks by net EV.  Grading reuses :func:`taimahjong.quiz.grade` unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from . import quiz
from .analysis import AnalysisContext, DEFAULT_ANALYSIS_CONTEXT
from .ev import EVRankEntry, ev_rank
from .quiz import EV_TOP_K, MAX_ATTEMPTS, QuizPosition, _evaluation_seed, _position_from, _score_template
from .selfplay import DecisionSnapshot, play_game

# Late-game pressure filter (initial definition per docs/ui-plan.md; tune later).
ENDGAME_WALL_MAX = 20
ENDGAME_SHANTEN_MAX = 1
# Stricter than quiz.EV_GAP_MIN: an endgame drill must have a clearly wrong choice.
ENDGAME_EV_GAP_MIN = 1.2
# Fold's net EV placing this high (1-based) among all actions marks a defense drill.
DEFENSE_FOLD_RANK = 2


@dataclass(frozen=True)
class EndgamePosition:
    """A late-game drill: the ordinary quiz view plus its push/fold teaching tag."""

    position: QuizPosition
    tag: str  # "attack" (push) or "defense" (fold pressure)


def _full_rank(
    position: QuizPosition,
    analysis: AnalysisContext = DEFAULT_ANALYSIS_CONTEXT,
) -> list[EVRankEntry]:
    """The quiz ranking with the fold pseudo-action retained, for tagging.

    Budget constants are read live off ``quiz`` so tests can monkeypatch them.
    """
    return ev_rank(
        position.hand,
        [opponent.view() for opponent in position.opponents],
        position.public_counts,
        len(position.own_melds),
        position.draws_remaining,
        quiz.EV_SIMS,
        _evaluation_seed(position),
        _score_template(position),
        calibration=analysis.calibration.calibration,
        top_k=EV_TOP_K,
        scheme=analysis.game.scheme,
    )


def _pressure(position: QuizPosition) -> bool:
    return position.wall_remaining <= ENDGAME_WALL_MAX and (
        position.shanten <= ENDGAME_SHANTEN_MAX
        or any(opponent.declared for opponent in position.opponents)
    )


def _tag(ranked: list[EVRankEntry]) -> str:
    """"defense" when folding ranks in the top DEFENSE_FOLD_RANK actions by net EV.

    ``ev_rank`` sorts the fold row last regardless of value, so its rank must be
    recomputed from net EV rather than read off the list order.
    """
    fold = next(entry for entry in ranked if entry.is_fold)
    beaten_by = sum(1 for entry in ranked if not entry.is_fold and entry.net_ev > fold.net_ev)
    return "defense" if beaten_by < DEFENSE_FOLD_RANK else "attack"


def generate_endgame_position(
    seed: int,
    analysis: AnalysisContext = DEFAULT_ANALYSIS_CONTEXT,
) -> EndgamePosition:
    """Find the first filtered late-game position at ``seed`` or later.

    Search order matches :func:`taimahjong.quiz.generate_position`: game seeds
    are tried as ``seed``, ``seed + 1``, and so on, up to MAX_ATTEMPTS games,
    so a seed alone reproduces the drill.
    """
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise ValueError("seed must be an integer")
    for game_seed in range(seed, seed + MAX_ATTEMPTS):
        snapshots: list[DecisionSnapshot] = []
        play_game(game_seed, snapshot_hook=snapshots.append, config=analysis.game)
        for snapshot in snapshots:
            position = _position_from(snapshot, game_seed)
            if not _pressure(position):
                continue
            ranked = _full_rank(position, analysis)
            playable = [entry for entry in ranked if not entry.is_fold]
            if len(playable) < 2:
                continue
            gap = playable[0].net_ev - playable[-1].net_ev
            if gap < ENDGAME_EV_GAP_MIN:
                continue
            return EndgamePosition(replace(position, candidate_ev_gap=gap), _tag(ranked))
    raise RuntimeError(f"no endgame position found in {MAX_ATTEMPTS} seeded games")
