import pytest

from taimahjong.bruteforce import bruteforce_shanten
from taimahjong.shanten import shanten
from taimahjong.tiles import parse_tiles


@pytest.mark.parametrize(
    ("hand", "expected"),
    [
        # Five melds plus a pair is a complete Taiwanese 17-tile hand.
        ("123m123p123s11122233z", -1),
        # The isolated 3z completes the pair on the next draw.
        ("123m123p123s1112223z", 0),
        # Five melds but no pair: one replacement can make the two singles a pair.
        ("123m123p123s11122234z", 0),
        # Four melds, a pair, and two unrelated honors needs one exchange for tenpai.
        ("123m123p123s1112234z", 1),
        # Honor-only structure: four triplets and four isolated honors is two-shanten.
        ("1111222233334444z", 2),
    ],
)
def test_known_shanten_values(hand, expected):
    counts = parse_tiles(hand)
    assert shanten(counts) == expected
    # The exchange oracle is exercised on the ordinary shapes below; this
    # all-honor two-shanten case keeps the expected value independently clear.
    if hand != "1111222233334444z":
        assert bruteforce_shanten(counts) == expected


def test_declared_melds_reduce_concealed_requirement():
    complete = parse_tiles("123m123p123s11122z")
    tenpai = parse_tiles("123m123p123s1112z")
    assert shanten(complete, melds_declared=1) == -1
    assert bruteforce_shanten(complete, melds_declared=1) == -1
    assert shanten(tenpai, melds_declared=1) == 0
    assert bruteforce_shanten(tenpai, melds_declared=1) == 0


@pytest.mark.parametrize("melds", [-1, 6, 1.5, True])
def test_invalid_declared_meld_count(melds):
    with pytest.raises(ValueError, match="melds_declared"):
        shanten(parse_tiles("123m456p789s1122334z"), melds)


def test_invalid_concealed_size_explains_expected_sizes():
    with pytest.raises(ValueError, match="expected 16 or 17"):
        shanten(parse_tiles("123m456p789s112233z"))
    with pytest.raises(ValueError, match="expected 13 or 14"):
        shanten(parse_tiles("123m456p789s1122334z"), melds_declared=1)
