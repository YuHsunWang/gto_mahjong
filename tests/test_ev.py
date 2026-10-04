"""Known-answer tests for M5b tai-unit EV approximations."""

from dataclasses import replace
from math import comb
from random import Random

import pytest

from taimahjong.danger import OpponentView, parse_river
import taimahjong.ev as ev
from taimahjong.ev import (
    DRAW_VALUE,
    FOLD_HAZARD_CUTOFF,
    FLOWERLESS_DEAD_WALL_TILES,
    declaration_ev,
    estimate_win_value,
    ev_rank,
    opponent_hazards,
    remaining_draws,
    TileAccounting,
)
from taimahjong.reference_ev import (
    _policy_discard,
    evaluate_candidate,
    representative_reference_cases,
    standard_small_wall_state,
)
from taimahjong.rollout import (
    CalibratedRonClaim,
    _calibrated_claim_probabilities,
    _winner_distribution,
    resolve_terminal,
)
from taimahjong.scoring import (
    EARTHLY_TAI, HEAVENLY_TAI, SCHEME_3_1, SCHEME_5_2, WinContext, score_hand,
)
from taimahjong.selfplay import Player, _settlement
from taimahjong.simulate import TrialTrace, WinningTrial, _greedy_discard
from taimahjong.tiles import parse_tiles


TENPAI = parse_tiles("123m123p123s1112223z")
POST_DRAW = parse_tiles("123m123p123s11122233z")


def _tile(text: str) -> int:
    return next(index for index, count in enumerate(parse_tiles(text)) if count)


def _visible_with_opponent(opponent: OpponentView) -> tuple[int, ...]:
    counts = [0] * 34
    for entry in opponent.river:
        counts[entry if isinstance(entry, int) else entry.tile] += 1
    for meld in opponent.melds:
        for tile in meld:
            counts[tile] += 1
    return tuple(counts)


def _stand_pat_visible() -> tuple[int, ...]:
    visible = [4 - count for count in TENPAI]
    visible[29] = 0
    for tile in (4, 5, 6, 7, 8, 10, 11, 13, 14, 15, 16, 17, 19, 20, 22, 23, 24, 25, 26, 27, 28, 30, 31, 32, 33):
        visible[tile] -= 1
    return tuple(visible)


def test_part0_confirmed_scoring_totals():
    assert (HEAVENLY_TAI, EARTHLY_TAI) == (16, 8)
    dragons = parse_tiles("123m111555666777z22z")
    assert score_hand(dragons, (), WinContext(_tile("2z"))).total_tai == 19
    assert score_hand(dragons, (), WinContext(_tile("2z"), round_wind=_tile("1z"), seat_wind=_tile("1z"))).total_tai == 21
    winds = parse_tiles("111222333444555z66z")
    assert score_hand(winds, (), WinContext(_tile("6z"), self_draw=True)).total_tai == 48
    melds = [(0, 1, 2), (12, 13, 14), (24, 25, 26), (27, 27, 27), (31, 31, 31)]
    assert score_hand(parse_tiles("22z"), melds, WinContext(_tile("2z"))).total_tai == 4


def test_ev_rank_is_seed_deterministic_and_net_ev_is_signed_payment_mean():
    first = ev_rank(POST_DRAW, [], (0,) * 34, turns=3, sims=80, seed=19)
    assert first == ev_rank(POST_DRAW, [], (0,) * 34, turns=3, sims=80, seed=19)
    real = [entry for entry in first if not entry.is_fold]
    assert [entry.net_ev for entry in real] == sorted(
        (entry.net_ev for entry in real), reverse=True,
    )
    assert all(
        entry.net_ev == sum(entry.trial_values) / entry.sample_count
        for entry in first
    )
    assert all(
        entry.net_ev == pytest.approx(entry.attack_ev - entry.risk_ev)
        for entry in first
    )


def test_determinized_opponents_track_public_tenpai_state_and_conserve_tiles():
    hand = parse_tiles("123m456m789m11223p345s")
    river_tiles = (6, 7, 8, 14, 15, 16, 18, 19, 20, 21, 22, 23, 24, 25)

    def sampled_rate(opponent, samples=200):
        visible = _visible_with_opponent(opponent)
        acting_seat, seats, _ = ev._production_seats((opponent,), None)
        opponent_seat = next(
            seat for seat, view in enumerate(seats)
            if seat != acting_seat and view is opponent
        )
        tenpai = 0
        for index in range(samples):
            world = ev._sample_production_world(
                hand, visible, (opponent,), 8, None, 100_000 + index,
            )
            repeat = ev._sample_production_world(
                hand, visible, (opponent,), 8, None, 100_000 + index,
            )
            assert world == repeat
            concealed = world.players[opponent_seat].hand
            tenpai += ev._production_shanten(tuple(concealed), 0) == 0
            for tile in range(34):
                accounted = (
                    hand[tile]
                    + visible[tile]
                    + sum(
                        player.hand[tile]
                        for seat, player in enumerate(world.players)
                        if seat != acting_seat
                    )
                    + world.wall.count(tile)
                )
                assert accounted <= 4
        return tenpai / samples

    silent = OpponentView(list(river_tiles), [])
    threatening = OpponentView(
        [ev.RiverEntry(tile, "tsumogiri") for tile in river_tiles], [],
    )
    silent_rate = sampled_rate(silent)
    threatening_rate = sampled_rate(threatening)
    assert abs(silent_rate - ev.tenpai_score(silent, 14).score) < 0.08
    assert abs(threatening_rate - ev.tenpai_score(threatening, 14).score) < 0.08
    assert threatening_rate > silent_rate + 0.25

    declared = OpponentView(
        [ev.RiverEntry(6), ev.RiverEntry(7)], [], declared_at=1,
    )
    assert sampled_rate(declared, samples=32) == 1.0


