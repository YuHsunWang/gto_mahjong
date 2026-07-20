"""Seeded teaching positions for probability-grounded discard practice.

Only table information visible to the player is retained.  Hidden opponent
hands remain inside self-play and never become part of a :class:`QuizPosition`.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from functools import lru_cache
from math import ceil
from typing import Callable, TypeVar

from .danger import OpponentView, RiverEntry, danger_score, fold_score, format_river, tenpai_score
from .ev import EVRankEntry, WinValueContext, evaluate_discard, ev_rank
from .scoring import WinContext
from .selfplay import DEALER_SEAT, DecisionSnapshot, _cached_shanten, play_game
from .shanten import shanten
from .tiles import format_tiles, validate_counts


# Position filter constants.  They are intentionally fixed so a seed alone
# reproduces both the selected position and its teaching verdict.
SHANTEN_MAX = 2
MIN_TURN = 5
EV_GAP_MIN = 0.8
GOOD_DELTA = 0.3
MAX_ATTEMPTS = 80

# Fixed quiz evaluation budget.  The position seed is transformed below and
# passed to every EV call, so Monte Carlo sampling remains reproducible.
#
# Two-stage evaluation: EV_SIMS is the cheap budget used to rank every
# candidate and pick the list and its order (CRN stabilises that ranking).
# REFINE_SIMS is spent only on the two candidates that decide a grade — the
# rank-best and the one the player chose — re-estimated under the same CRN
# base seed. That cuts the verdict/ev_delta sampling noise to ~sqrt(EV_SIMS/
# REFINE_SIMS) without paying the high budget on all 5-7 candidates. The
# absolute EVs still carry Monte Carlo error that only more sims can reduce.
EV_SIMS = 24
REFINE_SIMS = 200
EV_TOP_K = 5

# Third, adaptive stage. REFINE_SIMS leaves cross-seed ev_delta noise around
# 0.05-0.15 tai, which is only well below the *wide* verdict boundary (1.0) but
# not the tight one (GOOD_DELTA) — a verdict whose ev_delta sits right on a
# boundary can still flip between CRN seeds. So when the REFINE_SIMS ev_delta
# lands within ESCALATE_MARGIN of a boundary, re-estimate the same two
# candidates at ESCALATE_SIMS (same CRN base seed) — spending the high budget
# only on the verdicts it can actually change. MARGINAL_BAND flags a final
# ev_delta still hugging a boundary: even ESCALATE_SIMS cannot make such a
# verdict certain, so the UI labels it "邊緣" rather than pretending it is crisp.
# These are read as module globals at call time so tests can monkeypatch them.
ESCALATE_SIMS = 800
ESCALATE_MARGIN = 0.15
MARGINAL_BAND = 0.10
# Escalation cost is dominated by Monte Carlo rollout depth: a far-from-tenpai
# hand takes many draws to resolve each trial, so one ESCALATE_SIMS estimate on
# a 3-shanten hand costs ~70s (vs a couple of seconds near tenpai) — and there
# the win-EV distinction between candidates is buried in noise anyway. So only
# near-tenpai verdicts are escalated: it is where a fine EV difference is both a
# real teaching point and cheap to resolve. Far-from-tenpai near-ties keep the
# REFINE_SIMS verdict (and are still flagged marginal when they hug a boundary).
ESCALATE_MAX_SHANTEN = 1


def verdict_for_delta(ev_delta: float) -> str:
    """Map an EV loss (best minus chosen, in tai) to a teaching verdict."""
    if ev_delta <= 0.0:
        return "best"
    if ev_delta < GOOD_DELTA:
        return "good"
    if ev_delta < 1.0:
        return "inaccuracy"
    return "mistake"


def threshold_gap(ev_delta: float) -> float:
    """Distance from ``ev_delta`` to the nearest verdict boundary."""
    return min(abs(ev_delta - threshold) for threshold in (0.0, GOOD_DELTA, 1.0))


def should_escalate(ev_delta: float, shanten: int) -> bool:
    """Whether a boundary-hugging verdict is worth (and cheap enough for) the
    higher ESCALATE_SIMS budget. Reads the gate constants live so tests can
    monkeypatch them."""
    return shanten <= ESCALATE_MAX_SHANTEN and threshold_gap(ev_delta) < ESCALATE_MARGIN


@dataclass(frozen=True)
class Verdict:
    """The adaptive-budget grading outcome shared by discard and call grading."""

    verdict: str
    ev_delta: float
    refined_sims: int  # budget the verdict was decided at (REFINE_SIMS or ESCALATE_SIMS)
    marginal: bool  # final ev_delta still hugs a verdict boundary

    @classmethod
    def exact_tie(cls, refined_sims: int) -> "Verdict":
        """Return an exact tie; ``marginal=False`` deliberately overrides the
        boundary flag because identical choices are never borderline."""
        return cls("best", 0.0, refined_sims, False)

    @property
    def ev_loss(self) -> float:
        """Non-negative loss suitable for accumulating player scores."""
        return max(0.0, self.ev_delta)


_Payload = TypeVar("_Payload")


def resolve_adaptive(estimate: Callable[[int], tuple[float, _Payload]], shanten: int) -> tuple[Verdict, _Payload]:
    """Grade a best-minus-chosen ev_delta under the two-stage adaptive budget.

    ``estimate(sims)`` returns ``(ev_delta, payload)`` for the best and chosen
    candidates re-estimated at ``sims`` sims (sharing the CRN base seed); the
    payload from the budget that decided the verdict is handed back so the caller
    keeps the final-budget estimates without recomputing. Escalation to
    ESCALATE_SIMS happens only when the REFINE_SIMS delta hugs a boundary and the
    hand is near tenpai. The exact-tie case (chosen IS the best) is the caller's
    to short-circuit — it must not be escalated or flagged marginal.
    """
    delta, payload = estimate(REFINE_SIMS)
    refined_sims = REFINE_SIMS
    if should_escalate(delta, shanten):
        delta, payload = estimate(ESCALATE_SIMS)
        refined_sims = ESCALATE_SIMS
    return Verdict(verdict_for_delta(delta), delta, refined_sims, threshold_gap(delta) < MARGINAL_BAND), payload


@dataclass(frozen=True)
class QuizOpponent:
    """One opponent's public state: no concealed *tiles*, but hand_count (the
    number of tiles held) is publicly observable in a real game."""

    seat: int
    river: tuple[RiverEntry, ...]
    melds: tuple[tuple[int, int, int], ...]
    declared_at: int | None
    tenpai_estimate: float
    fold_estimate: float
    dealer_streak: int = 0  # nonzero only when this opponent is the dealer
    hand_count: int = 0

    @property
    def declared(self) -> bool:
        return self.declared_at is not None

    @property
    def is_dealer(self) -> bool:
        return self.seat == DEALER_SEAT

    def view(self) -> OpponentView:
        return OpponentView(
            list(self.river), list(self.melds), self.declared_at,
            is_dealer=self.is_dealer, dealer_streak=self.dealer_streak,
            hand_count=self.hand_count,
        )


@dataclass(frozen=True)
class QuizPosition:
    """A reproducible post-draw decision view from one seat's perspective."""

    seed: int
    seat: int
    turn: int
    drawn_tile: int
    hand: tuple[int, ...]
    own_river: tuple[RiverEntry, ...]
    own_melds: tuple[tuple[int, int, int], ...]
    opponents: tuple[QuizOpponent, ...]
    public_counts: tuple[int, ...]
    visible_counts: tuple[int, ...]
    shanten: int
    draws_remaining: int
    wall_remaining: int
    candidate_ev_gap: float
    dealer_streak: int = 0  # the table's 連莊 count (dealer is always seat 0)

    @property
    def is_dealer(self) -> bool:
        """Seat 0 is the dealer in the self-play/trainer model."""
        return self.seat == DEALER_SEAT

    @property
    def own_hand(self) -> tuple[int, ...]:
        """Alias that makes the concealed-hand ownership explicit to callers."""
        return self.hand

    def render(self) -> str:
        lines = [
            f"Quiz seed: {self.seed}  Seat: {self.seat}  Turn: {self.turn}",
            f"Draw: {_tile_name(self.drawn_tile)}",
            f"Hand: {format_tiles(self.hand)}",
            f"Own river: {format_river(list(self.own_river)) or '-'}",
            f"Own melds: {_melds_text(self.own_melds)}",
        ]
        for opponent in self.opponents:
            declaration = "yes" if opponent.declared else "no"
            lines.append(
                f"Opponent {opponent.seat}: river {format_river(list(opponent.river)) or '-'} | "
                f"melds {_melds_text(opponent.melds)} | declared {declaration} | "
                f"tenpai {opponent.tenpai_estimate:.2f} | fold {opponent.fold_estimate:.2f}"
            )
        lines.append(f"Visible counts: {format_tiles(self.visible_counts)}")
        return "\n".join(lines)


