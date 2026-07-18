from math import isclose

import pytest

from taimahjong.danger import (
    LATE_TURN,
    MIN_FOLD_SAMPLE,
    OpponentView,
    RiverEntry,
    danger_score,
    fold_score,
    format_river,
    parse_river,
    rank_discards,
    tenpai_score,
)
from taimahjong.tiles import parse_tiles


def _public(opponent):
    counts = [0] * 34
    for entry in opponent.river:
        counts[entry if isinstance(entry, int) else entry.tile] += 1
    for meld in opponent.melds:
        for tile in meld:
            counts[tile] += 1
    return tuple(counts)


def test_river_notation_round_trip_and_plain_integer_compatibility():
    text = "1*2.3m4*p5.s"
    river = parse_river(text)
    assert [(entry.tile, entry.origin) for entry in river] == [
        (0, "tsumogiri"),
        (1, "tedashi"),
        (2, "unknown"),
        (12, "tsumogiri"),
        (22, "tedashi"),
    ]
    assert format_river(river) == text
    assert format_river(parse_river("123m")) == "123m"

    # Existing callers can continue to supply tile integers and get unknown
    # origin semantics without changing danger calculations.
    opponent = OpponentView([0, 1, 2], [])
    assert tenpai_score(opponent, 6).signals["trailing_tsumogiri_run"] == 0
    assert danger_score(3, opponent, _public(opponent), (0,) * 34).score > 0


def test_tenpai_score_is_bounded_and_monotonic_for_melds_turn_and_tsumogiri_run():
    no_meld = tenpai_score(OpponentView([], []), 6).score
    one_meld = tenpai_score(OpponentView([], [(0, 0, 0)]), 6).score
    two_melds = tenpai_score(OpponentView([], [(0, 0, 0), (1, 1, 1)]), 6).score
    assert 0 <= no_meld <= one_meld <= two_melds <= 1

    opponent = OpponentView([], [])
    assert tenpai_score(opponent, 2).score <= tenpai_score(opponent, 12).score <= 1

    one_tsumo = OpponentView([RiverEntry(0, "tsumogiri")], [])
    two_tsumo = OpponentView([RiverEntry(0, "tsumogiri"), RiverEntry(1, "tsumogiri")], [])
    assert tenpai_score(opponent, 8).score <= tenpai_score(one_tsumo, 8).score <= tenpai_score(two_tsumo, 8).score


def test_unknown_origin_is_neutral_and_recent_tedashi_marks_wait_change():
    one_tsumo = OpponentView([RiverEntry(0, "tsumogiri")], [])
    unknown_after = OpponentView([RiverEntry(0, "tsumogiri"), RiverEntry(1, "unknown")], [])
    assert tenpai_score(one_tsumo, 8).signals["trailing_tsumogiri_run"] == 1
    assert tenpai_score(unknown_after, 8).signals["trailing_tsumogiri_run"] == 1
    assert isclose(tenpai_score(one_tsumo, 8).score, tenpai_score(unknown_after, 8).score)

    changed = tenpai_score(OpponentView([RiverEntry(4, "tedashi")], []), LATE_TURN)
    assert changed.recent_wait_change is True
    assert "recent_tedashi_multiplier" in changed.signals


def test_opponent_view_rejects_streak_without_dealer():
    # Parity with scoring.WinContext: a 連莊 count only makes sense for the
    # dealer, so a non-dealer view carrying one is a wiring bug we reject early.
    assert OpponentView([0], [], None, is_dealer=True, dealer_streak=2).dealer_streak == 2
    with pytest.raises(ValueError, match="dealer_streak requires"):
        OpponentView([0], [], None, dealer_streak=1)
    with pytest.raises(ValueError, match="non-negative"):
        OpponentView([0], [], None, is_dealer=True, dealer_streak=-1)


def test_migi_declaration_validation_tenpai_fold_and_hard_safety():
    assert OpponentView([0], [], 0).declared_at == 0
    assert OpponentView([0, 1], [], 1).declared_at == 1
    with pytest.raises(ValueError, match="0 or 1"):
        OpponentView([0, 1, 2], [], 2)

    opponent = OpponentView([RiverEntry(0), RiverEntry(1)], [], 0)
    declared = tenpai_score(opponent, 12)
    assert declared.score == 1.0
    assert declared.signals == {"declared": True}
    assert declared.recent_wait_change is False
    assert fold_score(opponent, [0, 1]) == 0.0

    visible = _public(opponent)
    post_declaration = danger_score(1, opponent, visible, (0,) * 34)
    pre_declaration = danger_score(0, opponent, visible, (0,) * 34)
    assert post_declaration.score == 0.0
    assert post_declaration.modifiers["declared_safe"] == 1.0
    assert pre_declaration.score > 0.0
    assert "declared_safe" not in pre_declaration.modifiers


def test_fold_score_rewards_safety_shapes_and_penalizes_tedashi_middle_tiles():
    safe = OpponentView([0, 1, 2, 3], [])
    assert fold_score(safe, [0, 1, 2, 3]) == 1.0

    middle_tedashi = OpponentView([0, 1, 2, RiverEntry(4, "tedashi")], [])
    assert fold_score(middle_tedashi, [0, 1, 2, 4]) < fold_score(safe, [0, 1, 2, 3])

    assert fold_score(OpponentView([0] * (MIN_FOLD_SAMPLE - 1), []), [0]) == 0.0


def test_rank_discards_exposes_shared_tenpai_and_expected_danger_product():
    hand = parse_tiles("123m123p123s11122233z")
    opponent = OpponentView([RiverEntry(3, "tsumogiri"), RiverEntry(4, "tsumogiri"), RiverEntry(5, "unknown")], [])
    ranked = rank_discards(hand, opponent, _public(opponent))
    assert ranked
    assert len({entry.tenpai_score for entry in ranked}) == 1
    assert all(entry.expected_danger == entry.danger.score * entry.tenpai_score for entry in ranked)