def test_world_sampler_takes_tenpai_rates_from_the_calibration_table():
    # The self-play table measures the opponent tenpai rate directly; the
    # uncalibrated heuristic ran 3-20x above it early in the hand. With a
    # table the sampler follows it, and uses the heuristic only for a cell the
    # table does not cover (None).
    class TableCalibration:
        def __init__(self, rate):
            self.rate = rate

        def deal_in_probability(self, _danger_score):
            return 0.0

        def tenpai_probability(self, _melds, _turn, _run):
            return self.rate

    hand = parse_tiles("123m456m789m11223p345s")
    river_tiles = (6, 7, 8, 14, 15, 16, 18, 19, 20, 21, 22, 23, 24, 25)
    opponent = OpponentView(list(river_tiles), [])
    visible = _visible_with_opponent(opponent)
    acting_seat, seats, _ = ev._production_seats((opponent,), None)
    opponent_seat = next(
        seat for seat, view in enumerate(seats)
        if seat != acting_seat and view is opponent
    )

    def tenpai_share(calibration, samples=100):
        hits = 0
        for index in range(samples):
            world = ev._sample_production_world(
                hand, visible, (opponent,), 8, None, 200_000 + index,
                calibration=calibration,
            )
            hits += ev._production_shanten(
                tuple(world.players[opponent_seat].hand), 0,
            ) == 0
        return hits / samples

    assert tenpai_share(TableCalibration(0.0)) == 0.0
    assert tenpai_share(TableCalibration(1.0)) == 1.0
    heuristic = ev.tenpai_score(opponent, len(river_tiles)).score
    assert abs(tenpai_share(TableCalibration(None)) - heuristic) < 0.1


def test_calibrated_rank_is_exact_with_and_without_settlement_cache(monkeypatch):
    import taimahjong.rollout as rollout

    class FixedCalibration:
        def deal_in_probability(self, _danger_score):
            return 0.2

        def tenpai_probability(self, _melds, _turn, _run):
            return None

    def rank():
        return ev_rank(
            POST_DRAW, (), (0,) * 34, turns=2, sims=4, seed=19,
            exhaustive=True, calibration=FixedCalibration(),
        )

    cache = rollout._cached_ron_settlement
    cache.cache_clear()
    cached = rank()
    assert cache.cache_info().hits > 0
    monkeypatch.setattr(rollout, "_cached_ron_settlement", cache.__wrapped__)
    # Pin whole entries, including each trial's payment and ranking order.
    # A rounding tolerance would hide a key that loses settlement state.
    assert cached == rank()


def test_calibrated_ron_incremental_public_state_matches_fresh_callback():
    class FixedCalibration:
        def deal_in_probability(self, score):
            return min(0.3, score / 100)

    hand = parse_tiles("123m123p123s1112223z")
    value_hand = (parse_tiles("123m123p123s11122233z"), _tile("3z"))
    value_hands = (None, value_hand, value_hand, value_hand)
    players = [Player("attack", list(hand)) for _ in range(4)]
    players[2].declared_at = 0
    players[2].river = parse_river("9m")
    calibration = FixedCalibration()
    cached = ev._calibrated_ron(calibration, 0, value_hands)
    for step in range(12):
        discarder = step % 4
        tile = step % 9
        fresh = ev._calibrated_ron(calibration, 0, value_hands)
        assert cached(players, discarder, tile) == fresh(players, discarder, tile)
        # Terminal continuations append one public discard after each claim.
        players[discarder].river.append(ev.RiverEntry(tile))
    # The callback must reset when handed a new trial's player sequence.
    players = [Player("attack", list(hand)) for _ in range(4)]
    fresh = ev._calibrated_ron(calibration, 0, value_hands)
    assert cached(players, 0, 4) == fresh(players, 0, 4)


