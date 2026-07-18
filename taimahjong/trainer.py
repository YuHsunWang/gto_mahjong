"""Interactive, step-through self-play for "play a hand to completion" training.

A generator drives one seeded game and pauses (``yield``) at every discard the
human seat must make, handing back a :class:`~taimahjong.quiz.QuizPosition` the
caller can render and grade with the existing quiz tooling.  The caller sends
the chosen tile back with ``generator.send(tile)`` and the game continues,
resolving opponents with the same bot policies and rules as
:func:`taimahjong.selfplay.play_game`.

Phase 1 scope (deliberate, documented):
- The human seat plays concealed: it may win by self-draw or by ron, but it
  does not pon/chi (so every human discard follows a draw and always has a
  full observable snapshot).  Human call decisions and their EV are Phase 2.
- Opponents call normally.  No kong, no flowers, no guo-shui — identical to the
  self-play simplifications.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from random import Random

from . import quiz  # budget/adaptive constants read live (quiz.*) so tests can monkeypatch them
from .ev import WinValueContext, estimate_win_value, evaluate_discard, ev_rank
from .quiz import EV_TOP_K, QuizPosition, _evaluation_seed, _position_from
from .scoring import WinContext
from .selfplay import (
    Player,
    RiverEntry,
    _best_call,
    _cached_shanten,
    _call_options,
    _choose_discard,
    _decision_snapshot,
    _settlement,
)


@dataclass(frozen=True)
class TrainerDecision:
    """A discard the human seat must make; render/grade via quiz tooling."""

    position: QuizPosition


@dataclass(frozen=True)
class CallOption:
    """One legal pon/chi the human could declare on an opponent's discard."""

    kind: str  # "pon" or "chi"
    meld: tuple[int, int, int]  # the completed 3-tile set (sorted)
    consumed: tuple[int, int]  # the two tiles taken from the concealed hand


@dataclass(frozen=True)
class TrainerCallDecision:
    """A pon/chi the human MAY declare on an opponent's discard (or pass).

    ``position`` reuses the quiz view for rendering (its ``drawn_tile`` carries
    the callable tile, relabelled by the UI). ``options`` are the legal calls;
    the caller sends back an int index to call that option, or None/-1 to pass.
    """

    position: QuizPosition
    offered_tile: int
    discarder: int
    options: tuple[CallOption, ...]


@dataclass(frozen=True)
class CallVerdict(quiz.Verdict):
    """A call choice's :class:`~taimahjong.quiz.Verdict` plus the best action's EV
    at the verdict's final budget (for display consistency)."""

    best_ev: float


@dataclass(frozen=True)
class CallEvaluation:
    """EV of each call option plus passing, GTO-Wizard style.

    ``pass_ev`` and ``option_evs`` are the cheap EV_SIMS estimates that rank the
    actions and populate the table. ``best_ev`` is the *best* action re-estimated
    at REFINE_SIMS; :meth:`verdict_for` re-estimates the chosen action at the
    same budget and CRN base seed, escalating both to ESCALATE_SIMS when the
    ev_delta lands on a verdict boundary — the same adaptive scheme as the
    discard grader. ``decision``/``base_seed`` are carried so the chosen action
    can be refined on demand."""

    pass_ev: float
    option_evs: tuple[float, ...]  # cheap EV_SIMS estimates, aligned with options
    best_index: int | None  # index into options, or None if passing ranks best
    best_ev: float  # best action re-estimated at ``best_ev_sims``
    best_ev_sims: int  # budget that produced ``best_ev``
    decision: "TrainerCallDecision" = field(compare=False, repr=False)
    base_seed: int = 0
    # Each option's cheap-best post-call discard; refine re-estimates just that
    # single discard (not the whole post-call ranking), so a call refine costs
    # the same one-discard budget as a discard refine.
    option_best_discards: tuple[int | None, ...] = ()

    def _action_ev(self, choice: int | None, sims: int) -> float:
        """Re-estimate one action (pass or an option) at ``sims`` under the seed."""
        if choice is None:
            return _refine_pass(self.decision, self.base_seed, sims)
        return _refine_option(
            self.decision, self.decision.options[choice],
            self.option_best_discards[choice], self.base_seed, sims,
        )

    def _action_shanten(self, choice: int | None) -> int:
        """Shanten of the hand refined for this action — post-call for an option
        (a call strictly advances the hand), the concealed hand for a pass. The
        cost gate keys on this, not the pre-call hand."""
        if choice is None:
            return self.decision.position.shanten
        post, melds = _post_call(self.decision.position, self.decision.options[choice])
        return _cached_shanten(post, len(melds))

    def verdict_for(self, choice: int | None) -> CallVerdict:
        """Grade a call choice via the shared adaptive resolver: the best and
        chosen actions re-estimated at REFINE_SIMS, escalated to ESCALATE_SIMS
        only when the ev_delta hugs a boundary and both actions are near tenpai."""
        if choice == self.best_index:
            # Same action, same CRN seed: an exact tie, never escalated.
            tie = quiz.Verdict.exact_tie(self.best_ev_sims)
            return CallVerdict(tie.verdict, tie.ev_delta, tie.refined_sims, tie.marginal, self.best_ev)

        def estimate(sims: int) -> tuple[float, float]:
            # Reuse only the budget that actually produced self.best_ev.
            best_ev = self.best_ev if sims == self.best_ev_sims else self._action_ev(self.best_index, sims)
            return best_ev - self._action_ev(choice, sims), best_ev

        # Gate on whichever refined hand is farther from tenpai (a call advances
        # the hand, so the pre-call shanten would under-count), keeping both
        # actions' escalation cheap.
        gate_shanten = max(self._action_shanten(self.best_index), self._action_shanten(choice))
        outcome, best_ev = quiz.resolve_adaptive(estimate, gate_shanten)
        return CallVerdict(outcome.verdict, outcome.ev_delta, outcome.refined_sims, outcome.marginal, best_ev)