@dataclass(frozen=True)
class QuizGrade:
    position: QuizPosition
    best: EVRankEntry
    chosen: EVRankEntry
    ranked: tuple[EVRankEntry, ...]
    ev_delta: float
    rank_position: int | None
    verdict: str
    refined_sims: int = REFINE_SIMS  # budget the verdict was decided at (REFINE_SIMS or ESCALATE_SIMS)
    marginal: bool = False  # final ev_delta still hugs a verdict boundary

    @property
    def ev_loss(self) -> float:
        """Non-negative loss suitable for accumulating player scores."""
        return max(0.0, self.ev_delta)


def _tile_name(tile: int) -> str:
    counts = [0] * 34
    counts[tile] = 1
    return format_tiles(counts)


def _melds_text(melds: tuple[tuple[int, int, int], ...]) -> str:
    pieces: list[str] = []
    for meld in melds:
        counts = [0] * 34
        for tile in meld:
            counts[tile] += 1
        pieces.append(format_tiles(counts))
    return ";".join(pieces) or "-"


def _combined_counts(*groups: tuple[int, ...]) -> tuple[int, ...]:
    counts = [0] * 34
    for group in groups:
        for tile, count in enumerate(group):
            counts[tile] += count
    return tuple(counts)


def _river_counts(
    opponents: tuple[tuple[int, OpponentView], ...], excluded_seat: int, own_river: tuple[RiverEntry, ...]
) -> tuple[int, ...]:
    counts = [0] * 34
    for entry in own_river:
        counts[entry.tile] += 1
    for seat, view in opponents:
        if seat == excluded_seat:
            continue
        for entry in view.river:
            counts[entry if isinstance(entry, int) else entry.tile] += 1
    return tuple(counts)


