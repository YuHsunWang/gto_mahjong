"""Single-trial terminal rollout convergence and invariants."""

from collections import Counter
from dataclasses import replace
from math import sqrt
from random import Random

import pytest

from taimahjong.config import DEFAULT_RULES
from taimahjong.danger import RiverEntry
from taimahjong.ev import _production_discard_policy
from taimahjong.reference_ev import (
    OUTCOME_KINDS,
    _policy_discard,
    evaluate_candidate,
    representative_reference_cases,
    standard_small_wall_state,
)
from taimahjong.rollout import (
    CalibratedRonClaim,
    _winner_distribution,
    resolve_terminal,
    resolve_terminal_distribution,
)
from taimahjong.selfplay import Player
from taimahjong.tiles import parse_tiles


@pytest.mark.parametrize("menqing_three", [False, True])
def test_rollout_last_live_tsumo_scores_one_extra_tai(menqing_three):
    rules = replace(DEFAULT_RULES, menqing_self_draw_three=menqing_three)
    waiting = list(parse_tiles("111m456789p234s55789s"))
    tile = 19  # 2s
    waiting[tile] -= 1
    players = [
        Player("attack", list(parse_tiles("147m147p147s1234567z")))
        for _ in range(4)
    ]
    players[1].hand = waiting

    def run(wall, configured_rules=rules):
        return resolve_terminal(
            players, wall, 1, 1, None, _policy_discard, Random(1),
            rules=configured_rules,
        )

    ordinary = run((tile, tile))
    last = run((tile,))
    default = run((tile,), DEFAULT_RULES)
    assert ordinary.kind == last.kind == "self_tsumo"
    assert last.value_units == ordinary.value_units + 1
    assert last.deltas[1] == ordinary.deltas[1] + 3
    assert last.value_units == default.value_units + int(menqing_three)


@pytest.mark.parametrize("calibrated", [False, True])
@pytest.mark.parametrize("acting_seat", [0, 1])
def test_rollout_last_live_discard_scores_river_bottom(calibrated, acting_seat):
    winning = parse_tiles("111m456789p234s55789s")
    tile = 19
    waiting = list(winning)
    waiting[tile] -= 1
    players = [
        Player("attack", list(parse_tiles("147m147p147s1234567z")))
        for _ in range(4)
    ]
    players[1].hand = waiting

    def claims(_players, _discarder, discarded):
        if discarded != tile:
            return ()
        return (CalibratedRonClaim(1, 1.0, winning_hand=winning, scoring_tile=tile),)

    def run(wall, opening=None):
        return resolve_terminal(
            players, wall, acting_seat, 0, opening, lambda *_: tile, Random(1),
            calibrated_ron=claims if calibrated else None,
        )

    ordinary = run((tile, tile))
    last = run((tile,))
    expected_kind = "self_ron" if acting_seat == 1 else "opponent_ron"
    assert last.kind == ordinary.kind == expected_kind
    assert last.value_units == ordinary.value_units + 1
    assert last.deltas[1] == ordinary.deltas[1] + 1
    # An opening discard has no preceding normal draw in this rollout.
    if acting_seat == 0:
        players[0].hand[tile] = 1
        assert run((), tile).value_units == ordinary.value_units


FIRST_CHARACTER = 0  # 1m, the opening discard in the priced-claim tests
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


def test_acting_continuation_advances_caller_visible_by_each_discard_once():
    concealed = parse_tiles("147m147p147s1234567z")
    actor_concealed = parse_tiles("147m147p147s12345z")
    called = next(
        tile for tile, count in enumerate(parse_tiles("5s")) if count
    )
    opening = next(
        tile for tile, count in enumerate(parse_tiles("1m")) if count
    )
    wall = tuple(
        tile
        for text in ("2m", "3m", "5m", "6m", "8m", "9m", "2p", "3p")
        for tile, count in enumerate(parse_tiles(text))
        if count
    )
    players = [Player("attack", list(concealed)) for _ in range(4)]
    players[0].hand = list(actor_concealed)
    players[0].melds.append((called, called, called))
    players[1].river.append(RiverEntry(called))
    players[2].river.append(RiverEntry(called))
    visible = [0] * 34
    visible[called] = 4
    opponent_discards = []
    actor_discards = []
    snapshots = []

    def rollout_discard(hand, _remaining, _melds):
        discarded = next(tile for tile in wall if hand[tile])
        opponent_discards.append(discarded)
        return discarded

    def acting_discard(hand, _remaining, public, _melds):
        snapshots.append(public)
        discarded = next(tile for tile in wall if hand[tile])
        actor_discards.append(discarded)
        return discarded

    terminal = resolve_terminal(
        players,
        wall,
        0,
        1,
        opening,
        rollout_discard,
        Random(7),
        acting_discard_policy=acting_discard,
        visible=visible,
    )

    first_expected = visible.copy()
    first_expected[opening] += 1
    for discarded in opponent_discards[:3]:
        first_expected[discarded] += 1
    second_expected = first_expected.copy()
    second_expected[actor_discards[0]] += 1
    for discarded in opponent_discards[3:6]:
        second_expected[discarded] += 1

    assert terminal.kind == "draw"
    assert snapshots == [tuple(first_expected), tuple(second_expected)]
    assert snapshots[0][opening] == snapshots[1][opening] == 1
    assert snapshots[0][called] == snapshots[1][called] == 4


