"""Seeded teaching positions for probability-grounded discard practice.

Only table information visible to the player is retained.  Hidden opponent
hands remain inside self-play and never become part of a :class:`QuizPosition`.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from functools import lru_cache

from .danger import OpponentView, RiverEntry, danger_score, fold_score, format_river, tenpai_score
from .ev import EVRankEntry, WinValueContext, deal_in_ev, estimate_win_value, ev_rank
from .scoring import WinContext
from .selfplay import DecisionSnapshot, play_game
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
EV_SIMS = 24
EV_TOP_K = 5


@dataclass(frozen=True)
class QuizOpponent:
    """One opponent's public state, with no concealed-hand field."""

    seat: int
    river: tuple[RiverEntry, ...]
    melds: tuple[tuple[int, int, int], ...]
    declared_at: int | None
    tenpai_estimate: float
    fold_estimate: float

    @property
    def declared(self) -> bool:
        return self.declared_at is not None

    def view(self) -> OpponentView:
        return OpponentView(list(self.river), list(self.melds), self.declared_at)


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
    candidate_ev_gap: float

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
        draws_remaining=max(1, 18 - snapshot.turn),
        candidate_ev_gap=0.0,
    )


def _evaluation_seed(position: QuizPosition) -> int:
    return position.seed * 1_000_003 + position.seat * 997 + position.turn


def _score_template(position: QuizPosition) -> WinValueContext:
    return WinValueContext(WinContext(winning_tile=0), position.own_melds)


@lru_cache(maxsize=256)
def _rank(position: QuizPosition) -> tuple[EVRankEntry, ...]:
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


def _evaluate_discard(position: QuizPosition, tile: int) -> EVRankEntry:
    post = list(position.hand)
    post[tile] -= 1
    attack = estimate_win_value(
        tuple(post),
        position.draws_remaining,
        len(position.own_melds),
        position.public_counts,
        EV_SIMS,
        _evaluation_seed(position) + tile * 1_000_003,
        _score_template(position),
    )
    losses = tuple(deal_in_ev(tile, opponent.view(), position.public_counts, tuple(post), None) for opponent in position.opponents)
    risk = sum(losses)
    return EVRankEntry(tile, attack.p_win, attack.mean_value_units, attack.expected_win_ev, losses, risk, attack.expected_win_ev - risk)


def grade(position: QuizPosition, chosen_tile: int) -> QuizGrade:
    """Evaluate a legal discard with the same deterministic budget as generation."""
    if not isinstance(chosen_tile, int) or isinstance(chosen_tile, bool) or not 0 <= chosen_tile < 34:
        raise ValueError("chosen tile must be an index from 0 through 33")
    if not position.hand[chosen_tile]:
        raise ValueError("chosen tile must be present in the hand")
    ranked = tuple(_rank(position))
    best = ranked[0]
    rank_position = next((index for index, entry in enumerate(ranked, start=1) if entry.discard == chosen_tile), None)
    chosen = ranked[rank_position - 1] if rank_position is not None else _evaluate_discard(position, chosen_tile)
    ev_delta = best.net_ev - chosen.net_ev
    if ev_delta <= 0.0:
        verdict = "best"
    elif ev_delta < GOOD_DELTA:
        verdict = "good"
    elif ev_delta < 1.0:
        verdict = "inaccuracy"
    else:
        verdict = "mistake"
    return QuizGrade(position, best, chosen, ranked, ev_delta, rank_position, verdict)


def _ev_table(entries: tuple[EVRankEntry, ...]) -> list[str]:
    lines = ["Discard  Net EV  P(win)  E[win value]  E[loss]"]
    for entry in entries:
        value = "-" if entry.mean_win_value is None else f"{entry.mean_win_value:.2f}"
        lines.append(f"{_tile_name(entry.discard):<7}  {entry.net_ev:>6.2f}  {entry.p_win:>6.3f}  {value:>12}  {entry.risk_ev:>7.2f}")
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
    if grade.best.discard == grade.chosen.discard:
        runner_up = grade.ranked[1]
        kind, opponent_index, difference = _dominant_difference(grade.best, runner_up)
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