def _opponents_from(snapshot: DecisionSnapshot) -> tuple[QuizOpponent, ...]:
    opponents: list[QuizOpponent] = []
    for seat, view in snapshot.opponents:
        frozen_river = tuple(entry if isinstance(entry, RiverEntry) else RiverEntry(entry) for entry in view.river)
        frozen_melds = tuple(view.melds)
        frozen_view = OpponentView(list(frozen_river), list(frozen_melds), view.declared_at)
        opponents.append(
            QuizOpponent(
                seat,
                frozen_river,
                frozen_melds,
                view.declared_at,
                tenpai_score(frozen_view, snapshot.turn).score,
                fold_score(frozen_view, _river_counts(snapshot.opponents, seat, snapshot.river)),
                dealer_streak=snapshot.dealer_streak if seat == DEALER_SEAT else 0,
                hand_count=view.hand_count,
            )
        )
    return tuple(opponents)


def _position_from(snapshot: DecisionSnapshot, seed: int) -> QuizPosition:
    hand = validate_counts(snapshot.hand)
    public = validate_counts(snapshot.public_counts)
    visible = _combined_counts(hand, public)
    if any(count > 4 for count in visible):
        raise AssertionError("observable tile copies were not conserved")
    return QuizPosition(
        seed=seed,
        seat=snapshot.seat,
        turn=snapshot.turn,
        drawn_tile=snapshot.drawn_tile,
        hand=hand,
        own_river=tuple(snapshot.river),
        own_melds=tuple(snapshot.melds),
        opponents=_opponents_from(snapshot),
        public_counts=public,
        visible_counts=visible,
        shanten=shanten(hand, len(snapshot.melds)),
        # Remaining draws from the actual live wall (one draw per four tiles),
        # not a turn-count proxy: this reflects who is close to running out.
        draws_remaining=max(1, ceil(snapshot.wall_remaining / 4)),
        wall_remaining=snapshot.wall_remaining,
        candidate_ev_gap=0.0,
        dealer_streak=snapshot.dealer_streak,
    )


def _evaluation_seed(position: QuizPosition) -> int:
    return position.seed * 1_000_003 + position.seat * 997 + position.turn


def _score_template(position: QuizPosition) -> WinValueContext:
    # The dealer earns an extra tai on a win (plus 連莊拉莊 per repeat), so the
    # human's own win value depends on whether this seat is the dealer.
    return WinValueContext(
        WinContext(
            winning_tile=0,
            dealer=position.is_dealer,
            dealer_streak=position.dealer_streak if position.is_dealer else 0,
        ),
        position.own_melds,
    )


@lru_cache(maxsize=256)
def _rank_cached(position: QuizPosition) -> tuple[EVRankEntry, ...]:
    return tuple(entry for entry in ev_rank(
        position.hand,
        [opponent.view() for opponent in position.opponents],
        position.public_counts,
        len(position.own_melds),
        position.draws_remaining,
        EV_SIMS,
        _evaluation_seed(position),
        _score_template(position),
        top_k=EV_TOP_K,
    ) if not entry.is_fold)


