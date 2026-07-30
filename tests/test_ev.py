"""Known-answer tests for M5b tai-unit EV approximations."""

from dataclasses import replace
from math import comb
from random import Random

import pytest

from taimahjong.danger import OpponentView, parse_river
import taimahjong.ev as ev
from taimahjong.ev import (
    DRAW_VALUE,
    FOLD_HAZARD_CUTOFF,
    declaration_ev,
    estimate_win_value,
    ev_rank,
    opponent_hazards,
    remaining_draws,
    TileAccounting,
)
from taimahjong.reference_ev import (
    _policy_discard,
    evaluate_candidate,
    representative_reference_cases,
    standard_small_wall_state,
)
from taimahjong.rollout import CalibratedRonClaim, resolve_terminal
from taimahjong.scoring import EARTHLY_TAI, HEAVENLY_TAI, WinContext, score_hand
from taimahjong.selfplay import Player
from taimahjong.tiles import parse_tiles


TENPAI = parse_tiles("123m123p123s1112223z")
POST_DRAW = parse_tiles("123m123p123s11122233z")


def _tile(text: str) -> int:
    return next(index for index, count in enumerate(parse_tiles(text)) if count)


def _visible_with_opponent(opponent: OpponentView) -> tuple[int, ...]:
    counts = [0] * 34
    for entry in opponent.river:
        counts[entry if isinstance(entry, int) else entry.tile] += 1
    for meld in opponent.melds:
        for tile in meld:
            counts[tile] += 1
    return tuple(counts)


def _stand_pat_visible() -> tuple[int, ...]:
    visible = [4 - count for count in TENPAI]
    visible[29] = 0
    for tile in (4, 5, 6, 7, 8, 10, 11, 13, 14, 15, 16, 17, 19, 20, 22, 23, 24, 25, 26, 27, 28, 30, 31, 32, 33):
        visible[tile] -= 1
    return tuple(visible)


def test_part0_confirmed_scoring_totals():
    assert (HEAVENLY_TAI, EARTHLY_TAI) == (16, 8)
    dragons = parse_tiles("123m111555666777z22z")
    assert score_hand(dragons, (), WinContext(_tile("2z"))).total_tai == 19
    assert score_hand(dragons, (), WinContext(_tile("2z"), round_wind=_tile("1z"), seat_wind=_tile("1z"))).total_tai == 21
    winds = parse_tiles("111222333444555z66z")
    assert score_hand(winds, (), WinContext(_tile("6z"), self_draw=True)).total_tai == 48
    melds = [(0, 1, 2), (12, 13, 14), (24, 25, 26), (27, 27, 27), (31, 31, 31)]
    assert score_hand(parse_tiles("22z"), melds, WinContext(_tile("2z"))).total_tai == 4


def test_ev_rank_is_seed_deterministic_and_net_ev_is_signed_payment_mean():
    first = ev_rank(POST_DRAW, [], (0,) * 34, turns=3, sims=80, seed=19)
    assert first == ev_rank(POST_DRAW, [], (0,) * 34, turns=3, sims=80, seed=19)
    real = [entry for entry in first if not entry.is_fold]
    assert [entry.net_ev for entry in real] == sorted(
        (entry.net_ev for entry in real), reverse=True,
    )
    assert all(
        entry.net_ev == sum(entry.trial_values) / entry.sample_count
        for entry in first
    )
    assert all(
        entry.net_ev == pytest.approx(entry.attack_ev - entry.risk_ev)
        for entry in first
    )


