"""Filter and tagging coverage for the endgame drill generator."""

from dataclasses import replace

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
    monkeypatch.setattr("taimahjong.quiz.REFINE_SIMS", 3)
    monkeypatch.setattr(endgame, "ENDGAME_EV_GAP_MIN", 0.1)
    quiz._rank_cached.cache_clear()
    first = endgame.generate_endgame_position(1)
    second = endgame.generate_endgame_position(1)
    assert first == second
    assert first.position.wall_remaining <= endgame.ENDGAME_WALL_MAX
    assert first.position.candidate_ev_gap >= 0.1
    assert first.tag in {"attack", "defense"}
    quiz._rank_cached.cache_clear()


@pytest.mark.parametrize("refined_fold_ev, expected_tag", [(0.5, "defense"), (-1.0, "attack")])
def test_generate_rejects_winners_curse_and_uses_refined_teaching_data(
    monkeypatch, refined_fold_ev, expected_tag,
):
    # Selecting on the cheap estimate picks lucky draws (winner's curse).
    # Reject that snapshot when its gap collapses, then keep the first one
    # whose refined gap survives and teach from that same refined ranking.
    monkeypatch.setattr(quiz, "EV_SIMS", 2)
    monkeypatch.setattr(quiz, "REFINE_SIMS", 3)
    monkeypatch.setattr(endgame, "MAX_ATTEMPTS", 1)
    positions = [replace(_position(20, 1), turn=turn) for turn in range(10, 14)]
    monkeypatch.setattr(endgame, "_position_from", lambda snapshot, seed: snapshot)

    def play_game(seed, snapshot_hook, config):
        for position in positions:
            snapshot_hook(position)

    monkeypatch.setattr(endgame, "play_game", play_game)
    cheap_fold_ev = -1.0 if expected_tag == "defense" else 5.0
    refined = [_entry(3, endgame.ENDGAME_EV_GAP_MIN), _entry(4, 0.0),
               _entry(-1, refined_fold_ev, is_fold=True)]
    rankings = {
        (10, quiz.EV_SIMS): [_entry(3, 0.5), _entry(4, 0.0)],
        (11, quiz.EV_SIMS): [_entry(3, 3.0), _entry(4, 0.0), _entry(-1, 1.0, True)],
        (11, quiz.REFINE_SIMS): [_entry(3, 0.5), _entry(4, 0.0), _entry(-1, 1.0, True)],
        (12, quiz.EV_SIMS): [_entry(3, 4.0), _entry(4, 0.0), _entry(-1, cheap_fold_ev, True)],
        (12, quiz.REFINE_SIMS): refined,
    }
    calls = []

    def ev_rank(hand, opponents, public_counts, melds, draws, sims, seed, template, **kwargs):
        turn = seed - positions[0].seed * 1_000_003
        calls.append((turn, sims))
        return rankings[(turn, sims)]

    monkeypatch.setattr(endgame, "ev_rank", ev_rank)
    generated = endgame.generate_endgame_position(1)

    assert generated.position == replace(positions[2], candidate_ev_gap=endgame.ENDGAME_EV_GAP_MIN)
    assert generated.tag == expected_tag
    assert generated.defense_policy is refined[-1]
    assert calls == [(10, 2), (11, 2), (11, 3), (12, 2), (12, 3)]


def test_generate_rejects_non_integer_seed():
    with pytest.raises(ValueError):
        endgame.generate_endgame_position(True)
