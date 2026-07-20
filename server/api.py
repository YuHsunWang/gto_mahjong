"""FastAPI JSON layer over the taimahjong engine (W1 of docs/ui-plan.md).

Wraps the existing quiz / endgame / trainer / EV / scoring entry points as
JSON endpoints and (from W2 on) serves the static SPA.  EV grading stays
synchronous — the client renders the frozen position with a "計算 EV 中"
state while the request runs, the same 3-state flow the Streamlit app uses.

Run locally with::

    uvicorn server.api:app --reload
"""

from __future__ import annotations

import sys
import threading
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from random import SystemRandom
from typing import Any

# `uvicorn server.api:app` from the repo root works, but running the module
# directly puts server/ (not the repo root) on sys.path — same guard as webapp.
_REPO_ROOT = str(Path(__file__).resolve().parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from taimahjong.calibration import Calibration
from taimahjong.danger import OpponentView, RiverEntry, fold_score, parse_river, tenpai_score
from taimahjong.endgame import EndgamePosition, generate_endgame_position
from taimahjong.ev import EVRankEntry, ev_rank, remaining_draws
from taimahjong.quiz import QuizGrade, QuizPosition, explain, generate_position, grade
from taimahjong.scoring import BASE_UNITS, WinContext, score_hand
from taimahjong.tiles import parse_tiles
from taimahjong.trainer import (
    TrainerCallDecision,
    TrainerDecision,
    TrainerKongDecision,
    TrainerOutcome,
    evaluate_call,
    evaluate_kong,
    play_trainer,
)

app = FastAPI(title="台灣麻將教室 API")

_RANDOM = SystemRandom()
_MAX_SESSIONS = 64


# ---------------------------------------------------------------------------
# Input parsing (compact tile notation, shared with the CLI / Streamlit app)


def _tile_from_compact(text: str) -> int:
    counts = parse_tiles(text)
    found = [tile for tile, count in enumerate(counts) if count]
    if len(found) != 1 or counts[found[0]] != 1:
        raise ValueError("expected exactly one tile, e.g. 3m")
    return found[0]


def _parse_melds(text: str) -> list[tuple[int, int, int]]:
    if not text.strip():
        return []
    melds: list[tuple[int, int, int]] = []
    for item in text.split(";"):
        counts = parse_tiles(item.strip())
        tiles = tuple(tile for tile, count in enumerate(counts) for _ in range(count))
        if len(tiles) != 3:
            raise ValueError("each meld must be exactly three tiles, e.g. 123s;777s")
        melds.append(tiles)
    return melds


def _add_counts(*groups: tuple[int, ...] | list[int]) -> tuple[int, ...]:
    counts = [0] * 34
    for group in groups:
        for tile, count in enumerate(group):
            counts[tile] += count
    return tuple(counts)


def _opponent_public_counts(opponent: OpponentView) -> tuple[int, ...]:
    counts = [0] * 34
    for entry in opponent.river:
        counts[entry.tile if isinstance(entry, RiverEntry) else entry] += 1
    for meld in opponent.melds:
        for tile in meld:
            counts[tile] += 1
    return tuple(counts)


@lru_cache(maxsize=1)
def _calibration() -> Calibration | None:
    path = Path(__file__).resolve().parents[1] / "data" / "calibration.json"
    return Calibration.from_path(path) if path.exists() else None


# ---------------------------------------------------------------------------
# Serialization


def _river_payload(river) -> list[dict[str, Any]]:
    return [{"tile": entry.tile, "origin": entry.origin} for entry in river]


def _position_payload(position: QuizPosition) -> dict[str, Any]:
    return {
        "seed": position.seed,
        "seat": position.seat,
        "turn": position.turn,
        "drawn_tile": position.drawn_tile,
        "hand": list(position.hand),
        "own_river": _river_payload(position.own_river),
        "own_melds": [list(meld) for meld in position.own_melds],
        "opponents": [
            {
                "seat": opponent.seat,
                "river": _river_payload(opponent.river),
                "melds": [list(meld) for meld in opponent.melds],
                "declared": opponent.declared,
                "declared_at": opponent.declared_at,
                "tenpai_estimate": opponent.tenpai_estimate,
                "fold_estimate": opponent.fold_estimate,
                "is_dealer": opponent.is_dealer,
                "dealer_streak": opponent.dealer_streak,
                "hand_count": opponent.hand_count,
            }
            for opponent in position.opponents
        ],
        "shanten": position.shanten,
        "wall_remaining": position.wall_remaining,
        "draws_remaining": position.draws_remaining,
        "is_dealer": position.is_dealer,
        "dealer_streak": position.dealer_streak,
        "candidate_ev_gap": position.candidate_ev_gap,
    }


def _entry_payload(entry: EVRankEntry) -> dict[str, Any]:
    return {
        "discard": entry.discard,
        "is_fold": entry.is_fold,
        "label": entry.label,
        "net_ev": entry.net_ev,
        "p_win": entry.p_win,
        "survival_adjusted_p_win": entry.survival_adjusted_p_win,
        "p_draw": entry.p_draw,
        "mean_win_value": entry.mean_win_value,
        "risk_ev": entry.risk_ev,
    }


def _grade_payload(result: QuizGrade) -> dict[str, Any]:
    return {
        "verdict": result.verdict,
        "marginal": result.marginal,
        "ev_delta": result.ev_delta,
        "ev_loss": result.ev_loss,
        "refined_sims": result.refined_sims,
        "rank_position": result.rank_position,
        "best": _entry_payload(result.best),
        "chosen": _entry_payload(result.chosen),
        "ranked": [_entry_payload(entry) for entry in result.ranked],
        "explain": explain(result),
    }


# ---------------------------------------------------------------------------
# Quiz + endgame drills (stateless: the seed reproduces the position)


class SeedRequest(BaseModel):
    seed: int | None = None


class GradeRequest(BaseModel):
    seed: int
    tile: int


@lru_cache(maxsize=128)
def _quiz_position(seed: int) -> QuizPosition:
    return generate_position(seed)


@lru_cache(maxsize=128)
def _endgame_position(seed: int) -> EndgamePosition:
    return generate_endgame_position(seed)


def _new_seed(requested: int | None) -> int:
    return _RANDOM.randrange(1, 1_000_000) if requested is None else requested


def _engine(call, *args):
    """Run an engine entry point, mapping its input errors to HTTP 422."""
    try:
        return call(*args)
    except (ValueError, RuntimeError) as error:
        raise HTTPException(status_code=422, detail=str(error))


@app.post("/api/quiz/new")
def quiz_new(request: SeedRequest) -> dict[str, Any]:
    position = _engine(_quiz_position, _new_seed(request.seed))
    return {"position": _position_payload(position)}


@app.post("/api/quiz/grade")
def quiz_grade(request: GradeRequest) -> dict[str, Any]:
    position = _engine(_quiz_position, request.seed)
    return {"grade": _grade_payload(_engine(grade, position, request.tile))}


@app.post("/api/endgame/new")
def endgame_new(request: SeedRequest) -> dict[str, Any]:
    drill = _engine(_endgame_position, _new_seed(request.seed))
    return {"position": _position_payload(drill.position), "tag": drill.tag}


@app.post("/api/endgame/grade")
def endgame_grade(request: GradeRequest) -> dict[str, Any]:
    drill = _engine(_endgame_position, request.seed)
    return {"grade": _grade_payload(_engine(grade, drill.position, request.tile)), "tag": drill.tag}


# ---------------------------------------------------------------------------
# Trainer sessions (in-memory, single-user local tool per docs/ui-plan.md)


@dataclass
class _TrainerSession:
    seed: int
    human_seat: int
    dealer_streak: int
    generator: Any
    current: Any  # TrainerDecision | TrainerKongDecision | TrainerCallDecision | TrainerOutcome
    step: int = 0
    score: dict[str, float] = field(default_factory=lambda: {"decisions": 0, "best": 0, "loss": 0.0})
    feedback: dict[str, Any] | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)


