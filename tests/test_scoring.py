"""Known-answer tests for the tai scoring module."""

import pytest

from taimahjong.scoring import WinContext, score_hand
from taimahjong.tiles import parse_tiles


def _names(result):
    return {name for name, _ in result.items}


def _tile(text):
    counts = parse_tiles(text)
    return next(index for index, count in enumerate(counts) if count)


def test_full_flush_all_triplets_five_concealed_self_draw():
    hand = parse_tiles("111222333444555m66m")
    context = WinContext(winning_tile=_tile("6m"), self_draw=True)
    result = score_hand(hand, (), context)
    names = _names(result)
    assert "full flush (清一色)" in names
    assert "all triplets (碰碰胡)" in names
    assert "five concealed triplets (五暗刻)" in names
    assert "concealed hand (門清)" in names
    assert "self-draw (自摸)" in names
    # waits were 3m/6m/7m, so no single-wait tai; total 8+4+8+1+1
    assert "single wait (獨聽)" not in names
    assert result.total_tai == 22
    assert result.value_units == 25


def test_pinghu_all_runs_ron():
    hand = parse_tiles("123456789m123p11678s")
    context = WinContext(winning_tile=_tile("6s"))
    result = score_hand(hand, (), context)
    assert _names(result) == {"all runs (平胡)", "concealed hand (門清)"}
    assert result.total_tai == 3


def test_ron_completed_triplet_is_not_concealed():
    hand = parse_tiles("111222333m44455p567s")
    ron = score_hand(hand, (), WinContext(winning_tile=_tile("4p")))
    assert "three concealed triplets (三暗刻)" in _names(ron)
    assert ron.total_tai == 3  # 門清 1 + 三暗刻 2

    tsumo = score_hand(hand, (), WinContext(winning_tile=_tile("4p"), self_draw=True))
    assert "four concealed triplets (四暗刻)" in _names(tsumo)
    assert tsumo.total_tai == 7  # 門清 1 + 自摸 1 + 四暗刻 5


def test_all_called_single_wait_ron():
    melds = [(0, 1, 2), (12, 13, 14), (24, 25, 26), (27, 27, 27), (31, 31, 31)]
    hand = parse_tiles("22z")
    result = score_hand(hand, melds, WinContext(winning_tile=_tile("2z")))
    names = _names(result)
    assert "all called (全求人)" in names
    assert "single wait (獨聽)" in names
    assert "dragon triplets x1 (三元牌刻)" in names
    assert "concealed hand (門清)" not in names
    assert result.total_tai == 4


def test_migi_dealer_streak_stack_on_pinghu():
    hand = parse_tiles("123456789m123p11678s")
    context = WinContext(
        winning_tile=_tile("6s"), dealer=True, dealer_streak=2, migi_declared=True
    )
    result = score_hand(hand, (), context)
    # 平胡2 + 門清1 + migi8 + 莊1 + 連2拉2=4
    assert result.total_tai == 16


def test_big_winds_all_honors():
    hand = parse_tiles("111222333444555z66z")
    context = WinContext(winning_tile=_tile("6z"), self_draw=True)
    result = score_hand(hand, (), context)
    names = _names(result)
    assert "big four winds (大四喜)" in names
    assert "all honors (字一色)" in names
    assert "all triplets (碰碰胡)" in names
    assert "five concealed triplets (五暗刻)" in names
    assert "single wait (獨聽)" in names
    # 16+16+4+8+1(白刻)+1(門清)+1(自摸)+1(獨聽)
    assert result.total_tai == 48


def test_big_dragons_half_flush():
    hand = parse_tiles("123m111555666777z22z")
    result = score_hand(hand, (), WinContext(winning_tile=_tile("2z")))
    names = _names(result)
    assert "big three dragons (大三元)" in names
    assert "dragon triplets x3 (三元牌刻)" not in names
    assert "half flush (混一色)" in names
    assert "four concealed triplets (四暗刻)" in names
    # 8+4+5+1(門清)+1(獨聽); 大三元 replaces its component dragon triplets.
    assert result.total_tai == 19


def test_round_and_seat_wind_tai():
    hand = parse_tiles("123m111555666777z22z")
    context = WinContext(winning_tile=_tile("2z"), round_wind=_tile("1z"), seat_wind=_tile("1z"))
    result = score_hand(hand, (), context)
    names = _names(result)
    assert "round wind (圈風)" in names
    assert "seat wind (門風)" in names
    assert "dragon triplets x3 (三元牌刻)" not in names
    assert result.total_tai == 21


