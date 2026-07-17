from pathlib import Path

from taimahjong.calibration import (
    Calibration,
    DANGER_BUCKETS,
    counts_from_games,
    load_table,
    merge_counts,
    table_document,
    write_merged_table,
)
from taimahjong.selfplay import play_game, play_games
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


def test_chunked_counts_merge_like_the_same_seeded_chunks(tmp_path):
    first = counts_from_games(play_games(6, 101))
    second = counts_from_games(play_games(7, 202))
    combined = merge_counts(first, second)
    path = tmp_path / "chunked.json"
    write_merged_table(path, first, {"seeds": [101]})
    write_merged_table(path, second, {"seeds": [202]})
    assert load_table(path)["counts"] == combined


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