def test_determinized_opponents_track_public_tenpai_state_and_conserve_tiles():
    hand = parse_tiles("123m456m789m11223p345s")
    river_tiles = (6, 7, 8, 14, 15, 16, 18, 19, 20, 21, 22, 23, 24, 25)

    def sampled_rate(opponent, samples=200):
        visible = _visible_with_opponent(opponent)
        acting_seat, seats, _ = ev._production_seats((opponent,), None)
        opponent_seat = next(
            seat for seat, view in enumerate(seats)
            if seat != acting_seat and view is opponent
        )
        tenpai = 0
        for index in range(samples):
            world = ev._sample_production_world(
                hand, visible, (opponent,), 8, None, 100_000 + index,
            )
            repeat = ev._sample_production_world(
                hand, visible, (opponent,), 8, None, 100_000 + index,
            )
            assert world == repeat
            concealed = world.players[opponent_seat].hand
            tenpai += ev._production_shanten(tuple(concealed), 0) == 0
            for tile in range(34):
                accounted = (
                    hand[tile]
                    + visible[tile]
                    + sum(
                        player.hand[tile]
                        for seat, player in enumerate(world.players)
                        if seat != acting_seat
                    )
                    + world.wall.count(tile)
                )
                assert accounted <= 4
        return tenpai / samples

    silent = OpponentView(list(river_tiles), [])
    threatening = OpponentView(
        [ev.RiverEntry(tile, "tsumogiri") for tile in river_tiles], [],
    )
    silent_rate = sampled_rate(silent)
    threatening_rate = sampled_rate(threatening)
    assert abs(silent_rate - ev.tenpai_score(silent, 14).score) < 0.08
    assert abs(threatening_rate - ev.tenpai_score(threatening, 14).score) < 0.08
    assert threatening_rate > silent_rate + 0.25

    declared = OpponentView(
        [ev.RiverEntry(6), ev.RiverEntry(7)], [], declared_at=1,
    )
    assert sampled_rate(declared, samples=32) == 1.0


def test_calibrated_ron_value_redeterminizes_non_tenpai_to_a_physical_win():
    hand = list(parse_tiles("147m147p147s1234567z"))
    available = [4 - count for count in hand]

    first = ev._ron_value_hand(hand, available, 0, Random(41))
    repeat = ev._ron_value_hand(hand, available, 0, Random(41))
    completed, winning_tile = first

    assert ev._production_shanten(tuple(hand), 0) > 0
    assert first == repeat
    assert ev._production_shanten(completed, 0) == -1
    assert completed[winning_tile] > 0
    assert score_hand(completed, (), WinContext(winning_tile)).value_units >= 4


def test_immediate_actor_deal_in_is_a_negative_terminal_payment():
    class CalibrationMustNotRun:
        def deal_in_probability(self, _danger_score):
            raise AssertionError("known rollout hands must remain physical")

    state = standard_small_wall_state(wall=())
    references = list(state.players)
    references[2] = replace(
        references[2],
        hand=parse_tiles("123456m123p123s333z6z"),
    )
    state = replace(state, players=tuple(references))
    players = tuple(
        Player(
            "attack",
            list(reference.hand),
            declared_at=reference.declared_at,
        )
        for reference in state.players
    )

    entries = ev_rank(
        state.players[state.acting_seat].hand,
        (),
        (0,) * 34,
        turns=0,
        sims=2,
        seed=11,
        calibration=CalibrationMustNotRun(),
        scheme=state.scheme,
        exhaustive=True,
        discard_policy=_policy_discard,
        rollout_players=players,
        rollout_wall=state.wall,
        acting_seat=state.acting_seat,
        next_seat=state.next_seat,
        dealer_streak=state.dealer_streak,
    )
    deal_in = next(
        entry for entry in entries
        if not entry.is_fold and entry.discard == _tile("6z")
    )

    assert deal_in.net_ev < 0
    assert deal_in.attack_ev == 0
    assert deal_in.risk_ev == -deal_in.net_ev
    assert len(set(deal_in.trial_values)) == 1


def test_determinized_rollout_has_physical_risk_without_calibration():
    class FixedCalibration:
        def deal_in_probability(self, _danger_score):
            return 1.0

    opponent = OpponentView(parse_river("9m"), [], None)
    uncalibrated = ev_rank(
        POST_DRAW,
        [opponent],
        parse_tiles("9m"),
        turns=0,
        sims=2,
        seed=17,
        exhaustive=True,
    )
    calibrated = ev_rank(
        POST_DRAW,
        [opponent],
        parse_tiles("9m"),
        turns=0,
        sims=2,
        seed=17,
        calibration=FixedCalibration(),
        exhaustive=True,
    )

    assert any(entry.risk_ev > 0.0 for entry in uncalibrated)
    assert all(entry.risk_ev > 0.0 for entry in calibrated)
    assert sum(entry.risk_ev for entry in calibrated) > sum(
        entry.risk_ev for entry in uncalibrated
    )
    assert all(
        entry.net_ev == entry.attack_ev - entry.risk_ev
        for entry in calibrated
    )


