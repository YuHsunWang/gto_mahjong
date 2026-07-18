"""Four-player, 136-tile Taiwanese-mahjong self-play simulator.

This deliberately models ordinary tiles only: 136 tiles, no flowers, no
kang, no temporary ``guo shui`` rule, and no flower replacement.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from random import Random
from math import sqrt
from pathlib import Path
from typing import Callable

from .calibration import Calibration
from .danger import OpponentView, RiverEntry, danger_score, fold_score, tenpai_score
from .ev import BASELINE_TENPAI_RATE, DECLARED_FACTOR, opponent_value_estimate
from .scoring import BASE_UNITS, DEALER_TAI, STREAK_TAI_PER_WIN, WinContext, score_hand
from .shanten import shanten
from .ukeire import DiscardAnalysis


POLICIES = ("attack", "cautious", "ev_aware")

# M5c's deliberately cheap, deterministic replacement for per-discard Monte
# Carlo.  Candidate attack value is relative ukeire times a shanten lookup;
# risk is a calibrated per-opponent deal-in loss.  These are policy constants,
# not Taiwan-human-play estimates.
ATTACK_TOP_K = 5
SHANTEN_WIN_WEIGHT = {-1: 1.0, 0: 0.45, 1: 0.18, 2: 0.06}
SHANTEN_FALLBACK_WEIGHT = 0.02
EXPECTED_TAI_PROXY = 1.0
DEALER_SEAT = 0


@lru_cache(maxsize=200_000)
def _cached_shanten(hand: tuple[int, ...], melds: int) -> int:
    return shanten(hand, melds)


@lru_cache(maxsize=100_000)
def _cached_ukeire(hand: tuple[int, ...], melds: int, visible: tuple[int, ...]) -> tuple[tuple[int, int], ...]:
    current = _cached_shanten(hand, melds)
    accepted: list[tuple[int, int]] = []
    for tile, count in enumerate(hand):
        if count == 4:
            continue
        drawn = list(hand)
        drawn[tile] += 1
        if _cached_shanten(tuple(drawn), melds) < current:
            accepted.append((tile, 4 - hand[tile] - visible[tile]))
    return tuple(accepted)


@lru_cache(maxsize=100_000)
def _cached_analysis(hand: tuple[int, ...], melds: int, visible: tuple[int, ...]) -> tuple[DiscardAnalysis, ...]:
    """M2-equivalent cached discard analysis used only by self-play bots."""
    results: list[DiscardAnalysis] = []
    for tile, count in enumerate(hand):
        if not count:
            continue
        post = list(hand)
        post[tile] -= 1
        after = tuple(post)
        accepted = dict(_cached_ukeire(after, melds, visible))
        results.append(DiscardAnalysis(tile, _cached_shanten(after, melds), accepted, sum(accepted.values())))
    return tuple(sorted(results, key=lambda item: (item.shanten_after, -item.total, item.discard)))


@dataclass
class Player:
    policy: str
    hand: list[int] = field(default_factory=lambda: [0] * 34)
    river: list[RiverEntry] = field(default_factory=list)
    melds: list[tuple[int, int, int]] = field(default_factory=list)
    declared_at: int | None = None
    discards: int = 0
    # Set on the DEALER_SEAT player only: dealership is table state, carried
    # here so every observer's view can price the 連莊 premium without
    # threading a game parameter through each danger/EV call chain.
    dealer_streak: int = 0

    @property
    def declared(self) -> bool:
        return self.declared_at is not None


@dataclass(frozen=True)
class GameResult:
    events: list[dict]
    outcome: str
    winner: int | None
    discarder: int | None
    turns: int
    winning_hand: tuple[int, ...] | None = None
    winning_melds: int = 0
    point_deltas: tuple[int, int, int, int] = (0, 0, 0, 0)
    value_units: int = 0
    dealer_streak: int = 0
    dealer_premium: int = 0  # units added to the dealer's leg for a non-dealer winner

    def summary(self) -> tuple:
        return (
            self.outcome, self.winner, self.discarder, self.turns,
            tuple(tuple(sorted(event.items())) for event in self.events), self.point_deltas, self.value_units,
            self.dealer_streak, self.dealer_premium,
        )


@dataclass(frozen=True)
class HeadToHeadResult:
    """Point-accounted ev_aware versus attack comparison over paired seats."""

    games: int
    seed_start: int
    ev_aware_mean: float
    attack_mean: float
    difference: float
    standard_error: float
    significance: float | None
    game_deltas: tuple[tuple[float, float], ...]


@dataclass(frozen=True)
class DecisionSnapshot:
    """A player's observable table state immediately after a non-winning draw.

    The snapshot deliberately carries no opponent concealed hands.  It is an
    additive hook for teaching or diagnostics; ordinary self-play behavior is
    unchanged when no hook is supplied.
    """

    seat: int
    hand: tuple[int, ...]
    river: tuple[RiverEntry, ...]
    melds: tuple[tuple[int, int, int], ...]
    opponents: tuple[tuple[int, OpponentView], ...]
    public_counts: tuple[int, ...]
    turn: int
    drawn_tile: int
    wall_remaining: int = 0  # live-wall tiles left to draw (observable in play)
    dealer_streak: int = 0  # the table's 連莊 count (dealer is always seat 0)


def _public_counts(players: list[Player]) -> tuple[int, ...]:
    counts = [0] * 34
    for player in players:
        for entry in player.river:
            counts[entry.tile] += 1
        for meld in player.melds:
            for tile in meld:
                counts[tile] += 1
    return tuple(counts)


def _view(player: Player, seat: int) -> OpponentView:
    return OpponentView(
        list(player.river), list(player.melds), player.declared_at,
        is_dealer=seat == DEALER_SEAT,
        dealer_streak=player.dealer_streak if seat == DEALER_SEAT else 0,
    )


def _decision_snapshot(player_index: int, drawn_tile: int, players: list[Player], wall_remaining: int = 0) -> DecisionSnapshot:
    """Copy the public table view available to ``player_index`` after drawing."""
    player = players[player_index]
    return DecisionSnapshot(
        seat=player_index,
        hand=tuple(player.hand),
        river=tuple(player.river),
        melds=tuple(player.melds),
        opponents=tuple((index, _view(other, index)) for index, other in enumerate(players) if index != player_index),
        public_counts=_public_counts(players),
        turn=player.discards + 1,
        drawn_tile=drawn_tile,
        wall_remaining=wall_remaining,
        dealer_streak=players[DEALER_SEAT].dealer_streak,
    )


def _trailing_tsumogiri_run(river: list[RiverEntry]) -> int:
    run = 0
    for entry in reversed(river):
        if entry.origin == "tedashi":
            break
        if entry.origin == "tsumogiri":
            run += 1
    return run


def _assert_conservation(players: list[Player], wall: list[int], dead: list[int]) -> None:
    total = len(wall) + len(dead)
    for player in players:
        total += sum(player.hand) + len(player.river) + sum(len(meld) for meld in player.melds)
    assert total == 136, f"tile conservation failed: {total} != 136"
    all_counts = [0] * 34
    for tile in wall + dead:
        all_counts[tile] += 1
    for player in players:
        for tile, count in enumerate(player.hand):
            all_counts[tile] += count
        for entry in player.river:
            all_counts[entry.tile] += 1
        for meld in player.melds:
            for tile in meld:
                all_counts[tile] += 1
    assert all(count == 4 for count in all_counts), "individual tile copies were not conserved"


def _danger_for(player_index: int, tile: int, post_hand: list[int], players: list[Player]) -> float:
    visible = _public_counts(players)
    return danger_score(tile, _view(players[player_index], player_index), visible, tuple(post_hand)).score


@lru_cache(maxsize=1)
def _default_calibration() -> Calibration | None:
    """Load the committed table once; a missing table leaves a safe fallback."""
    path = Path(__file__).resolve().parent.parent / "data" / "calibration.json"
    return Calibration.from_path(path) if path.exists() else None


def _tenpai_factor(opponent: OpponentView) -> float:
    if opponent.declared_at is not None:
        return DECLARED_FACTOR
    score = tenpai_score(opponent, len(opponent.river)).score
    return min(3.0, max(0.25, score / BASELINE_TENPAI_RATE))


def _ev_aware_discard(player_index: int, analyses: tuple[DiscardAnalysis, ...], players: list[Player]) -> int:
    """Choose from M2's top candidates plus the raw minimum-danger discard."""
    player = players[player_index]
    visible = _public_counts(players)
    opponents = [(index, _view(other, index)) for index, other in enumerate(players) if index != player_index]
    danger_by_candidate: dict[int, dict[int, float]] = {}
    for analysis in analyses:
        post = list(player.hand)
        post[analysis.discard] -= 1
        danger_by_candidate[analysis.discard] = {
            index: danger_score(analysis.discard, opponent, visible, tuple(post)).score
            for index, opponent in opponents
        }
    candidates = list(analyses[:ATTACK_TOP_K])
    safest = min(analyses, key=lambda analysis: (sum(danger_by_candidate[analysis.discard].values()), analysis.discard))
    if safest.discard not in {analysis.discard for analysis in candidates}:
        candidates.append(safest)
    best_ukeire = max((analysis.total for analysis in analyses), default=0)
    calibration = _default_calibration()
    ranked: list[tuple[float, int, int]] = []
    for order, analysis in enumerate(candidates):
        post = list(player.hand)
        post[analysis.discard] -= 1
        relative_ukeire = analysis.total / best_ukeire if best_ukeire else 0.0
        attack = SHANTEN_WIN_WEIGHT.get(analysis.shanten_after, SHANTEN_FALLBACK_WEIGHT)
        attack *= relative_ukeire * (BASE_UNITS + EXPECTED_TAI_PROXY)
        risk = 0.0
        for index, opponent in opponents:
            danger = danger_by_candidate[analysis.discard][index]
            probability = calibration.deal_in_probability(danger) if calibration else None
            # The committed table normally supplies this.  The fallback only
            # keeps the simulator usable before a first calibration build.
            probability = 0.0 if probability is None else probability
            risk += probability * opponent_value_estimate(opponent) * _tenpai_factor(opponent)
        ranked.append((attack - risk, -order, analysis.discard))
    return max(ranked)[2]


