"""Seeded exhaustive-vs-pruned EV reference corpus (MJ-008)."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter

from .danger import OpponentView, parse_river
from .ev import EVRankEntry, ev_rank
from .scoring import SCHEME_3_1, SCHEME_5_2, ScoringScheme
from .tiles import parse_tiles


PRUNING_RECALL_TARGET = 0.99


@dataclass(frozen=True)
class EVBenchmarkCase:
    name: str
    hand: tuple[int, ...]
    opponents: tuple[OpponentView, ...]
    visible: tuple[int, ...]
    turns: int
    seed: int
    scheme: ScoringScheme
    tags: frozenset[str]


@dataclass(frozen=True)
class PruningCaseResult:
    name: str
    fixed_top: int
    pruned_top: int
    exhaustive_top: int
    fixed_regret: float
    regret: float
    fixed_seconds: float
    pruned_seconds: float
    exhaustive_seconds: float


@dataclass(frozen=True)
class PruningReport:
    cases: int
    target_recall: float
    fixed_top_k_recall_at_1: float
    recall_at_1: float
    fixed_top_k_mean_regret: float
    fixed_top_k_worst_regret: float
    mean_regret: float
    worst_regret: float
    fixed_top_k_seconds: float
    pruned_seconds: float
    exhaustive_seconds: float
    decision: str
    results: tuple[PruningCaseResult, ...]


def _visible(*opponents: OpponentView) -> tuple[int, ...]:
    counts = [0] * 34
    for opponent in opponents:
        for entry in opponent.river:
            counts[entry.tile if hasattr(entry, "tile") else entry] += 1
        for meld in opponent.melds:
            for tile in meld:
                counts[tile] += 1
    return tuple(counts)


def benchmark_corpus() -> tuple[EVBenchmarkCase, ...]:
    """Fixed cases spanning the pre-declared MJ-008 coverage dimensions."""
    generic = parse_tiles("123456789m11234p567s")
    alternate = parse_tiles("123m123p123s11122z333z")
    flush = parse_tiles("11122334455667789m")
    declared = OpponentView(parse_river("19m"), [], 1)
    dealer = OpponentView(
        parse_river("1p3p5p"), [], None,
        is_dealer=True, dealer_streak=3,
    )
    open_flush = OpponentView(
        parse_river("1s4s7s"), [(9, 10, 11), (12, 13, 14)], None,
    )
    return (
        EVBenchmarkCase(
            "early-default", generic, (), (0,) * 34, 12, 8101,
            SCHEME_3_1, frozenset({"early"}),
        ),
        EVBenchmarkCase(
            "mid-declared", generic, (declared,), _visible(declared), 6, 8102,
            SCHEME_3_1, frozenset({"mid", "declared"}),
        ),
        EVBenchmarkCase(
            "late-pressure", alternate, (declared,), _visible(declared), 2, 8103,
            SCHEME_5_2, frozenset({"late", "declared"}),
        ),
        EVBenchmarkCase(
            "flush-hand", flush, (), (0,) * 34, 6, 8104,
            SCHEME_5_2, frozenset({"mid", "flush"}),
        ),
        EVBenchmarkCase(
            "dealer-streak", generic, (dealer,), _visible(dealer), 4, 8105,
            SCHEME_3_1, frozenset({"mid", "dealer_streak"}),
        ),
        EVBenchmarkCase(
            "open-flush-opponent", alternate, (open_flush,), _visible(open_flush), 3, 8106,
            SCHEME_5_2, frozenset({"late", "flush"}),
        ),
    )


def _real(entries: list[EVRankEntry]) -> list[EVRankEntry]:
    return sorted(
        (entry for entry in entries if not entry.is_fold),
        key=lambda entry: (-entry.net_ev, entry.discard),
    )


def measure_pruning(
    corpus: tuple[EVBenchmarkCase, ...] | None = None,
    *,
    sims: int = 24,
) -> PruningReport:
    cases = benchmark_corpus() if corpus is None else corpus
    results: list[PruningCaseResult] = []
    fixed_recalls = 0
    recalls = 0
    for case in cases:
        started = perf_counter()
        fixed = _real(ev_rank(
            case.hand,
            case.opponents,
            case.visible,
            turns=case.turns,
            sims=sims,
            seed=case.seed,
            scheme=case.scheme,
            reference_fixed_top_k=True,
        ))
        fixed_seconds = perf_counter() - started
        started = perf_counter()
        pruned = _real(ev_rank(
            case.hand,
            case.opponents,
            case.visible,
            turns=case.turns,
            sims=sims,
            seed=case.seed,
            scheme=case.scheme,
        ))
        pruned_seconds = perf_counter() - started
        started = perf_counter()
        exhaustive = _real(ev_rank(
            case.hand,
            case.opponents,
            case.visible,
            turns=case.turns,
            sims=sims,
            seed=case.seed,
            scheme=case.scheme,
            exhaustive=True,
        ))
        exhaustive_seconds = perf_counter() - started
        exhaustive_by_tile = {entry.discard: entry for entry in exhaustive}
        fixed_top = fixed[0].discard
        pruned_top = pruned[0].discard
        exhaustive_top = exhaustive[0].discard
        fixed_regret = max(
            0.0,
            exhaustive[0].net_ev - exhaustive_by_tile[fixed_top].net_ev,
        )
        regret = max(
            0.0,
            exhaustive[0].net_ev - exhaustive_by_tile[pruned_top].net_ev,
        )
        fixed_recalls += int(fixed_top == exhaustive_top)
        recalls += int(pruned_top == exhaustive_top)
        results.append(PruningCaseResult(
            case.name,
            fixed_top,
            pruned_top,
            exhaustive_top,
            fixed_regret,
            regret,
            fixed_seconds,
            pruned_seconds,
            exhaustive_seconds,
        ))
    fixed_recall = 0.0 if not cases else fixed_recalls / len(cases)
    recall = 0.0 if not cases else recalls / len(cases)
    fixed_regrets = [result.fixed_regret for result in results]
    regrets = [result.regret for result in results]
    return PruningReport(
        len(cases),
        PRUNING_RECALL_TARGET,
        fixed_recall,
        recall,
        0.0 if not fixed_regrets else sum(fixed_regrets) / len(fixed_regrets),
        0.0 if not fixed_regrets else max(fixed_regrets),
        0.0 if not regrets else sum(regrets) / len(regrets),
        0.0 if not regrets else max(regrets),
        sum(result.fixed_seconds for result in results),
        sum(result.pruned_seconds for result in results),
        sum(result.exhaustive_seconds for result in results),
        (
            "keep_fixed_top_k"
            if fixed_recall >= PRUNING_RECALL_TARGET
            else "switched_to_confidence_bound_screening"
            if recall >= PRUNING_RECALL_TARGET
            else "widen_confidence_bound_screening"
        ),
        tuple(results),
    )
