"""Known-answer tests for M5b tai-unit EV approximations."""

from math import comb

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
from taimahjong.scoring import EARTHLY_TAI, HEAVENLY_TAI, WinContext, score_hand
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


def test_ev_rank_is_seed_deterministic_and_attack_only_orders_by_attack_ev():
    first = ev_rank(POST_DRAW, [], (0,) * 34, turns=3, sims=80, seed=19)
    assert first == ev_rank(POST_DRAW, [], (0,) * 34, turns=3, sims=80, seed=19)
    real = [entry for entry in first if not entry.is_fold]
    assert [entry.attack_ev for entry in real] == sorted(
        (entry.attack_ev for entry in real),
        reverse=True,
    )
    assert all(entry.risk_ev == 0 for entry in first)


def test_declared_safe_discard_dominates_equal_efficiency_risky_discard():
    # 3m and 2p both leave shanten 0 with four ukeire; only 3m is discarded
    # after the opponent's declaration and therefore hard-excluded by M4a+.
    opponent = OpponentView(parse_river("1m3m"), [], declared_at=0)
    visible = _visible_with_opponent(opponent)
    entries = ev_rank(POST_DRAW, [opponent], visible, turns=1, sims=400, seed=11, top_k=10)
    by_tile = {entry.discard: entry for entry in entries}
    safe, risky = by_tile[_tile("3m")], by_tile[_tile("2p")]
    # The first 3m is genbutsu; total policy risk can still be non-zero after
    # the next draw because MJ-007 now prices the policy's subsequent discard.
    assert risky.risk_ev > 0
    assert safe.net_ev > risky.net_ev


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


def test_opponent_hazard_survival_strictly_reduces_attack_ev_and_net_ev():
    opponent = OpponentView(parse_river("123456789m123456789p"), [], None)
    visible = _visible_with_opponent(opponent)
    safe = {entry.discard: entry for entry in ev_rank(POST_DRAW, [], visible, turns=3, sims=80, seed=19, top_k=10) if not entry.is_fold}
    threatened = {
        entry.discard: entry
        for entry in ev_rank(POST_DRAW, [opponent], visible, turns=3, sims=80, seed=19, top_k=10)
        if not entry.is_fold
    }
    assert all(threatened[tile].attack_ev < entry.attack_ev for tile, entry in safe.items() if entry.attack_ev > 0)
    assert all(threatened[tile].net_ev < entry.net_ev for tile, entry in safe.items() if entry.attack_ev > 0)


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


def test_zero_hazard_attack_ev_is_exactly_the_pre_m7_value():
    entries = [entry for entry in ev_rank(POST_DRAW, [], (0,) * 34, turns=3, sims=80, seed=19) if not entry.is_fold]
    sample = entries[0]
    post = list(POST_DRAW)
    post[sample.discard] -= 1
    attack_visible = [0] * 34
    attack_visible[sample.discard] = 1
    previous = estimate_win_value(tuple(post), 3, visible=attack_visible, sims=80, seed=19)
    assert sample.attack_ev == previous.expected_win_ev
    assert sample.survival_adjusted_p_win == previous.p_win


def test_ev_attack_pool_marks_each_candidate_discard_visible(monkeypatch):
    hand = parse_tiles("123m123p123s11122z333z")
    captured = {}

    def fake_estimate(
        counts16, turns, melds_declared, visible, sims, seed,
        context_template, survival, scheme, discard_policy=None,
    ):
        discard = next(tile for tile in range(34) if counts16[tile] < hand[tile])
        captured[discard] = visible
        return ev.WinValueEstimate(0.0, None, 0.0)

    monkeypatch.setattr(ev, "_discounted_win_estimate", fake_estimate)
    ev_rank(hand, [], (0,) * 34, turns=1, sims=1, seed=1, top_k=34)

    assert captured[29][29] == 1
    assert sum(captured[29]) == 1


def test_draw_value_shifts_net_ev_by_exact_draw_term(monkeypatch):
    baseline = {entry.discard: entry for entry in ev_rank(POST_DRAW, [], (0,) * 34, turns=3, sims=80, seed=19) if not entry.is_fold}
    assert DRAW_VALUE == 0.0
    monkeypatch.setattr(ev, "DRAW_VALUE", 2.5)
    shifted = {entry.discard: entry for entry in ev_rank(POST_DRAW, [], (0,) * 34, turns=3, sims=80, seed=19) if not entry.is_fold}
    for tile, before in baseline.items():
        after = shifted[tile]
        assert after.net_ev - before.net_ev == after.p_draw * 2.5


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