def test_calibrated_ron_is_one_zero_sum_terminal_payment():
    players = [Player("attack") for _ in range(4)]
    players[0].hand = list(POST_DRAW)
    terminal = resolve_terminal(
        players,
        (),
        0,
        1,
        _tile("1m"),
        _policy_discard,
        Random(1),
        calibrated_ron=lambda _players, _discarder, _tile: (
            CalibratedRonClaim(1, 1.0, 7),
        ),
    )

    assert terminal.kind == "opponent_ron"
    assert terminal.deltas == (-7, 7, 0, 0)
    assert terminal.value_units == 7
    assert terminal.ron_winners == (1,)


def test_calibrated_push_records_opening_discard_before_continuation():
    players = [Player("attack") for _ in range(4)]
    players[0].hand = list(POST_DRAW)
    for player in players[1:]:
        player.hand = list(TENPAI)
    snapshots = []

    def no_claims(current, _discarder, _tile):
        snapshots.append(tuple(len(player.river) for player in current))
        return ()

    resolve_terminal(
        players,
        (_tile("9m"),),
        0,
        1,
        _tile("1m"),
        lambda hand, _remaining, _melds: next(
            tile for tile, count in enumerate(hand) if count
        ),
        Random(1),
        calibrated_ron=no_claims,
    )

    assert snapshots[0][0] == 0
    assert snapshots[1][0] == 1


def test_calibrated_ron_hand_uses_physical_settlement_and_stays_zero_sum():
    players = [Player("attack") for _ in range(4)]
    players[0].hand = list(POST_DRAW)
    completed = parse_tiles("123456m123p123s333z66z")
    winning_tile = _tile("6z")
    hand_value = score_hand(
        completed, (), WinContext(winning_tile),
    ).value_units
    terminal = resolve_terminal(
        players,
        (),
        0,
        1,
        _tile("1m"),
        _policy_discard,
        Random(1),
        calibrated_ron=lambda _players, _discarder, _tile: (
            CalibratedRonClaim(
                1,
                1.0,
                winning_hand=completed,
                scoring_tile=winning_tile,
            ),
        ),
    )

    # Seat 0 is the dealer, so the physical ron settlement adds its bilateral
    # one-tai dealer leg to the non-dealer winner's hand value.
    assert terminal.deltas == (-(hand_value + 1), hand_value + 1, 0, 0)
    assert sum(terminal.deltas) == 0
    assert terminal.value_units == hand_value
    assert terminal.kind == "opponent_ron"
    assert terminal.ron_winners == (1,)


def test_declaration_dead_wait_is_zero_and_not_recommended():
    advice = declaration_ev(TENPAI, parse_tiles("333z"), turns=1, sims=20, seed=1)
    assert advice.declared.expected_win_ev == 0
    assert advice.declared.mean_value_units is None
    assert not advice.should_declare


def test_declaration_locked_branch_uses_exact_hypergeometric_and_migi_bonus():
    visible = _stand_pat_visible()
    turns = 5
    advice = declaration_ev(TENPAI, visible, turns=turns, sims=40, seed=3)
    pool = sum(4 - hand - seen for hand, seen in zip(TENPAI, visible))
    wins = 3
    expected = 1 - comb(pool - wins, turns) / comb(pool, turns)
    assert advice.declared.p_win == expected
    completed = list(TENPAI)
    completed[29] += 1
    no_migi = score_hand(tuple(completed), (), WinContext(29, self_draw=True)).value_units
    assert advice.declared.mean_value_units == no_migi + 8


def test_winning_trial_values_are_scored_as_self_draws():
    visible = _stand_pat_visible()
    estimate = estimate_win_value(TENPAI, turns=5, visible=visible, sims=1000, seed=4)
    completed = list(TENPAI)
    completed[29] += 1
    expected_value = score_hand(tuple(completed), (), WinContext(29, self_draw=True)).value_units
    assert estimate.p_win > 0
    assert estimate.mean_value_units == expected_value


def test_remaining_draws_uses_live_wall_and_four_seats():
    # 26 -> 14: the 48 tiles in three hidden opponent hands are not drawable.
    assert remaining_draws(POST_DRAW, (0,) * 34) == 14  # ceil((136 - 16 - 17 - 48) / 4)
    assert remaining_draws(POST_DRAW, parse_tiles("9999m")) == 13  # four public tiles also left the wall