_SESSIONS: OrderedDict[str, _TrainerSession] = OrderedDict()


class TrainerNewRequest(BaseModel):
    seed: int | None = None
    human_seat: int = 0
    dealer_streak: int = 0


class TrainerActRequest(BaseModel):
    step: int
    action: str  # "discard" | "kong" | "call"
    tile: int | None = None  # discard only
    option: int | None = None  # kong/call: option index, or None to skip/pass


def _decision_payload(item: Any) -> dict[str, Any]:
    if isinstance(item, TrainerOutcome):
        return {
            "type": "outcome",
            "outcome": item.outcome,
            "headline": item.headline,
            "human_won": item.human_won,
            "human_dealt_in": item.human_dealt_in,
            "robbed_kong": item.robbed_kong,
            "winner": item.winner,
            "discarder": item.discarder,
            "point_delta": item.point_delta,
            "turns": item.turns,
            "dealer_streak_in": item.dealer_streak_in,
            "next_dealer_streak": item.next_dealer_streak,
            "next_human_seat": item.next_human_seat,
        }
    if isinstance(item, TrainerKongDecision):
        return {
            "type": "kong",
            "position": _position_payload(item.position),
            "options": [
                {"kind": option.kind, "tile": option.tile, "post_shanten": option.post_shanten}
                for option in item.options
            ],
        }
    if isinstance(item, TrainerCallDecision):
        return {
            "type": "call",
            "position": _position_payload(item.position),
            "offered_tile": item.offered_tile,
            "discarder": item.discarder,
            "options": [
                {"kind": option.kind, "meld": list(option.meld), "consumed": list(option.consumed)}
                for option in item.options
            ],
        }
    assert isinstance(item, TrainerDecision)
    return {"type": "discard", "position": _position_payload(item.position)}


