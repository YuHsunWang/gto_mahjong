"""Whole-hand continuation invariants, information boundaries, and pairing."""

from copy import deepcopy
from dataclasses import replace
import hashlib
import importlib.util
import json
from pathlib import Path
from random import Random

import pytest

spec = importlib.util.spec_from_file_location("midgame_deviation_check", Path(__file__).resolve().parents[1] / "scripts" / "midgame_deviation_check.py")
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)
from taimahjong.danger import RiverEntry, rank_discards
from taimahjong.midgame_corpus import (
    MidgameCase, build_corpus, case_document, case_from_document, sample_case, stage_for,
)
from taimahjong.midgame_game import (
    BASE_PROFILE, STRATEGIES, actor_shanten, bootstrap_interval, choose_discard,
    finish_case, paired_case_gains, profiles, reshuffled_wall,
)
from taimahjong.selfplay import (
    Player, _assert_conservation, _decision_snapshot, play_game,
)
from taimahjong.tiles import parse_tiles


ATTACK = ("attack",) * 4
MIXED = ("attack", "cautious", "attack", "cautious")

# Captured from the unmodified engine before this refactor. Include complete
# events, point deltas, turns, scoring and kong metadata, not just winners.
@pytest.mark.parametrize("seed,policies,kong,digest", [
    (1, ATTACK, "none", "257a15a44ae138ff5284cc87b68f6fabef8a24c6494704bd6cceb47bded3eb09"),
    (1, MIXED, "none", "a7d9fcd6d67143464ae8510ac146c0527937e5389ed6d220a743d724d95d8652"),
    (1, ATTACK, "all", "133a8c1c0f0eca60940443a7e43fb1a26e9bf01b3bd9be2b720835cf276ab55d"),
    (941, ATTACK, "none", "9ebc61255a37d29d48360988e85dcef8a4c74630ccf2198451432f2fb4e3693e"),
    (941, MIXED, "none", "0329d265c652ad373eb1c70661d92d1bd83349b4ade9f33398625150472b8ce0"),
    (941, ATTACK, "all", "64181a87e74a4820f76ee130f39e5c7165dccf56aa653cb5fd288e08369e417f"),
    (20260754, ATTACK, "none", "ed2af139b1f1d8f04854df43e7d4fdb3d5e27e935bd65410f15c9a59220ecc1e"),
    (20260754, MIXED, "none", "063dd1d98d2e1da8368b14c93b312096b4320d8b002190ae56baf2c567a2c218"),
    (20260754, ATTACK, "all", "ed2af139b1f1d8f04854df43e7d4fdb3d5e27e935bd65410f15c9a59220ecc1e"),
])
def test_existing_fixed_seed_outputs_unchanged(seed, policies, kong, digest):
    result = play_game(seed, policies, kong_policy=kong)
    assert hashlib.sha256(repr(result.summary()).encode()).hexdigest() == digest


@pytest.fixture(scope="module")
def corpus():
    return build_corpus(6, 1)


def test_real_wall_resume_matches_original_payoffs_and_is_not_mutating(corpus):
    for case in corpus:
        before = case_document(case)
        restored = case_from_document(json.loads(json.dumps(before)))
        assert finish_case(restored, ATTACK).point_deltas == case.original_payoffs
        assert case_document(case) == before
        _assert_conservation(restored.state.players, restored.state.wall, restored.state.dead)


@pytest.mark.parametrize("seed,kong", [(0, "concealed_added"), (1, "none"), (23, "concealed_added"), (941, "all"), (20260754, "concealed_added")])
def test_every_pre_discard_resume_matches_full_original_trace(seed, kong):
    states = []
    original = play_game(seed, ATTACK, kong_policy=kong, dealer_streak=2,
                         state_hook=lambda state: states.append(deepcopy(state)))
    if seed in (0, 23):
        assert original.outcome == {0: "tsumo", 23: "draw"}[seed]
    assert any(state.drawn_tile is None for state in states), "cover post-call continuation"
    for state in states:
        resumed = play_game(policies=ATTACK, initial_state=state)
        assert resumed.summary() == original.summary()
        if not any(player.declared for player in state.players):
            case = MidgameCase(seed, 1, 1, state, original.point_deltas)
            restored = case_from_document(json.loads(json.dumps(case_document(case))))
            assert finish_case(restored, ATTACK).summary() == original.summary()