@pytest.mark.parametrize(
    ("out_of_hands", "revealed_holdings", "expected_turns"),
    [
        ("9m", "", 14),
        ("9m", "111p", 14),  # the same opponent tiles merely become an open pon
        ("9m9p", "111p777s", 14),  # multiple opponents' chi/pon holdings
        ("9m9p12z", "111p777s8888m", 13),  # several melds plus a revealed kong
    ],
)
def test_live_wall_accounting_separates_discards_from_revealed_holdings(
    out_of_hands, revealed_holdings, expected_turns,
):
    accounting = TileAccounting(
        parse_tiles(out_of_hands) if out_of_hands else (0,) * 34,
        parse_tiles(revealed_holdings) if revealed_holdings else (0,) * 34,
    )
    assert remaining_draws(POST_DRAW, accounting) == expected_turns


def test_explicit_wall_and_derived_accounting_return_the_same_turns():
    accounting = TileAccounting(
        parse_tiles("9m9p12z"),
        parse_tiles("111p777s8888m"),
    )
    derived_live_wall = 136 - 16 - sum(POST_DRAW) - 3 * 16 - 4
    assert remaining_draws(POST_DRAW, accounting) == remaining_draws(
        POST_DRAW, accounting, wall_remaining=derived_live_wall,
    )


def test_opponent_tsumo_payment_is_included_in_actor_ev():
    case = next(
        case
        for case in representative_reference_cases()
        if case.strata.branch_character == "opponent-tsumo"
    )
    exact = {
        discard: evaluate_candidate(case.state, discard)
        for discard in case.state.legal_discards
    }
    target = next(
        discard
        for discard, evaluation in exact.items()
        if any(
            outcome.outcome.kind == "opponent_tsumo"
            and outcome.outcome.payment.deltas[case.state.acting_seat] < 0
            for outcome in evaluation.outcomes
        )
    )
    players = tuple(
        Player(
            "attack",
            list(reference.hand),
            declared_at=reference.declared_at,
        )
        for reference in case.state.players
    )
    entry = next(
        entry
        for entry in ev_rank(
            case.state.players[case.state.acting_seat].hand,
            (),
            (0,) * 34,
            turns=1,
            sims=24,
            seed=case.seed,
            scheme=case.state.scheme,
            exhaustive=True,
            discard_policy=_policy_discard,
            rollout_players=players,
            rollout_wall=case.state.wall,
            acting_seat=case.state.acting_seat,
            next_seat=case.state.next_seat,
            dealer_streak=case.state.dealer_streak,
        )
        if not entry.is_fold and entry.discard == target
    )

    assert entry.net_ev == float(exact[target].actor_ev)
    assert any(payment < 0 for payment in entry.trial_values)


def test_folded_opponent_contributes_zero_hazard():
    folding = OpponentView(parse_river("1234z"), [], None)
    safety_source = OpponentView(parse_river("1234z"), [], None)
    assert FOLD_HAZARD_CUTOFF == 0.60
    assert opponent_hazards([folding, safety_source])[0] == 0.0


def test_own_river_can_make_an_opponent_folded_for_survival_hazard():
    target = OpponentView(parse_river("1m1p1s"), [], None)
    own_river = parse_river("1m1p1s")

    assert opponent_hazards([target])[0] > 0.0
    assert opponent_hazards([target], own_river)[0] == 0.0


