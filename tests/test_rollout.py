"""Single-trial terminal rollout convergence and invariants."""

from collections import Counter
from dataclasses import replace
from math import sqrt
from random import Random

from taimahjong.config import DEFAULT_RULES
from taimahjong.ev import _production_discard_policy
from taimahjong.reference_ev import (
    OUTCOME_KINDS,
    _policy_discard,
    evaluate_candidate,
    representative_reference_cases,
    standard_small_wall_state,
)
from taimahjong.rollout import resolve_terminal
from taimahjong.selfplay import Player
from taimahjong.tiles import parse_tiles


TRIALS_PER_CANDIDATE = 2_048
STANDARD_ERROR_MULTIPLIER = 4.0
CONVERGENCE_CANDIDATES = (
    (12, 0, 7312),
    (18, 0, 7318),
    (20, 31, 7320),
    (23, 31, 7323),
)


def _rollout_players(state):
    return [
        Player(
            "attack",
            list(reference.hand),
            declared_at=reference.declared_at,
        )
        for reference in state.players
    ]


def _exact_standard_deviation(evaluation, acting_seat):
    exact_mean = float(evaluation.actor_ev)
    variance = sum(
        float(item.probability)
        * (item.outcome.payment.deltas[acting_seat] - exact_mean) ** 2
        for item in evaluation.outcomes
    )
    return sqrt(variance)


def test_resolve_terminal_honors_multi_ron_rules_and_conserves():
    state = standard_small_wall_state(wall=())
    references = list(state.players)
    references[2] = replace(
        references[2],
        hand=parse_tiles("123456m123p123s333z6z"),
    )
    state = replace(state, players=tuple(references))
    all_rules = replace(
        DEFAULT_RULES,
        rules_id="taiwanese-multi-ron-v1",
        multi_ron="all",
    )

    nearest = resolve_terminal(
        _rollout_players(state),
        state.wall,
        state.acting_seat,
        state.next_seat,
        32,
        _policy_discard,
        Random(1),
        dealer_streak=state.dealer_streak,
        scheme=state.scheme,
        rules=DEFAULT_RULES,
    )
    multi = resolve_terminal(
        _rollout_players(state),
        state.wall,
        state.acting_seat,
        state.next_seat,
        32,
        _policy_discard,
        Random(1),
        dealer_streak=state.dealer_streak,
        scheme=state.scheme,
        rules=all_rules,
    )

    assert nearest.kind == multi.kind == "opponent_ron"
    assert nearest.ron_winners == (1,)
    assert multi.ron_winners == (1, 2)
    assert sum(nearest.deltas) == sum(multi.deltas) == 0
    assert multi.deltas[1] > 0
    assert multi.deltas[2] > 0
    assert multi.deltas[state.acting_seat] < nearest.deltas[state.acting_seat]


def test_resolve_terminal_supports_declared_melds_including_actor():
    concealed = parse_tiles("147m147p147s1234z")
    closed = parse_tiles("147m147p147s1234567z")
    discard = next(
        tile for tile, count in enumerate(parse_tiles("5z")) if count
    )
    draw = next(
        tile for tile, count in enumerate(parse_tiles("9m")) if count
    )

    for declared_seat in (0, 1):
        players = [
            Player(
                "attack",
                list(concealed if seat == declared_seat else closed),
                melds=[(0, 1, 2)] if seat == declared_seat else [],
            )
            for seat in range(4)
        ]
        players[0].hand[discard] += 1

        terminal = resolve_terminal(
            players,
            (draw,) * 4,
            0,
            1,
            discard,
            _production_discard_policy,
            Random(41),
        )

        assert sum(
            terminal.kind == kind for kind in OUTCOME_KINDS
        ) == 1
        assert len(terminal.deltas) == 4
        assert sum(terminal.deltas) == 0


def test_rollout_converges_to_exact_oracle_and_covers_reachable_kinds():
    cases = representative_reference_cases()
    all_observed = set()
    all_reachable = set()
    observed_actor_deal_in = False
    observed_opponent_ron_off_opponent = False

    for case_index, discard, seed in CONVERGENCE_CANDIDATES:
        case = cases[case_index]
        players = _rollout_players(case.state)
        exact = evaluate_candidate(case.state, discard)
        exact_mean = float(exact.actor_ev)
        exact_sigma = _exact_standard_deviation(
            exact, case.state.acting_seat,
        )
        tolerance = (
            STANDARD_ERROR_MULTIPLIER
            * exact_sigma
            / sqrt(TRIALS_PER_CANDIDATE)
        )
        rng = Random(seed)
        actor_deltas = []
        observed = Counter()

        for _ in range(TRIALS_PER_CANDIDATE):
            terminal = resolve_terminal(
                players,
                case.state.wall,
                case.state.acting_seat,
                case.state.next_seat,
                discard,
                _policy_discard,
                rng,
                dealer_streak=case.state.dealer_streak,
                scheme=case.state.scheme,
                rules=DEFAULT_RULES,
            )
            assert sum(
                terminal.kind == kind for kind in OUTCOME_KINDS
            ) == 1
            assert len(terminal.deltas) == 4
            assert sum(terminal.deltas) == 0
            observed[terminal.kind] += 1
            if terminal.kind == "opponent_ron":
                observed_actor_deal_in |= (
                    terminal.discarder == case.state.acting_seat
                )
                observed_opponent_ron_off_opponent |= (
                    terminal.discarder != case.state.acting_seat
                )
            actor_deltas.append(
                terminal.deltas[case.state.acting_seat]
            )

        sample_mean = sum(actor_deltas) / TRIALS_PER_CANDIDATE
        reachable = {
            item.outcome.kind
            for item in exact.outcomes
            if item.probability
        }
        assert set(observed) == reachable
        if tolerance == 0:
            assert sample_mean == exact_mean
        else:
            assert abs(sample_mean - exact_mean) <= tolerance
        all_observed.update(observed)
        all_reachable.update(reachable)

    assert all_reachable == OUTCOME_KINDS
    assert all_observed == OUTCOME_KINDS
    assert observed_actor_deal_in
    assert observed_opponent_ron_off_opponent