def _session_payload(session_id: str, session: _TrainerSession) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "step": session.step,
        "seed": session.seed,
        "human_seat": session.human_seat,
        "dealer_streak": session.dealer_streak,
        "scorecard": dict(session.score),
        "decision": _decision_payload(session.current),
        "feedback": session.feedback,
    }


def _get_session(session_id: str) -> _TrainerSession:
    session = _SESSIONS.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="unknown trainer session")
    return session


@app.post("/api/trainer/new")
def trainer_new(request: TrainerNewRequest) -> dict[str, Any]:
    seed = _new_seed(request.seed)
    generator = _engine(play_trainer, seed, request.human_seat, ("attack", "cautious", "attack", "cautious"), request.dealer_streak)
    first = _engine(next, generator)
    session = _TrainerSession(seed, request.human_seat, request.dealer_streak, generator, first)
    session_id = uuid.uuid4().hex
    _SESSIONS[session_id] = session
    while len(_SESSIONS) > _MAX_SESSIONS:
        _SESSIONS.popitem(last=False)
    return _session_payload(session_id, session)


@app.get("/api/trainer/{session_id}")
def trainer_get(session_id: str) -> dict[str, Any]:
    session = _get_session(session_id)
    with session.lock:
        return _session_payload(session_id, session)


def _record(session: _TrainerSession, verdict: str, ev_loss: float) -> None:
    session.score["decisions"] += 1
    session.score["best"] += int(verdict == "best")
    session.score["loss"] += ev_loss


def _validate_option(options, option: int | None) -> int | None:
    """Map the client's option field to the generator protocol (None = pass)."""
    if option is None:
        return None
    if not 0 <= option < len(options):
        raise HTTPException(status_code=422, detail="option index out of range")
    return option


@app.post("/api/trainer/{session_id}/act")
def trainer_act(session_id: str, request: TrainerActRequest) -> dict[str, Any]:
    session = _get_session(session_id)
    with session.lock:
        if request.step != session.step:
            raise HTTPException(status_code=409, detail=f"stale step {request.step}, session is at {session.step}")
        item = session.current
        if isinstance(item, TrainerOutcome):
            raise HTTPException(status_code=409, detail="hand is already over")

        if isinstance(item, TrainerDecision):
            if request.action != "discard" or request.tile is None:
                raise HTTPException(status_code=422, detail="current decision expects action=discard with a tile")
            # grade() validates the tile before anything is sent into the
            # generator — a bad send would terminate the game generator.
            result = _engine(grade, item.position, request.tile)
            _record(session, result.verdict, result.ev_loss)
            session.feedback = {"kind": "discard", "chosen_tile": request.tile, **_grade_payload(result)}
            session.current = session.generator.send(request.tile)
        elif isinstance(item, TrainerKongDecision):
            if request.action != "kong":
                raise HTTPException(status_code=422, detail="current decision expects action=kong")
            choice = _validate_option(item.options, request.option)
            evaluation = evaluate_kong(item)
            result = evaluation.verdict_for(choice)
            _record(session, result.verdict, result.ev_loss)
            session.feedback = {
                "kind": "kong",
                "choice": choice,
                "verdict": result.verdict,
                "marginal": result.marginal,
                "ev_delta": result.ev_delta,
                "ev_loss": result.ev_loss,
                "refined_sims": result.refined_sims,
                "best_ev": result.best_ev,
                "best_index": evaluation.best_index,
                "pass_ev": evaluation.pass_ev,
                "option_evs": list(evaluation.option_evs),
            }
            session.current = session.generator.send(choice)
        elif isinstance(item, TrainerCallDecision):
            if request.action != "call":
                raise HTTPException(status_code=422, detail="current decision expects action=call")
            choice = _validate_option(item.options, request.option)
            evaluation = evaluate_call(item)
            result = evaluation.verdict_for(choice)
            _record(session, result.verdict, result.ev_loss)
            session.feedback = {
                "kind": "call",
                "choice": choice,
                "verdict": result.verdict,
                "marginal": result.marginal,
                "ev_delta": result.ev_delta,
                "ev_loss": result.ev_loss,
                "refined_sims": result.refined_sims,
                "best_ev": result.best_ev,
                "best_index": evaluation.best_index,
                "pass_ev": evaluation.pass_ev,
                "option_evs": list(evaluation.option_evs),
            }
            session.current = session.generator.send(choice)
        else:  # pragma: no cover - the isinstance set above is exhaustive
            raise HTTPException(status_code=500, detail="unknown decision type")

        session.step += 1
        return _session_payload(session_id, session)