def test_corpus_is_reproducible_and_never_contains_declarations(corpus):
    repeated = build_corpus(len(corpus), 1)
    assert [case_document(case) for case in corpus] == [case_document(case) for case in repeated]
    assert len({case.game_seed for case in corpus}) == len(corpus)
    assert any(case.state.drawn_tile is None for case in corpus)
    assert any(case.state.drawn_tile is not None for case in corpus)
    for case in corpus:
        assert not any(player.declared for player in case.state.players)
        assert 1 <= case.decision_index <= case.eligible_decisions
        assert case.stage == stage_for(case.wall_remaining)


def test_reservoir_uses_every_eligible_point_including_last(monkeypatch):
    # Observe the bounded RNG draws rather than trusting a particular seed's
    # chosen point. The last draw must be allowed to replace every earlier one.
    bounds = []

    class LastPoint:
        def __init__(self, seed):
            pass

        def randrange(self, bound):
            bounds.append(bound)
            return 0

    import taimahjong.midgame_corpus as module
    monkeypatch.setattr(module, "Random", LastPoint)
    case = sample_case(1, 9)
    assert bounds == list(range(1, case.eligible_decisions + 1))
    assert case.decision_index == case.eligible_decisions


@pytest.mark.parametrize("remaining,stage", [(0, "late"), (19, "late"), (20, "mid"), (38, "mid"), (39, "early"), (58, "early")])
def test_stage_cut_points(remaining, stage):
    assert stage_for(remaining) == stage


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_discard_does_not_depend_on_concealed_opponent_or_wall(corpus, strategy):
    case = corpus[0]
    left = deepcopy(case.state)
    right = deepcopy(left)
    opponent = (left.current + 1) % 4
    # Swap one hidden opponent tile with a different hidden wall tile. Both
    # resulting states are physical, with the same public table and counts.
    old = next(tile for tile, count in enumerate(right.players[opponent].hand) if count)
    index = next(index for index, tile in enumerate(right.wall) if tile != old)
    new = right.wall[index]
    right.players[opponent].hand[old] -= 1
    right.players[opponent].hand[new] += 1
    right.wall[index] = old
    Random(71).shuffle(right.wall)
    _assert_conservation(right.players, right.wall, right.dead)
    observation = _decision_snapshot(left.current, left.drawn_tile, left.players, len(left.wall))
    other = _decision_snapshot(right.current, right.drawn_tile, right.players, len(right.wall))
    assert observation == other
    assert choose_discard(observation, strategy) == choose_discard(other, strategy)


@pytest.mark.parametrize("hand,attacking", [
    ("123456m123p123s12367z", {"tenpai_attack": False, "one_shanten_attack": False}),
    ("123456m123p123s11567z", {"tenpai_attack": False, "one_shanten_attack": True}),
    ("123456m123p123s111z56z", {"tenpai_attack": True, "one_shanten_attack": True}),
])
def test_attack_thresholds_use_post_discard_shanten(hand, attacking):
    # Make the snapshot from public engine adapters; it contains no wall.
    players = [Player("attack") for _ in range(4)]
    players[0].hand = list(parse_tiles(hand))
    observation = _decision_snapshot(0, 31, players)
    for strategy, expected in attacking.items():
        _, folding = choose_discard(observation, strategy)
        assert folding is not expected
    assert choose_discard(observation, "attack")[1] is False
    assert choose_discard(observation, "fold")[1] is True


def test_fold_matches_river_aware_ranking_with_efficiency_ties(corpus):
    case = corpus[0]
    state = case.state
    observation = _decision_snapshot(state.current, state.drawn_tile, state.players, len(state.wall))
    by_opponent = [rank_discards(observation.hand, opponent, observation.public_counts,
                                len(observation.melds) + len(observation.kongs))
                   for _, opponent in observation.opponents]
    efficiency = [row.analysis.discard for row in by_opponent[0]]
    danger = {tile: max(next(row.expected_danger for row in rows if row.analysis.discard == tile)
                        for rows in by_opponent) for tile in efficiency}
    expected = min(efficiency, key=lambda tile: (danger[tile], efficiency.index(tile)))
    assert choose_discard(observation, "fold") == (expected, True)
    # Supplying a declared-safe river should materially change danger evidence.
    safe_tile = next(tile for tile in efficiency if observation.hand[tile] + observation.public_counts[tile] <= 2)
    public_opponent = replace(observation.opponents[0][1], river=[RiverEntry(safe_tile), RiverEntry(safe_tile)],
                              melds=[], declared_at=0, discard_count=2)
    visible = list(observation.public_counts)
    visible[safe_tile] += 2
    rows = rank_discards(observation.hand, public_opponent, visible,
                         len(observation.melds) + len(observation.kongs))
    assert next(row.expected_danger for row in rows if row.analysis.discard == safe_tile) == 0