def _choose_discard(player_index: int, drawn_tile: int | None, players: list[Player]) -> tuple[int, bool]:
    player = players[player_index]
    if player.declared:
        assert drawn_tile is not None
        return drawn_tile, False
    visible = _public_counts(players)
    analyses = _cached_analysis(tuple(player.hand), len(player.melds), visible)
    assert analyses
    if player.policy == "ev_aware":
        return _ev_aware_discard(player_index, analyses, players), False
    fold_active = (
        player.policy == "cautious"
        and _cached_shanten(tuple(player.hand), len(player.melds)) >= 2
        and any(other.declared or len(other.melds) >= 4 for index, other in enumerate(players) if index != player_index)
    )
    if not fold_active:
        return analyses[0].discard, False
    threats = [index for index, other in enumerate(players) if index != player_index and (other.declared or len(other.melds) >= 4)]
    ranked: list[tuple[float, int, int]] = []
    for order, analysis in enumerate(analyses):
        post = list(player.hand)
        post[analysis.discard] -= 1
        ranked.append((max(_danger_for(opponent, analysis.discard, post, players) for opponent in threats), order, analysis.discard))
    return min(ranked)[2], True


def _dealer_leg_premium(outcome: str, winner: int | None, discarder: int | None, dealer_streak: int) -> int:
    """Extra units on the dealer's payment leg when a non-dealer wins.

    Premium in tai == premium in value units: value_units = BASE_UNITS +
    total tai, and the premium is extra tai on an already-scored win.  A
    dealer winner gets 0 here because their premium is baked into the hand
    value by ``score_hand`` (every leg pays it).
    """
    if winner is None or winner == DEALER_SEAT:
        return 0
    if outcome == "ron" and discarder != DEALER_SEAT:
        return 0
    return DEALER_TAI + STREAK_TAI_PER_WIN * dealer_streak