def test_validation_errors():
    with pytest.raises(ValueError):
        score_hand(parse_tiles("123456789m123p1167s"), (), WinContext(winning_tile=_tile("6s")))
    with pytest.raises(ValueError):
        score_hand(parse_tiles("123456789m123p11677s"), (), WinContext(winning_tile=_tile("6s")))
    with pytest.raises(ValueError):
        WinContext(winning_tile=0, heavenly=True, earthly=True)
    with pytest.raises(ValueError):
        WinContext(winning_tile=0, dealer_streak=1)
    with pytest.raises(ValueError):
        score_hand(parse_tiles("123456789m123p11678s"), (), WinContext(winning_tile=_tile("9p")))


def test_max_decomposition_is_chosen():
    # 123123123m can be read as runs; triplet reading scores higher with 111222333m
    hand = parse_tiles("111222333m456p55s678s")
    result = score_hand(hand, (), WinContext(winning_tile=_tile("5s"), self_draw=True))
    assert "three concealed triplets (三暗刻)" in _names(result)


# --- Phase 2b Stage 1: kong scoring ---

def test_kong_bloom_on_self_draw_adds_one_tai():
    # 4 concealed runs + pair + one concealed kong; win by self-draw on the wall.
    hand = parse_tiles("234567m234p234s55s")  # 14 tiles = 4 sets + pair
    context = WinContext(winning_tile=_tile("2s"), self_draw=True, kong_bloom=True)
    result = score_hand(hand, (), context, kongs=((_tile("1z"), True),))
    names = _names(result)
    assert "kong bloom (槓上開花)" in names
    assert "concealed hand (門清)" in names  # a concealed kong keeps 門清
    assert "self-draw (自摸)" in names
    assert result.total_tai == 3  # 門清1 + 自摸1 + 槓上開花1 (waits 2s/5s, no 獨聽)


def test_robbing_the_kong_on_ron_adds_one_tai_and_open_kong_breaks_menqing():
    hand = parse_tiles("234567m234p234s55s")
    context = WinContext(winning_tile=_tile("2s"), robbed_kong=True)
    result = score_hand(hand, (), context, kongs=((_tile("1z"), False),))  # open kong
    names = _names(result)
    assert "robbing the kong (搶槓)" in names
    assert "concealed hand (門清)" not in names  # open kong breaks 門清


def test_concealed_kongs_count_toward_concealed_triplets():
    # 1 concealed triplet + 2 concealed kongs = 三暗刻.
    hand = parse_tiles("111m234567p55s")  # 11 tiles = 3 sets + pair (declared_sets=2)
    context = WinContext(winning_tile=_tile("1m"), self_draw=True)
    result = score_hand(hand, (), context, kongs=((_tile("1z"), True), (_tile("2z"), True)))
    assert "three concealed triplets (三暗刻)" in _names(result)


def test_open_kong_does_not_count_as_concealed_triplet():
    hand = parse_tiles("111m234567p55s")
    context = WinContext(winning_tile=_tile("1m"), self_draw=True)
    result = score_hand(hand, (), context, kongs=((_tile("1z"), True), (_tile("2z"), False)))
    names = _names(result)
    assert "three concealed triplets (三暗刻)" not in names  # only 1 triplet + 1 concealed kong
    assert "concealed hand (門清)" not in names  # the open kong breaks it


def test_kong_counts_as_triplet_for_all_triplets():
    hand = parse_tiles("111222333444m55m")  # 14 tiles, all triplets + pair
    context = WinContext(winning_tile=_tile("5m"), self_draw=True)
    result = score_hand(hand, (), context, kongs=((_tile("1z"), False),))
    assert "all triplets (碰碰胡)" in _names(result)


def test_kong_size_validation_and_context_rules():
    with pytest.raises(ValueError):  # wrong concealed size for one declared kong
        score_hand(parse_tiles("234567m234p234s5s"), (), WinContext(winning_tile=_tile("2s")), kongs=((_tile("1z"), True),))
    with pytest.raises(ValueError):  # 槓上開花 must be a self-draw
        WinContext(winning_tile=0, kong_bloom=True)
    with pytest.raises(ValueError):  # 搶槓 must be a ron
        WinContext(winning_tile=0, self_draw=True, robbed_kong=True)