# Convergence against the exact oracle (~12s).
@pytest.mark.slow
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


def _claiming_players():
    players = [Player("attack") for _ in range(4)]
    players[0].hand = list(parse_tiles("123456m123p123s333z66z"))
    return players


def test_priced_ron_splits_the_world_instead_of_tossing_a_coin():
    # An empty wall leaves exactly two terminals: the priced claim, or the draw
    # it fails to make.  With one claim at even odds the mixture must be the
    # payment itself halved -- no sampling anywhere.
    mixture = resolve_terminal_distribution(
        _claiming_players(),
        (),
        0,
        1,
        FIRST_CHARACTER,
        _policy_discard,
        Random(1),
        calibrated_ron=lambda _players, _discarder, _tile: (
            CalibratedRonClaim(1, 0.5, 8),
        ),
    )

    assert mixture.total_probability == pytest.approx(1.0)
    assert mixture.probability("opponent_ron") == pytest.approx(0.5)
    assert mixture.probability("draw") == pytest.approx(0.5)
    assert mixture.expected_deltas == pytest.approx((-4.0, 4.0, 0.0, 0.0))
    assert sum(mixture.expected_deltas) == pytest.approx(0.0)


def test_priced_ron_mass_survives_across_several_discards():
    # Two mutually exclusive actual-winner probabilities exhaust the opening
    # discard's mass.  Neither is discounted by a second claim arbitration.
    mixture = resolve_terminal_distribution(
        _claiming_players(),
        (),
        0,
        1,
        FIRST_CHARACTER,
        _policy_discard,
        Random(1),
        calibrated_ron=lambda _players, _discarder, _tile: (
            CalibratedRonClaim(1, 0.5, 8),
            CalibratedRonClaim(2, 0.5, 8),
        ),
    )

    assert mixture.probability("draw") == pytest.approx(0.0)
    assert mixture.probability("opponent_ron") == pytest.approx(1.0)
    winners = {
        terminal.ron_winners: probability
        for probability, terminal in mixture.outcomes
        if terminal.ron_winners
    }
    assert winners[(1,)] == pytest.approx(0.5)
    assert winners[(2,)] == pytest.approx(0.5)


def test_resolve_terminal_refuses_to_collapse_a_genuine_mixture():
    with pytest.raises(ValueError, match="coin toss"):
        resolve_terminal(
            _claiming_players(),
            (),
            0,
            1,
            FIRST_CHARACTER,
            _policy_discard,
            Random(1),
            calibrated_ron=lambda _players, _discarder, _tile: (
                CalibratedRonClaim(1, 0.5, 8),
            ),
        )


def test_winner_distribution_uses_mutually_exclusive_calibration_directly():
    distribution = _winner_distribution(
        {1: 0.2, 2: 0.2}, 0, DEFAULT_RULES,
    )

    assert distribution == pytest.approx({(1,): 0.2, (2,): 0.2, (): 0.6})
    assert sum(distribution.values()) == pytest.approx(1.0)


def test_winner_distribution_normalizes_independent_rows_above_one():
    distribution = _winner_distribution(
        {1: 0.8, 2: 0.4, 3: 0.3}, 0, DEFAULT_RULES,
    )

    assert distribution == pytest.approx({
        (1,): 0.8 / 1.5,
        (2,): 0.4 / 1.5,
        (3,): 0.3 / 1.5,
    })
    assert distribution.get((), 0.0) == 0.0
    assert sum(distribution.values()) == pytest.approx(1.0)


@pytest.mark.parametrize("calibrated", [False, True])
def test_opening_last_normal_draw_discard_gets_river_bottom(calibrated):
    winning = parse_tiles("111m456789p234s55789s")
    tile = 19
    players = [Player("attack", list(parse_tiles("147m147p147s1234567z"))) for _ in range(4)]
    players[1].hand = list(winning)
    players[1].hand[tile] -= 1
    players[0].hand[tile] = 1

    def claims(*_):
        return (CalibratedRonClaim(1, 1.0, winning_hand=winning, scoring_tile=tile),)

    def run(live_draw):
        return resolve_terminal(
            players, (), 0, 1, tile, _policy_discard, Random(1),
            wall_remaining=0, opening_live_draw=live_draw,
            calibrated_ron=claims if calibrated else None,
        )

    assert run(True).value_units == run(False).value_units + 1


def test_rollout_horizon_does_not_end_real_live_wall():
    tile = 19
    waiting = list(parse_tiles("111m456789p234s55789s"))
    waiting[tile] -= 1
    players = [Player("attack", list(parse_tiles("147m147p147s1234567z"))) for _ in range(4)]
    players[1].hand = waiting

    def run(real_remaining):
        return resolve_terminal(
            players, (tile,), 1, 1, None, _policy_discard, Random(1),
            wall_remaining=real_remaining,
        )

    ordinary = run(2)
    last = run(1)
    assert ordinary.kind == last.kind == "self_tsumo"
    assert last.value_units == ordinary.value_units + 1
