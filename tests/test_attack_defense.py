"""Attack/defense is two independent public-information questions per hand."""

from copy import deepcopy
from dataclasses import replace
from functools import lru_cache

import pytest
from fastapi.testclient import TestClient

from server import api
from taimahjong.attack_defense import grade, recommendation, risk_levels
from taimahjong.danger import kong_tiles, meld_tiles
from taimahjong.midgame_corpus import sample_case
from taimahjong.midgame_exit import case_observation
from taimahjong.midgame_game import choose_discard, discard_risks
from taimahjong.selfplay import _cached_analysis


@lru_cache(maxsize=None)
def case(game_seed=1, selection_seed=2):
    return sample_case(game_seed, selection_seed)


@pytest.mark.parametrize("seeds", [(1, 2), (2, 3), (3, 4), (5, 6)])
def test_correct_sets_match_engine_and_grade_every_legal_choice(seeds):
    observation = case_observation(case(*seeds))
    analyses = _cached_analysis(
        observation.hand, len(observation.melds) + len(observation.kongs), observation.public_counts,
    )
    best_shanten = min(item.shanten_after for item in analyses)
    best_ukeire = max(item.total for item in analyses if item.shanten_after == best_shanten)
    attacks = sorted(item.discard for item in analyses if (item.shanten_after, item.total) == (best_shanten, best_ukeire))
    risks = {tile: risk for risk, _, tile in discard_risks(observation)}
    defenses = sorted(tile for tile, risk in risks.items() if risk == min(risks.values()))
    for item in analyses:
        result = grade(observation, item.discard, item.discard)
        assert result["attack"]["correct_tiles"] == attacks
        assert result["defense"]["correct_tiles"] == defenses
        assert result["attack"]["correct"] is (item.discard in attacks)
        assert result["defense"]["correct"] is (item.discard in defenses)
        assert result["attack"]["ukeire"] == item.total
        assert result["attack"]["best_ukeire"] == best_ukeire
        assert result["shanten_after"] == best_shanten
        assert result["recommendation"] == recommendation(observation, best_shanten)
        assert result["attack"]["risk_level"] == risk_levels(risks)[item.discard]
        assert result["defense"]["risk_level"] == risk_levels(risks)[item.discard]
        assert result["shared_tiles"] == sorted(set(attacks) & set(defenses))


def test_fixed_seeds_exercise_both_kinds_of_ties_and_both_overlap_outcomes():
    attack_tie = grade(case_observation(case(5, 6)), 1, 1)
    defense_tie = grade(case_observation(case(2, 3)), 29, 29)
    overlap = grade(case_observation(case()), 33, 33)
    separate = grade(case_observation(case(3, 4)), 26, 29)
    assert attack_tie["attack"]["correct_tiles"] == [1, 14, 32]
    assert defense_tie["defense"]["correct_tiles"] == [29, 31]
    assert overlap["shared_tiles"] == [33]
    assert separate["shared_tiles"] == []


@pytest.mark.parametrize("risks, expected", [
    ({0: 1}, {0: "安全"}),
    ({0: 7, 1: 7, 2: 7}, {0: "安全", 1: "安全", 2: "安全"}),
    ({0: 0, 1: 1, 2: 2}, {0: "安全", 1: "普通", 2: "危險"}),
    ({0: 0, 1: 1, 2: 2, 3: 3}, {0: "安全", 1: "安全", 2: "普通", 3: "危險"}),
    # Ties straddling either third keep their lowest competition rank.
    ({0: 0, 1: 1, 2: 1, 3: 2, 4: 2, 5: 3},
     {0: "安全", 1: "安全", 2: "安全", 3: "普通", 4: "普通", 5: "危險"}),
])
def test_risk_thirds_including_boundary_ties(risks, expected):
    assert risk_levels(risks) == expected


@pytest.mark.parametrize("wall, shanten, strategy, verdict", [
    (9, 0, "keep_safe", "已經聽牌：不要拆聽，能聽的牌裡打最安全的"),
    (9, 1, "fold", "該下車，之後一路打安全牌"),
    (9, 2, "fold", "該下車，之後一路打安全牌"),
    (10, 0, "attack", "該進攻"),
    (10, 1, "keep_safe", "不拆一向聽，挑安全的打"),
    (10, 2, "fold", "該下車，之後一路打安全牌"),
    (19, 0, "attack", "該進攻"),
    (19, 1, "keep_safe", "不拆一向聽，挑安全的打"),
    (19, 2, "fold", "該下車，之後一路打安全牌"),
    (20, 0, "attack", "該進攻"),
    (20, 1, "attack", "該進攻"),
    (20, 2, "attack", "該進攻"),
    (0, 1, "fold", "該下車，之後一路打安全牌"),
    (58, 2, "attack", "該進攻"),
])
def test_verdict_wall_shanten_boundaries_and_engine_recommendation(wall, shanten, strategy, verdict):
    observation = replace(case_observation(case(3, 4)), wall_remaining=wall)
    assert recommendation(observation, shanten) == {
        "strategy": strategy, "verdict": verdict,
        "tile": choose_discard(observation, strategy)[0],
    }


