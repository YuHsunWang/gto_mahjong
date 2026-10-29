"""Exit decisions: actor isolation, public features, sampling and paired worlds."""

from collections import Counter
from copy import deepcopy
import csv
import hashlib
import importlib.util
import json
from pathlib import Path
from random import Random

import pytest

spec = importlib.util.spec_from_file_location("midgame_exit_check", Path(__file__).resolve().parents[1] / "scripts" / "midgame_exit_check.py")
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)
from taimahjong import midgame_corpus as corpus_module
from taimahjong import midgame_game as game_module
from taimahjong.danger import rank_discards, tenpai_score
from taimahjong.midgame_corpus import (
    build_corpus, build_stratified_corpus, case_document, case_from_document,
)
from taimahjong.midgame_exit import (
    ACTOR_PROFILES, case_observation, decision_features, finish_actor_case,
)
from taimahjong.midgame_game import choose_discard, finish_case, reshuffled_wall
from taimahjong.selfplay import _assert_conservation, play_game


ATTACK = ("attack",) * 4


@pytest.fixture(scope="module")
def cases():
    return build_stratified_corpus(3, 1)


def test_legacy_corpus_golden_output():
    # Captured on this branch before adding stratification, including full
    # states, selected indices, original payoffs, and seed draw order.
    data = [case_document(case) for case in build_corpus(6, 1)]
    assert hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest() == "f2feb1658cbbad5c6a20a0f41a110ff81494ccc1cb7b2bc961d15df6a0d6234f"


def test_max_wall_corpus_only_samples_the_endgame_window():
    # The "near exhaustion" question needs cases only where the wall is short.
    endgame = build_corpus(4, 1, max_wall=9)
    assert all(case.wall_remaining <= 9 for case in endgame)
    assert [case_document(case) for case in endgame] == [case_document(case) for case in build_corpus(4, 1, max_wall=9)]
    for case in endgame:
        assert not any(player.declared for player in case.state.players)
        assert finish_case(case, ATTACK).point_deltas == case.original_payoffs


def test_stratified_counts_reproducible_undeclared_one_per_game(cases):
    repeated = build_stratified_corpus(3, 1)
    assert [case_document(case) for case in cases] == [case_document(case) for case in repeated]
    assert Counter(case.stage for case in cases) == {"early": 3, "mid": 3, "late": 3}
    assert len({case.game_seed for case in cases}) == len(cases)
    for case in cases:
        assert not any(player.declared for player in case.state.players)
        assert all(player.policy == "attack" for player in case.state.players)
        assert finish_case(case, ATTACK).point_deltas == case.original_payoffs
        assert case_from_document(json.loads(json.dumps(case_document(case)))) == case


def test_stratified_reservoir_uniform_over_still_needed_points(monkeypatch):
    # Inspect reservoir bounds directly: all and only eligible decisions in
    # the needed stages get consecutive 1/k replacement probabilities.
    bounds = []
    wall_sizes = []

    class LastPoint:
        def __init__(self, seed):
            pass

        def randrange(self, bound):
            bounds.append(bound)
            return 0

    original_play = corpus_module.play_game

    def observed(*args, state_hook, **kwargs):
        def capture(state):
            if not any(player.declared for player in state.players) and len(state.wall) <= 38:
                wall_sizes.append(len(state.wall))
            state_hook(state)
        return original_play(*args, state_hook=capture, **kwargs)

    monkeypatch.setattr(corpus_module, "Random", LastPoint)
    monkeypatch.setattr(corpus_module, "play_game", observed)
    case = corpus_module.sample_case(23, 7, eligible_stages=frozenset(("mid", "late")))
    assert bounds == list(range(1, len(wall_sizes) + 1))
    assert case.decision_index == case.eligible_decisions == len(wall_sizes)
    assert case.wall_remaining == wall_sizes[-1]
    assert any(20 <= remaining <= 38 for remaining in wall_sizes)
    assert any(remaining <= 19 for remaining in wall_sizes)


