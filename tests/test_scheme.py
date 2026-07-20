"""底/台 scoring-scheme coverage.

The scheme is a payout convention layered on a hand's tai. These tests lock
three things: the value math, that the house default (底3台1) reproduces the
legacy ``value_units`` and pre-scheme EV exactly, and that a different scheme
actually flows through the EV ranking (so it can change a decision).
"""

import pytest

from taimahjong.ev import ev_rank, opponent_value_estimate
from taimahjong.danger import OpponentView, parse_river
from taimahjong.scoring import (
    BASE_UNITS,
    DEFAULT_SCHEME,
    SCHEME_3_1,
    SCHEME_5_2,
    ScoringScheme,
    WinContext,
    score_hand,
)
from taimahjong.tiles import parse_tiles


def test_value_math_and_presets():
    assert SCHEME_3_1.value(0) == 3 and SCHEME_3_1.value(4) == 7  # 底3 + 1×台
    assert SCHEME_5_2.value(0) == 5 and SCHEME_5_2.value(4) == 13  # 底5 + 2×台
    assert DEFAULT_SCHEME == SCHEME_3_1
    assert SCHEME_3_1.base_units == BASE_UNITS and SCHEME_3_1.tai_units == 1


@pytest.mark.parametrize("bad", [(-1, 1), (3, 0), (3, -2)])
def test_scheme_rejects_out_of_range(bad):
    with pytest.raises(ValueError):
        ScoringScheme(*bad)


def test_default_scheme_reproduces_legacy_value_units():
    # 底3台1 must equal the pre-scheme value_units property for any hand, so
    # self-play/calibration (which still call value_units) are unaffected.
    hand = parse_tiles("123m111555666777z22z")
    result = score_hand(hand, (), WinContext(winning_tile=33, self_draw=True))
    assert result.value_in(SCHEME_3_1) == result.value_units
    assert result.value_in(SCHEME_5_2) == 5 + 2 * result.total_tai


def test_opponent_value_scales_with_scheme():
    # A declared opponent is worth 8 tai; the deal-in magnitude must rescale
    # with the scheme exactly like a win's value does.
    declared = OpponentView(parse_river("1234z"), [], 0)
    assert opponent_value_estimate(declared, SCHEME_3_1) == 3 + 8
    assert opponent_value_estimate(declared, SCHEME_5_2) == 5 + 2 * 8


def _top_net(entries):
    return next(entry.net_ev for entry in entries if not entry.is_fold)


def test_ev_rank_default_matches_scheme_3_1_and_differs_for_5_2():
    # Same hand, same CRN seed: 底3台1 must be identical to the pre-scheme
    # default, and 底5台2 must move the numbers (proving the scheme threads all
    # the way through the ranking, not just the score tool).
    hand = parse_tiles("123456789m11234p567s")
    kwargs = dict(turns=8, sims=60, seed=11)
    default = ev_rank(hand, [], (0,) * 34, **kwargs)
    three_one = ev_rank(hand, [], (0,) * 34, scheme=SCHEME_3_1, **kwargs)
    five_two = ev_rank(hand, [], (0,) * 34, scheme=SCHEME_5_2, **kwargs)
    assert _top_net(default) == pytest.approx(_top_net(three_one))
    assert _top_net(five_two) != pytest.approx(_top_net(three_one))
    # 底5台2 weights tai more heavily, so a positive win EV grows.
    assert _top_net(five_two) > _top_net(three_one)