@dataclass(frozen=True)
class TrainerOutcome:
    """Terminal state of a trainer game, from the human seat's perspective."""

    outcome: str  # "tsumo", "ron", or "draw"
    human_won: bool
    human_dealt_in: bool
    winner: int | None
    discarder: int | None
    point_delta: int  # human seat's signed value-unit change
    turns: int

    @property
    def headline(self) -> str:
        if self.outcome == "draw":
            return "流局"
        if self.human_won:
            return "自摸胡牌！" if self.outcome == "tsumo" else "榮和胡牌！"
        if self.human_dealt_in:
            return "放槍了…"
        who = "自摸" if self.outcome == "tsumo" else "被別家胡"
        return f"對手{who}（座位 {self.winner}）"


def _ron_winner(current: int, tile: int, players: list[Player]) -> int | None:
    """Closest downstream seat that wins on ``tile`` (includes the human)."""
    for offset in range(1, 4):
        index = (current + offset) % 4
        hand = players[index].hand
        completed = tuple(hand[:tile] + [hand[tile] + 1] + hand[tile + 1:])
        if _cached_shanten(completed, len(players[index].melds)) == -1:
            return index
    return None


def _outcome(outcome: str, winner: int | None, discarder: int | None,
             human_seat: int, deltas: tuple[int, int, int, int], turns: int) -> TrainerOutcome:
    return TrainerOutcome(
        outcome=outcome,
        human_won=winner == human_seat,
        human_dealt_in=outcome == "ron" and discarder == human_seat,
        winner=winner,
        discarder=discarder,
        point_delta=deltas[human_seat],
        turns=turns,
    )


def _human_call_options(player: Player, tile: int, is_next_seat: bool) -> tuple[CallOption, ...]:
    """All legal pon (any seat) and chi (next seat only) calls on ``tile``.

    Reuses selfplay's shanten-improving call enumeration, so only calls that
    strictly advance the hand are offered — passing always remains a choice.
    """
    options: list[CallOption] = []
    for removed, meld, _ in _call_options(player, tile, chi=False):
        options.append(CallOption("pon", meld, removed))
    if is_next_seat:
        for removed, meld, _ in _call_options(player, tile, chi=True):
            options.append(CallOption("chi", meld, removed))
    return tuple(options)


def _apply_call(player: Player, discarder: Player, option: CallOption) -> None:
    """Mutate state for a declared call: consume hand tiles, add the meld."""
    discarder.river.pop()
    for consumed in option.consumed:
        player.hand[consumed] -= 1
    player.melds.append(option.meld)


def _post_call(position: QuizPosition, option: CallOption) -> tuple[tuple[int, ...], tuple[tuple[int, int, int], ...]]:
    """The concealed hand and meld set after declaring ``option`` (hand opens)."""
    post = list(position.hand)
    for consumed in option.consumed:
        post[consumed] -= 1
    return tuple(post), position.own_melds + (option.meld,)


def _pass_ev(decision: TrainerCallDecision, base_seed: int, sims: int) -> float:
    """Self-draw win EV of keeping the concealed hand (the 'pass' pseudo-option)."""
    position = decision.position
    return estimate_win_value(
        position.hand, position.draws_remaining, len(position.own_melds),
        position.public_counts, sims, base_seed,
        WinValueContext(WinContext(winning_tile=0, dealer=position.is_dealer), position.own_melds),
    ).expected_win_ev