def test_calibrated_ron_prices_every_opponent_and_keeps_actor_physical():
    # The deal-in table counts every discard against every opponent, so its
    # rate already integrates over hidden hands. It must price an opponent
    # whatever that opponent's sampled hand is: firing it only when the sampled
    # hand waits on the tile multiplied the rate by that chance a second time
    # (deal-in risk 80-100x too low). The sampled hand only values the ron.
    class FixedCalibration:
        def deal_in_probability(self, _danger_score):
            return 0.2

    waiting = parse_tiles("123m123p123s1112223z")
    winning = parse_tiles("123456m123p123s333z9m")
    winning_tile = _tile("9m")
    value_hand = (parse_tiles("123m123p123s11122233z"), _tile("3z"))
    players = [Player("attack", list(waiting)) for _ in range(4)]
    players[2].hand = list(winning)
    claims = ev._calibrated_ron(
        FixedCalibration(), 0, (None, value_hand, value_hand, value_hand),
    )

    probabilities, estimates = _calibrated_claim_probabilities(
        players, 1, winning_tile, 0, claims,
    )
    distribution = _winner_distribution(probabilities, 1, ev.DEFAULT_RULES)

    completed_actor = list(players[0].hand)
    completed_actor[winning_tile] += 1
    assert ev._production_shanten(tuple(completed_actor), 0) == 0
    assert probabilities == {2: 0.2, 3: 0.2, 0: 0.0}
    assert distribution == pytest.approx({(2,): 0.2, (3,): 0.2, (): 0.6})
    # Seat 2 waits on the discard and is valued on it; seat 3 cannot win on
    # it and is valued by the world's value hand instead.
    completed_seat2 = list(winning)
    completed_seat2[winning_tile] += 1
    assert estimates[2].winning_hand == tuple(completed_seat2)
    assert estimates[2].scoring_tile == winning_tile
    assert (estimates[3].winning_hand, estimates[3].scoring_tile) == value_hand

    # The actor's own claim stays physical but keeps the nearest-claim order:
    # seats 2 and 3 sit between discarder 1 and the actor, so they claim first.
    players[0].hand = list(winning)
    players[2].hand = list(waiting)
    probabilities, _ = _calibrated_claim_probabilities(
        players, 1, winning_tile, 0, claims,
    )
    distribution = _winner_distribution(probabilities, 1, ev.DEFAULT_RULES)

    assert probabilities == pytest.approx({2: 0.2, 3: 0.2, 0: 0.6})
    assert distribution == pytest.approx({(2,): 0.2, (3,): 0.2, (0,): 0.6})
    assert distribution.get((), 0.0) == 0.0

    # Discarder 3 sits right before the actor: nobody is nearer.
    probabilities, _ = _calibrated_claim_probabilities(
        players, 3, winning_tile, 0, claims,
    )
    assert probabilities == {0: 1.0}
    assert _winner_distribution(probabilities, 3, ev.DEFAULT_RULES) == {(0,): 1.0}


def test_calibrated_opening_deal_in_matches_the_table_rate():
    # No draws left: the only RON chance is the opening discard, so the
    # deal-in mass must be the three opponents' table rates for every
    # candidate. The old gate fired a rate only when that opponent's sampled
    # hand waited on that very tile, so almost all of the mass went missing.
    class FixedCalibration:
        def deal_in_probability(self, _danger_score):
            return 0.2

        def tenpai_probability(self, _melds, _turn, _run):
            return None

    opponents = [
        OpponentView(parse_river(river), [])
        for river in ("9m9p1z", "4z5s6s", "7s8s9s")
    ]
    visible = [0] * 34
    for opponent in opponents:
        for count_index, count in enumerate(_visible_with_opponent(opponent)):
            visible[count_index] += count
    entries = ev_rank(
        POST_DRAW,
        opponents,
        tuple(visible),
        turns=0,
        sims=40,
        seed=17,
        calibration=FixedCalibration(),
        exhaustive=True,
    )

    assert entries
    for entry in entries:
        assert entry.p_draw == pytest.approx(1.0 - 3 * 0.2)
        assert entry.risk_ev > 0.0


def test_immediate_actor_deal_in_is_a_negative_terminal_payment():
    class CalibrationMustNotRun:
        def deal_in_probability(self, _danger_score):
            raise AssertionError("known rollout hands must remain physical")

    state = standard_small_wall_state(wall=())
    references = list(state.players)
    references[2] = replace(
        references[2],
        hand=parse_tiles("123456m123p123s333z6z"),
    )
    state = replace(state, players=tuple(references))
    players = tuple(
        Player(
            "attack",
            list(reference.hand),
            declared_at=reference.declared_at,
        )
        for reference in state.players
    )

    entries = ev_rank(
        state.players[state.acting_seat].hand,
        (),
        (0,) * 34,
        turns=0,
        sims=2,
        seed=11,
        calibration=CalibrationMustNotRun(),
        scheme=state.scheme,
        exhaustive=True,
        discard_policy=_policy_discard,
        rollout_players=players,
        rollout_wall=state.wall,
        acting_seat=state.acting_seat,
        next_seat=state.next_seat,
        dealer_streak=state.dealer_streak,
    )
    deal_in = next(
        entry for entry in entries
        if not entry.is_fold and entry.discard == _tile("6z")
    )

    assert deal_in.net_ev < 0
    assert deal_in.attack_ev == 0
    assert deal_in.risk_ev == -deal_in.net_ev
    assert len(set(deal_in.trial_values)) == 1


def test_determinized_rollout_has_physical_risk_without_calibration():
    class FixedCalibration:
        def deal_in_probability(self, _danger_score):
            return 1.0

        def tenpai_probability(self, _melds, _turn, _run):
            return None

    # The opponent has to be credibly close to tenpai for a physical deal-in to
    # be possible at all. Two melds and a seven-tile river put tenpai_score near
    # 0.556; a silent opponent on turn one sits near 0.018, because that is the
    # dealt hand and its true tenpai rate is zero. Demanding physical risk there
    # would be demanding a physical impossibility, not testing the channel.
    opponent = OpponentView(
        parse_river("9m9p1z4z5s6s7s"), [(4, 4, 4), (13, 13, 13)], None,
    )
    visible = parse_tiles("9m9p1z4z5s6s7s555m555p")
    uncalibrated = ev_rank(
        POST_DRAW,
        [opponent],
        visible,
        turns=0,
        sims=40,
        seed=17,
        exhaustive=True,
    )
    calibrated = ev_rank(
        POST_DRAW,
        [opponent],
        visible,
        turns=0,
        sims=40,
        seed=17,
        calibration=FixedCalibration(),
        exhaustive=True,
    )

    assert any(entry.risk_ev > 0.0 for entry in uncalibrated)
    # A table that says every discard deals in prices the opening discard as a
    # certain ron, whatever the sampled hands wait on.
    assert all(
        entry.p_draw == 0.0 and entry.attack_ev == 0.0 and entry.risk_ev > 0.0
        for entry in calibrated
    )
    assert all(
        entry.net_ev == entry.attack_ev - entry.risk_ev
        for entry in calibrated
    )


