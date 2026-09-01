"""Cross-layer provenance and legacy meld/kong compatibility."""

import pytest

from server.api import _parse_melds, _position_payload
from taimahjong.__main__ import _parse_opponent_melds
from taimahjong.danger import (
    DeclaredKong,
    DeclaredMeld,
    OpponentView,
    RiverEntry,
    danger_score,
    kong_tiles,
)
from taimahjong.ev import ev_rank, opponent_value_estimate
from taimahjong.quiz import QuizOpponent, QuizPosition, _position_from
from taimahjong.scoring import WinContext, score_hand
from taimahjong.selfplay import Player, _declare_kong, play_game
from taimahjong.tiles import parse_tiles


def test_bare_triples_keep_public_scoring_danger_and_ev_results():
    """Legacy parsers and public numerical entry points remain metadata-blind."""
    assert _parse_opponent_melds("123m") == [(0, 1, 2)]
    assert _parse_melds("123m") == [(0, 1, 2)]

    bare_scoring_melds = [
        (0, 1, 2),
        (12, 13, 14),
        (24, 25, 26),
        (27, 27, 27),
        (31, 31, 31),
    ]
    rich_scoring_melds = [
        DeclaredMeld(meld, meld[0], index % 4, index + 1)
        for index, meld in enumerate(bare_scoring_melds)
    ]
    bare_score = score_hand(
        parse_tiles("22z"), bare_scoring_melds, WinContext(winning_tile=28),
    )
    assert bare_score.total_tai == 4
    assert score_hand(
        parse_tiles("22z"), rich_scoring_melds, WinContext(winning_tile=28),
    ) == bare_score

    visible = [0] * 34
    for tile in (0, 1, 2):
        visible[tile] += 1
    bare_danger = danger_score(
        4, OpponentView([], [(0, 1, 2)]), visible, [0] * 34,
    )
    rich_danger = danger_score(
        4,
        OpponentView([], [DeclaredMeld((0, 1, 2), 2, 3, 8)]),
        visible,
        [0] * 34,
    )
    assert bare_danger.score == 13.0
    assert rich_danger == bare_danger

    hand = parse_tiles("123m123p123s11122233z")
    ev_visible = [0] * 34
    ev_visible[8] = 1
    ev_visible[9] = 3
    ev_kwargs = {
        "melds_declared": 0,
        "turns": 1,
        "sims": 2,
        "seed": 17,
        "top_k": 2,
    }
    bare_opponent = OpponentView(
        [RiverEntry(8)], [(9, 9, 9)], hand_count=13,
    )
    rich_opponent = OpponentView(
        [RiverEntry(8)], [DeclaredMeld((9, 9, 9), 9, 2, 4)], hand_count=13,
    )
    bare_ev = ev_rank(hand, [bare_opponent], ev_visible, **ev_kwargs)
    rich_ev = ev_rank(hand, [rich_opponent], ev_visible, **ev_kwargs)
    # A snapshot of which candidates survive screening, not a claim about
    # which discard is best: the screening pilot draws its own worlds, so a
    # two-trial budget decides this set from a sample the entries never use.
    assert [(entry.discard, entry.net_ev) for entry in bare_ev] == [
        (0, 4.0),
        (1, 3.0),
        (27, 0.0),
        (27, 0.0),
    ]
    assert rich_ev == bare_ev
    assert opponent_value_estimate(OpponentView([], [(31, 31, 31)])) == 4.0
    assert opponent_value_estimate(
        OpponentView([], [DeclaredMeld((31, 31, 31), 31, 0, 1)])
    ) == 4.0


@pytest.mark.parametrize("seat", [-1, 4, True])
def test_declared_meld_rejects_out_of_range_source_seats(seat):
    with pytest.raises(ValueError, match="called_from_seat"):
        DeclaredMeld((0, 1, 2), 2, seat, 1)


@pytest.mark.parametrize("discard_number", [0, -1, True])
def test_declared_meld_rejects_non_positive_discard_numbers(discard_number):
    with pytest.raises(ValueError, match="called_from_discard_number"):
        DeclaredMeld((0, 1, 2), 2, 3, discard_number)


def test_declared_meld_validates_shape_called_tile_and_all_or_null_provenance():
    with pytest.raises(ValueError, match="called_tile must occur"):
        DeclaredMeld((0, 1, 2), 3, 1, 1)
    with pytest.raises(ValueError, match="all be null or all be known"):
        DeclaredMeld((0, 1, 2), called_tile=2)
    with pytest.raises(ValueError, match="three tile indices"):
        DeclaredMeld((0, 1))
    with pytest.raises(ValueError, match="three tile indices"):
        DeclaredMeld((0, 1, 34))