def test_dodge_real_wall_matches_single_override_replay_and_trace(cases, monkeypatch):
    case = next(case for case in cases if not decision_features(case_observation(case))["attack_equals_safest"])
    before = case_document(case)
    calls = []
    original_choose = game_module.choose_discard

    def observed(observation, strategy):
        calls.append((observation, strategy))
        return original_choose(observation, strategy)

    monkeypatch.setattr(game_module, "choose_discard", observed)
    actual = finish_actor_case(case, "dodge_once")
    assert calls[0][0] == case_observation(case)
    assert [strategy for _, strategy in calls] == ["fold"] + ["attack"] * (len(calls) - 1)
    assert any(obs.seat == case.state.current for obs, _ in calls[1:]), "cover later actor decisions"
    assert any(obs.seat != case.state.current for obs, _ in calls[1:])
    # A different initial tile can change future draws/calls/wins. Compare the
    # complete trace to an independent all-attack replay with ONLY its first
    # discard replaced, rather than requiring impossible unchanged futures.
    first = True

    def single_override(observation):
        nonlocal first
        strategy = "fold" if first else "attack"
        first = False
        return original_choose(observation, strategy)

    expected = play_game(policies=ATTACK, initial_state=case.state, discard_policy=single_override)
    assert actual.summary() == expected.summary()
    baseline = finish_case(case, ATTACK)
    start = len(case.state.events)
    assert actual.events[:start] == baseline.events[:start]
    assert original_choose(calls[0][0], "fold")[0] != original_choose(calls[0][0], "attack")[0]
    assert case_document(case) == before


def test_equal_initial_tiles_give_exact_attack_payoffs(cases):
    equal = [case for case in cases if decision_features(case_observation(case))["attack_equals_safest"]]
    assert equal, "exercise the no-op dodge case"
    for case in equal:
        for wall in (None, reshuffled_wall(case, 9), reshuffled_wall(case, 17)):
            attack = finish_actor_case(case, "attack", wall=wall)
            dodge = finish_actor_case(case, "dodge_once", wall=wall)
            assert attack.point_deltas == dodge.point_deltas
            # Fold-active is diagnostics only; every physical event matches.
            assert [{k: v for k, v in event.items() if k != "fold_policy_active"} for event in attack.events] == [
                {k: v for k, v in event.items() if k != "fold_policy_active"} for event in dodge.events]


def test_fold_rest_uses_fold_on_all_actor_discards_only(cases, monkeypatch):
    original_choose = game_module.choose_discard
    actor_calls = 0
    other_calls = 0
    for case in cases:
        def observed(observation, strategy):
            nonlocal actor_calls, other_calls
            if observation.seat == case.state.current:
                actor_calls += 1
                assert strategy == "fold"
            else:
                other_calls += 1
                assert strategy == "attack"
            return original_choose(observation, strategy)
        monkeypatch.setattr(game_module, "choose_discard", observed)
        assert finish_actor_case(case, "fold_rest").summary() == finish_case(case, ("fold", "attack", "attack", "attack")).summary()
    assert actor_calls > len(cases) * 2
    assert other_calls > 0


def test_features_ignore_hidden_contents_and_wall_order(cases):
    for case in cases:
        changed = deepcopy(case)
        for offset in (1, 2, 3):
            player = changed.state.players[(changed.state.current + offset) % 4]
            old = next(tile for tile, count in enumerate(player.hand) if count)
            index = next(index for index, tile in enumerate(changed.state.wall) if tile != old)
            new = changed.state.wall[index]
            player.hand[old] -= 1
            player.hand[new] += 1
            changed.state.wall[index] = old
        Random(71).shuffle(changed.state.wall)
        _assert_conservation(changed.state.players, changed.state.wall, changed.state.dead)
        assert case_observation(case) == case_observation(changed)
        assert decision_features(case_observation(case)) == decision_features(case_observation(changed))
    with pytest.raises(AssertionError, match="observation"):
        decision_features(cases[0].state)