def test_calibrated_ron_is_one_zero_sum_terminal_payment():
    players = [Player("attack") for _ in range(4)]
    players[0].hand = list(POST_DRAW)
    terminal = resolve_terminal(
        players,
        (),
        0,
        1,
        _tile("1m"),
        _policy_discard,
        Random(1),
        calibrated_ron=lambda _players, _discarder, _tile: (
            CalibratedRonClaim(1, 1.0, 7),
        ),
    )

    assert terminal.kind == "opponent_ron"
    assert terminal.deltas == (-7, 7, 0, 0)
    assert terminal.value_units == 7
    assert terminal.ron_winners == (1,)


def test_calibrated_ron_cannot_override_the_actors_physical_hand():
    players = [Player("attack") for _ in range(4)]
    players[0].hand = list(parse_tiles("147m147p147s1234567z"))
    players[1].hand = list(parse_tiles("147m147p147s1234567z"))
    terminal = resolve_terminal(
        players,
        (_tile("9m"),),
        0,
        1,
        None,
        _policy_discard,
        Random(1),
        calibrated_ron=lambda _players, _discarder, _tile: (
            CalibratedRonClaim(0, 1.0, 7),
        ),
    )

    assert terminal.kind == "draw"
    assert terminal.deltas == (0, 0, 0, 0)
    assert terminal.ron_winners == ()


def test_calibrated_push_records_opening_discard_before_continuation():
    players = [Player("attack") for _ in range(4)]
    players[0].hand = list(POST_DRAW)
    for player in players[1:]:
        player.hand = list(TENPAI)
    snapshots = []

    def no_claims(current, _discarder, _tile):
        snapshots.append(tuple(len(player.river) for player in current))
        return ()

    resolve_terminal(
        players,
        (_tile("9m"),),
        0,
        1,
        _tile("1m"),
        lambda hand, _remaining, _melds: next(
            tile for tile, count in enumerate(hand) if count
        ),
        Random(1),
        calibrated_ron=no_claims,
    )

    assert snapshots[0][0] == 0
    assert snapshots[1][0] == 1


def test_calibrated_ron_hand_uses_physical_settlement_and_stays_zero_sum():
    players = [Player("attack") for _ in range(4)]
    players[0].hand = list(POST_DRAW)
    completed = parse_tiles("123456m123p123s333z66z")
    winning_tile = _tile("6z")
    hand_value = score_hand(
        completed, (), WinContext(winning_tile),
    ).value_units
    terminal = resolve_terminal(
        players,
        (),
        0,
        1,
        _tile("1m"),
        _policy_discard,
        Random(1),
        calibrated_ron=lambda _players, _discarder, _tile: (
            CalibratedRonClaim(
                1,
                1.0,
                winning_hand=completed,
                scoring_tile=winning_tile,
            ),
        ),
    )

    # Seat 0 is the dealer, so the physical ron settlement adds its bilateral
    # one-tai dealer leg to the non-dealer winner's hand value.
    assert terminal.deltas == (-(hand_value + 1), hand_value + 1, 0, 0)
    assert sum(terminal.deltas) == 0
    assert terminal.value_units == hand_value
    assert terminal.kind == "opponent_ron"
    assert terminal.ron_winners == (1,)


def test_declaration_dead_wait_is_zero_and_not_recommended():
    advice = declaration_ev(TENPAI, parse_tiles("333z"), turns=1, sims=20, seed=1)
    assert advice.declared.expected_win_ev == 0
    assert advice.declared.mean_value_units is None
    assert not advice.should_declare


def test_declaration_locked_branch_uses_exact_hypergeometric_and_migi_bonus():
    visible = _stand_pat_visible()
    turns = 5
    advice = declaration_ev(TENPAI, visible, turns=turns, sims=40, seed=3)
    pool = sum(4 - hand - seen for hand, seen in zip(TENPAI, visible))
    wins = 3
    expected = 1 - comb(pool - wins, turns) / comb(pool, turns)
    assert advice.declared.p_win == expected
    completed = list(TENPAI)
    completed[29] += 1
    no_migi = score_hand(tuple(completed), (), WinContext(29, self_draw=True)).value_units
    assert advice.declared.mean_value_units == no_migi + 8


def test_winning_trial_values_are_scored_as_self_draws():
    visible = _stand_pat_visible()
    estimate = estimate_win_value(TENPAI, turns=5, visible=visible, sims=1000, seed=4)
    completed = list(TENPAI)
    completed[29] += 1
    expected_value = score_hand(tuple(completed), (), WinContext(29, self_draw=True)).value_units
    assert estimate.p_win > 0
    assert estimate.mean_value_units == expected_value


