"""#128: an opponent's concealed-kong tile is hidden information.

A real player sees that the opponent holds a concealed kong, never which tile.
If the tile leaks, practice scores are computed with information the player
does not have (e.g. "no 白 left"), so these tests swap the hidden tile and
require every decision input and the API payload to stay identical.
"""

from server import api
from taimahjong.danger import RiverEntry, danger_score
from taimahjong.quiz import _position_from
from taimahjong.ev import ev_rank
from taimahjong.selfplay import Player, _decision_snapshot, _default_calibration
from taimahjong.trainer import _trainer_position

WHITE, GREEN = 31, 32


def _counts(tiles):
    counts = [0] * 34
    for tile in tiles:
        counts[tile] += 1
    return counts


def _table(hidden_tile):
    # Seat 1 holds a concealed kong; nobody else holds or shows 白 or 發.
    players = [
        Player("attack", _counts([0, 1, 2, 3, 4, 5, 9, 10, 11, 12, 13, 18, 19, 20, 21, 22])),
        Player("attack", _counts([6, 7, 8, 14, 15, 16, 23, 24, 25, 27, 27, 28, 28])),
        Player("attack", _counts([0, 1, 2, 3, 4, 5, 9, 10, 11, 12, 13, 18, 19, 20, 21, 22])),
        Player("attack", _counts([6, 7, 8, 14, 15, 16, 23, 24, 25, 29, 29, 30, 30, 26, 26, 17])),
    ]
    players[1].kongs.append((hidden_tile, True))
    players[1].river.append(RiverEntry(33))
    players[1].discards = 1
    return players


def _decision_inputs(snapshot):
    views = [
        (seat, view.melds, view.set_count, view.concealed_kongs, view.hand_count)
        for seat, view in snapshot.opponents
    ]
    post = list(snapshot.hand)
    post[0] -= 1
    dangers = [
        danger_score(0, view, snapshot.public_counts, tuple(post)).score
        for _, view in snapshot.opponents
    ]
    return snapshot.public_counts, views, dangers


def test_opponent_concealed_kong_tile_never_reaches_decision_inputs():
    white = _decision_snapshot(0, None, _table(WHITE))
    green = _decision_snapshot(0, None, _table(GREEN))
    assert white.public_counts[WHITE] == 0
    assert _decision_inputs(white) == _decision_inputs(green)
    seat_one = dict(white.opponents)[1]
    assert seat_one.melds == [] and seat_one.set_count == 1


def test_opponent_concealed_kong_tile_never_reaches_payload():
    builders = (
        lambda players: _position_from(_decision_snapshot(0, None, players), 1),
        lambda players: _trainer_position(0, None, players, 50, 1),
    )
    for build in builders:
        white, green = (api._position_payload(build(_table(tile))) for tile in (WHITE, GREEN))
        assert white == green
        kong = next(o for o in white["opponents"] if o["seat"] == 1)["kong_details"][0]
        assert kong["tile"] is None and kong["concealed"] is True


def test_ev_rank_samples_the_hidden_kong_without_seeing_it():
    # The world sampler must draw the hidden tile itself; it used to overcount
    # that kind (>4 copies) when building ron value hands.
    results = []
    for tile in (WHITE, GREEN):
        players = _table(tile)
        players[0].hand[14] += 1  # the drawn tile
        position = _trainer_position(0, 14, players, 50, 1)
        ranked = ev_rank(
            position.hand, [o.view() for o in position.opponents], position.public_counts,
            0, position.draws_remaining, 20, 1, calibration=_default_calibration(),
        )
        results.append([(entry.discard, entry.net_ev) for entry in ranked])
    assert results[0] == results[1]


def test_own_concealed_kong_stays_visible_to_its_owner():
    players = _table(WHITE)
    assert _decision_snapshot(1, None, players).public_counts[WHITE] == 4
    payload = api._position_payload(_trainer_position(1, None, players, 50, 1))
    assert payload["own_kong_details"][0]["tile"] == WHITE
