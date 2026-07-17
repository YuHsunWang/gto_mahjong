"""Teaching-shell coverage: positions must be reproducible and observable."""

import subprocess
import sys

import pytest

from taimahjong.quiz import EV_GAP_MIN, GOOD_DELTA, MIN_TURN, SHANTEN_MAX, generate_position, grade


@pytest.fixture(scope="module")
def position():
    return generate_position(1)


def _observed_counts(position):
    counts = list(position.hand)
    for entry in position.own_river:
        counts[entry.tile] += 1
    for meld in position.own_melds:
        for tile in meld:
            counts[tile] += 1
    for opponent in position.opponents:
        for entry in opponent.river:
            counts[entry.tile] += 1
        for meld in opponent.melds:
            for tile in meld:
                counts[tile] += 1
    return tuple(counts)


def test_same_seed_renders_and_grades_identically(position):
    repeated = generate_position(1)
    answer = next(tile for tile, count in enumerate(position.hand) if count)
    assert position.render() == repeated.render()
    assert grade(position, answer) == grade(repeated, answer)


def test_filter_constraints_hold_for_several_seeded_positions():
    for seed in (1, 2, 3):
        position = generate_position(seed)
        assert position.shanten <= SHANTEN_MAX
        assert position.turn >= MIN_TURN
        assert any(len(opponent.melds) >= 2 or opponent.declared or opponent.tenpai_estimate >= 0.4 for opponent in position.opponents)
        assert position.candidate_ev_gap >= EV_GAP_MIN


def test_snapshot_is_public_information_only_and_counts_every_visible_tile(position):
    assert all(not hasattr(opponent, "hand") for opponent in position.opponents)
    assert _observed_counts(position) == position.visible_counts
    assert sum(position.hand) + 3 * len(position.own_melds) == 17


def test_grading_best_worst_off_candidate_and_illegal_choices(position):
    probe = next(tile for tile, count in enumerate(position.hand) if count)
    initial = grade(position, probe)
    best_grade = grade(position, initial.best.discard)
    assert best_grade.verdict == "best"
    assert best_grade.ev_delta == 0

    worst_grade = grade(position, initial.ranked[-1].discard)
    expected = "good" if worst_grade.ev_delta < GOOD_DELTA else "inaccuracy" if worst_grade.ev_delta < 1.0 else "mistake"
    assert worst_grade.verdict == expected

    candidates = {entry.discard for entry in initial.ranked}
    off_candidate = next(tile for tile, count in enumerate(position.hand) if count and tile not in candidates)
    off_grade = grade(position, off_candidate)
    assert off_grade.chosen.discard == off_candidate
    assert off_grade.rank_position is None

    illegal = next(tile for tile, count in enumerate(position.hand) if not count)
    with pytest.raises(ValueError, match="present in the hand"):
        grade(position, illegal)


def test_quiz_cli_noninteractive_prints_best_verdict(position):
    answer = grade(position, next(tile for tile, count in enumerate(position.hand) if count)).best.discard
    counts = [0] * 34
    counts[answer] = 1
    from taimahjong.tiles import format_tiles

    result = subprocess.run(
        [sys.executable, "-B", "-m", "taimahjong", "--quiz", "--seed", "1", "--answer", format_tiles(counts)],
        cwd=".",
        text=True,
        capture_output=True,
        check=False,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "Verdict: best" in result.stdout