def test_ev_simulation_threads_scheme_and_cache_keeps_scheme_specific_discard():
    completed = list(TENPAI)
    completed[29] += 1
    win = WinningTrial(tuple(completed), 29, 1)
    winning_schemes = []
    policy_schemes = []

    def fake_winning_trials(*_args, scheme=None):
        winning_schemes.append(scheme)
        return (win,)

    def fake_policy_trials(*_args, scheme=None):
        policy_schemes.append(scheme)
        return (TrialTrace(0, win),)

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(ev, "winning_trials", fake_winning_trials)
    monkeypatch.setattr(ev, "policy_trials", fake_policy_trials)
    try:
        three_one = estimate_win_value(TENPAI, turns=1, sims=1, scheme=SCHEME_3_1)
        five_two = estimate_win_value(TENPAI, turns=1, sims=1, scheme=SCHEME_5_2)
        ev._discounted_win_estimate(
            TENPAI, 1, 0, (0,) * 34, 1, 1, None, (1.0,), SCHEME_3_1,
        )
        ev._discounted_win_estimate(
            TENPAI, 1, 0, (0,) * 34, 1, 1, None, (1.0,), SCHEME_5_2,
        )
    finally:
        monkeypatch.undo()

    assert (three_one.net_ev, five_two.net_ev) == (6.0, 11.0)
    assert winning_schemes == [SCHEME_3_1, SCHEME_5_2]
    assert policy_schemes == [SCHEME_3_1, SCHEME_5_2]

    current = parse_tiles("33345777m333667778s")
    remaining = (
        2, 4, 0, 2, 1, 3, 1, 2, 4, 4, 1, 1, 0, 3, 3, 2, 4,
        2, 2, 0, 1, 4, 3, 0, 0, 3, 2, 4, 2, 1, 2, 3, 2, 1,
    )
    _greedy_discard.cache_clear()
    assert _greedy_discard(current, remaining, 0, SCHEME_3_1) == (24, 0)
    assert _greedy_discard(current, remaining, 0, SCHEME_5_2) == (25, 0)


def test_remaining_draws_uses_live_wall_and_four_seats():
    # Flowerless Taiwanese mahjong reserves 7 dun (14 tiles), leaving 57 -> 14;
    # the 48 tiles in three hidden opponent hands are not drawable.
    assert remaining_draws(POST_DRAW, (0,) * 34) == 14  # floor((136 - 14 - 17 - 48) / 4)
    assert remaining_draws(POST_DRAW, parse_tiles("9999m")) == 13  # four public tiles also left the wall


@pytest.mark.parametrize("kongs", range(5))
def test_derived_live_wall_retires_one_tile_per_declared_kong(kongs):
    from taimahjong.selfplay import KONG_DEAD_WALL_BACKFILL_TILES

    expected_live_wall = 136 - FLOWERLESS_DEAD_WALL_TILES - 17 - 3 * 16 - KONG_DEAD_WALL_BACKFILL_TILES * kongs
    assert remaining_draws(POST_DRAW, (0,) * 34, kongs=kongs) == expected_live_wall // 4


def test_explicit_live_wall_does_not_double_count_kongs():
    assert remaining_draws(POST_DRAW, wall_remaining=51, kongs=4) == 12


def test_revealed_kong_costs_the_wall_only_its_backfill_tile():
    """DEV-181: a declared kong shortens the live wall by its backfill tile only.

    Its four tiles sit in the owner's 16-tile holding, so passing them through
    ``TileAccounting.revealed_holdings`` must not deduct them from the wall as
    well. 136 - 14 dead - 17 own - 48 opponents - 1 backfill = 56 -> 14 draws;
    counting the kong's tiles too would give 52 -> 13.
    """
    kong_on_table = TileAccounting(revealed_holdings=parse_tiles("9999m"))
    assert remaining_draws(POST_DRAW, kong_on_table, kongs=1) == 14
    assert remaining_draws(POST_DRAW, kong_on_table, kongs=1) == remaining_draws(POST_DRAW, kongs=1)


@pytest.mark.parametrize("live_wall", [55, 7])
def test_automatic_horizon_stays_in_live_wall_and_preserves_actor_turn_order(live_wall):
    """Post-discard play starts downstream, so the actor gets floor(live/4) draws.

    The dead wall is reserved: a production world may not pad an incomplete
    table round with it just to give the actor one more draw.
    """
    seen = [0] * 34
    if live_wall < 55:
        needed_out_of_hands = 55 - live_wall
        for tile, available in enumerate(4 - count for count in POST_DRAW):
            taken = min(available, needed_out_of_hands)
            seen[tile] = taken
            needed_out_of_hands -= taken
            if not needed_out_of_hands:
                break
        assert needed_out_of_hands == 0
    turns = remaining_draws(POST_DRAW, tuple(seen), wall_remaining=live_wall)
    world = ev._sample_production_world(
        POST_DRAW, tuple(seen), (), turns, None, 20260904,
    )

    assert len(world.wall) <= live_wall
    # The next seat draws first; seat 1, 2, 3, then the actor at seat 0.
    assert sum(index % 4 == 3 for index in range(len(world.wall))) == turns


