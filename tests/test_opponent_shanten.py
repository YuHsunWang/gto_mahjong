"""DEV-120: the sampled opponents must occupy the middle of the distribution.

Before this model, a hand that failed the tenpai draw was filled by drawing
uniformly from the unseen pool. Uniform draws land on 3-shanten and worse
nearly every time, so a sampled opponent was either waiting or nearly
hopeless and the 1- and 2-shanten hands that actually apply pressure were
missing. These tests hold the sampler to the distribution self-play observed.
"""

import random
from pathlib import Path

import pytest

from taimahjong.calibration import MIN_CELL_COUNT
from taimahjong.danger import OpponentView, parse_river
from taimahjong.ev import (
    _construct_shanten_hand,
    _default_opponent_shanten,
    _production_seats,
    _production_shanten,
    _sample_production_world,
)
from taimahjong.opponent_shanten import (
    OpponentShanten,
    cell_key,
    counts_from_games,
    document,
    view_key,
)
from taimahjong.tiles import parse_tiles


DOCUMENT_PATH = Path(__file__).parents[1] / "data" / "opponent-shanten.json"


class _Game:
    def __init__(self, events):
        self.events = events


def _event(melds=0, turn=8, run=0, shanten=2):
    return {
        "melds": melds,
        "turn": turn,
        "tsumogiri_run": run,
        "true_shanten": shanten,
    }


def _threatening_view(turn=8, suit="s"):
    """An opponent on a long tsumogiri run: high tenpai score."""
    river = parse_river(f"1*2*3*4*5*6*7*8*{suit}")[:turn]
    return OpponentView(list(river), [], hand_count=16)


def _quiet_view(turn=8, suit="m"):
    """The same turn count, but every discard came from the hand."""
    river = parse_river(f"1.2.3.4.5.6.7.8.{suit}")[:turn]
    return OpponentView(list(river), [], hand_count=16)


def test_cell_key_matches_the_tenpai_table_key_shape():
    # The conditioning must be literally the tenpai table's, so the two
    # models describe the same partition of public states.
    assert cell_key(0, 3, 0) == "0|1-6|0"
    assert cell_key(2, 8, 2) == "2|7-12|1-2"
    assert cell_key(1, 15, 5) == "1|13+|3+"


def test_view_key_reads_the_public_state_the_way_tenpai_score_does():
    assert view_key(_threatening_view(turn=8), 8) == "0|7-12|3+"
    assert view_key(_quiet_view(turn=8), 8) == "0|7-12|0"


def test_counts_refuse_events_without_a_recorded_shanten():
    stale = _Game([{"melds": 0, "turn": 8, "tsumogiri_run": 0}])
    with pytest.raises(ValueError, match="true_shanten"):
        counts_from_games([stale])


def test_counts_drop_winning_hands_and_tally_the_rest():
    games = [_Game([_event(shanten=-1), _event(shanten=1), _event(shanten=1)])]
    assert counts_from_games(games) == {"0|7-12|0": {"1": 2}}


def test_backoff_walks_to_the_coarsest_cell_with_enough_mass():
    # The exact cell holds one observation, far under the lookup minimum, so
    # the model must not price a distribution off it.
    counts = {
        "0|7-12|0": {"1": 1},
        "0|7-12|3+": {"2": MIN_CELL_COUNT},
        "3|1-6|0": {"4": MIN_CELL_COUNT},
    }
    model = OpponentShanten(document(counts))
    sparse = model.distribution(_quiet_view(turn=8), 8)
    # Pooled over run bucket: 1 observation at shanten 1 is still under the
    # minimum, so it keeps backing off until the pooled cells qualify.
    assert sparse
    assert sum(probability for _, probability in sparse) == pytest.approx(1.0)
    populated = model.distribution(_threatening_view(turn=8), 8)
    assert populated == ((2, 1.0),)


def test_distribution_is_conditional_on_not_being_tenpai():
    counts = {"0|7-12|0": {"0": 500, "1": 30, "2": 70}}
    model = OpponentShanten(document(counts))
    distribution = dict(model.distribution(_quiet_view(turn=8), 8))
    # The tenpai mass belongs to tenpai_score, not here, so it is excluded
    # from the normalisation rather than shrinking the other cells.
    assert distribution == {1: pytest.approx(0.3), 2: pytest.approx(0.7)}


def test_sample_is_an_inverse_transform_over_the_conditional_mass():
    counts = {"0|7-12|0": {"0": 100, "1": 30, "2": 70}}
    model = OpponentShanten(document(counts))
    view = _quiet_view(turn=8)
    assert model.sample(view, 8, 0.0) == 1
    assert model.sample(view, 8, 0.29) == 1
    assert model.sample(view, 8, 0.31) == 2
    assert model.sample(view, 8, 0.999) == 2


