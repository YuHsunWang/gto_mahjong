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

from dataclasses import dataclass
from random import Random

from .quiz import QuizPosition, _position_from
from .selfplay import (
    Player,
    RiverEntry,
    _best_call,
    _cached_shanten,
    _choose_discard,
    _decision_snapshot,
    _settlement,
)


@dataclass(frozen=True)
class TrainerDecision:
    """A discard the human seat must make; render/grade via quiz tooling."""

    position: QuizPosition


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


def play_trainer(
    seed: int,
    human_seat: int = 0,
    policies: tuple[str, str, str, str] = ("attack", "cautious", "attack", "cautious"),
):
    """Generator: yields a :class:`TrainerDecision` at each human discard.

    Protocol::

        gen = play_trainer(seed)
        item = next(gen)
        while isinstance(item, TrainerDecision):
            item = gen.send(chosen_tile)   # a tile present in the hand
        # item is a TrainerOutcome
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
            position = _position_from(_decision_snapshot(current, drawn_tile, players), seed)
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

        # Opponents may pon (priority, closest downstream) or chi (next seat).
        # The human seat never calls in Phase 1, so it is skipped here.
        caller: int | None = None
        selected = None
        if not player.declared:
            for offset in range(1, 4):
                index = (current + offset) % 4
                if index == human_seat or players[index].declared:
                    continue
                selected = _best_call(players[index], tile, False)
                if selected:
                    caller = index
                    break
            if caller is None:
                index = (current + 1) % 4
                if index != human_seat and not players[index].declared:
                    selected = _best_call(players[index], tile, True)
                    if selected:
                        caller = index
        if caller is not None and selected is not None:
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