def test_declared_context_reaches_ev_rollout_scores_migi_and_locks_tsumogiri(monkeypatch):
    """A migi hand keeps its 8-tai declaration value and may only tsumogiri."""
    import taimahjong.rollout as rollout

    context = WinContext(winning_tile=_tile("3z"), migi_declared=True)
    world = ev._sample_production_world(
        POST_DRAW, (0,) * 34, (), 1, context, 20260904,
    )
    actor = 1
    assert world.players[actor].declared_at == 0

    _, value = _settlement(
        "tsumo", actor, None, list(world.players), POST_DRAW, _tile("3z"), 0,
    )
    # Seat 1 is South in an East round; settlement scores both winds (DEV-245).
    undeclared = score_hand(
        POST_DRAW, (), WinContext(
            _tile("3z"), self_draw=True,
            round_wind=_tile("1z"), seat_wind=_tile("2z"),
        ),
    ).value_units
    assert value == undeclared + 8

    # The rollout reaches the actor after three downstream draws.  If it asks
    # a declared actor's continuation policy to choose, it could tedashi from
    # the concealed hand, which is illegal after a migi declaration.
    monkeypatch.setattr(rollout, "_cached_shanten", lambda *_: 0)
    def concealed_discard(*_args):
        pytest.fail("a declared actor must tsumogiri instead of using policy")

    resolve_terminal(
        world.players, (0, 1, 2, 3), actor, (actor + 1) % 4, _tile("3z"),
        lambda hand, *_: next(tile for tile, count in enumerate(hand) if count),
        Random(3), acting_discard_policy=concealed_discard, visible=(0,) * 34,
    )


def test_declared_opponent_locks_tsumogiri_in_terminal_rollout(monkeypatch):
    """A declared opponent cannot reshape its frozen hand with tedashi."""
    import taimahjong.rollout as rollout

    def hand(start: int) -> list[int]:
        counts = [0] * 34
        for tile in range(start, start + 4):
            counts[tile] = 4
        return counts

    players = [
        Player("attack", hand(0)),
        Player("attack", hand(4), declared_at=0),
        Player("attack", hand(8)),
        Player("attack", hand(12)),
    ]
    monkeypatch.setattr(rollout, "_cached_shanten", lambda *_: 0)

    def tedashi_policy(*_args):
        pytest.fail("a declared opponent must tsumogiri instead of using policy")

    resolve_terminal(
        players, (16,), 0, 1, 0, tedashi_policy, Random(3),
    )


@pytest.mark.parametrize(
    ("out_of_hands", "revealed_holdings", "expected_turns"),
    [
        ("9m", "", 14),
        ("9m", "111p", 14),  # the same opponent tiles merely become an open pon
        ("9m9p", "111p777s", 13),  # multiple opponents' chi/pon holdings
        ("9m9p12z", "111p777s8888m", 13),  # several melds plus a revealed kong
    ],
)
def test_live_wall_accounting_separates_discards_from_revealed_holdings(
    out_of_hands, revealed_holdings, expected_turns,
):
    accounting = TileAccounting(
        parse_tiles(out_of_hands) if out_of_hands else (0,) * 34,
        parse_tiles(revealed_holdings) if revealed_holdings else (0,) * 34,
    )
    assert remaining_draws(POST_DRAW, accounting) == expected_turns


def test_explicit_wall_and_derived_accounting_return_the_same_turns():
    accounting = TileAccounting(
        parse_tiles("9m9p12z"),
        parse_tiles("111p777s8888m"),
    )
    derived_live_wall = 136 - FLOWERLESS_DEAD_WALL_TILES - sum(POST_DRAW) - 3 * 16 - 4
    assert remaining_draws(POST_DRAW, accounting) == remaining_draws(
        POST_DRAW, accounting, wall_remaining=derived_live_wall,
    )


def test_opponent_tsumo_payment_is_included_in_actor_ev():
    case = next(
        case
        for case in representative_reference_cases()
        if case.strata.branch_character == "opponent-tsumo"
    )
    exact = {
        discard: evaluate_candidate(case.state, discard)
        for discard in case.state.legal_discards
    }
    target = next(
        discard
        for discard, evaluation in exact.items()
        if any(
            outcome.outcome.kind == "opponent_tsumo"
            and outcome.outcome.payment.deltas[case.state.acting_seat] < 0
            for outcome in evaluation.outcomes
        )
    )
    players = tuple(
        Player(
            "attack",
            list(reference.hand),
            declared_at=reference.declared_at,
        )
        for reference in case.state.players
    )
    entry = next(
        entry
        for entry in ev_rank(
            case.state.players[case.state.acting_seat].hand,
            (),
            (0,) * 34,
            turns=1,
            sims=24,
            seed=case.seed,
            scheme=case.state.scheme,
            exhaustive=True,
            discard_policy=_policy_discard,
            rollout_players=players,
            rollout_wall=case.state.wall,
            acting_seat=case.state.acting_seat,
            next_seat=case.state.next_seat,
            dealer_streak=case.state.dealer_streak,
        )
        if not entry.is_fold and entry.discard == target
    )

    assert entry.net_ev == float(exact[target].actor_ev)
    assert any(payment < 0 for payment in entry.trial_values)


def test_folded_opponent_contributes_zero_hazard():
    folding = OpponentView(parse_river("1234z"), [], None)
    safety_source = OpponentView(parse_river("1234z"), [], None)
    assert FOLD_HAZARD_CUTOFF == 0.60
    assert opponent_hazards([folding, safety_source])[0] == 0.0