def _settlement(
    outcome: str,
    winner: int | None,
    discarder: int | None,
    players: list[Player],
    winning_hand: tuple[int, ...] | None,
    winning_tile: int | None,
    dealer_streak: int = 0,
) -> tuple[tuple[int, int, int, int], int]:
    """Score a terminal game using M5a, with deliberate bot-table omissions.

    No winds, heavenly/earthly values, or dealer payment doubling are
    modeled.  Ron is paid solely by the actual discarder; tsumo uses
    Taiwanese three-opponent equal payments.

    The dealer premium (莊 + 連莊拉莊) is bilateral: a dealer winner bakes it
    into the hand value via ``score_hand`` (every payment leg involves the
    dealer, so a uniform per-leg value is exact), while a non-dealer winner's
    hand is scored without it and the premium is added only to the dealer's
    payment leg — ron off the dealer, or the dealer's share of a tsumo.
    """
    if outcome == "draw":
        return (0, 0, 0, 0), 0
    assert winner is not None and winning_hand is not None and winning_tile is not None
    dealer_won = winner == DEALER_SEAT
    value = score_hand(
        winning_hand,
        players[winner].melds,
        WinContext(
            winning_tile=winning_tile,
            self_draw=outcome == "tsumo",
            dealer=dealer_won,
            dealer_streak=dealer_streak if dealer_won else 0,
            migi_declared=players[winner].declared,
        ),
    ).value_units
    premium = _dealer_leg_premium(outcome, winner, discarder, dealer_streak)
    deltas = [0, 0, 0, 0]
    if outcome == "ron":
        assert discarder is not None
        deltas[winner] += value + premium
        deltas[discarder] -= value + premium
    else:
        deltas[winner] += 3 * value + premium
        for seat in range(4):
            if seat != winner:
                deltas[seat] -= value + (premium if seat == DEALER_SEAT else 0)
    assert sum(deltas) == 0
    return tuple(deltas), value