def test_profiles_and_self_gains_are_exactly_zero(corpus):
    assert len(profiles()) == len(set(profiles())) == 13
    assert profiles()[0] == BASE_PROFILE
    assert all(sum(a != b for a, b in zip(profile, BASE_PROFILE)) == 1 for profile in profiles()[1:])
    table = []
    for case in corpus[:2]:
        actor = case.state.current
        row = []
        for seed in range(2):
            result = finish_case(case, BASE_PROFILE, wall=reshuffled_wall(case, seed))
            row.append(tuple(result.point_deltas[(actor + role) % 4] for role in range(4)))
        table.append(row)
    for role in range(4):
        assert paired_case_gains(table, table, role) == (0.0, 0.0)


def test_wall_randomization_preserves_everything_else(corpus):
    case = corpus[0]
    before = case_document(case)
    wall = reshuffled_wall(case, 31)
    assert wall == reshuffled_wall(case, 31)
    assert wall != tuple(case.state.wall)
    assert sorted(wall) == sorted(case.state.wall)
    finish_case(case, BASE_PROFILE, wall=wall)
    assert case_document(case) == before
    with pytest.raises(ValueError, match="multiset"):
        finish_case(case, BASE_PROFILE, wall=wall[:-1])


def test_bootstrap_clusters_worlds_inside_cases():
    base = [[[0] * 4, [0] * 4], [[0] * 4, [0] * 4]]
    other = [[[0, 2, 0, 0], [0, 6, 0, 0]], [[0, -1, 0, 0], [0, -3, 0, 0]]]
    values = paired_case_gains(base, other, 1)
    assert values == (4.0, -2.0)
    assert bootstrap_interval(values, seed=1) == {"cases": 2, "mean_gain": 1.0, "ci95": [-2.0, 4.0]}
    assert bootstrap_interval((), seed=1) == {"cases": 0, "mean_gain": None, "ci95": None}


def test_checkpoint_resume_replays_only_interrupted_world_and_pairs_profiles(tmp_path, monkeypatch):
    checkpoint = tmp_path / "checkpoint.json"
    original_finish = cli.finish_case
    seen = []

    def interrupted(case, profile, *, wall):
        seen.append((profile, wall))
        if len(seen) == 18:
            raise RuntimeError("simulated interruption")
        return original_finish(case, profile, wall=wall)

    monkeypatch.setattr(cli, "finish_case", interrupted)
    with pytest.raises(RuntimeError, match="interruption"):
        cli.run(cases=1, sims=2, seed=1, checkpoint=checkpoint)
    saved = json.loads(checkpoint.read_text())
    assert len(saved["worlds"][0]) == 1
    assert len({wall for _, wall in seen[:13]}) == 1
    assert tuple(profile for profile, _ in seen[:13]) == profiles()
    case = case_from_document(saved["corpus"][0])
    assert case.state.current != 0, "exercise actor-relative payoff rotation"
    expected = original_finish(case, BASE_PROFILE, wall=seen[0][1]).point_deltas
    assert saved["worlds"][0][0][0] == [expected[(case.state.current + role) % 4] for role in range(4)]
    monkeypatch.setattr(cli, "finish_case", original_finish)
    resumed = cli.run(cases=1, sims=2, seed=1, checkpoint=checkpoint, resume=True)
    uninterrupted_path = tmp_path / "uninterrupted.json"
    uninterrupted = cli.run(cases=1, sims=2, seed=1, checkpoint=uninterrupted_path)
    assert resumed["deviations"] == uninterrupted["deviations"]
    assert json.loads(checkpoint.read_text())["worlds"] == json.loads(uninterrupted_path.read_text())["worlds"]
    assert resumed["base_self_gain_by_role"] == [[0.0]] * 4
    assert len(resumed["deviations"]) == 12
    assert set(resumed["deviations"][0]["by_stage"]) == {"early", "mid", "late"}
    assert set(resumed["deviations"][0]["by_actor_shanten"]) == {"tenpai", "1-shanten", "2+-shanten"}
    with pytest.raises(ValueError, match="differ"):
        cli.run(cases=1, sims=3, seed=1, checkpoint=checkpoint, resume=True)
    with pytest.raises(ValueError, match="exists"):
        cli.run(cases=1, sims=2, seed=1, checkpoint=checkpoint)