def test_own_river_can_make_an_opponent_folded_for_survival_hazard():
    target = OpponentView(parse_river("1m1p1s"), [], None)
    own_river = parse_river("1m1p1s")

    assert opponent_hazards([target])[0] > 0.0
    assert opponent_hazards([target], own_river)[0] == 0.0


def test_production_rank_does_not_call_legacy_attack_composition(monkeypatch):
    # net_ev must come from coherent terminal payments, never from a separately
    # estimated attack term. The additive decomposition helpers this once also
    # guarded are gone; _discounted_win_estimate survives only for the
    # declaration advisor and must still stay out of the ranking path.
    def fail(*args, **kwargs):
        raise AssertionError("legacy attack estimator entered production rank")

    monkeypatch.setattr(ev, "_discounted_win_estimate", fail)

    ranked = ev_rank(
        POST_DRAW, [], (0,) * 34, turns=1, sims=2, seed=19, exhaustive=True,
    )
    assert ranked


def test_crn_reuses_the_same_wall_order_for_every_candidate(monkeypatch):
    import taimahjong.rollout as rollout

    state = standard_small_wall_state()
    players = tuple(
        Player(
            "attack",
            list(reference.hand),
            declared_at=reference.declared_at,
        )
        for reference in state.players
    )
    choices = {}

    def fake_terminal(
        players, wall, acting_seat, next_seat, discard, discard_policy, rng,
        **kwargs,
    ):
        choices.setdefault(discard, []).append(
            None if not wall else rng.randrange(len(wall))
        )
        return rollout.TerminalMixture(((
            1.0,
            rollout.TerminalResult("draw", None, None, None, (0, 0, 0, 0), 0),
        ),))

    monkeypatch.setattr(
        rollout, "resolve_terminal_distribution", fake_terminal,
    )
    ev_rank(
        state.players[state.acting_seat].hand,
        (),
        (0,) * 34,
        turns=1,
        sims=12,
        seed=47,
        exhaustive=True,
        discard_policy=_policy_discard,
        rollout_players=players,
        rollout_wall=state.wall,
        acting_seat=state.acting_seat,
        next_seat=state.next_seat,
    )

    schedules = [schedule[:12] for schedule in choices.values()]
    assert schedules
    assert all(schedule == schedules[0] for schedule in schedules[1:])


def test_fold_and_push_with_same_discard_have_separate_terminal_cache(monkeypatch):
    import taimahjong.rollout as rollout

    calls = []

    def fake_terminal(
        players, wall, acting_seat, next_seat, discard, discard_policy, rng,
        **kwargs,
    ):
        defensive = kwargs["acting_discard_policy"] is not None
        calls.append((discard, defensive))
        payment = -1 if defensive else 1
        deltas = [0, 0, 0, 0]
        deltas[acting_seat] = payment
        deltas[(acting_seat + 1) % 4] = -payment
        return rollout.TerminalMixture(((
            1.0,
            rollout.TerminalResult("draw", None, None, None, tuple(deltas), 0),
        ),))

    monkeypatch.setattr(
        rollout, "resolve_terminal_distribution", fake_terminal,
    )
    ranked = ev_rank(
        POST_DRAW, [], (0,) * 34,
        turns=1, sims=2, seed=19, exhaustive=True,
    )
    fold = next(entry for entry in ranked if entry.is_fold)
    push = next(
        entry
        for entry in ranked
        if not entry.is_fold and entry.discard == fold.discard
    )

    assert calls.count((fold.discard, False)) == 2
    assert calls.count((fold.discard, True)) == 2
    assert push.trial_values == (1.0, 1.0)
    assert fold.trial_values == (-1.0, -1.0)


def test_legacy_draw_value_cannot_change_zero_payment_draw_terminals(monkeypatch):
    baseline = {entry.discard: entry for entry in ev_rank(POST_DRAW, [], (0,) * 34, turns=3, sims=80, seed=19) if not entry.is_fold}
    assert DRAW_VALUE == 0.0
    monkeypatch.setattr(ev, "DRAW_VALUE", 2.5)
    shifted = {entry.discard: entry for entry in ev_rank(POST_DRAW, [], (0,) * 34, turns=3, sims=80, seed=19) if not entry.is_fold}
    for tile, before in baseline.items():
        after = shifted[tile]
        assert after.trial_values == before.trial_values
        assert after.net_ev == before.net_ev


def test_defense_policy_is_last_labeled_and_has_an_executable_first_discard():
    opponent = OpponentView(parse_river("123456789m"), [], None)
    entries = ev_rank(POST_DRAW, [opponent], _visible_with_opponent(opponent), turns=3, sims=80, seed=19, top_k=10)
    fold = entries[-1]
    real = entries[:-1]
    assert fold.is_fold and fold.label == "defense_policy"
    assert fold.action_plan is not None
    assert fold.discard == fold.action_plan.first_discard
    assert POST_DRAW[fold.discard] > 0
    assert fold.action_plan.principles


def test_opponent_value_estimate_scales_with_dealer_streak():
    # Dealing into the dealer settles the bilateral premium, so the defender's
    # loss-magnitude read must be +1 for a dealer at streak 0 and +2 more per
    # repeat — the exact gradient that makes a streaking dealer scarier.
    river = parse_river("1m3m5p")
    peer = OpponentView(list(river), [], None)
    base = ev.opponent_value_estimate(peer)
    values = [
        ev.opponent_value_estimate(OpponentView(list(river), [], None, is_dealer=True, dealer_streak=streak))
        for streak in range(4)
    ]
    assert values[0] - base == ev.OPPONENT_DEALER_TAI
    assert [value - values[0] for value in values] == [0, 2, 4, 6]


