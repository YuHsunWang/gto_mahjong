"""Optional Jev mistake labels for graded discards.

The EV engine already reports *which component* separated the model's discard
from the player's (:func:`taimahjong.quiz.explain` via ``_component_lines``):
"higher win EV by 0.44 tai", "lower expected loss vs Opponent 2".  It does not
name the mahjong concept behind that gap, because no component of the rollout
carries one.  This module asks one System One ``Choice`` for that name.

Nothing here sits on the engine's correctness path.  The label is advisory
decoration: no EV, ranking, verdict or ``ev_delta`` depends on it, and grading
behaves identically when the call is skipped.  It is skipped whenever the SDK
is absent, ``TYPESAFE_API_KEY`` is unset, the request fails, the decision was
not a mistake, the top pair is unresolved, or the returned confidence sits
under :data:`MIN_CONFIDENCE`.

Only ``server/api.py`` imports this module, so the CLI, the package's own
entry points and the test suite stay offline and dependency-free.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

from .quiz import QuizGrade, _component_lines, _tile_name
from .ukeire import discard_analysis

# Conservative starting gate: below this the distribution is spread widely
# enough that naming one concept would overstate what the model saw.  It is a
# starting point to evaluate on real graded hands, not a calibrated constant.
MIN_CONFIDENCE = 0.6

# The grade the player is waiting on already cost seconds of Monte Carlo, so a
# few seconds more is tolerable — but an advisory label must never be the
# reason a decision never renders.
TIMEOUT_SECONDS = 5.0

# Option keys are stable identifiers for code and for the client's display
# map; the meaning the model reads lives entirely in the descriptions.
LABELS: dict[str, dict[str, str]] = {
    "rushed_narrow_wait": {
        "what": (
            "The player took an immediate but narrow tenpai when keeping a "
            "wider one-away shape was worth more."
        ),
        "not_for": (
            "Discards that neither reached tenpai nor gave one up, and late "
            "positions where any tenpai is the point."
        ),
    },
    "broke_wide_shape": {
        "what": (
            "The player broke a block or partial set that was carrying most "
            "of the hand's tile acceptance, losing draws for no compensation."
        ),
        "not_for": (
            "Breaking a shape deliberately to reach tenpai — that is "
            "rushed_narrow_wait — or to discard a safe tile under pressure."
        ),
    },
    "ignored_danger": {
        "what": (
            "The player discarded into a read opponent threat: an opponent "
            "close to tenpai, declared, or showing a concentrated suit, where "
            "the model's discard gave that opponent far less."
        ),
        "not_for": (
            "Positions where no opponent shows a threat and the gap is a "
            "pure efficiency difference."
        ),
    },
    "over_defensive": {
        "what": (
            "The player paid real hand value for safety that the table did "
            "not justify: the opponents' threat was modest and the model kept "
            "attacking."
        ),
        "not_for": (
            "Folding against a genuinely threatening table, which is correct "
            "play rather than a mistake."
        ),
    },
    "wrong_pair_choice": {
        "what": (
            "The player kept or broke the wrong pair, so the hand ended up "
            "with the weaker eyes or lost its only pair."
        ),
        "not_for": (
            "Sequence and run decisions that happen to involve a pair as a "
            "side effect."
        ),
    },
    "no_concept_error": {
        "what": (
            "No named concept explains the gap: both discards follow the same "
            "plan and the difference is a small numeric edge only."
        ),
        "not_for": "Any position where one of the named concepts clearly fits.",
    },
}

INSTRUCTIONS = (
    "A Taiwanese 16-tile mahjong student discarded `chosen.tile` from the "
    "position in `position`. The Monte Carlo engine ranked `best.tile` above "
    "it by `ev_delta` net EV. Both discards and their engine components are "
    "given. Name the single mahjong concept the student got wrong. Judge only "
    "the student's discard against the engine's; do not re-rank the hand, and "
    "do not invent a threat the position does not show."
)


@dataclass(frozen=True)
class MistakeLabel:
    """One named concept for a graded mistake, above the confidence gate."""

    label: str
    confidence: float
    probabilities: dict[str, float]


def _discard_shape(grade: QuizGrade, tile: int) -> dict[str, Any]:
    """Shanten and tile acceptance after one discard, or empty when unavailable.

    ``discard_analysis`` validates hand size against the declared meld count;
    a position it rejects simply contributes no shape fields rather than
    failing the label.
    """
    melds_declared = len(grade.position.own_melds) + len(grade.position.own_kongs)
    try:
        analyses = discard_analysis(grade.position.hand, melds_declared)
    except ValueError:
        return {}
    match = next((entry for entry in analyses if entry.discard == tile), None)
    if match is None:
        return {}
    return {"shanten_after": match.shanten_after, "ukeire_total": match.total}


def _entry_state(grade: QuizGrade, entry: Any) -> dict[str, Any]:
    return {
        "tile": _tile_name(entry.discard),
        "net_ev": round(entry.net_ev, 3),
        "p_win": round(entry.p_win, 3),
        "mean_win_value": (
            None if entry.mean_win_value is None else round(entry.mean_win_value, 3)
        ),
        "risk_ev": round(entry.risk_ev, 3),
        **_discard_shape(grade, entry.discard),
    }


def build_state(grade: QuizGrade) -> dict[str, Any]:
    """Assemble the question's state from values the engine already produced.

    Pure and offline, so the state a label was asked about can be inspected
    and tested without the SDK or a key.
    """
    best_line, chosen_line = _component_lines(grade)
    return {
        "position": grade.position.render(),
        "best": _entry_state(grade, grade.best),
        "chosen": _entry_state(grade, grade.chosen),
        "ev_delta": round(grade.ev_delta, 3),
        "engine_components": {"best": best_line, "chosen": chosen_line},
    }


def _is_labelable(grade: QuizGrade) -> bool:
    """Whether naming a mistake would agree with what the engine claims.

    Two positions are excluded on principle rather than on cost. A discard the
    engine did not rank below its own is not a mistake; and when the top pair
    is unresolved, the engine is already telling the player it cannot separate
    those two, so labelling one of them a concept error would contradict the
    verdict the same screen shows.
    """
    if grade.ev_delta <= 0.0 or grade.best.discard == grade.chosen.discard:
        return False
    if grade.ranking_state != "clear" and len(grade.ranked) >= 2:
        top_pair = {grade.ranked[0].discard, grade.ranked[1].discard}
        if grade.chosen.discard in top_pair:
            return False
    return True


def _client() -> Any:
    if not os.environ.get("TYPESAFE_API_KEY"):
        return None
    try:
        from typesafe_sdk import TypeSafeClient
    except ImportError:
        return None
    return TypeSafeClient(timeout=TIMEOUT_SECONDS)


def label_mistake(grade: QuizGrade) -> MistakeLabel | None:
    """Name the concept behind a graded mistake, or ``None`` when unavailable.

    ``None`` is the ordinary answer, not an error path: it means the screen
    shows exactly what it showed before this module existed.
    """
    if not _is_labelable(grade):
        return None
    client = _client()
    if client is None:
        return None
    from typesafe_sdk import Choice

    try:
        with client:
            response = client.system_one(
                build_state(grade),
                {
                    "mistake": Choice(
                        instructions=INSTRUCTIONS,
                        criteria=LABELS,
                    ),
                },
            )
        answer = response.answers["mistake"]
    except Exception:
        # An advisory decoration must not fail the grading request that the
        # player is waiting on; the screen falls back to the engine's own
        # component explanation. It is logged rather than swallowed, because a
        # silent None is indistinguishable from a confidently withheld label.
        logging.getLogger(__name__).warning("mistake label unavailable", exc_info=True)
        return None
    if answer.confidence < MIN_CONFIDENCE or answer.choice == "no_concept_error":
        return None
    return MistakeLabel(
        label=answer.choice,
        confidence=float(answer.confidence),
        probabilities={key: float(value) for key, value in answer.probabilities.items()},
    )
