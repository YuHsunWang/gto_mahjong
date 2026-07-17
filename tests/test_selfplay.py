from math import sqrt
from pathlib import Path

from taimahjong.calibration import (
    Calibration,
    DANGER_BUCKETS,
    DANGER_MODIFIERS,
    DANGER_REFERENCE,
    MIN_CELL_COUNT,
    counts_from_games,
    load_table,
    merge_counts,
    table_document,
    write_merged_table,
)
from taimahjong.selfplay import Player, _choose_discard, head_to_head, play_game, play_games
from taimahjong.shanten import shanten


def test_fixed_seed_is_deterministic_and_conserves_tiles():
    first = play_game(941)
    second = play_game(941)
    assert first.summary() == second.summary()
    # Conservation is asserted after every draw, discard, and call; a batch
    # exercises those assertions across changing wall and meld states.
    assert len(play_games(12, 942)) == 12


def test_smoke_batch_has_each_terminal_path_and_valid_wins():
    games = play_games(50, 20260717)
    outcomes = {game.outcome for game in games}
    assert {"ron", "tsumo", "draw"} <= outcomes
    assert any(event["declared"] for game in games for event in game.events)
    for game in games:
        if game.outcome != "draw":
            assert game.winning_hand is not None
            assert shanten(game.winning_hand, game.winning_melds) == -1


def test_point_accounting_conserves_and_charges_the_actual_loser():
    games = play_games(50, 20260717)
    assert all(sum(game.point_deltas) == 0 for game in games)
    for game in games:
        if game.outcome == "ron":
            assert game.discarder == game.events[-1]["seat"]
            assert game.point_deltas[game.winner] == game.value_units
            assert game.point_deltas[game.discarder] == -game.value_units
        elif game.outcome == "tsumo":
            assert game.point_deltas[game.winner] == 3 * game.value_units
            assert all(
                delta == -game.value_units
                for seat, delta in enumerate(game.point_deltas)
                if seat != game.winner
            )
        else:
            assert game.point_deltas == (0, 0, 0, 0)


def test_ev_aware_is_deterministic_and_chooses_the_safe_known_case():
    # This 17-tile state is the first seat-zero decision from fixed seed 1.
    # Attack's M2 choice is 2s (19); the calibrated policy instead takes the
    # lower-danger 2z (28), so the test catches a risk term that is ignored.
    hand = (0, 0, 0, 0, 0, 0, 0, 0, 2, 1, 2, 0, 0, 1, 0, 1, 0, 0, 0, 1, 1, 1, 1, 0, 0, 1, 1, 0, 1, 0, 0, 1, 2, 0)
    players = [Player("attack") for _ in range(4)]
    players[0].hand = list(hand)
    assert _choose_discard(0, 8, players) == (19, False)
    players[0].policy = "ev_aware"
    first = _choose_discard(0, 8, players)
    second = _choose_discard(0, 8, players)
    assert first == second == (28, False)


def test_head_to_head_smoke_batch_records_point_deltas():
    result = head_to_head(40, 41000)
    assert result.games == 40
    assert len(result.game_deltas) == 40
    assert all(ev == -attack for ev, attack in result.game_deltas)


def test_chunked_counts_merge_like_the_same_seeded_chunks(tmp_path):
    first = counts_from_games(play_games(6, 101))
    second = counts_from_games(play_games(7, 202))
    combined = merge_counts(first, second)
    path = tmp_path / "chunked.json"
    write_merged_table(path, first, {"seeds": [101]})
    write_merged_table(path, second, {"seeds": [202]})
    assert load_table(path)["counts"] == combined


def test_per_opponent_danger_exposure_matches_the_actual_winner():
    games = play_games(8, 731)
    counts = counts_from_games(games)
    observations = sum(cell["observations"] for cell in counts["deal_in"].values())
    deal_ins = sum(cell["deal_ins"] for cell in counts["deal_in"].values())
    events = [event for game in games for event in game.events]
    assert observations == 3 * len(events)
    assert deal_ins == sum(event["dealt_in"] for event in events)


def test_calibration_lookup_interpolates_and_falls_back_for_small_cells():
    counts = {
        "games": 0,
        "tenpai": {
            "0|1-6|0": {"observations": 30, "tenpai": 6},
            "1|1-6|0": {"observations": 29, "tenpai": 20},
        },
        "deal_in": {bucket: {"observations": 0, "deal_ins": 0} for bucket in DANGER_BUCKETS},
        "fold": {"attack": {"windows": 0, "score_sum": 0.0}, "cautious": {"windows": 0, "score_sum": 0.0}},
    }
    counts["deal_in"]["0-1"] = {"observations": 30, "deal_ins": 3}
    counts["deal_in"]["1-2"] = {"observations": 30, "deal_ins": 9}
    calibration = Calibration(table_document(counts))
    assert calibration.tenpai_probability(0, 1, 0) == 0.2
    assert calibration.tenpai_probability(1, 1, 0) is None
    assert calibration.deal_in_probability(1.0) == 0.2
    assert Calibration(table_document(counts), min_cell_count=31).deal_in_probability(1.0) is None


def test_committed_calibration_has_signal_and_monotonic_tenpai():
    document_path = Path(__file__).parents[1] / "data" / "calibration.json"
    calibration = Calibration.from_path(document_path)
    assert calibration.document["counts"]["games"] >= 2000
    assert calibration.document["metadata"]["danger_reference"] == DANGER_REFERENCE
    assert calibration.document["metadata"]["danger_modifiers"] == DANGER_MODIFIERS
    assert calibration.document["metadata"]["policy_mix"] == ["attack", "cautious", "ev_aware", "ev_aware"]
    table = calibration.tables["tenpai"]
    for turn in ("1-6", "7-12", "13+"):
        for run in ("0", "1-2", "3+"):
            cells = [table[f"{melds}|{turn}|{run}"] for melds in range(6)]
            if all(cell["observations"] >= 30 for cell in cells):
                values = [cell["probability"] for cell in cells]
                assert values == sorted(values)
    danger = calibration.tables["deal_in"]
    values = [danger[bucket]["probability"] for bucket in DANGER_BUCKETS]
    assert values == sorted(values)
    raw = [danger[bucket] for bucket in DANGER_BUCKETS]
    inversions = [
        (left, right)
        for left, right in zip(raw, raw[1:])
        if left["observations"] >= MIN_CELL_COUNT
        and right["observations"] >= MIN_CELL_COUNT
        and left["empirical_probability"] > right["empirical_probability"]
    ]
    assert len(inversions) <= 1
    if inversions:
        left, right = inversions[0]
        pooled = (left["deal_ins"] + right["deal_ins"]) / (left["observations"] + right["observations"])
        standard_error = sqrt(pooled * (1 - pooled) * (1 / left["observations"] + 1 / right["observations"]))
        assert left["empirical_probability"] - right["empirical_probability"] <= 1.5 * standard_error
