from math import isclose, sqrt

import pytest

from taimahjong.danger import (
    MELD_FLUSH,
    MELD_FLUSH_HONOR,
    MIN_RIVER_NUMERIC,
    SHAPE_RIVER_DISCOUNT,
    SUIT_VOID,
    OpponentView,
    danger_score,
    rank_discards,
)
from taimahjong.tiles import parse_tiles
from taimahjong.ukeire import discard_analysis


def _counts(tiles):
    counts = [0] * 34
    for tile in tiles:
        counts[tile] += 1
    return tuple(counts)


def _public(opponent):
    return _counts(opponent.river + [tile for meld in opponent.melds for tile in meld])


def _assessment(tile, opponent=None, visible=None, hand=None):
    opponent = opponent or OpponentView([], [])
    visible = _public(opponent) if visible is None else visible
    hand = (0,) * 34 if hand is None else hand
    return danger_score(tile, opponent, visible, hand)


def _shape_map(assessment):
    return {(shape.name, shape.required_tiles): shape for shape in assessment.feasible_shapes}


def test_wait_shape_known_answers_for_honor_terminal_and_middle():
    honor = _assessment(27)
    assert [(shape.name, shape.required_tiles) for shape in honor.feasible_shapes] == [
        ("tanki", (27,)),
        ("shanpon", (27,)),
    ]

    terminal = _assessment(0)
    assert [(shape.name, shape.required_tiles) for shape in terminal.feasible_shapes] == [
        ("tanki", (0,)),
        ("shanpon", (0,)),
        ("ryanmen", (1, 2)),
    ]

    middle = _assessment(4)
    assert [(shape.name, shape.required_tiles) for shape in middle.feasible_shapes] == [
        ("tanki", (4,)),
        ("shanpon", (4,)),
        ("ryanmen", (5, 6)),
        ("ryanmen", (2, 3)),
        ("kanchan", (3, 5)),
    ]


def test_wall_logic_removes_sequence_shapes_and_validates_copy_limits():
    blocked_neighbors = [0] * 34
    for tile in (2, 3, 5, 6):
        blocked_neighbors[tile] = 4
    assessment = _assessment(4, visible=tuple(blocked_neighbors))
    assert [shape.name for shape in assessment.feasible_shapes] == ["tanki", "shanpon"]

    # With two visible copies plus this discard, one unseen copy remains:
    # tanki is possible but shanpon is not.
    two_visible = [0] * 34
    two_visible[4] = 2
    assessment = _assessment(4, visible=tuple(two_visible))
    assert "tanki" in [shape.name for shape in assessment.feasible_shapes]
    assert "shanpon" not in [shape.name for shape in assessment.feasible_shapes]

    all_elsewhere = [0] * 34
    all_elsewhere[4] = 4
    with pytest.raises(ValueError, match="more than four"):
        _assessment(4, visible=tuple(all_elsewhere))


def test_adding_visible_neighbor_copies_never_increases_danger():
    baseline = _assessment(4)
    more_visible = [0] * 34
    more_visible[3] = 3
    more_visible[5] = 3
    blocked = _assessment(4, visible=tuple(more_visible))
    assert blocked.score <= baseline.score


def test_shape_level_river_evidence_discounts_required_kinds_only():
    empty = _assessment(1)
    opponent = OpponentView([0, 2], [])  # 1m early, 3m in the recent third
    river = _assessment(1, opponent)
    shapes = _shape_map(river)
    assert shapes[("tanki", (1,))].river_multiplier == 1.0
    assert shapes[("shanpon", (1,))].river_multiplier == 1.0
    assert shapes[("ryanmen", (2, 3))].river_multiplier == SHAPE_RIVER_DISCOUNT
    assert isclose(
        shapes[("kanchan", (0, 2))].river_multiplier,
        sqrt(SHAPE_RIVER_DISCOUNT) * SHAPE_RIVER_DISCOUNT,
    )
    assert 0 < river.score < empty.score


def test_shape_river_recency_uses_newest_third_boundary():
    early = OpponentView([0, 9, 10, 11, 12, 13], [])
    recent = OpponentView([9, 10, 11, 12, 13, 0], [])
    early_shape = _shape_map(_assessment(1, early))[("kanchan", (0, 2))]
    recent_shape = _shape_map(_assessment(1, recent))[("kanchan", (0, 2))]
    assert isclose(early_shape.river_multiplier, sqrt(SHAPE_RIVER_DISCOUNT))
    assert recent_shape.river_multiplier == SHAPE_RIVER_DISCOUNT


def test_flush_trigger_and_suit_void_use_max_not_product():
    opponent = OpponentView([0, 1, 2, 3, 9, 10, 11, 12], [(18, 19, 20)])
    bamboo = _assessment(18, opponent)
    honor = _assessment(27, opponent)
    plain_bamboo = _assessment(18)
    assert bamboo.modifiers["suit_void"] == SUIT_VOID
    assert bamboo.modifiers["meld_flush"] == MELD_FLUSH
    assert bamboo.modifiers["suit_flush_max"] == MELD_FLUSH
    assert bamboo.score == plain_bamboo.score * MELD_FLUSH
    assert honor.modifiers["meld_flush_honor"] == MELD_FLUSH_HONOR


def test_suit_void_requires_enough_numeric_discards_and_targets_only_missing_suit():
    river = [0, 1, 2, 3, 4, 9, 10, 11]
    opponent = OpponentView(river, [])
    bamboo = _assessment(18, opponent)
    characters = _assessment(0, opponent)
    dots = _assessment(9, opponent)
    assert bamboo.modifiers == {"suit_void": SUIT_VOID}
    assert characters.modifiers == {}
    assert dots.modifiers == {}

    short_river = OpponentView(river[: MIN_RIVER_NUMERIC - 1], [])
    assert _assessment(18, short_river).modifiers == {}


def test_visible_contract_requires_opponent_public_tiles_and_handles_post_discard_hand():
    opponent = OpponentView([0], [])
    with pytest.raises(ValueError, match="must include"):
        danger_score(1, opponent, (0,) * 34, (0,) * 34)
    hand = [0] * 34
    hand[0] = 1
    visible = [0] * 34
    visible[1] = 2
    assessment = danger_score(1, OpponentView([], []), tuple(visible), tuple(hand))
    assert "tanki" in [shape.name for shape in assessment.feasible_shapes]
    assert "shanpon" not in [shape.name for shape in assessment.feasible_shapes]


def test_rank_discards_keeps_m2_order_and_attaches_danger():
    hand = parse_tiles("123m123p123s11122233z")
    opponent = OpponentView([3, 4, 5, 15, 16, 17], [])
    visible = _public(opponent)
    expected = discard_analysis(hand, visible=visible)
    ranked = rank_discards(hand, opponent, visible)
    assert [entry.analysis for entry in ranked] == expected
    assert [entry.discard for entry in ranked] == [entry.discard for entry in expected]
    assert all(entry.danger.score >= 0 for entry in ranked)
