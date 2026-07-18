"""Interactive trainer generator: determinism, termination, and Phase-1 rules."""

import pytest

from taimahjong.quiz import grade
from taimahjong.trainer import TrainerDecision, TrainerOutcome, play_trainer


def _play(seed, pick):
    """Drive one trainer game; ``pick(position) -> tile`` chooses each discard."""
    gen = play_trainer(seed, human_seat=0)
    item = next(gen)
    decisions = []
    while isinstance(item, TrainerDecision):
        decisions.append(item.position)
        item = gen.send(pick(item.position))
    assert isinstance(item, TrainerOutcome)
    return decisions, item


def _discard_drawn(position):
    if position.hand[position.drawn_tile]:
        return position.drawn_tile
    return next(tile for tile, count in enumerate(position.hand) if count)


def test_trainer_games_terminate_with_valid_outcomes():
    for seed in range(1, 16):
        decisions, outcome = _play(seed, _discard_drawn)
        assert outcome.outcome in {"tsumo", "ron", "draw"}
        assert outcome.turns > 0
        # Human plays concealed in Phase 1: never any declared meld for seat 0.
        for position in decisions:
            assert position.own_melds == ()
        # A dealt-in outcome must be a ron the human discarded into.
        if outcome.human_dealt_in:
            assert outcome.outcome == "ron"


def test_trainer_is_deterministic_for_a_fixed_policy():
    a_decisions, a_outcome = _play(7, _discard_drawn)
    b_decisions, b_outcome = _play(7, _discard_drawn)
    assert [p.hand for p in a_decisions] == [p.hand for p in b_decisions]
    assert a_outcome == b_outcome


def test_trainer_positions_are_gradeable():
    decisions, _ = _play(3, _discard_drawn)
    assert decisions, "seed 3 should present at least one human decision"
    result = grade(decisions[0], _discard_drawn(decisions[0]))
    assert result.verdict in {"best", "good", "inaccuracy", "mistake"}
    # The ranked quiz shortlist can omit a legal chosen discard; grade() then
    # evaluates it directly and classifies it as best if its EV is higher.
    if result.verdict == "best":
        assert result.ev_delta <= 0.0
    else:
        assert result.ev_delta > 0.0


def test_trainer_rejects_illegal_discard():
    gen = play_trainer(5, human_seat=0)
    position = next(gen).position
    missing = next(tile for tile, count in enumerate(position.hand) if count == 0)
    with pytest.raises(ValueError):
        gen.send(missing)


def test_trainer_validates_arguments():
    with pytest.raises(ValueError):
        next(play_trainer(1, human_seat=4))
    with pytest.raises(ValueError):
        next(play_trainer(True))
