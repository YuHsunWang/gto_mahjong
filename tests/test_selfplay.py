from math import sqrt
from pathlib import Path

import taimahjong.selfplay as selfplay

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
from taimahjong.selfplay import (
    Player,
    _choose_discard,
    _declared,
    _robbing_winner,
    _settlement,
    head_to_head,
    play_game,
    play_games,
)
from taimahjong.shanten import shanten
from taimahjong.tiles import parse_tiles


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
    # 雙向計 makes the dealer's leg asymmetric when a non-dealer wins:
    # conservation is the invariant, per-leg equality is not.
    games = play_games(50, 20260717)
    assert all(sum(game.point_deltas) == 0 for game in games)
    for game in games:
        premium = game.dealer_premium
        if game.outcome == "ron":
            assert game.discarder == game.events[-1]["seat"]
            assert premium == (0 if game.winner == 0 or game.discarder != 0 else 1)
            assert game.point_deltas[game.winner] == game.value_units + premium
            assert game.point_deltas[game.discarder] == -(game.value_units + premium)
        elif game.outcome == "tsumo":
            assert premium == (0 if game.winner == 0 else 1)
            assert game.point_deltas[game.winner] == 3 * game.value_units + premium
            for seat, delta in enumerate(game.point_deltas):
                if seat == game.winner:
                    continue
                expected = game.value_units + (premium if seat == 0 else 0)
                assert delta == -expected
        else:
            assert game.point_deltas == (0, 0, 0, 0)


def _ron_settlement(winner, discarder, dealer_streak=0):
    """Settle a fixed pinghu ron so only the seats/streak vary across calls."""
    players = [Player("attack") for _ in range(4)]
    winning = parse_tiles("123456789m123p11678s")
    tile = next(index for index, count in enumerate(parse_tiles("6s")) if count)
    return _settlement("ron", winner, discarder, players, winning, tile, dealer_streak)


def test_non_dealer_ron_off_dealer_adds_bilateral_premium_even_at_streak_zero():
    # Intentional behavior change (雙向計): the dealer's payment leg carries
    # DEALER_TAI even at streak 0, so the same hand ron'd off the dealer pays
    # exactly one unit more than ron'd off a non-dealer.
    off_dealer, value = _ron_settlement(winner=1, discarder=0)
    off_peer, same_value = _ron_settlement(winner=1, discarder=2)
    assert value == same_value
    assert off_dealer[1] == off_peer[1] + 1
    assert off_dealer[0] == -(value + 1)
    assert sum(off_dealer) == sum(off_peer) == 0


def test_streak_raises_dealer_leg_by_two_per_repeat():
    # 連N拉N: each dealer repeat adds STREAK_TAI_PER_WIN=2 to the bilateral
    # premium, so dealing in as the streaking dealer gets linearly costlier —
    # the exact gradient the defense model and trainer must teach.
    legs = [_ron_settlement(winner=1, discarder=0, dealer_streak=streak)[0] for streak in range(3)]
    assert [deltas[1] - legs[0][1] for deltas in legs] == [0, 2, 4]
    # A dealer winner's streak is baked into the hand value instead, never the leg.
    dealer_win, dealer_value = _ron_settlement(winner=0, discarder=2, dealer_streak=2)
    base_win, base_value = _ron_settlement(winner=0, discarder=2, dealer_streak=0)
    assert dealer_value == base_value + 4
    assert dealer_win[0] == dealer_value