def _post_call_choice(player: Player, removed: tuple[int, int]) -> tuple[int, int] | None:
    """Return (resulting shanten, discard) if this two-tile call improves it."""
    before = _cached_shanten(tuple(player.hand), len(player.melds))
    candidate = list(player.hand)
    candidate[removed[0]] -= 1
    candidate[removed[1]] -= 1
    analyses = _cached_analysis(tuple(candidate), len(player.melds) + 1, (0,) * 34)
    if not analyses or analyses[0].shanten_after >= before:
        return None
    return analyses[0].shanten_after, analyses[0].discard


def _call_options(player: Player, tile: int, chi: bool) -> list[tuple[tuple[int, int], tuple[int, int, int], int]]:
    options: list[tuple[tuple[int, int], tuple[int, int, int], int]] = []
    if not chi:
        if player.hand[tile] >= 2:
            choice = _post_call_choice(player, (tile, tile))
            if choice:
                options.append(((tile, tile), (tile, tile, tile), choice[0]))
        return options
    if tile >= 27:
        return options
    suit, rank = divmod(tile, 9)
    offset = suit * 9
    for pair in ((rank - 2, rank - 1), (rank - 1, rank + 1), (rank + 1, rank + 2)):
        if not all(0 <= value < 9 for value in pair):
            continue
        first, second = offset + pair[0], offset + pair[1]
        if player.hand[first] and player.hand[second]:
            choice = _post_call_choice(player, (first, second))
            if choice:
                options.append(((first, second), tuple(sorted((tile, first, second))), choice[0]))
    return options


def _best_call(player: Player, tile: int, chi: bool) -> tuple[tuple[int, int], tuple[int, int, int]] | None:
    options = _call_options(player, tile, chi)
    if not options:
        return None
    removed, meld, _ = min(options, key=lambda option: (option[2], option[1]))
    return removed, meld