def test_keep_safe_is_the_safest_discard_that_keeps_the_best_shanten():
    # "Stay tenpai but pick the safe tile": never gives up shanten, and among
    # the shanten-keeping discards nothing is strictly safer.
    from taimahjong.midgame_game import discard_risks
    from taimahjong.selfplay import _cached_analysis
    differs = 0
    for case in build_corpus(20, 3):
        observation = case_observation(case)
        analyses = _cached_analysis(observation.hand, len(observation.melds) + len(observation.kongs), observation.public_counts)
        shanten = {analysis.discard: analysis.shanten_after for analysis in analyses}
        risks = {tile: risk for risk, _, tile in discard_risks(observation)}
        tile, _ = choose_discard(observation, "keep_safe")
        assert shanten[tile] == analyses[0].shanten_after
        assert risks[tile] == min(risks[t] for t in risks if shanten[t] == analyses[0].shanten_after)
        differs += tile != analyses[0].discard
    assert differs, "fixture must exercise a case where keep_safe leaves the attack tile"


def test_features_match_public_fold_scores_and_efficiency(cases):
    for case in cases:
        obs = case_observation(case)
        features = decision_features(obs)
        rows = [rank_discards(obs.hand, opponent, obs.public_counts, len(obs.melds) + len(obs.kongs)) for _, opponent in obs.opponents]
        danger = {row.analysis.discard: max(next(item.expected_danger for item in opponent_rows if item.analysis.discard == row.analysis.discard) for opponent_rows in rows) for row in rows[0]}
        attack = choose_discard(obs, "attack")[0]
        safe = choose_discard(obs, "fold")[0]
        assert features["attack_tile"] == attack
        assert features["safest_tile"] == safe
        assert features["actor_shanten"] == next(row.analysis.shanten_after for row in rows[0] if row.analysis.discard == attack)
        assert features["attack_danger"] == danger[attack]
        assert features["safest_danger"] == danger[safe] == min(danger.values())
        assert features["attack_danger_rank"] == 1 + sum(value < danger[attack] for value in danger.values())
        assert features["max_opponent_tenpai_score"] == max(tenpai_score(opponent).score for _, opponent in obs.opponents)
        assert features["opponent_melds"] == sum(len(opponent.melds) for _, opponent in obs.opponents)
        assert features["wall_remaining"] == len(case.state.wall)
        assert features["stage"] == case.stage
        assert features["attack_is_drawn"] == (attack == obs.drawn_tile)
        assert features["attack_equals_safest"] == (attack == safe)


def test_crn_resume_atomic_case_and_actor_payoff_rotation(tmp_path, monkeypatch):
    path = tmp_path / "checkpoint.json"
    original_finish = cli.finish_actor_case
    seen = []

    def interrupted(case, profile, *, wall):
        seen.append((case.game_seed, profile, wall))
        if len(seen) == 2 * len(ACTOR_PROFILES) + 2:  # second case, first world
            raise RuntimeError("interrupted world")
        return original_finish(case, profile, wall=wall)

    monkeypatch.setattr(cli, "finish_actor_case", interrupted)
    with pytest.raises(RuntimeError, match="interrupted"):
        cli.run(per_stage=1, sims=2, seed=1, checkpoint=path)
    saved = json.loads(path.read_text())
    assert [len(row) for row in saved["worlds"]] == [2, 0, 0]
    assert [profile for _, profile, _ in seen[:len(ACTOR_PROFILES)]] == list(ACTOR_PROFILES)
    assert len({wall for _, _, wall in seen[:len(ACTOR_PROFILES)]}) == 1
    case = case_from_document(saved["corpus"][0])
    assert case.state.current != 0
    expected = original_finish(case, "attack", wall=seen[0][2]).point_deltas
    assert saved["worlds"][0][0][0] == [expected[(case.state.current + role) % 4] for role in range(4)]
    completed = []

    def observed(case, profile, *, wall):
        completed.append((case.game_seed, profile, wall))
        return original_finish(case, profile, wall=wall)

    monkeypatch.setattr(cli, "finish_actor_case", observed)
    resumed = cli.run(per_stage=1, sims=2, seed=1, checkpoint=path, resume=True)
    assert len(completed) == 2 * 2 * len(ACTOR_PROFILES)
    for offset in range(0, len(completed), len(ACTOR_PROFILES)):
        group = completed[offset:offset + len(ACTOR_PROFILES)]
        assert len({(seed, wall) for seed, _, wall in group}) == 1
        assert [profile for _, profile, _ in group] == list(ACTOR_PROFILES)
    full_path = tmp_path / "full.json"
    full = cli.run(per_stage=1, sims=2, seed=1, checkpoint=full_path)
    assert resumed["deviations"] == full["deviations"]
    assert resumed["per_case"] == full["per_case"]
    assert json.loads(path.read_text())["worlds"] == json.loads(full_path.read_text())["worlds"]
    for parameters in ({"per_stage": 2, "sims": 2, "seed": 1}, {"per_stage": 1, "sims": 3, "seed": 1}, {"per_stage": 1, "sims": 2, "seed": 2}):
        with pytest.raises(ValueError, match="differ"):
            cli.run(**parameters, checkpoint=path, resume=True)
    monkeypatch.setattr(cli, "source_digest", lambda: "changed")
    with pytest.raises(ValueError, match="differ"):
        cli.run(per_stage=1, sims=2, seed=1, checkpoint=path, resume=True)