def test_cautious_avoids_feeding_the_dealer(monkeypatch):
    # Two fold candidates with a deliberate split: 1m is dangerous to the dealer
    # (seat 0) and safe to the peer; 9m is the reverse. Raw max-danger would feed
    # the dealer (1m's 8 > 9m's 9? no — the dealer weight tips it). With the
    # dealer weight ON, cautious must pick the dealer-safe 9m; with the bonus
    # patched to 0 (seat-blind baseline) it reverts to the raw-danger 1m.
    one_m, nine_m = 0, 8
    danger = {one_m: {0: 8.0, 2: 1.0}, nine_m: {0: 1.0, 2: 9.0}}
    # Every other candidate is made maximally dangerous so the fold choice is a
    # clean contest between 1m and 9m.
    monkeypatch.setattr(selfplay, "_danger_for", lambda opponent, tile, post, players: danger.get(tile, {}).get(opponent, 100.0))

    players = [Player("attack") for _ in range(4)]
    players[1].policy = "cautious"
    # A shanten>=2 scattered hand containing both 1m and 9m as legal discards.
    players[1].hand = list(parse_tiles("1159m159p159s1234567z"))
    players[0].declared_at = 0  # dealer is a declared threat
    players[0].river = [selfplay.RiverEntry(0)]
    players[2].declared_at = 0  # a second, non-dealer declared threat
    players[2].river = [selfplay.RiverEntry(0)]

    with_weight, folded = _choose_discard(1, None, players)
    assert folded and with_weight == nine_m
    monkeypatch.setattr(selfplay, "CAUTIOUS_DEALER_BONUS", 0.0)
    without_weight, _ = _choose_discard(1, None, players)
    assert without_weight == one_m


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
    # While hands are still developing (turns 1-12), more declared melds means a
    # more likely tenpai, so P(tenpai) rises with melds within a turn/run bucket.
    # This is NOT asserted for the late game (turn 13+): there, open hands that
    # failed to complete keep tsumogiri-ing without being tenpai — and harder
    # dealer-folding (M3) feeds that pool — so the relationship legitimately
    # inverts. (Regenerated from seeds 30001-30040, mix attack/cautious/ev/ev.)
    checked_buckets = 0
    for turn in ("1-6", "7-12"):
        for run in ("0", "1-2", "3+"):
            populated = [table[f"{melds}|{turn}|{run}"] for melds in range(6) if table[f"{melds}|{turn}|{run}"]["observations"] >= 30]
            if len(populated) >= 2:
                values = [cell["probability"] for cell in populated]
                assert values == sorted(values), f"{turn}|{run} not monotonic: {values}"
                checked_buckets += 1
    assert checked_buckets >= 4, "the developing-phase monotonicity check must cover several buckets"
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


# --- M5: kong engine ---

def test_kong_policy_none_reproduces_baseline():
    # The entire kong branch must be inert by default: a "none" game equals the
    # pre-kong engine tile-for-tile, so enabling kongs never silently perturbs
    # existing behavior or the committed calibration.
    for seed in (941, 20260717, 42, 30001):
        assert play_game(seed).summary() == play_game(seed, kong_policy="none").summary()


def test_kong_all_policy_conserves_tiles_and_uses_dead_wall():
    # Conservation is asserted inside play_game after every kong/replacement, so
    # a batch that actually declares kongs exercises the dead-wall draw path.
    games = [play_game(seed, ("attack", "attack", "attack", "attack"), kong_policy="all") for seed in range(200, 320)]
    konged = [game for game in games if game.kongs]
    assert konged, "the all policy should declare kongs across 120 attack games"
    # A win with kongs still resolves to a valid winning hand at its declared count.
    for game in games:
        if game.outcome != "draw":
            assert shanten(game.winning_hand, game.winning_melds) == -1
        if game.kong_bloom or game.robbed_kong:
            assert game.outcome in {"tsumo", "ron"}


def test_added_kong_can_be_robbed():
    # 搶槓: a seat waiting on the tile a rival adds to a pon wins off that tile.
    players = [Player("attack") for _ in range(4)]
    # Seat 1 is tenpai on 6s (a pinghu wait); seats 2/3 hold valid non-winning
    # hands (real play never has an empty seat, which shanten would reject).
    players[1].hand = list(parse_tiles("123456789m123p1178s"))
    players[2].hand = list(parse_tiles("112233m112233p1122s"))
    players[3].hand = list(parse_tiles("112233m112233p1122s"))
    six_s = next(index for index, count in enumerate(parse_tiles("6s")) if count)
    assert _robbing_winner(players, konger=0, tile=six_s) == 1
    # A tile nobody waits on cannot be robbed.
    one_z = next(index for index, count in enumerate(parse_tiles("1z")) if count)
    assert _robbing_winner(players, konger=0, tile=one_z) is None


def test_kong_bloom_flag_reaches_settlement_and_adds_one_tai():
    # 槓上開花 must thread from the loop into scoring: the same self-draw win with
    # a concealed kong scores exactly KONG_BLOOM_TAI (1) more when the flag is set.
    players = [Player("attack") for _ in range(4)]
    players[0].kongs = [(next(i for i, c in enumerate(parse_tiles("1z")) if c), True)]
    winning_hand = parse_tiles("234567m234p234s55s")
    two_s = next(index for index, count in enumerate(parse_tiles("2s")) if count)
    _, plain = _settlement("tsumo", 0, None, players, winning_hand, two_s)
    _, bloom = _settlement("tsumo", 0, None, players, winning_hand, two_s, kong_bloom=True)
    assert bloom - plain == 1


def test_kong_counts_as_one_declared_set_for_shanten():
    # A concealed kong occupies a declared set, so _declared feeds shanten the
    # right count and a hand completed around one kong resolves to a win.
    player = Player("attack")
    player.kongs = [(next(i for i, c in enumerate(parse_tiles("1z")) if c), True)]
    player.hand = list(parse_tiles("234567m234p234s55s"))  # 14 tiles = 17 - 3*1
    assert _declared(player) == 1
    assert shanten(tuple(player.hand), _declared(player)) == -1
