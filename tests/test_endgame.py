"""Filter and tagging coverage for the endgame drill generator."""

import pytest

from taimahjong import endgame, quiz
from taimahjong.ev import EVRankEntry
from taimahjong.quiz import QuizOpponent, QuizPosition


def _entry(discard: int, net_ev: float, is_fold: bool = False) -> EVRankEntry:
    return EVRankEntry(discard, 0.1, 2.0, 0.5, (), 0.2, net_ev, is_fold=is_fold, label="fold" if is_fold else None)


def _position(wall_remaining: int, shanten: int, declared_at: int | None = None) -> QuizPosition:
    opponent = QuizOpponent(1, (), (), declared_at, 0.3, 0.1)
    return QuizPosition(
        seed=1, seat=0, turn=10, drawn_tile=0, hand=(1,) + (0,) * 33,
        own_river=(), own_melds=(), opponents=(opponent,),
        public_counts=(0,) * 34, visible_counts=(1,) + (0,) * 33,
        shanten=shanten, draws_remaining=5, wall_remaining=wall_remaining,
        candidate_ev_gap=0.0,
    )


def test_pressure_requires_late_wall_and_shanten_or_declaration():
    assert endgame._pressure(_position(wall_remaining=20, shanten=1))
    assert endgame._pressure(_position(wall_remaining=20, shanten=3, declared_at=2))
    assert not endgame._pressure(_position(wall_remaining=21, shanten=0))  # early wall
    assert not endgame._pressure(_position(wall_remaining=20, shanten=2))  # no pressure


def test_tag_ranks_fold_by_net_ev_not_list_order():
    # The policy record is kept outside discard-table order; tagging must
    # compare policy EV instead of trusting its list position.
    fold_second = [_entry(3, 5.0), _entry(4, 1.0), _entry(-1, 2.0, is_fold=True)]
    assert endgame._tag(fold_second) == "defense"
    fold_last = [_entry(3, 5.0), _entry(4, 4.0), _entry(-1, -1.0, is_fold=True)]
    assert endgame._tag(fold_last) == "attack"


def test_generate_is_deterministic_and_meets_the_filter(monkeypatch):
    monkeypatch.setattr("taimahjong.quiz.EV_SIMS", 2)
    monkeypatch.setattr(endgame, "ENDGAME_EV_GAP_MIN", 0.1)
    quiz._rank_cached.cache_clear()
    first = endgame.generate_endgame_position(1)
    second = endgame.generate_endgame_position(1)
    assert first == second
    assert first.position.wall_remaining <= endgame.ENDGAME_WALL_MAX
    assert first.position.candidate_ev_gap >= 0.1
    assert first.tag in {"attack", "defense"}
    quiz._rank_cached.cache_clear()


def test_generate_rejects_non_integer_seed():
    with pytest.raises(ValueError):
        endgame.generate_endgame_position(True)