def test_position_payload_preserves_legacy_arrays_and_adds_aligned_details():
    own_known = DeclaredMeld((3, 4, 5), 5, 3, 8)
    own_legacy = (6, 6, 6)
    opponent_known = DeclaredMeld((18, 18, 18), 18, 1, 6)
    opponent_legacy = (19, 20, 21)
    opponent = QuizOpponent(
        seat=2,
        river=(),
        melds=(opponent_known, opponent_legacy),
        declared_at=None,
        tenpai_estimate=0.5,
        fold_estimate=0.0,
    )
    position = QuizPosition(
        seed=1,
        seat=0,
        turn=1,
        drawn_tile=0,
        hand=(0,) * 34,
        own_river=(),
        own_melds=(own_known, own_legacy),
        opponents=(opponent,),
        public_counts=(0,) * 34,
        visible_counts=(0,) * 34,
        shanten=0,
        draws_remaining=1,
        wall_remaining=4,
        candidate_ev_gap=0.0,
        own_kongs=(DeclaredKong(22, False, 2, 4), (23, True)),
    )

    payload = _position_payload(position)
    assert payload["own_melds"] == [[3, 4, 5], [6, 6, 6]]
    assert payload["opponents"][0]["melds"] == [
        [18, 18, 18],
        [19, 20, 21],
    ]
    assert [detail["tiles"] for detail in payload["own_meld_details"]] == payload["own_melds"]
    assert [
        detail["tiles"] for detail in payload["opponents"][0]["meld_details"]
    ] == payload["opponents"][0]["melds"]
    assert payload["own_meld_details"][0] == {
        "tiles": [3, 4, 5],
        "called_tile": 5,
        "called_from_seat": 3,
        "called_from_discard_number": 8,
    }
    assert payload["opponents"][0]["meld_details"][0] == {
        "tiles": [18, 18, 18],
        "called_tile": 18,
        "called_from_seat": 1,
        "called_from_discard_number": 6,
    }
    for detail in (
        payload["own_meld_details"][1],
        payload["opponents"][0]["meld_details"][1],
    ):
        assert detail["called_tile"] is None
        assert detail["called_from_seat"] is None
        assert detail["called_from_discard_number"] is None
    assert payload["own_kong_details"] == [
        {
            "tile": 22,
            "concealed": False,
            "called_from_seat": 2,
            "called_from_discard_number": 4,
        },
        {
            "tile": 23,
            "concealed": True,
            "called_from_seat": None,
            "called_from_discard_number": None,
        },
    ]


def _selfplay_payloads(seed: int) -> list[dict]:
    payloads = []
    play_game(
        seed,
        snapshot_hook=lambda snapshot: payloads.append(
            _position_payload(_position_from(snapshot, seed))
        ),
    )
    return payloads


def _payload_melds(payload: dict):
    for legacy, detail in zip(payload["own_melds"], payload["own_meld_details"]):
        yield payload["seat"], legacy, detail
    for opponent in payload["opponents"]:
        for legacy, detail in zip(opponent["melds"], opponent["meld_details"]):
            yield opponent["seat"], legacy, detail


@pytest.mark.parametrize(
    ("seed", "owner", "tiles", "called_tile", "source", "discard_number"),
    [
        (1, 3, [14, 14, 14], 14, 1, 1),
        (2, 2, [15, 16, 17], 17, 1, 3),
    ],
    ids=("pon", "chi"),
)
def test_selfplay_call_provenance_reaches_the_position_payload(
    seed, owner, tiles, called_tile, source, discard_number,
):
    match = None
    source_river = None
    for payload in _selfplay_payloads(seed):
        for row in _payload_melds(payload):
            if row[0] == owner and row[1] == tiles:
                match = row[2]
                if payload["seat"] == source:
                    source_river = payload["own_river"]
                else:
                    source_river = next(
                        opponent["river"]
                        for opponent in payload["opponents"]
                        if opponent["seat"] == source
                    )
                break
        if match is not None:
            break

    assert match == {
        "tiles": tiles,
        "called_tile": called_tile,
        "called_from_seat": source,
        "called_from_discard_number": discard_number,
    }
    # The stable number is the source player's ordinal before the claimed tile
    # was removed, not its now-shorter river slot.
    assert len(source_river) == discard_number - 1


def test_big_open_kong_records_source_while_added_and_concealed_kongs_do_not():
    game = play_game(32, ("attack",) * 4, kong_policy="all")
    big_open, added = game.kongs
    assert isinstance(big_open, DeclaredKong)
    assert kong_tiles(big_open) == (32, False)
    assert tuple(big_open) == (32, False)
    assert big_open.called_from_seat == 2
    assert big_open.called_from_discard_number == 3
    assert any(
        event["seat"] == big_open.called_from_seat
        and event["turn"] == big_open.called_from_discard_number
        for event in game.events
    )
    assert isinstance(added, DeclaredKong) and not added.concealed
    assert added.called_from_seat is None
    assert added.called_from_discard_number is None

    player = Player("attack")
    player.hand[4] = 4
    _declare_kong(player, 4, True, [5])
    concealed = player.kongs[-1]
    assert isinstance(concealed, DeclaredKong) and concealed.concealed
    assert concealed.called_from_seat is None
    assert concealed.called_from_discard_number is None


@pytest.mark.parametrize(
    "kwargs",
    [
        {"called_from_seat": -1, "called_from_discard_number": 1},
        {"called_from_seat": 4, "called_from_discard_number": 1},
        {"called_from_seat": 1, "called_from_discard_number": 0},
        {"called_from_seat": 1, "called_from_discard_number": -1},
    ],
)
def test_declared_kong_validates_source_provenance(kwargs):
    with pytest.raises(ValueError):
        DeclaredKong(0, False, **kwargs)
