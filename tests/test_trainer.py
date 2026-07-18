"""Interactive trainer generator: termination, determinism, and call decisions."""

import pytest

from taimahjong.quiz import grade
from taimahjong.trainer import (
    TrainerCallDecision,
    TrainerDecision,
    TrainerOutcome,
    evaluate_call,
    play_trainer,
)


def _discard_drawn(position):
    if position.drawn_tile is not None and position.hand[position.drawn_tile]:
        return position.drawn_tile
    return next(tile for tile, count in enumerate(position.hand) if count)


def _play(seed, pick, call_pick=lambda decision: None):
    """Drive one game; ``pick`` chooses each discard, ``call_pick`` each call
    (default: pass every call, so the human stays concealed)."""
    gen = play_trainer(seed, human_seat=0)
    item = next(gen)
    decisions = []
    while not isinstance(item, TrainerOutcome):
        if isinstance(item, TrainerDecision):
            decisions.append(item.position)
            item = gen.send(pick(item.position))
        else:
            item = gen.send(call_pick(item))
    return decisions, item


def test_trainer_games_terminate_with_valid_outcomes():
    for seed in range(1, 16):
        decisions, outcome = _play(seed, _discard_drawn)  # passes all calls
        assert outcome.outcome in {"tsumo", "ron", "draw"}
        assert outcome.turns > 0
        # Passing every call keeps the human concealed: no declared meld.
        for position in decisions:
            assert position.own_melds == ()
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
    if result.verdict == "best":
        assert result.ev_delta <= 0.0
    else:
        assert result.ev_delta > 0.0


def test_trainer_rejects_illegal_discard():
    gen = play_trainer(5, human_seat=0)
    position = next(gen).position  # dealer's first action is always a discard
    missing = next(tile for tile, count in enumerate(position.hand) if count == 0)
    with pytest.raises(ValueError):
        gen.send(missing)


def test_trainer_validates_arguments():
    with pytest.raises(ValueError):
        next(play_trainer(1, human_seat=4))
    with pytest.raises(ValueError):
        next(play_trainer(True))


# --- Phase 2a: pon/chi call decisions ---

def _first_call(seed_range=range(1, 20)):
    """Return the first TrainerCallDecision offered, passing everything before."""
    for seed in seed_range:
        gen = play_trainer(seed, human_seat=0)
        item = next(gen)
        while not isinstance(item, TrainerOutcome):
            if isinstance(item, TrainerCallDecision):
                return item
            item = gen.send(_discard_drawn(item.position) if isinstance(item, TrainerDecision) else None)
    return None


def test_trainer_offers_and_evaluates_call_decisions():
    decision = _first_call()
    assert decision is not None, "expected a call decision in seeds 1-19"
    assert decision.options, "a call decision must offer at least one legal call"
    assert all(option.kind in {"pon", "chi"} for option in decision.options)
    # Every consumed tile is actually held; the meld includes the offered tile.
    for option in decision.options:
        for consumed in option.consumed:
            assert decision.position.hand[consumed] > 0
        assert decision.offered_tile in option.meld
    evaluation = evaluate_call(decision)
    assert len(evaluation.option_evs) == len(decision.options)
    assert evaluation.best_index is None or 0 <= evaluation.best_index < len(decision.options)
    result = evaluation.verdict_for(None)
    assert result.verdict in {"best", "good", "inaccuracy", "mistake"}
    # Verdict rests on best/chosen re-estimated (escalated near a boundary); like
    # the discard grader, ev_delta <= 0 exactly when chosen is the best action.
    assert (result.ev_delta <= 0.0) == (result.verdict == "best")


def test_evaluate_call_is_deterministic_and_refines_best_and_chosen():
    decision = _first_call()
    assert decision is not None, "expected a call decision in seeds 1-19"
    a = evaluate_call(decision)
    b = evaluate_call(decision)
    # Fixed CRN base seed -> identical refined best and verdict for passing.
    assert a.best_ev == b.best_ev
    assert a.best_index == b.best_index
    assert a.verdict_for(None) == b.verdict_for(None)
    # Choosing the best action yields exactly zero delta (same refined estimate).
    best = a.verdict_for(a.best_index)
    assert best.verdict == "best" and best.ev_delta == 0.0 and best.marginal is False


def test_call_ev_credits_dealer_tai_for_dealer_seat():
    # Seat 0 is the dealer, so a win there is worth an extra 莊 tai. The call-EV
    # path (pass/option value) must credit it just like the discard grader does;
    # a regression that drops the dealer flag understates the human's win EV and
    # biases the pass-vs-call ev_delta that decides borderline call verdicts.
    from taimahjong.ev import WinValueContext, estimate_win_value
    from taimahjong.quiz import _evaluation_seed
    from taimahjong.scoring import WinContext
    from taimahjong.trainer import _pass_ev

    decision = _first_call()
    assert decision is not None, "expected a call decision in seeds 1-19"
    position = decision.position
    assert position.is_dealer, "human_seat 0 is the dealer in the trainer model"
    base = _evaluation_seed(position)

    def win_ev(dealer: bool) -> float:
        return estimate_win_value(
            position.hand, position.draws_remaining, len(position.own_melds),
            position.public_counts, 200, base,
            WinValueContext(WinContext(winning_tile=0, dealer=dealer), position.own_melds),
        ).expected_win_ev

    dealer_ev, non_dealer_ev = win_ev(True), win_ev(False)
    assert dealer_ev > non_dealer_ev, "this position has win chance, so the 莊 tai must move the EV"
    assert _pass_ev(decision, base, 200) == dealer_ev


def test_taking_a_call_opens_hand_and_game_terminates():
    for seed in range(1, 20):
        gen = play_trainer(seed, human_seat=0)
        item = next(gen)
        took = saw_open = False
        while not isinstance(item, TrainerOutcome):
            if isinstance(item, TrainerCallDecision) and not took:
                took = True
                item = gen.send(0)  # take the first offered call
            elif isinstance(item, TrainerDecision):
                if took and item.position.own_melds:
                    saw_open = True
                item = gen.send(_discard_drawn(item.position))
            else:
                item = gen.send(None)
        if took:
            assert saw_open, "after calling, a later discard view should show the meld"
            assert item.outcome in {"tsumo", "ron", "draw"}
            return
    pytest.fail("no call was offered to take in seeds 1-19")


def test_trainer_rejects_invalid_call_choice():
    for seed in range(1, 20):
        gen = play_trainer(seed, human_seat=0)
        item = next(gen)
        while not isinstance(item, TrainerOutcome):
            if isinstance(item, TrainerCallDecision):
                with pytest.raises(ValueError):
                    gen.send(999)  # out-of-range option index
                return
            item = gen.send(_discard_drawn(item.position) if isinstance(item, TrainerDecision) else None)
    pytest.fail("no call decision in seeds 1-19")
