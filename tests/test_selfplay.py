from dataclasses import replace
from pathlib import Path

import pytest
import taimahjong.selfplay as selfplay

from taimahjong.calibration import (
    BETA_PRIOR_ALPHA,
    BETA_PRIOR_BETA,
    Calibration,
    DANGER_BUCKETS,
    DANGER_EDGES,
    DANGER_MODIFIERS,
    DANGER_REFERENCE,
    MIN_CELL_COUNT,
    counts_from_games,
    danger_bucket,
    empty_counts,
    load_table,
    merge_counts,
    table_document,
    write_merged_table,
)
from taimahjong.config import DEFAULT_RULES, resolve_ron_claims
from taimahjong.danger import OpponentView, danger_score
from taimahjong.selfplay import (
    KONG_DEAD_WALL_BACKFILL_TILES,
    Player,
    _assert_conservation,
    _choose_discard,
    _declare_kong,
    _declared,
    _robbing_winners,
    _settle_ron_winners,
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
    # A batch is only a smoke test if it actually reaches every terminal path
    # and at least one migi declaration; both together are rare (about 3% of
    # 50-game batches), so this seed differs from the one the point-accounting
    # test uses.  If the deal moves again, rescan for a seed satisfying both
    # rather than dropping either half of the assertion.
    games = play_games(50, 20260754)
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


def test_multi_ron_policy_changes_winners_and_conserves_every_payment():
    players = [Player("attack") for _ in range(4)]
    players[1].hand = list(parse_tiles("123456m123p123s111z5z"))
    players[2].hand = list(parse_tiles("123456p123m789s222z5z"))
    tile = next(index for index, count in enumerate(parse_tiles("5z")) if count)

    def can_ron(seat):
        if seat not in (1, 2):
            return False
        completed = list(players[seat].hand)
        completed[tile] += 1
        return shanten(tuple(completed), _declared(players[seat])) == -1

    nearest = resolve_ron_claims(0, can_ron, DEFAULT_RULES)
    all_rules = replace(
        DEFAULT_RULES, rules_id="taiwanese-multi-ron-v1", multi_ron="all",
    )
    all_winners = resolve_ron_claims(0, can_ron, all_rules)

    assert nearest == (1,)
    assert all_winners == (1, 2)

    winning_hands = {}
    for winner in all_winners:
        completed = list(players[winner].hand)
        completed[tile] += 1
        winning_hands[winner] = tuple(completed)
    nearest_deltas, _ = _settle_ron_winners(
        nearest, 0, players, winning_hands, tile,
    )
    all_deltas, _ = _settle_ron_winners(
        all_winners, 0, players, winning_hands, tile,
    )

    assert sum(nearest_deltas) == sum(all_deltas) == 0
    assert nearest_deltas[1] > 0 and nearest_deltas[2] == 0
    assert all_deltas[1] > 0 and all_deltas[2] > 0
    assert all_deltas[0] < nearest_deltas[0] < 0


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


def test_ev_aware_is_deterministic_and_chooses_the_safe_known_case(monkeypatch):
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
    # The calibration audit needs a policy instrument that changes only the
    # calibrated risk term.  If this branch ever touches the committed table,
    # the independent evaluation would reproduce the feedback loop it audits.
    def forbidden_load():
        pytest.fail("independent policy loaded the calibration table")

    monkeypatch.setattr(selfplay, "_default_calibration", forbidden_load)
    assert _choose_discard(0, 8, players, consume_calibration=False) == (19, False)


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
    expected = (
        (3 + BETA_PRIOR_ALPHA) / (30 + BETA_PRIOR_ALPHA + BETA_PRIOR_BETA)
        + (9 + BETA_PRIOR_ALPHA) / (30 + BETA_PRIOR_ALPHA + BETA_PRIOR_BETA)
    ) / 2
    assert calibration.deal_in_probability(1.0) == pytest.approx(expected)
    assert Calibration(table_document(counts), min_cell_count=31).deal_in_probability(1.0) is None
    # The shipped v2 document has a single 13+ cell.  A regenerated document
    # may split that heterogeneous tail without changing how the shipped file
    # is interpreted, while retaining Jeffreys smoothing and monotonic PAV.
    edges = DANGER_EDGES + (16.0,)
    buckets = DANGER_BUCKETS[:-1] + ("13-16", "16+")
    counts = empty_counts(buckets)
    counts["deal_in"]["9-13"] = {"observations": 1000, "deal_ins": 10}
    counts["deal_in"]["13-16"] = {"observations": 1000, "deal_ins": 5}
    counts["deal_in"]["16+"] = {"observations": 1000, "deal_ins": 20}
    document = table_document(
        counts,
        {"danger_binning": {"edges": list(edges), "buckets": list(buckets)}},
        danger_buckets=buckets,
    )

    calibration = Calibration(document)
    pooled = (10 + 0.5 + 5 + 0.5) / (1000 + 1 + 1000 + 1)
    assert danger_bucket(13.0, edges, buckets) == "13-16"
    assert calibration.deal_in_probability(11.0) == pytest.approx(pooled)
    assert calibration.deal_in_probability(14.5) == pytest.approx(pooled)
    assert calibration.deal_in_probability(20.0) == pytest.approx((20 + 0.5) / (1000 + 1))


def test_jeffreys_smoothing_keeps_observed_zero_deal_in_bucket_positive():
    five_z = next(index for index, count in enumerate(parse_tiles("5z")) if count)
    opponent = OpponentView([five_z], [])
    visible = list(parse_tiles("5z"))
    post_discard_hand = list(parse_tiles("5z"))
    assessment = danger_score(
        five_z, opponent, tuple(visible), tuple(post_discard_hand),
    )
    assert [shape.name for shape in assessment.feasible_shapes] == ["tanki"]
    assert assessment.score == 0.3

    counts = empty_counts()
    counts["deal_in"]["0-1"] = {"observations": MIN_CELL_COUNT, "deal_ins": 0}

    calibration = Calibration(table_document(counts))

    assert calibration.deal_in_probability(assessment.score) == (
        BETA_PRIOR_ALPHA
        / (MIN_CELL_COUNT + BETA_PRIOR_ALPHA + BETA_PRIOR_BETA)
    )
    assert calibration.deal_in_probability(assessment.score) > 0.0


def test_committed_calibration_has_signal_and_monotonic_tenpai():
    document_path = Path(__file__).parents[1] / "data" / "calibration.json"
    calibration = Calibration.from_path(document_path)
    assert calibration.document["counts"]["games"] == calibration.document["metadata"]["fit_games"]
    assert calibration.document["metadata"]["games"] >= 2000
    assert calibration.document["metadata"]["held_out_games"] > 0
    assert calibration.document["metadata"]["seed_range"]["start"] > 30040
    assert calibration.document["metadata"]["ev_model"]["source_date"] == "2026-07-29"
    assert calibration.document["quality"]["brier_score"] >= 0
    assert calibration.document["quality"]["log_loss"] >= 0
    assert len(calibration.document["quality"]["reliability_curve"]) == len(
        calibration.danger_buckets
    )
    assert calibration.document["metadata"]["danger_reference"] == DANGER_REFERENCE
    assert calibration.document["metadata"]["danger_modifiers"] == DANGER_MODIFIERS
    assert calibration.document["metadata"]["policy_mix"] == ["attack", "cautious", "ev_aware", "ev_aware"]
    table = calibration.tables["tenpai"]
    # While hands are still developing (turns 1-12), more declared melds means a
    # more likely tenpai, so P(tenpai) rises with melds within a turn/run bucket.
    # This is NOT asserted for the late game (turn 13+): there, open hands that
    # failed to complete keep tsumogiri-ing without being tenpai — and harder
    # dealer-folding (M3) feeds that pool — so the relationship legitimately
    # inverts. Restrict this broad structural check to cells with 10x the
    # lookup minimum so sparse early-game run buckets do not turn sampling
    # noise into a committed-table failure. The exposure floor alone is not
    # enough: the check compares probabilities, so the numerator has to be
    # resolvable too. At 6,400 fit games the 1-6|3+ row cleared 300 exposures
    # on 29/592 and 13/390 tenpai, a 1.19-standard-error step that reads as an
    # inversion. Requiring the lookup minimum in tenpai events as well drops
    # exactly those cells and leaves five buckets to check.
    checked_buckets = 0
    for turn in ("1-6", "7-12"):
        for run in ("0", "1-2", "3+"):
            populated = [
                table[f"{melds}|{turn}|{run}"]
                for melds in range(6)
                if table[f"{melds}|{turn}|{run}"]["observations"]
                >= 10 * MIN_CELL_COUNT
                and table[f"{melds}|{turn}|{run}"]["tenpai"] >= MIN_CELL_COUNT
            ]
            if len(populated) >= 2:
                values = [cell["probability"] for cell in populated]
                assert values == sorted(values), f"{turn}|{run} not monotonic: {values}"
                checked_buckets += 1
    assert checked_buckets >= 4, "the developing-phase monotonicity check must cover several buckets"
    danger = calibration.tables["deal_in"]
    # Read the binning the document itself declares, which is what production
    # reads: DEV-119 split the open-ended tail at 16, so a shipped table now
    # has eight cells and an older one still has seven.
    buckets = calibration.danger_buckets
    values = [danger[bucket]["probability"] for bucket in buckets]
    assert values == sorted(values)

    # This used to assert that at most one adjacent pair inverted empirically
    # and that the inversion sat inside 1.5 standard errors, i.e. that any
    # inversion was sampling noise. Eight thousand independent-policy games
    # falsified that: 9-13 is 0.866347% (1,386/159,982) against 13-16's
    # 0.656045% (546/83,226), far outside 1.5 SE, and PAV pools the two to one
    # value. The real DEV-119 defect was never the dip; it was that the old
    # open-ended 13+ cell averaged that dip together with a 16+ population
    # three times hotter, so the most dangerous cell priced below its
    # neighbour. That is what this now asserts, and it is what the
    # pre-promotion table failed: its 13+ cell was 0.774546% against 9-13's
    # 0.857410%.
    populated = [
        (bucket, danger[bucket])
        for bucket in buckets
        if danger[bucket]["observations"] >= MIN_CELL_COUNT
    ]
    assert len(populated) >= 2
    top_bucket, top_cell = populated[-1]
    hotter = [
        bucket
        for bucket, cell in populated[:-1]
        if cell["empirical_probability"] >= top_cell["empirical_probability"]
    ]
    assert not hotter, (
        f"{top_bucket} is the most dangerous cell but prices at or below "
        f"{hotter}; the tail is mixing populations again"
    )


# --- M5: kong engine ---

def test_kong_policy_none_reproduces_baseline():
    # The entire kong branch must be inert by default: a "none" game equals the
    # pre-kong engine tile-for-tile, so enabling kongs never silently perturbs
    # existing behavior or the committed calibration.
    for seed in (941, 20260717, 42, 30001):
        assert play_game(seed).summary() == play_game(seed, kong_policy="none").summary()


def test_kong_backfills_dead_wall_and_costs_one_live_draw():
    # 「一槓一」: every kong consumes exactly one future live-wall draw.
    players = [Player("attack") for _ in range(4)]
    players[0].hand[0] = 4
    remaining = [tile for tile in range(34) for _ in range(4)]
    for _ in range(4):
        remaining.remove(0)
    dead = remaining[:14]
    wall = remaining[14:]
    initial_live_tiles = len(wall)

    _declare_kong(players[0], 0, True, dead, wall)

    assert len(wall) == initial_live_tiles - KONG_DEAD_WALL_BACKFILL_TILES * len(players[0].kongs)
    assert len(dead) == 14
    _assert_conservation(players, wall, dead)


def test_kong_with_empty_live_wall_does_not_backfill_or_corrupt_tiles():
    players = [Player("attack") for _ in range(4)]
    players[0].hand[0] = 4
    remaining = [tile for tile in range(34) for _ in range(4)]
    for _ in range(4):
        remaining.remove(0)
    dead = [remaining.pop()]
    players[1].hand = [remaining.count(tile) for tile in range(34)]
    wall: list[int] = []

    _declare_kong(players[0], 0, True, dead, wall)

    assert wall == []
    assert dead == []
    _assert_conservation(players, wall, dead)


# Full-game invariant sweep (~22s).
@pytest.mark.slow
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
    assert _robbing_winners(players, konger=0, tile=six_s) == (1,)
    # A tile nobody waits on cannot be robbed.
    one_z = next(index for index, count in enumerate(parse_tiles("1z")) if count)
    assert _robbing_winners(players, konger=0, tile=one_z) == ()


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


# --- M7: experiment invariants ---

def test_per_seat_kong_policy_restricts_kongs_to_enabled_seats():
    # The experiment attributes a kong lift to one seat, so a per-seat policy
    # must let ONLY that seat kong; a leak would contaminate the EV measurement.
    seen_seats = set()
    for seed in range(200, 320):
        game = play_game(seed, ("attack", "attack", "attack", "attack"), kong_policy=("all", "none", "none", "none"))
        seen_seats.update(seat for seat, _, _ in game.kong_log)
    assert seen_seats == {0}, f"only seat 0 may kong, saw {seen_seats}"


# EV comparison over a large self-play batch (~35s).
@pytest.mark.slow
def test_daiminkan_is_not_positive_ev_under_house_rule():
    # 大明槓 scores 0 tai, breaks nothing extra, and forfeits 槓上開花, so enabling
    # it on top of 暗槓/加槓 must not raise the actor's EV. Paired seeds (same wall)
    # isolate the 大明槓 decision; this pins the house-rule consequence the kong
    # experiment demonstrates. Small batch keeps the test fast; the docs report
    # the large-sample magnitude.
    seed, games = 40001, 200
    def seat0_ev(kong_policy):
        total = sum(
            play_game(seed + offset, ("attack", "attack", "attack", "attack"),
                      kong_policy=(kong_policy, "none", "none", "none")).point_deltas[0]
            for offset in range(games)
        )
        return total / games
    added_only = seat0_ev("concealed_added")
    with_daiminkan = seat0_ev("all")
    assert with_daiminkan <= added_only + 0.05, (
        f"大明槓 should not help: all={with_daiminkan:.3f} vs concealed_added={added_only:.3f}"
    )