def test_a_cell_with_no_non_tenpai_mass_declines_to_invent_a_shape():
    model = OpponentShanten(document({"0|7-12|0": {"0": 50}}))
    assert model.distribution(_quiet_view(turn=8), 8) == ()
    assert model.sample(_quiet_view(turn=8), 8, 0.5) is None


@pytest.mark.parametrize("target", [0, 1, 2, 3, 4])
def test_constructed_hands_sit_at_exactly_their_target_shanten(target):
    rng = random.Random(20260901 + target)
    built = 0
    for _ in range(40):
        hand = _construct_shanten_hand([4] * 34, 16, 0, target, rng)
        if hand is None:
            continue
        built += 1
        assert sum(hand) == 16
        assert all(0 <= count <= 4 for count in hand)
        assert _production_shanten(tuple(hand), 0) == target
    # Rejection sampling cannot reach 1- and 2-shanten at any useful rate,
    # which is why the walk exists; it must succeed nearly always.
    assert built >= 38


def test_constructed_hands_come_out_of_the_declared_pool():
    rng = random.Random(7)
    # Only three suits' worth of tiles are available; the constructor must
    # never hand back a tile the pool did not hold.
    remaining = [4] * 27 + [0] * 7
    hand = _construct_shanten_hand(remaining, 16, 0, 2, rng)
    assert hand is not None
    assert all(hand[tile] == 0 for tile in range(27, 34))
    assert all(hand[tile] <= remaining[tile] for tile in range(34))


@pytest.mark.skipif(
    not DOCUMENT_PATH.exists(), reason="opponent-shanten document not built",
)
def test_sampled_worlds_reproduce_the_observed_distribution():
    model = _default_opponent_shanten()
    assert model is not None, "the committed document must load"

    # Distinct suits per river keep the unseen pool wide enough that hand
    # construction is not fighting for the last copies of a tile.
    views = (
        _threatening_view(turn=8, suit="s"),
        _quiet_view(turn=8, suit="m"),
        _quiet_view(turn=8, suit="m"),
    )
    hand = parse_tiles("123456789p1234567z")
    seen = tuple(
        sum(entry.tile == tile for view in views for entry in view.river)
        for tile in range(34)
    )
    acting_seat, _, _ = _production_seats(views, None)
    observed: dict[int, int] = {}
    non_tenpai = 0
    for trial in range(150):
        world = _sample_production_world(
            hand, seen, views, 8, None, 5_000 + trial,
        )
        for seat, player in enumerate(world.players):
            if seat == acting_seat:
                continue  # the acting seat holds the known hand
            distance = _production_shanten(tuple(player.hand), len(player.melds))
            if distance <= 0:
                continue
            non_tenpai += 1
            observed[distance] = observed.get(distance, 0) + 1

    assert non_tenpai >= 300, "too few non-tenpai opponents to judge the shape"
    middle = sum(observed.get(distance, 0) for distance in (1, 2)) / non_tenpai
    # The failure this test exists for: uniform pool draws put essentially
    # nothing on 1- and 2-shanten. Self-play puts roughly half the non-tenpai
    # mass there, so anything under a fifth means the model is not reaching
    # the sampler.
    assert middle >= 0.20, f"the middle of the distribution is empty: {observed}"

    predicted = dict(model.distribution(_quiet_view(turn=8), 8))
    sampled = {
        distance: count / non_tenpai for distance, count in observed.items()
    }
    total_variation = 0.5 * sum(
        abs(sampled.get(distance, 0.0) - predicted.get(distance, 0.0))
        for distance in set(sampled) | set(predicted)
    )
    # Three seats share one pool and two of them read a different cell, so
    # exact agreement is not expected; a gross mismatch means the wiring,
    # not the sampling noise, is wrong.
    assert total_variation <= 0.30, f"sampled {sampled} against {predicted}"


def test_the_sampler_still_works_with_no_document(monkeypatch):
    monkeypatch.setattr(
        "taimahjong.ev._default_opponent_shanten", lambda: None,
    )
    views = (
        _threatening_view(turn=8, suit="s"),
        _quiet_view(turn=8, suit="m"),
        _quiet_view(turn=8, suit="m"),
    )
    hand = parse_tiles("123456789p1234567z")
    seen = tuple(
        sum(entry.tile == tile for view in views for entry in view.river)
        for tile in range(34)
    )
    world = _sample_production_world(hand, seen, views, 8, None, 99)
    for player in world.players:
        assert sum(player.hand) + 3 * len(player.melds) == 16