def play_game(
    seed: int | None = None,
    policies: tuple[str, str, str, str] = ("attack", "cautious", "attack", "cautious"),
    snapshot_hook: Callable[[DecisionSnapshot], None] | None = None,
    dealer_streak: int = 0,
) -> GameResult:
    """Play one deterministic-seeded game and retain every discard event in memory."""
    if len(policies) != 4 or any(policy not in POLICIES for policy in policies):
        raise ValueError("policies must name four entries from POLICIES")
    if not isinstance(dealer_streak, int) or isinstance(dealer_streak, bool) or dealer_streak < 0:
        raise ValueError("dealer_streak must be a non-negative integer")
    rng = Random(seed)
    tiles = [tile for tile in range(34) for _ in range(4)]
    rng.shuffle(tiles)
    players = [Player(policy) for policy in policies]
    players[DEALER_SEAT].dealer_streak = dealer_streak
    for _ in range(16):
        for player in players:
            player.hand[tiles.pop()] += 1
    dead = [tiles.pop() for _ in range(16)]
    wall = tiles
    events: list[dict] = []
    any_call = False
    current = 0
    needs_draw = True
    actions = 0
    _assert_conservation(players, wall, dead)

    while True:
        actions += 1
        assert actions < 1000, "game did not terminate"
        player = players[current]
        drawn_tile: int | None = None
        if needs_draw:
            if not wall:
                points, value = _settlement("draw", None, None, players, None, None, dealer_streak)
                return GameResult(events, "draw", None, None, actions, point_deltas=points, value_units=value, dealer_streak=dealer_streak)
            drawn_tile = wall.pop()
            player.hand[drawn_tile] += 1
            _assert_conservation(players, wall, dead)
            if _cached_shanten(tuple(player.hand), len(player.melds)) == -1:
                assert _cached_shanten(tuple(player.hand), len(player.melds)) == -1
                winning_hand = tuple(player.hand)
                points, value = _settlement("tsumo", current, None, players, winning_hand, drawn_tile, dealer_streak)
                return GameResult(
                    events, "tsumo", current, None, actions, winning_hand, len(player.melds), points, value,
                    dealer_streak, _dealer_leg_premium("tsumo", current, None, dealer_streak),
                )
            if snapshot_hook is not None and not player.declared:
                snapshot_hook(_decision_snapshot(current, drawn_tile, players, len(wall)))

        tile, fold_active = _choose_discard(current, drawn_tile, players)
        assert player.hand[tile] > 0
        origin = "tsumogiri" if drawn_tile == tile else "tedashi"
        player.hand[tile] -= 1
        turn = player.discards + 1
        true_tenpai = _cached_shanten(tuple(player.hand), len(player.melds)) == 0
        dangers = {
            index: _danger_for(index, tile, player.hand, players)
            for index in range(4)
            if index != current
        }
        player.river.append(RiverEntry(tile, origin))
        player.discards += 1
        if not any_call and not player.declared and turn <= 2 and true_tenpai:
            player.declared_at = len(player.river) - 1
        event = {
            "seat": current,
            "policy": player.policy,
            "turn": turn,
            "melds": len(player.melds),
            "tsumogiri_run": _trailing_tsumogiri_run(player.river),
            "declared": player.declared,
            "fold_policy_active": fold_active,
            "true_tenpai": true_tenpai,
            "dealt_in": False,
            "danger_score": max(dangers.values()),
            "danger_by_opponent": dangers,
            "deal_in_winner": None,
            "fold_window": False,
            "fold_score": 0.0,
        }
        other_counts = [0] * 34
        for index, other in enumerate(players):
            if index != current:
                for entry in other.river:
                    other_counts[entry.tile] += 1
        score = fold_score(_view(player, current), other_counts)
        if len(player.river) >= 3:
            event["fold_window"] = True
            event["fold_score"] = score
        events.append(event)
        _assert_conservation(players, wall, dead)

        winner = next(
            (
                index
                for offset in range(1, 4)
                for index in [(current + offset) % 4]
                if _cached_shanten(
                    tuple(players[index].hand[:tile] + [players[index].hand[tile] + 1] + players[index].hand[tile + 1 :]),
                    len(players[index].melds),
                )
                == -1
            ),
            None,
        )
        if winner is not None:
            event["dealt_in"] = True
            event["danger_score"] = dangers[winner]
            event["deal_in_winner"] = winner
            winning_hand = list(players[winner].hand)
            winning_hand[tile] += 1
            assert _cached_shanten(tuple(winning_hand), len(players[winner].melds)) == -1
            winning = tuple(winning_hand)
            points, value = _settlement("ron", winner, current, players, winning, tile, dealer_streak)
            return GameResult(
                events, "ron", winner, current, actions, winning, len(players[winner].melds), points, value,
                dealer_streak, _dealer_leg_premium("ron", winner, current, dealer_streak),
            )

        # Pon takes priority; ties use closest player downstream. Chi is next-seat only.
        caller: int | None = None
        selected: tuple[tuple[int, int], tuple[int, int, int]] | None = None
        # A migi discard remains in the declared player's observable river;
        # calls on it are not modeled because its river index anchors the
        # declaration and later hard-safety read.
        if not player.declared:
            for offset in range(1, 4):
                index = (current + offset) % 4
                if not players[index].declared:
                    selected = _best_call(players[index], tile, False)
                    if selected:
                        caller = index
                        break
            if caller is None:
                index = (current + 1) % 4
                if not players[index].declared:
                    selected = _best_call(players[index], tile, True)
                    if selected:
                        caller = index
        if caller is not None and selected is not None:
            removed, meld = selected
            players[current].river.pop()
            players[caller].hand[removed[0]] -= 1
            players[caller].hand[removed[1]] -= 1
            players[caller].melds.append(meld)
            any_call = True
            _assert_conservation(players, wall, dead)
            current = caller
            needs_draw = False
        else:
            current = (current + 1) % 4
            needs_draw = True


