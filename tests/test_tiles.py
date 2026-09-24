import pytest

from taimahjong.tiles import format_tiles, parse_tiles, validate_counts


def test_parse_and_format_round_trip():
    hand = "123m456p789s1122334z"
    counts = parse_tiles(hand)
    assert sum(counts) == 16
    assert format_tiles(counts) == hand


@pytest.mark.parametrize("notation", ["", "123", "0m", "8z", "m", "12x", "11111m"])
def test_parser_rejects_invalid_notation(notation):
    with pytest.raises(ValueError):
        parse_tiles(notation)


def test_count_validation_rejects_wrong_shape_and_multiplicity():
    with pytest.raises(ValueError, match="34"):
        validate_counts([0] * 33)
    with pytest.raises(ValueError, match="between 0 and 4"):
        validate_counts([5] + [0] * 33)


@pytest.mark.parametrize(
    ("counts", "message"),
    [
        ([5, "bad"] + [0] * 31, "tile counts must contain exactly 34 entries"),
        ([5, "bad"] + [0] * 32, "tile counts must be integers"),
        ([True] + [0] * 33, "tile counts must be integers"),
        ([5] + [0] * 33, "each tile count must be between 0 and 4"),
    ],
)
def test_count_validation_messages_and_error_precedence(counts, message):
    with pytest.raises(ValueError) as error:
        validate_counts(counts)
    assert str(error.value) == message


def test_count_validation_accepts_integer_subclasses():
    class TileCount(int):
        pass

    count = TileCount(1)
    assert validate_counts([count] + [0] * 33)[0] is count