def test_report_case_means_groups_csv_and_cost_scaling(cases, tmp_path):
    # Two worlds per case. Paired gains: dodge +2/-2, fold +4/0, keep_safe_once
    # +1/+1, keep_safe_rest +3/+3, so case means are exactly 0, 2, 1 and 3.
    document = {"parameters": {"per_stage": 3, "sims": 2, "seed": 1}, "source_digest": "test",
                "timing": {"corpus_seconds": 9., "rollout_seconds": 18.},
                "worlds": [[[[0]*4, [2,0,0,0], [4,0,0,0], [1,0,0,0], [3,0,0,0]],
                            [[0]*4, [-2,0,0,0], [0]*4, [1,0,0,0], [3,0,0,0]]] for _ in cases]}
    result = cli.report(document, cases)
    assert result["corpus_stage_counts"] == {"early": 3, "mid": 3, "late": 3}
    assert len(result["deviations"]) == 4
    for entry, gain in zip(result["deviations"], (0., 2., 1., 3.)):
        assert entry["mean_gain"] == gain
        assert entry["ci95"] == [gain, gain]
        for key in ("by_stage", "by_actor_shanten", "by_attack_danger_tercile"):
            assert sum(group["cases"] for group in entry[key].values()) == len(cases)
            for group in entry[key].values():
                assert group["mean_gain"] == (gain if group["cases"] else None)
        assert sum(group["cases"] for stage in entry["by_stage_and_danger_tercile"].values() for group in stage.values()) == len(cases)
    assert result["timing"]["extrapolated_300_per_stage_x100_seconds"] == 90900
    output, csv_path = tmp_path / "report.json", tmp_path / "cases.csv"
    cli.write_outputs(result, output, csv_path)
    assert json.loads(output.read_text())["deviations"] == result["deviations"]
    with csv_path.open() as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == len(cases)
    assert all(float(row["dodge_once_mean_gain"]) == 0 and float(row["fold_rest_mean_gain"]) == 2
               and float(row["keep_safe_once_mean_gain"]) == 1 and float(row["keep_safe_rest_mean_gain"]) == 3 for row in rows)
    assert set(rows[0]) == set(result["per_case"][0])
    assert cli.danger_terciles([0., 1., 2., 3.]) == ((1., 2.), ["low", "low", "middle", "high"])
    assert cli.danger_terciles([0., 0., 0.]) == ((0., 0.), ["low"] * 3)


@pytest.mark.parametrize("per_stage,sims", [(0, 1), (1, 0), (-1, 2)])
def test_positive_parameters(per_stage, sims):
    with pytest.raises(ValueError, match="positive"):
        cli.run(per_stage=per_stage, sims=sims, seed=1)