# ---------------------------------------------------------------------------
# Stateless analysis: EV ranking and hand scoring


class EvRankRequest(BaseModel):
    hand: str
    river: str = ""
    melds: str = ""
    declared_at: int | None = None
    visible: str = ""
    turns: int = 0  # 0 = derive from the visible pool
    sims: int = 400
    seed: int = 7


class ScoreRequest(BaseModel):
    hand: str
    win_tile: str
    melds: str = ""
    self_draw: bool = False
    dealer: bool = False
    dealer_streak: int = 0
    migi: bool = False
    heavenly: bool = False
    earthly: bool = False
    round_wind: str | None = None
    seat_wind: str | None = None


@app.post("/api/ev/rank")
def ev_rank_endpoint(request: EvRankRequest) -> dict[str, Any]:
    def run() -> dict[str, Any]:
        counts = parse_tiles(request.hand)
        opponent: OpponentView | None = None
        if request.river or request.melds or request.declared_at is not None:
            if not request.river:
                raise ValueError("opponent state requires the opponent's river")
            opponent = OpponentView(parse_river(request.river), _parse_melds(request.melds), request.declared_at)
            opponent.validate()
        other_visible = (0,) * 34 if not request.visible.strip() else parse_tiles(request.visible)
        visible = _add_counts(other_visible, _opponent_public_counts(opponent)) if opponent else other_visible
        turns = request.turns or remaining_draws(counts, visible)
        entries = ev_rank(
            counts, [] if opponent is None else [opponent], visible,
            turns=turns, sims=request.sims, seed=request.seed, calibration=_calibration(),
        )
        payload: dict[str, Any] = {"turns": turns, "entries": [_entry_payload(entry) for entry in entries]}
        if opponent is not None:
            payload["opponent"] = {
                "tenpai_estimate": tenpai_score(opponent, len(opponent.river)).score,
                "fold_estimate": fold_score(opponent, []),
            }
        return payload

    return _engine(run)


@app.post("/api/score")
def score_endpoint(request: ScoreRequest) -> dict[str, Any]:
    def run() -> dict[str, Any]:
        context = WinContext(
            winning_tile=_tile_from_compact(request.win_tile),
            self_draw=request.self_draw,
            dealer=request.dealer,
            dealer_streak=request.dealer_streak,
            migi_declared=request.migi,
            heavenly=request.heavenly,
            earthly=request.earthly,
            round_wind=None if request.round_wind is None else _tile_from_compact(request.round_wind),
            seat_wind=None if request.seat_wind is None else _tile_from_compact(request.seat_wind),
        )
        result = score_hand(parse_tiles(request.hand), tuple(_parse_melds(request.melds)), context)
        return {
            "items": [{"name": name, "tai": tai} for name, tai in result.items],
            "total_tai": result.total_tai,
            "value_units": result.value_units,
            "base_units": BASE_UNITS,
        }

    return _engine(run)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


# The W2 SPA is served from server/static/ when it exists; declared after the
# API routes so /api/* always wins over the catch-all static mount.
_STATIC_DIR = Path(__file__).resolve().parent / "static"
if _STATIC_DIR.is_dir():
    app.mount("/", StaticFiles(directory=_STATIC_DIR, html=True), name="static")
