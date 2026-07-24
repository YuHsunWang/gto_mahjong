"""MJ-008 exhaustive CRN mode and pruning measurement."""

from taimahjong.ev import ev_rank
from taimahjong.ev_benchmark import (
    PRUNING_RECALL_TARGET,
    benchmark_corpus,
    measure_pruning,
)
from taimahjong.tiles import parse_tiles


HAND = parse_tiles("123456789m11234p567s")


def test_exhaustive_mode_evaluates_every_legal_discard_with_crn():
    first = ev_rank(HAND, (), (0,) * 34, turns=2, sims=8, seed=71, exhaustive=True)
    second = ev_rank(HAND, (), (0,) * 34, turns=2, sims=8, seed=71, exhaustive=True)
    real = [entry for entry in first if not entry.is_fold]

    assert first == second
    assert {entry.discard for entry in real} == {
        tile for tile, count in enumerate(HAND) if count
    }
    assert all(entry.sample_count == 8 for entry in real)


def test_seeded_corpus_covers_required_scenarios_and_reports_recall_regret_latency():
    corpus = benchmark_corpus()
    tags = {tag for case in corpus for tag in case.tags}
    schemes = {case.scheme for case in corpus}
    report = measure_pruning(corpus, sims=4)

    assert {"early", "mid", "late", "declared", "flush", "dealer_streak"} <= tags
    assert len(schemes) == 2
    assert report.target_recall == PRUNING_RECALL_TARGET == 0.99
    assert 0 <= report.recall_at_1 <= 1
    assert report.mean_regret >= 0
    assert report.worst_regret >= report.mean_regret
    assert report.pruned_seconds >= 0 and report.exhaustive_seconds >= 0