def test_production_rank_does_not_call_legacy_attack_composition(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("legacy attack estimator entered production rank")

    monkeypatch.setattr(ev, "_discounted_win_estimate", fail)
    monkeypatch.setattr(ev, "_entry_from_policy", fail)

    ranked = ev_rank(
        POST_DRAW, [], (0,) * 34, turns=1, sims=2, seed=19, exhaustive=True,
    )
    assert ranked


def test_crn_reuses_the_same_wall_order_for_every_candidate(monkeypatch):
    import taimahjong.rollout as rollout

    state = standard_small_wall_state()
    players = tuple(
        Player(
            "attack",
            list(reference.hand),
            declared_at=reference.declared_at,
        )
        for reference in state.players
    )
    choices = {}

    def fake_terminal(
        players, wall, acting_seat, next_seat, discard, discard_policy, rng,
        **kwargs,
    ):
        choices.setdefault(discard, []).append(
            None if not wall else rng.randrange(len(wall))
        )
        return rollout.TerminalResult(
            "draw", None, None, None, (0, 0, 0, 0), 0,
        )

    monkeypatch.setattr(rollout, "resolve_terminal", fake_terminal)
    ev_rank(
        state.players[state.acting_seat].hand,
        (),
        (0,) * 34,
        turns=1,
        sims=12,
        seed=47,
        exhaustive=True,
        discard_policy=_policy_discard,
        rollout_players=players,
        rollout_wall=state.wall,
        acting_seat=state.acting_seat,
        next_seat=state.next_seat,
    )

    schedules = [schedule[:12] for schedule in choices.values()]
    assert schedules
    assert all(schedule == schedules[0] for schedule in schedules[1:])


def test_fold_and_push_with_same_discard_have_separate_terminal_cache(monkeypatch):
    import taimahjong.rollout as rollout

    calls = []

    def fake_terminal(
        players, wall, acting_seat, next_seat, discard, discard_policy, rng,
        **kwargs,
    ):
        defensive = kwargs["acting_discard_policy"] is not None
        calls.append((discard, defensive))
        payment = -1 if defensive else 1
        deltas = [0, 0, 0, 0]
        deltas[acting_seat] = payment
        deltas[(acting_seat + 1) % 4] = -payment
        return rollout.TerminalResult(
            "draw", None, None, None, tuple(deltas), 0,
        )

    monkeypatch.setattr(rollout, "resolve_terminal", fake_terminal)
    ranked = ev_rank(
        POST_DRAW, [], (0,) * 34,
        turns=1, sims=2, seed=19, exhaustive=True,
    )
    fold = next(entry for entry in ranked if entry.is_fold)
    push = next(
        entry
        for entry in ranked
        if not entry.is_fold and entry.discard == fold.discard
    )

    assert calls.count((fold.discard, False)) == 2
    assert calls.count((fold.discard, True)) == 2
    assert push.trial_values == (1.0, 1.0)
    assert fold.trial_values == (-1.0, -1.0)


def test_legacy_draw_value_cannot_change_zero_payment_draw_terminals(monkeypatch):
    baseline = {entry.discard: entry for entry in ev_rank(POST_DRAW, [], (0,) * 34, turns=3, sims=80, seed=19) if not entry.is_fold}
    assert DRAW_VALUE == 0.0
    monkeypatch.setattr(ev, "DRAW_VALUE", 2.5)
    shifted = {entry.discard: entry for entry in ev_rank(POST_DRAW, [], (0,) * 34, turns=3, sims=80, seed=19) if not entry.is_fold}
    for tile, before in baseline.items():
        after = shifted[tile]
        assert after.trial_values == before.trial_values
        assert after.net_ev == before.net_ev


def test_defense_policy_is_last_labeled_and_has_an_executable_first_discard():
    opponent = OpponentView(parse_river("123456789m"), [], None)
    entries = ev_rank(POST_DRAW, [opponent], _visible_with_opponent(opponent), turns=3, sims=80, seed=19, top_k=10)
    fold = entries[-1]
    real = entries[:-1]
    assert fold.is_fold and fold.label == "defense_policy"
    assert fold.action_plan is not None
    assert fold.discard == fold.action_plan.first_discard
    assert POST_DRAW[fold.discard] > 0
    assert fold.action_plan.principles


def test_opponent_value_estimate_scales_with_dealer_streak():
    # Dealing into the dealer settles the bilateral premium, so the defender's
    # loss-magnitude read must be +1 for a dealer at streak 0 and +2 more per
    # repeat — the exact gradient that makes a streaking dealer scarier.
    river = parse_river("1m3m5p")
    peer = OpponentView(list(river), [], None)
    base = ev.opponent_value_estimate(peer)
    values = [
        ev.opponent_value_estimate(OpponentView(list(river), [], None, is_dealer=True, dealer_streak=streak))
        for streak in range(4)
    ]
    assert values[0] - base == ev.OPPONENT_DEALER_TAI
    assert [value - values[0] for value in values] == [0, 2, 4, 6]


def test_deal_in_ev_rises_against_dealer():
    # The risk term that drives folding must respond: the same danger tile is a
    # larger expected loss when the modeled opponent is the streaking dealer.
    opponent_peer = OpponentView(parse_river("123456789m"), [], None)
    opponent_dealer = OpponentView(parse_river("123456789m"), [], None, is_dealer=True, dealer_streak=2)
    tile = _tile("5s")
    visible = _visible_with_opponent(opponent_peer)
    peer_risk = ev.deal_in_ev(tile, opponent_peer, visible, POST_DRAW, None)
    dealer_risk = ev.deal_in_ev(tile, opponent_dealer, visible, POST_DRAW, None)
    assert dealer_risk > peer_risk