def test_deal_in_ev_rises_against_dealer():
    # The risk term that drives folding must respond: the same danger tile is a
    # larger expected loss when the modeled opponent is the streaking dealer.
    opponent_peer = OpponentView(parse_river("123456789m"), [], None)
    opponent_dealer = OpponentView(parse_river("123456789m"), [], None, is_dealer=True, dealer_streak=2)
    tile = _tile("5s")
    visible = _visible_with_opponent(opponent_peer)
    peer_risk = ev.deal_in_ev(tile, opponent_peer, visible, POST_DRAW, None)
    dealer_risk = ev.deal_in_ev(tile, opponent_dealer, visible, POST_DRAW, None)
    assert dealer_risk > peer_risk


def test_defensive_policy_buys_safety_with_win_equity_when_nothing_threatens():
    """Why the defensive rule must not become production's unconditional default.

    The empirical game over ``{efficiency, deal_in_risk}`` makes all-defensive
    the unique equilibrium of the shallow endgame, which reads as an argument
    for shipping :func:`ev._defensive_discard_policy` as the rollout default.
    Measured 2026-08-27 on the 26 reference cases at 60 worlds, that swap costs
    0.835 tai of mean actor EV and triples exploitability (0.556 -> 1.684), and
    the loss is concentrated in cases where *no opponent has declared tenpai*.

    This pins the mechanism on the six cases that pay the most.  The defensive
    rule does not break its own tenpai there -- both rules stay at shanten 0 --
    it narrows the wait, trading a third of its live winning tiles for a tile
    that is marginally safer against opponents who are not threatening at all.
    A rule that earns its place has to condition on whether defence is called
    for; this test fails once one does, which is exactly when it should.
    """
    from taimahjong.best_response import observation_for
    from taimahjong.ev import _defensive_discard_policy, _production_discard_policy

    def live_waits(hand: tuple[int, ...], belief: tuple[int, ...]) -> int:
        return sum(
            belief[tile]
            for tile in range(34)
            if hand[tile] < 4
            and ev._production_shanten(
                tuple(count + (tile == index) for index, count in enumerate(hand)), 0,
            ) == -1
        )

    cases = [
        case for case in representative_reference_cases()
        if case.name.startswith("actor-tsumo-tenpai") and "threat-none" in case.name
    ]
    assert len(cases) == 6, "the corpus block this documents has changed size"

    for case in cases:
        observation = observation_for(case)
        belief = observation.belief_remaining()
        assert ev._production_shanten(observation.hand, 0) == 0, case.name

        measured = {}
        for label, policy in (
            ("production", _production_discard_policy),
            ("defensive", _defensive_discard_policy),
        ):
            discard = policy(observation.hand, belief, 0)
            after = list(observation.hand)
            after[discard] -= 1
            after = tuple(after)
            # Neither rule may drop tenpai here; the cost is in the wait, and
            # a broken tenpai would mean this test documents the wrong thing.
            assert ev._production_shanten(after, 0) == 0, (case.name, label)
            measured[label] = live_waits(after, belief)

        assert measured["defensive"] < measured["production"], case.name


@pytest.mark.parametrize("seat", [1, 2, 3])
def test_production_world_preserves_actor_seat_wind(seat):
    context = WinContext(0, seat_wind=27 + seat)
    opponents = tuple(OpponentView([], [], is_dealer=i == 0) for i in range(3))
    acting, views, _ = ev._production_seats(opponents, context)
    assert acting == seat
    assert tuple(view for view in views if view is not None) == opponents
    hand = parse_tiles("123m456m123p789s333z55p")
    world = ev._sample_production_world(hand, (0,) * 34, opponents, 0, context, 13)
    assert tuple(world.players[seat].hand) == hand
    _, value = _settlement("tsumo", acting, None, list(world.players), hand, 0)
    assert value == (6 if seat == 2 else 5)


def test_production_world_keeps_real_wall_end_beyond_horizon():
    template = ev.WinValueContext(WinContext(0), wall_remaining=17)
    world = ev._sample_production_world(POST_DRAW, (0,) * 34, (), 4, template, 13)
    assert len(world.wall) == 16
    assert world.wall_remaining == 17


@pytest.mark.parametrize("live_draw", [False, True])
def test_ev_opening_draw_context_reaches_terminal(live_draw):
    winning = parse_tiles("111m456789p234s55789s")
    tile = 19
    players = [Player("attack", list(parse_tiles("147m147p147s1234567z"))) for _ in range(4)]
    players[1].hand = list(winning)
    players[1].hand[tile] -= 1
    players[0].hand[tile] = 1
    ranked = ev_rank(
        tuple(players[0].hand), (), (0,) * 34, sims=1,
        rollout_players=players, rollout_wall=(), acting_seat=0,
        context_template=ev.WinValueContext(
            WinContext(0), wall_remaining=0, opening_live_draw=live_draw,
        ),
        _target_discard=tile,
    )
    ordinary, _ = _settlement("ron", 1, 0, players, winning, tile)
    assert ranked[0].net_ev == ordinary[0] - int(live_draw)