def play_games(games: int, seed: int | None = None, policies: tuple[str, str, str, str] = ("attack", "cautious", "attack", "cautious"), dealer_streak: int = 0) -> list[GameResult]:
    if not isinstance(games, int) or isinstance(games, bool) or games < 0:
        raise ValueError("games must be a non-negative integer")
    rng = Random(seed)
    return [play_game(rng.randrange(2**63), policies, dealer_streak=dealer_streak) for _ in range(games)]


def head_to_head(games: int, seed: int, dealer_streak: int = 0) -> HeadToHeadResult:
    """Run alternating-seat ev_aware/attack games and summarize point EV.

    Consecutive fixed seeds make a full comparison reproducible.  Even games
    alternate which policy owns dealer seat, cancelling this simulator's
    fixed-dealer-seat bias.
    """
    if not isinstance(games, int) or isinstance(games, bool) or games < 1:
        raise ValueError("games must be a positive integer")
    paired_policies = (
        ("ev_aware", "attack", "ev_aware", "attack"),
        ("attack", "ev_aware", "attack", "ev_aware"),
    )
    deltas: list[tuple[float, float]] = []
    differences: list[float] = []
    for index in range(games):
        policies = paired_policies[index % 2]
        game = play_game(seed + index, policies, dealer_streak=dealer_streak)
        ev_points = sum(game.point_deltas[seat] for seat, policy in enumerate(policies) if policy == "ev_aware") / 2
        attack_points = sum(game.point_deltas[seat] for seat, policy in enumerate(policies) if policy == "attack") / 2
        deltas.append((ev_points, attack_points))
        differences.append(ev_points - attack_points)
    ev_mean = sum(value[0] for value in deltas) / games
    attack_mean = sum(value[1] for value in deltas) / games
    difference = ev_mean - attack_mean
    if games < 2:
        standard_error = 0.0
    else:
        variance = sum((value - difference) ** 2 for value in differences) / (games - 1)
        standard_error = sqrt(variance / games)
    return HeadToHeadResult(
        games, seed, ev_mean, attack_mean, difference, standard_error,
        None if standard_error == 0 else difference / standard_error, tuple(deltas),
    )