def _rank(position: QuizPosition) -> tuple[EVRankEntry, ...]:
    """Cheap EV ranking keyed independently of the display-only gap."""
    return _rank_cached(replace(position, candidate_ev_gap=0.0))


def best_discard(position: QuizPosition) -> int:
    """Return the cheap ranking's best discard, equal to ``grade().best.discard``."""
    return _rank(position)[0].discard


def _interesting(position: QuizPosition) -> bool:
    return (
        position.shanten <= SHANTEN_MAX
        and position.turn >= MIN_TURN
        and any(len(opponent.melds) >= 2 or opponent.declared or opponent.tenpai_estimate >= 0.4 for opponent in position.opponents)
    )


def generate_position(seed: int) -> QuizPosition:
    """Find the first filtered post-draw position at ``seed`` or later.

    Search order is deterministic: game seeds are tried as ``seed``,
    ``seed + 1``, and so on, up to :data:`MAX_ATTEMPTS` games.
    """
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise ValueError("seed must be an integer")
    for game_seed in range(seed, seed + MAX_ATTEMPTS):
        snapshots: list[DecisionSnapshot] = []
        play_game(game_seed, snapshot_hook=snapshots.append)
        for snapshot in snapshots:
            position = _position_from(snapshot, game_seed)
            if not _interesting(position):
                continue
            ranked = _rank(position)
            gap = ranked[0].net_ev - ranked[-1].net_ev
            if gap >= EV_GAP_MIN:
                return replace(position, candidate_ev_gap=gap)
    raise RuntimeError(f"no interesting quiz position found in {MAX_ATTEMPTS} seeded games")


def _refine(position: QuizPosition, tile: int, sims: int) -> EVRankEntry:
    """Re-estimate one discard at ``sims`` sims, sharing the ranking's CRN base
    seed so the best/chosen difference stays variance-reduced while its absolute
    Monte Carlo error shrinks ~``sqrt(EV_SIMS / sims)``."""
    return evaluate_discard(
        position.hand,
        tile,
        [opponent.view() for opponent in position.opponents],
        position.public_counts,
        len(position.own_melds),
        position.draws_remaining,
        sims,
        _evaluation_seed(position),
        _score_template(position),
    )


def grade(position: QuizPosition, chosen_tile: int) -> QuizGrade:
    """Grade a legal discard: rank candidates cheaply, decide the verdict from
    the rank-best and chosen candidates re-estimated at REFINE_SIMS, and only
    when that ev_delta sits on a verdict boundary re-estimate both at the higher
    ESCALATE_SIMS — so the extra budget is spent solely on borderline verdicts."""
    if not isinstance(chosen_tile, int) or isinstance(chosen_tile, bool) or not 0 <= chosen_tile < 34:
        raise ValueError("chosen tile must be an index from 0 through 33")
    if not position.hand[chosen_tile]:
        raise ValueError("chosen tile must be present in the hand")
    ranked = tuple(_rank(position))
    rank_position = next((index for index, entry in enumerate(ranked, start=1) if entry.discard == chosen_tile), None)
    # The verdict comes from two same-CRN-seed estimates; the ranked table keeps
    # its cheaper EV_SIMS values. Choosing the rank-best tile is an exact tie
    # (ev_delta 0), never escalated or flagged marginal.
    if chosen_tile == ranked[0].discard:
        best = chosen = _refine(position, ranked[0].discard, REFINE_SIMS)
        outcome = Verdict.exact_tie(REFINE_SIMS)
    else:
        def estimate(sims: int) -> tuple[float, tuple[EVRankEntry, EVRankEntry]]:
            best_entry = _refine(position, ranked[0].discard, sims)
            chosen_entry = _refine(position, chosen_tile, sims)
            return best_entry.net_ev - chosen_entry.net_ev, (best_entry, chosen_entry)

        best_post = list(position.hand)
        best_post[ranked[0].discard] -= 1
        chosen_post = list(position.hand)
        chosen_post[chosen_tile] -= 1
        gate_shanten = max(
            _cached_shanten(tuple(best_post), len(position.own_melds)),
            _cached_shanten(tuple(chosen_post), len(position.own_melds)),
        )
        outcome, (best, chosen) = resolve_adaptive(estimate, gate_shanten)
    return QuizGrade(
        position, best, chosen, ranked, outcome.ev_delta, rank_position,
        outcome.verdict, outcome.refined_sims, outcome.marginal,
    )