def test_public_payload_and_grading_ignore_hidden_tile_values():
    original = case()
    changed = deepcopy(original)
    for seat, player in enumerate(changed.state.players):
        if seat != changed.state.current:
            # Keep hand sizes but change all concealed values, even impossibly.
            player.hand = [sum(player.hand)] + [0] * 33
    changed.state.wall[:] = [33] * len(changed.state.wall)
    changed.state.dead[:] = [32] * len(changed.state.dead)
    payload = api._attack_defense_payload(original)
    assert api._attack_defense_payload(changed) == payload
    assert grade(case_observation(original), 33, 33) == grade(case_observation(changed), 33, 33)
    assert set(payload) == {
        "seat", "dealer_seat", "is_dealer", "dealer_streak", "turn", "drawn_tile",
        "hand", "own_river", "own_melds", "own_meld_details", "own_kong_details",
        "opponents", "wall_remaining",
    }
    for opponent in payload["opponents"]:
        assert set(opponent) == {
            "seat", "river", "melds", "meld_details", "kong_details",
            "hand_count", "is_dealer", "dealer_streak",
        }
    assert payload["hand"] == original.state.players[original.state.current].hand
    assert payload["drawn_tile"] == original.state.drawn_tile


def test_public_table_preserves_every_river_meld_and_four_tile_kong():
    original = case()  # Includes an opponent kong.
    payload = api._attack_defense_payload(original)
    assert [p["seat"] for p in payload["opponents"]] == [(payload["seat"] + i) % 4 for i in (1, 2, 3)]
    actor = original.state.players[payload["seat"]]
    assert payload["own_river"] == api._river_payload(actor.river)
    assert payload["own_meld_details"] == [api._meld_detail_payload(m) for m in actor.melds]
    assert payload["own_kong_details"] == [api._kong_detail_payload(k) for k in actor.kongs]
    origins = {entry["origin"] for entry in payload["own_river"]}
    kongs = 0
    for opponent in payload["opponents"]:
        player = original.state.players[opponent["seat"]]
        assert opponent["river"] == api._river_payload(player.river)
        origins.update(entry["origin"] for entry in opponent["river"])
        assert opponent["melds"] == [list(meld_tiles(m)) for m in player.melds] + [[kong_tiles(k)[0]] * 4 for k in player.kongs]
        assert opponent["kong_details"] == [api._kong_detail_payload(k) for k in player.kongs]
        kongs += len(opponent["kong_details"])
    assert kongs > 0
    assert origins == {"tsumogiri", "tedashi"}
    assert payload["dealer_seat"] == 0
    assert payload["wall_remaining"] == original.wall_remaining


def test_stateless_api_recreates_case_and_grades_both_taps_and_all_ties():
    with TestClient(api.app) as client:
        seeds = {"game_seed": 5, "selection_seed": 6}
        created = client.post("/api/attack-defense/new", json=seeds)
        assert created.status_code == 200
        assert set(created.json()) == {"game_seed", "selection_seed", "position"}
        assert {key: created.json()[key] for key in seeds} == seeds
        observation = case_observation(case(5, 6))
        expected = grade(observation, 1, 1)
        for attack in expected["attack"]["correct_tiles"]:
            for defense in expected["defense"]["correct_tiles"]:
                api._attack_defense_case.cache_clear()  # No dependency on /new or a session.
                body = {**seeds, "attack_tile": attack, "defense_tile": defense}
                first = client.post("/api/attack-defense/grade", json=body)
                assert first.status_code == 200
                assert first.json()["grade"] == grade(observation, attack, defense)
                assert first.json()["grade"]["attack"]["correct"] is True
                assert first.json()["grade"]["defense"]["correct"] is True
                api._attack_defense_case.cache_clear()
                assert client.post("/api/attack-defense/grade", json=body).json() == first.json()


def test_api_grades_wrong_taps_independently_and_rejects_illegal_choices():
    with TestClient(api.app) as client:
        seeds = {"game_seed": 3, "selection_seed": 4}
        for attack, defense, correct in [(26, 29, (True, True)), (29, 26, (False, False)), (26, 26, (True, False)), (29, 29, (False, True))]:
            response = client.post("/api/attack-defense/grade", json={**seeds, "attack_tile": attack, "defense_tile": defense})
            assert response.status_code == 200
            result = response.json()["grade"]
            assert (result["attack"]["correct"], result["defense"]["correct"]) == correct
        missing = next(tile for tile, count in enumerate(case_observation(case(3, 4)).hand) if not count)
        for field in ("attack_tile", "defense_tile"):
            for invalid in (missing, -1, 34, True, "26"):
                body = {**seeds, "attack_tile": 26, "defense_tile": 29, field: invalid}
                assert client.post("/api/attack-defense/grade", json=body).status_code == 422
        assert client.post("/api/attack-defense/new", json={}).status_code == 200
        assert client.post("/api/attack-defense/grade", json={}).status_code == 422
