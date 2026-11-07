"""Shared lesson catalog and advisory Jev matching for graded mistakes.

Labels take precedence. Relevance scores are only a fallback and never affect
the engine's ranking, verdict or EV. Missing SDK/key and failed requests leave
grading usable without a lesson.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from math import isfinite
from pathlib import Path

from .mistake_label import MistakeLabel, _client, _is_labelable, build_state
from .quiz import QuizGrade

LESSONS = json.loads(
    (Path(__file__).resolve().parents[1] / "data/reference/lessons/lessons.json")
    .read_text(encoding="utf-8")
)

LABEL_LESSONS: dict[str, str | None] = {
    "rushed_narrow_wait": "rush-vs-wide",
    "broke_wide_shape": "lone-terminal",
    "ignored_danger": "respect-threat",
    "over_defensive": "keep-attacking",
    "wrong_pair_choice": "pair-vs-run",
    "no_concept_error": None,
}

# Starting point on the 0–3 rubric, not a calibrated relevance threshold.
# Require evidence of the lesson's actual decision, beyond shared vocabulary.
MIN_RELEVANCE = 2.5

RELEVANCE_CRITERIA = [
    "The lesson teaches a different decision; its advice does not address the engine's gap.",
    "The lesson shares a tile shape or topic, but the position does not show the decision its advice addresses.",
    "The position shows the lesson's decision, but the engine components leave its role in the student's mistake ambiguous.",
    "The position and engine components show the mistake this lesson teaches; applying its advice directly explains the better discard.",
]


@dataclass(frozen=True)
class LessonMatch:
    lesson_id: str
    source: str
    scores: dict[str, float]


def match_lesson(grade: QuizGrade, label: MistakeLabel | None) -> LessonMatch | None:
    """Use a known label or score every lesson in one bounded SDK request."""
    if not _is_labelable(grade):
        return None
    if label is not None:
        lesson_id = LABEL_LESSONS.get(label.label)
        return None if lesson_id is None else LessonMatch(lesson_id, "label", {})
    try:
        client = _client()
        if client is None:
            return None
        from typesafe_sdk import Score

        with client:
            response = client.system_one(
                build_state(grade),
                {
                    lesson["id"]: Score(
                        instructions={
                            "task": (
                                "Rate how directly this lesson explains the student's "
                                "discard mistake against the engine's best discard. "
                                "Use only the supplied position and engine components; "
                                "do not re-rank discards or invent an opponent threat."
                            ),
                            "lesson": lesson,
                        },
                        criteria=RELEVANCE_CRITERIA,
                    )
                    for lesson in LESSONS
                },
            )
        scores = {
            lesson["id"]: float(response.answers[lesson["id"]].score)
            for lesson in LESSONS
        }
        if any(not isfinite(score) or not 0 <= score <= 3 for score in scores.values()):
            raise ValueError("lesson relevance outside its rubric")
    except Exception:
        logging.getLogger(__name__).warning("lesson matching unavailable", exc_info=True)
        return None
    # Catalog order breaks ties deterministically; all scores remain reusable.
    lesson_id = max(scores, key=scores.get)
    if scores[lesson_id] < MIN_RELEVANCE:
        return None
    return LessonMatch(lesson_id, "jev", scores)
