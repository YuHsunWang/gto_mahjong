"""Interactive trainer generator: termination, determinism, and call decisions."""

import pytest

from taimahjong.quiz import grade
from taimahjong.trainer import (
    KongOption,
    TrainerCallDecision,
    TrainerDecision,
    TrainerKongDecision,
    TrainerOutcome,
    _outcome,
    _human_kong_options,
    evaluate_call,
    evaluate_kong,
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


def test_call_ev_credits_dealer_streak_for_dealer_seat():
    from dataclasses import replace

    from taimahjong.ev import estimate_win_value
    from taimahjong.quiz import _evaluation_seed, _score_template
    from taimahjong.trainer import _pass_ev

    decision = _first_call()
    assert decision is not None
    position = replace(decision.position, dealer_streak=2)
    streak_decision = replace(decision, position=position)
    base = _evaluation_seed(position)
    expected = estimate_win_value(
        position.hand, position.draws_remaining,
        len(position.own_melds) + len(position.own_kongs), position.public_counts,
        200, base, _score_template(position),
    ).expected_win_ev

    assert _pass_ev(streak_decision, base, 200) == expected
    assert _score_template(position).context.dealer_streak == 2


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


# --- M6: self-draw kong decisions ---

def test_kong_options_are_legal_and_shanten_safe():
    """Only four-in-hand 暗槓 and a pon's drawn fourth 加槓 may be offered, and
    either must preserve or improve shanten."""
    from taimahjong.selfplay import Player, _cached_shanten, _declared

    concealed = Player("attack")
    for tile, count in ((0, 1), (5, 1), (9, 3), (11, 1), (16, 4), (17, 2), (21, 1), (22, 1), (23, 1), (24, 1), (29, 1)):
        concealed.hand[tile] = count
    options = _human_kong_options(concealed)
    assert options == (KongOption("concealed", 16, 3),)
    assert options[0].post_shanten <= _cached_shanten(tuple(concealed.hand), _declared(concealed))

    added = Player("attack")
    added.melds.append((9, 9, 9))
    for tile, count in ((1, 1), (3, 1), (4, 1), (8, 3), (9, 1), (12, 1), (15, 1), (18, 1), (24, 2), (25, 1), (26, 1)):
        added.hand[tile] = count
    assert _human_kong_options(added) == (KongOption("added", 9, 3),)

    unsound = Player("attack")
    for tile, count in enumerate((4, 3, 3, 3, 3, 1)):
        unsound.hand[tile] = count
    assert _human_kong_options(unsound) == ()


def test_kong_verdict_is_adaptive_and_deterministic(monkeypatch):
    """Kong grading keeps the call grader's CRN/adaptive-budget contract rather
    than assigning a fixed, noisy grade to a replacement-draw choice."""
    from dataclasses import replace
    import taimahjong.trainer as trainer
    from taimahjong.selfplay import _cached_shanten

    position = next(play_trainer(1)).position
    hand = [0] * 34
    for tile, count in ((0, 1), (5, 1), (9, 3), (11, 1), (16, 4), (17, 2), (21, 1), (22, 1), (23, 1), (24, 1), (29, 1)):
        hand[tile] = count
    hand_tuple = tuple(hand)
    position = replace(
        position, hand=hand_tuple, own_melds=(), public_counts=(0,) * 34,
        visible_counts=hand_tuple, shanten=_cached_shanten(hand_tuple, 0), draws_remaining=1,
    )
    decision = TrainerKongDecision(position, (KongOption("concealed", 16, 3),))
    monkeypatch.setattr(trainer.quiz, "EV_SIMS", 1)
    monkeypatch.setattr(trainer.quiz, "REFINE_SIMS", 2)
    monkeypatch.setattr(trainer.quiz, "ESCALATE_SIMS", 3)
    calls = []
    original = trainer.quiz.resolve_adaptive

    def traced(estimate, shanten):
        calls.append(shanten)
        return original(estimate, shanten)

    monkeypatch.setattr(trainer.quiz, "resolve_adaptive", traced)
    a = evaluate_kong(decision, seed=41)
    b = evaluate_kong(decision, seed=41)
    choice = 0 if a.best_index is None else None
    assert a == b
    assert a.verdict_for(choice) == b.verdict_for(choice)
    assert calls == [max(position.shanten, 3), max(position.shanten, 3)]


def test_trainer_ev_preserves_concealed_kong_for_menqing_tai():
    from dataclasses import replace

    from taimahjong.ev import _score_value
    from taimahjong.quiz import _score_template
    from taimahjong.tiles import parse_tiles

    position = next(play_trainer(1)).position
    hand = parse_tiles("234567m234p234s55s")
    kong_tile = next(tile for tile, count in enumerate(parse_tiles("1z")) if count)
    win_tile = next(tile for tile, count in enumerate(parse_tiles("2s")) if count)
    position = replace(position, hand=hand, own_melds=(), own_kongs=((kong_tile, True),))

    # play_trainer(1) seat 0 is the dealer, and _score_value scores as a self-draw,
    # so preserving the concealed kong's 門清 gives 莊家1 + 門清1 + 自摸1 = 3 tai =>
    # 底3台1 value 6. If the kong were disguised as an exposed meld (the bug), 門清
    # would be lost, dropping this to 5 — so 6 is exactly what proves the fix.
    assert _score_value(hand, win_tile, _score_template(position)) == 6


def test_human_added_kong_can_be_robbed_and_skip_reaches_discard(monkeypatch):
    """A selected 加槓 checks 搶槓 before mutation; declining it simply reaches
    the trainer's normal discard prompt."""
    import taimahjong.trainer as trainer

    forced = (KongOption("added", 0, 0),)
    monkeypatch.setattr(trainer, "_human_kong_options", lambda player: forced)
    monkeypatch.setattr(trainer, "_settlement", lambda *args, **kwargs: ((-5, 5, 0, 0), 5))

    skipped = play_trainer(1)
    item = next(skipped)
    assert isinstance(item, TrainerKongDecision)
    assert isinstance(skipped.send(None), TrainerDecision)

    monkeypatch.setattr(trainer, "_robbing_winner", lambda players, konger, tile: 1)
    robbed = play_trainer(1)
    item = next(robbed)
    assert isinstance(item, TrainerKongDecision)
    outcome = robbed.send(0)
    assert outcome.robbed_kong is True
    assert outcome.human_dealt_in is True
    assert outcome.headline == "被搶槓…"


# --- M4: 連莊 state machine and dealer-aware trainer positions ---

def test_streak_increments_on_dealer_win_and_draw():
    # 流局連莊 + a dealer win both keep the dealer on seat 0 and grow the streak;
    # the human's seat is unchanged. This is the rule the trainer chains between
    # hands, so it is pinned at the pure-function level.
    won = _outcome("tsumo", 0, None, human_seat=2, deltas=(3, -1, -1, -1), turns=10, dealer_streak=1)
    assert won.next_dealer_streak == 2 and won.next_human_seat == 2
    drawn = _outcome("draw", None, None, human_seat=2, deltas=(0, 0, 0, 0), turns=18, dealer_streak=0)
    assert drawn.next_dealer_streak == 1 and drawn.next_human_seat == 2


def test_streak_resets_and_rotates_human_on_dealer_loss():
    # A non-dealer win passes dealership; the engine keeps the dealer on seat 0
    # and instead rotates the human one seat downstream, resetting the streak —
    # this is how the player comes to sit in each relation to the dealer.
    out = _outcome("ron", 1, 2, human_seat=3, deltas=(0, 5, -5, 0), turns=12, dealer_streak=3)
    assert out.next_dealer_streak == 0 and out.next_human_seat == 0


def test_streak_raises_dealer_opponent_value_in_a_trainer_position():
    # Sitting as 莊的下家 (human seat 1), the dealer is an opponent. The same
    # first position at streak 0 vs 2 must price that dealer opponent higher, so
    # the trainer actually teaches the 連莊 premium rather than only displaying it.
    from taimahjong.ev import opponent_value_estimate

    def first_dealer_view(streak):
        gen = play_trainer(1, human_seat=1, dealer_streak=streak)
        item = next(gen)
        while not isinstance(item, TrainerDecision):
            item = gen.send(None if isinstance(item, (TrainerCallDecision, TrainerKongDecision)) else _discard_drawn(item.position))
        dealer = next(opponent for opponent in item.position.opponents if opponent.seat == 0)
        return dealer.view()

    view0, view2 = first_dealer_view(0), first_dealer_view(2)
    assert view0.dealer_streak == 0 and view2.dealer_streak == 2
    assert opponent_value_estimate(view2) > opponent_value_estimate(view0)