def _refine_pass(decision: TrainerCallDecision, base_seed: int, sims: int) -> float:
    """Re-estimate the pass action at ``sims`` under the shared CRN seed."""
    return _pass_ev(decision, base_seed, sims)


def _option_rank(decision: TrainerCallDecision, option: CallOption, base_seed: int, sims: int) -> tuple[float, int | None]:
    """Cheap best post-call discard EV of declaring ``option``, and its tile."""
    position = decision.position
    post, melds = _post_call(position, option)
    ranked = ev_rank(
        post, [opponent.view() for opponent in position.opponents], position.public_counts,
        len(melds), position.draws_remaining, sims, base_seed,
        WinValueContext(WinContext(winning_tile=0, dealer=position.is_dealer), melds), top_k=EV_TOP_K,
    )
    playable = [entry for entry in ranked if not entry.is_fold]
    if not playable:
        return 0.0, None
    best = max(playable, key=lambda entry: entry.net_ev)
    return best.net_ev, best.discard


def _refine_option(decision: TrainerCallDecision, option: CallOption, discard: int | None, base_seed: int, sims: int) -> float:
    """Re-estimate declaring ``option`` at ``sims`` by re-scoring just its
    cheap-best post-call discard — the single deciding candidate, exactly as the
    discard grader refines one tile rather than re-ranking the whole set."""
    if discard is None:
        return 0.0
    position = decision.position
    post, melds = _post_call(position, option)
    entry = evaluate_discard(
        post, discard, [opponent.view() for opponent in position.opponents],
        position.public_counts, len(melds), position.draws_remaining,
        sims, base_seed, WinValueContext(WinContext(winning_tile=0, dealer=position.is_dealer), melds),
    )
    return entry.net_ev


def evaluate_call(decision: TrainerCallDecision, seed: int | None = None) -> CallEvaluation:
    """EV of each call option and of passing, under shared random numbers.

    Two-stage, mirroring the discard grader: every action is ranked cheaply at
    EV_SIMS (CRN base seed) to pick the best and each option's best post-call
    discard, then only the two actions a verdict depends on — the best and the
    chosen (via :meth:`CallEvaluation.verdict_for`) — are re-estimated at
    REFINE_SIMS under the same seed by re-scoring that one deciding discard. This
    cuts verdict noise ~sqrt(EV_SIMS/REFINE_SIMS) without paying the high budget
    on every option.

    Approximations (documented, Phase 2a): calling opens the hand (loses 門清
    and the migi option) and lets the player act now; its value is the best
    post-call discard EV via ``ev_rank``. Passing keeps the concealed hand; its
    value is the self-draw win EV of continuing, with no immediate discard risk.
    Tempo and the pass branch's future deal-in risk are not fully modelled.
    """
    base_seed = _evaluation_seed(decision.position) if seed is None else seed

    pass_ev = _pass_ev(decision, base_seed, quiz.EV_SIMS)
    ranked = [_option_rank(decision, option, base_seed, quiz.EV_SIMS) for option in decision.options]
    option_evs = tuple(ev for ev, _ in ranked)
    option_best_discards = tuple(tile for _, tile in ranked)

    best_option_ev = max(option_evs, default=float("-inf"))
    best_index = option_evs.index(best_option_ev) if best_option_ev > pass_ev else None
    if best_index is None:
        best_ev = _refine_pass(decision, base_seed, quiz.REFINE_SIMS)
    else:
        best_ev = _refine_option(decision, decision.options[best_index], option_best_discards[best_index], base_seed, quiz.REFINE_SIMS)
    return CallEvaluation(pass_ev, option_evs, best_index, best_ev, quiz.REFINE_SIMS, decision, base_seed, option_best_discards)