def _ev_table(entries: tuple[EVRankEntry, ...]) -> list[str]:
    lines = ["Discard  Net EV  P(win)  E[win value]  E[loss]"]
    for entry in entries:
        value = "-" if entry.mean_win_value is None else f"{entry.mean_win_value:.1f}"
        lines.append(f"{_tile_name(entry.discard):<7}  {entry.net_ev:>6.1f}  {entry.p_win:>6.3f}  {value:>12}  {entry.risk_ev:>7.1f}")
    return lines


def _dominant_difference(best: EVRankEntry, chosen: EVRankEntry) -> tuple[str, int | None, float]:
    components: list[tuple[str, int | None, float]] = [("win", None, best.attack_ev - chosen.attack_ev)]
    components.extend(("loss", index, chosen_loss - best_loss) for index, (best_loss, chosen_loss) in enumerate(zip(best.opponent_losses, chosen.opponent_losses)))
    return max(components, key=lambda component: abs(component[2]))


def _dominant_component(grade: QuizGrade) -> tuple[str, int | None, float]:
    return _dominant_difference(grade.best, grade.chosen)


def _is_declared_safe(position: QuizPosition, tile: int, opponent_index: int) -> bool:
    post = list(position.hand)
    post[tile] -= 1
    return "declared_safe" in danger_score(tile, position.opponents[opponent_index].view(), position.public_counts, tuple(post)).modifiers


def _component_lines(grade: QuizGrade) -> tuple[str, str]:
    if grade.ev_delta <= 0.0 or grade.best.discard == grade.chosen.discard:
        # Compare the cheap ranked best against the cheap runner-up: both come
        # from the same EV_SIMS ranking under one CRN seed, so their component
        # difference is variance-reduced. grade.best is refined at a different
        # budget, so pairing it with the cheap runner-up would mix precisions.
        best_entry, runner_up = grade.ranked[0], grade.ranked[1]
        kind, opponent_index, difference = _dominant_difference(best_entry, runner_up)
        if kind == "win":
            direction = "higher" if difference >= 0 else "lower"
            amount = abs(difference)
            best_text = f"{direction} win EV by {amount:.2f} tai than the next-ranked choice."
            chosen_text = f"matches the best's {direction} win-EV component."
        else:
            assert opponent_index is not None
            label = f"Opponent {grade.position.opponents[opponent_index].seat}"
            safe_best = _is_declared_safe(grade.position, grade.best.discard, opponent_index)
            if safe_best:
                best_text = f"SAFE(declared) vs {label} compared with the next-ranked choice."
                chosen_text = f"matches the best's SAFE(declared) read vs {label}."
            else:
                direction = "lower" if difference >= 0 else "higher"
                amount = abs(difference)
                best_text = f"{direction} expected loss vs {label} by {amount:.2f} tai than the next-ranked choice."
                chosen_text = f"matches the best's {direction}-loss component vs {label}."
        return f"Best {_tile_name(grade.best.discard)}: {best_text}", f"Chosen {_tile_name(grade.chosen.discard)}: {chosen_text}"
    kind, opponent_index, difference = _dominant_component(grade)
    if kind == "win":
        if difference >= 0:
            best_text = f"higher win EV by {difference:.2f} tai."
            chosen_text = f"lower win EV by {difference:.2f} tai."
        else:
            best_text = f"lower win EV by {-difference:.2f} tai, offset by safety."
            chosen_text = f"higher win EV by {-difference:.2f} tai, but weaker overall safety."
    else:
        assert opponent_index is not None
        label = f"Opponent {grade.position.opponents[opponent_index].seat}"
        safe_best = _is_declared_safe(grade.position, grade.best.discard, opponent_index)
        safe_chosen = _is_declared_safe(grade.position, grade.chosen.discard, opponent_index)
        if difference >= 0:
            best_text = f"SAFE(declared) vs {label}." if safe_best else f"lower expected loss vs {label} by {difference:.2f} tai."
            chosen_text = f"SAFE(declared) vs {label}." if safe_chosen else f"higher expected loss vs {label} by {difference:.2f} tai."
        else:
            best_text = f"SAFE(declared) vs {label}." if safe_best else f"higher expected loss vs {label} by {-difference:.2f} tai."
            chosen_text = f"SAFE(declared) vs {label}." if safe_chosen else f"lower expected loss vs {label} by {-difference:.2f} tai."
    return f"Best {_tile_name(grade.best.discard)}: {best_text}", f"Chosen {_tile_name(grade.chosen.discard)}: {chosen_text}"


def explain(grade: QuizGrade) -> str:
    """Render EV rankings followed by component-grounded teaching notes."""
    best_line, chosen_line = _component_lines(grade)
    return "\n".join([*_ev_table(grade.ranked), best_line, chosen_line])
