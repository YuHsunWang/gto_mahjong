"""底/台 scoring-scheme coverage.

The scheme is a payout convention layered on a hand's tai. These tests lock
three things: the value math, that the house default (底3台1) reproduces the
legacy ``value_units`` and pre-scheme EV exactly, and that a different scheme
actually flows through the EV ranking (so it can change a decision).
"""

import subprocess
import sys

import pytest

from taimahjong.config import GameConfig
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
from taimahjong.selfplay import Player, _settlement
from taimahjong.tiles import parse_tiles


def test_value_math_and_presets():
    assert SCHEME_3_1.value(0) == 3 and SCHEME_3_1.value(4) == 7  # 底3 + 1×台
    assert SCHEME_5_2.value(0) == 5 and SCHEME_5_2.value(4) == 13  # 底5 + 2×台
    assert DEFAULT_SCHEME == SCHEME_3_1
    assert SCHEME_3_1.base_units == BASE_UNITS and SCHEME_3_1.tai_units == 1
    assert GameConfig.from_id("3-1").scheme == SCHEME_3_1
    assert GameConfig.from_id("5-2").scheme == SCHEME_5_2


def test_game_config_rejects_non_product_scheme():
    with pytest.raises(ValueError, match="presets"):
        GameConfig(ScoringScheme(4, 1))
    with pytest.raises(ValueError, match="3/1 or 5/2"):
        GameConfig.from_pair(6, 2)


@pytest.mark.parametrize("bad", [(-1, 1), (3, 0), (3, -2)])
def test_scheme_rejects_out_of_range(bad):
    with pytest.raises(ValueError):
        ScoringScheme(*bad)


def test_default_scheme_reproduces_legacy_value_units():
    # 底3台1 must equal the pre-scheme value_units property for any hand, so
    # explicitly wired default-scheme paths retain the legacy unit math.
    hand = parse_tiles("123m111555666777z22z")
    result = score_hand(hand, (), WinContext(winning_tile=33, self_draw=True))
    assert result.value_in(SCHEME_3_1) == result.value_units
    assert result.value_in(SCHEME_5_2) == 5 + 2 * result.total_tai


@pytest.mark.parametrize(
    ("scheme", "expected"),
    [(SCHEME_3_1, 7), (SCHEME_5_2, 13)],
)
def test_known_four_tai_hand_is_7_or_13_in_core_settlement_and_cli(scheme, expected):
    melds = [
        (0, 1, 2),
        (12, 13, 14),
        (24, 25, 26),
        (27, 27, 27),
        (31, 31, 31),
    ]
    hand = parse_tiles("22z")
    tile = next(index for index, count in enumerate(parse_tiles("2z")) if count)
    score = score_hand(hand, melds, WinContext(tile))
    assert score.total_tai == 4
    assert score.value_in(scheme) == expected

    players = [Player("attack") for _ in range(4)]
    players[1].melds = melds
    deltas, value = _settlement(
        "ron", 1, 2, players, hand, tile, scheme=scheme,
    )
    assert value == expected
    assert deltas == (0, expected, -expected, 0)

    result = subprocess.run(
        [
            sys.executable,
            "-B",
            "-m",
            "taimahjong",
            "22z",
            "--score",
            "--my-melds",
            "123m;456p;789s;111z;555z",
            "--win-tile",
            "2z",
            "--scheme",
            GameConfig(scheme).scheme_id,
        ],
        cwd=".",
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert f"= {expected} units" in result.stdout
    assert f"Scheme: {GameConfig(scheme).scheme_id}" in result.stdout


@pytest.mark.parametrize(
    ("scheme", "expected"),
    [
        (
            SCHEME_3_1,
            {
                "ron_peer": ((0, 6, -6, 0), 6),
                "ron_dealer_leg": ((-11, 11, 0, 0), 6),
                "tsumo_non_dealer": ((-12, 26, -7, -7), 7),
                "ron_dealer_win": ((11, 0, -11, 0), 11),
                "tsumo_dealer_win": ((36, -12, -12, -12), 12),
            },
        ),
        (
            SCHEME_5_2,
            {
                "ron_peer": ((0, 11, -11, 0), 11),
                "ron_dealer_leg": ((-21, 21, 0, 0), 11),
                "tsumo_non_dealer": ((-23, 49, -13, -13), 13),
                "ron_dealer_win": ((21, 0, -21, 0), 21),
                "tsumo_dealer_win": ((69, -23, -23, -23), 23),
            },
        ),
    ],
)
def test_payment_leg_goldens_conserve_four_players_in_both_schemes(scheme, expected):
    hand = parse_tiles("123456789m123p11678s")
    tile = next(index for index, count in enumerate(parse_tiles("6s")) if count)
    players = [Player("attack") for _ in range(4)]
    actual = {
        "ron_peer": _settlement("ron", 1, 2, players, hand, tile, scheme=scheme),
        "ron_dealer_leg": _settlement(
            "ron", 1, 0, players, hand, tile, dealer_streak=2, scheme=scheme,
        ),
        "tsumo_non_dealer": _settlement(
            "tsumo", 1, None, players, hand, tile, dealer_streak=2, scheme=scheme,
        ),
        "ron_dealer_win": _settlement(
            "ron", 0, 2, players, hand, tile, dealer_streak=2, scheme=scheme,
        ),
        "tsumo_dealer_win": _settlement(
            "tsumo", 0, None, players, hand, tile, dealer_streak=2, scheme=scheme,
        ),
    }
    assert actual == expected
    assert all(sum(deltas) == 0 for deltas, _ in actual.values())


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