def play_trainer(
    seed: int,
    human_seat: int = 0,
    policies: tuple[str, str, str, str] = ("attack", "cautious", "attack", "cautious"),
):
    """Generator: yields a discard or call decision at each human choice point.

    Yields :class:`TrainerDecision` (a discard; send back a tile index) or
    :class:`TrainerCallDecision` (a pon/chi you may declare on an opponent's
    discard; send back an option index to call, or None/-1 to pass).

    Protocol::

        gen = play_trainer(seed)
        item = next(gen)
        while not isinstance(item, TrainerOutcome):
            if isinstance(item, TrainerDecision):
                item = gen.send(chosen_tile)     # tile index in hand
            else:                                # TrainerCallDecision
                item = gen.send(option_index)    # int to call, None to pass
    """
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise ValueError("seed must be an integer")
    if human_seat not in range(4):
        raise ValueError("human_seat must be 0-3")

    rng = Random(seed)
    tiles = [tile for tile in range(34) for _ in range(4)]
    rng.shuffle(tiles)
    players = [Player(policy) for policy in policies]
    for _ in range(16):
        for player in players:
            player.hand[tiles.pop()] += 1
    dead = [tiles.pop() for _ in range(16)]  # noqa: F841 - dead wall, kept out of play
    wall = tiles
    current = 0
    needs_draw = True
    any_call = False
    actions = 0

    while True:
        actions += 1
        assert actions < 1000, "trainer game did not terminate"
        player = players[current]
        drawn_tile: int | None = None

        if needs_draw:
            if not wall:
                deltas, _ = _settlement("draw", None, None, players, None, None)
                yield _outcome("draw", None, None, human_seat, deltas, actions)
                return
            drawn_tile = wall.pop()
            player.hand[drawn_tile] += 1
            if _cached_shanten(tuple(player.hand), len(player.melds)) == -1:
                winning_hand = tuple(player.hand)
                deltas, _ = _settlement("tsumo", current, None, players, winning_hand, drawn_tile)
                yield _outcome("tsumo", current, None, human_seat, deltas, actions)
                return

        if current == human_seat and not player.declared:
            position = _position_from(_decision_snapshot(current, drawn_tile, players, len(wall)), seed)
            chosen = yield TrainerDecision(position)
            if not (isinstance(chosen, int) and not isinstance(chosen, bool) and 0 <= chosen < 34):
                raise ValueError("sent discard must be a tile index 0-33")
            if player.hand[chosen] <= 0:
                raise ValueError("sent discard is not in the hand")
            tile = chosen
        else:
            tile, _ = _choose_discard(current, drawn_tile, players)

        origin = "tsumogiri" if drawn_tile == tile else "tedashi"
        player.hand[tile] -= 1
        turn = player.discards + 1
        true_tenpai = _cached_shanten(tuple(player.hand), len(player.melds)) == 0
        player.river.append(RiverEntry(tile, origin))
        player.discards += 1
        if not any_call and not player.declared and turn <= 2 and true_tenpai:
            player.declared_at = len(player.river) - 1

        winner = _ron_winner(current, tile, players)
        if winner is not None:
            winning_hand = list(players[winner].hand)
            winning_hand[tile] += 1
            deltas, _ = _settlement("ron", winner, current, players, tuple(winning_hand), tile)
            yield _outcome("ron", winner, current, human_seat, deltas, actions)
            return

        # A call may be declared on this discard unless the discarder is a
        # migi-declared player. Priority: pon (closest downstream) beats chi
        # (next seat only). The human is offered their call when it has
        # priority; passing hands the tile to the next-priority opponent.
        caller: int | None = None
        selected: tuple[tuple[int, int], tuple[int, int, int]] | None = None
        human_option: CallOption | None = None
        if not player.declared:
            def priority(seats: set[int]) -> tuple[int, str] | None:
                for off in range(1, 4):
                    idx = (current + off) % 4
                    if idx in seats and _call_options(players[idx], tile, chi=False):
                        return idx, "pon"
                idx = (current + 1) % 4
                if idx in seats and _call_options(players[idx], tile, chi=True):
                    return idx, "chi"
                return None

            eligible = {s for s in range(4) if s != current and not players[s].declared}
            top = priority(eligible)
            if top is not None and top[0] == human_seat:
                is_next = (current + 1) % 4 == human_seat
                options = _human_call_options(players[human_seat], tile, is_next)
                if options:
                    position = _position_from(_decision_snapshot(human_seat, tile, players, len(wall)), seed)
                    choice = yield TrainerCallDecision(position, tile, current, options)
                    if choice is None or choice == -1:
                        top = priority(eligible - {human_seat})
                    elif isinstance(choice, int) and not isinstance(choice, bool) and 0 <= choice < len(options):
                        human_option = options[choice]
                    else:
                        raise ValueError("sent call choice must be an option index or None to pass")
                else:
                    top = priority(eligible - {human_seat})
            if human_option is None and top is not None and top[0] != human_seat:
                idx, kind = top
                selected = _best_call(players[idx], tile, chi=(kind == "chi"))
                if selected:
                    caller = idx

        if human_option is not None:
            _apply_call(players[human_seat], players[current], human_option)
            any_call = True
            current = human_seat
            needs_draw = False
        elif caller is not None and selected is not None:
            removed, meld = selected
            players[current].river.pop()
            players[caller].hand[removed[0]] -= 1
            players[caller].hand[removed[1]] -= 1
            players[caller].melds.append(meld)
            any_call = True
            current = caller
            needs_draw = False
        else:
            current = (current + 1) % 4
            needs_draw = True
