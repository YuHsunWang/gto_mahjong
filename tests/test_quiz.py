"""Teaching-shell coverage: positions must be reproducible and observable."""

import statistics
import subprocess
import sys

import pytest

import taimahjong.quiz as quiz
from taimahjong.ev import EVRankEntry, evaluate_discard
from taimahjong.quiz import (
    ESCALATE_SIMS,
    EV_GAP_MIN,
    EV_SIMS,
    GOOD_DELTA,
    MIN_TURN,
    REFINE_SIMS,
    SHANTEN_MAX,
    QuizGrade,
    Verdict,
    _component_lines,
    _evaluation_seed,
    _rank,
    _rank_cached,
    _score_template,
    generate_position,
    grade,
    threshold_gap,
)


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


def test_dealer_opponent_view_flags_seat_zero():
    # The seat->dealer mapping is the load-bearing wiring for every downstream
    # dealer-aware EV: the seat-0 opponent's view must report is_dealer, and no
    # other seat may. (A non-dealer human position always has a dealer opponent.)
    for seed in (1, 2, 3):
        position = generate_position(seed)
        if position.is_dealer:
            continue  # human is the dealer; no opponent carries the flag
        for opponent in position.opponents:
            assert opponent.view().is_dealer == (opponent.seat == 0)
        dealer_opponents = [opp for opp in position.opponents if opp.seat == 0]
        assert len(dealer_opponents) == 1 and dealer_opponents[0].view().is_dealer
        break
    else:
        raise AssertionError("no non-dealer human position found in seeds 1-3")


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


def test_rank_cache_normalizes_candidate_ev_gap():
    _rank_cached.cache_clear()
    generated = generate_position(1)
    before = _rank_cached.cache_info()
    grade(generated, generated.drawn_tile)
    after = _rank_cached.cache_info()
    assert after.hits >= before.hits + 1


def test_threshold_gap_reads_good_delta_live(monkeypatch):
    monkeypatch.setattr(quiz, "GOOD_DELTA", 0.6)
    assert threshold_gap(0.6) == 0.0
    assert threshold_gap(0.3) == 0.3


def _entry(discard, attack_ev):
    return EVRankEntry(discard, 0.0, None, attack_ev, (), 0.0, attack_ev)


def test_component_lines_treat_negative_delta_as_tie(position):
    ranked = (_entry(0, 2.0), _entry(1, 1.0))
    synthetic = QuizGrade(position, _entry(0, 0.0), _entry(1, 1.0), ranked, -0.1, 2, "best")
    best_line, chosen_line = _component_lines(synthetic)
    assert "than the next-ranked choice" in best_line
    assert "matches the best's" in chosen_line
    assert "Chosen 2m: lower win EV" not in chosen_line


def test_ev_loss_clamps_negative_delta(position):
    assert Verdict("best", -0.1, REFINE_SIMS, False).ev_loss == 0.0
    ranked = (_entry(0, 2.0), _entry(1, 1.0))
    grade_with_negative_delta = QuizGrade(position, ranked[0], ranked[1], ranked, -0.1, 2, "best")
    assert grade_with_negative_delta.ev_loss == 0.0


def _refined(position, tile, sims):
    """The single-discard net EV at ``sims`` under the position's CRN seed."""
    return evaluate_discard(
        position.hand, tile, [opponent.view() for opponent in position.opponents],
        position.public_counts, len(position.own_melds), position.draws_remaining,
        sims, _evaluation_seed(position), _score_template(position),
    )


def test_grade_verdict_and_delta_come_from_two_same_seed_estimates(position):
    # The verdict rests on the rank-best and chosen candidates re-estimated at
    # the verdict's budget (shared CRN seed), not on the cheap ranked EVs.
    ranked = _rank(position)
    chosen_tile = ranked[-1].discard
    result = grade(position, chosen_tile)

    assert result.refined_sims in (REFINE_SIMS, ESCALATE_SIMS)
    assert result.best == _refined(position, ranked[0].discard, result.refined_sims)
    assert result.chosen == _refined(position, chosen_tile, result.refined_sims)
    assert result.ev_delta == result.best.net_ev - result.chosen.net_ev
    # The displayed ranked table keeps its cheaper EV_SIMS values, so the refined
    # best generally differs from the cheap ranked[0] it was refined from.
    assert result.ranked == ranked

    # Fixed seed is reproducible down to the refined estimates and marginal flag.
    assert grade(position, chosen_tile) == result


def test_grade_escalation_gate_is_selective_and_deterministic(position, monkeypatch):
    # Escalation is gated on BOTH nearness to a verdict boundary and nearness to
    # tenpai (a cost bound). Force each gate on/off, with a small escalated
    # budget so the test stays fast.
    chosen_tile = _rank(position)[-1].discard
    monkeypatch.setattr("taimahjong.quiz.ESCALATE_SIMS", 48)

    # Margin gate shut: far from any boundary -> keep the REFINE_SIMS verdict.
    monkeypatch.setattr("taimahjong.quiz.ESCALATE_MARGIN", 0.0)
    assert grade(position, chosen_tile).refined_sims == REFINE_SIMS

    # Margin gate open but shanten gate shut: borderline yet too far from tenpai.
    monkeypatch.setattr("taimahjong.quiz.ESCALATE_MARGIN", 999.0)
    monkeypatch.setattr("taimahjong.quiz.ESCALATE_MAX_SHANTEN", -1)
    assert grade(position, chosen_tile).refined_sims == REFINE_SIMS

    # Both gates open -> escalate, and deterministically so.
    monkeypatch.setattr("taimahjong.quiz.ESCALATE_MAX_SHANTEN", 34)
    forced = grade(position, chosen_tile)
    assert forced.refined_sims == 48
    assert grade(position, chosen_tile) == forced


def test_grade_marginal_flag_tracks_boundary_band(position, monkeypatch):
    chosen_tile = _rank(position)[-1].discard
    monkeypatch.setattr("taimahjong.quiz.ESCALATE_MARGIN", 0.0)  # keep it cheap, no escalation

    monkeypatch.setattr("taimahjong.quiz.MARGINAL_BAND", 999.0)
    assert grade(position, chosen_tile).marginal is True
    monkeypatch.setattr("taimahjong.quiz.MARGINAL_BAND", 0.0)
    assert grade(position, chosen_tile).marginal is False


def test_refined_ev_delta_has_lower_cross_seed_variance_than_cheap(position):
    # The point of the refinement stage: with more sims per candidate, the
    # verdict's ev_delta swings far less as the CRN base seed changes.
    ranked = _rank(position)
    best_tile, chosen_tile = ranked[0].discard, ranked[-1].discard
    opponents = [opponent.view() for opponent in position.opponents]
    template = _score_template(position)

    def ev_delta(sims, seed):
        best = evaluate_discard(position.hand, best_tile, opponents, position.public_counts,
                                len(position.own_melds), position.draws_remaining, sims, seed, template)
        chosen = evaluate_discard(position.hand, chosen_tile, opponents, position.public_counts,
                                  len(position.own_melds), position.draws_remaining, sims, seed, template)
        return best.net_ev - chosen.net_ev

    seeds = range(101, 109)
    cheap = statistics.pstdev(ev_delta(EV_SIMS, seed) for seed in seeds)
    refined = statistics.pstdev(ev_delta(REFINE_SIMS, seed) for seed in seeds)
    assert refined < 0.7 * cheap


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
