"""Known-answer tests for M5b tai-unit EV approximations."""

from math import comb

from taimahjong.danger import OpponentView, parse_river
from taimahjong.ev import declaration_ev, estimate_win_value, ev_rank
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
    assert [entry.attack_ev for entry in first] == sorted((entry.attack_ev for entry in first), reverse=True)
    assert all(entry.risk_ev == 0 for entry in first)


def test_declared_safe_discard_dominates_equal_efficiency_risky_discard():
    # 3m and 2p both leave shanten 0 with four ukeire; only 3m is discarded
    # after the opponent's declaration and therefore hard-excluded by M4a+.
    opponent = OpponentView(parse_river("1m3m"), [], declared_at=0)
    visible = _visible_with_opponent(opponent)
    entries = ev_rank(POST_DRAW, [opponent], visible, turns=1, sims=400, seed=11, top_k=10)
    by_tile = {entry.discard: entry for entry in entries}
    safe, risky = by_tile[_tile("3m")], by_tile[_tile("2p")]
    assert safe.risk_ev == 0
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
