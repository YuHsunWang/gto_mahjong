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
from typing import Callable, Mapping

from .calibration import Calibration
from .config import (
    DEFAULT_GAME_CONFIG,
    DEFAULT_RULES,
    GameConfig,
    RulesConfig,
    resolve_ron_claims,
)
from .danger import OpponentView, RiverEntry, danger_score, fold_score, tenpai_score
from .ev import BASELINE_TENPAI_RATE, DECLARED_FACTOR, opponent_value_estimate
from .scoring import BASE_UNITS, DEFAULT_SCHEME, DEALER_TAI, STREAK_TAI_PER_WIN, ScoringScheme, WinContext, score_hand
from .shanten import shanten
from .ukeire import DiscardAnalysis


POLICIES = ("attack", "cautious", "ev_aware")
KONG_POLICIES = ("none", "concealed_added", "all")

# M5c's deliberately cheap, deterministic replacement for per-discard Monte
# Carlo.  Candidate attack value is relative ukeire times a shanten lookup;
# risk uses a bot-domain calibrated deal-in lookup when available. These are
# policy constants and bot-ecology estimates, not Taiwan-human-play estimates.
ATTACK_TOP_K = 5
SHANTEN_WIN_WEIGHT = {-1: 1.0, 0: 0.45, 1: 0.18, 2: 0.06}
SHANTEN_FALLBACK_WEIGHT = 0.02
EXPECTED_TAI_PROXY = 1.0
DEALER_SEAT = 0
# Cautious defends harder against the dealer: each fold candidate's danger to
# the dealer is scaled by 1 + CAUTIOUS_DEALER_BONUS x (1 + streak), so a
# streaking dealer's threat dominates the fold choice. 0 reproduces the
# seat-blind cautious baseline (used by the dealer-aware-off experiment arm).
CAUTIOUS_DEALER_BONUS = 0.5


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
    # Declared kongs as (tile, concealed) pairs; their four tiles live here,
    # outside ``hand``. Each occupies one declared set (see ``_declared``).
    kongs: list[tuple[int, bool]] = field(default_factory=list)

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
    kongs: tuple[tuple[int, bool], ...] = ()  # the winner's declared kongs
    kong_bloom: bool = False  # win on a kong's self-drawn replacement (槓上開花)
    robbed_kong: bool = False  # win by robbing an added kong (搶槓)
    kong_log: tuple[tuple[int, int, bool], ...] = ()  # every declared kong: (seat, tile, concealed)

    def summary(self) -> tuple:
        return (
            self.outcome, self.winner, self.discarder, self.turns,
            tuple(tuple(sorted(event.items())) for event in self.events), self.point_deltas, self.value_units,
            self.dealer_streak, self.dealer_premium, self.kongs, self.kong_bloom, self.robbed_kong, self.kong_log,
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
        for tile, _ in player.kongs:
            counts[tile] += 4
    return tuple(counts)


def _view(player: Player, seat: int) -> OpponentView:
    # A kong is public but OpponentView.melds is strictly three tiles, so we
    # expose the kong to the shape/danger layer as its triplet; the fourth copy
    # is already in the visible counts (_public_counts adds all four).
    kong_triplets = [(tile, tile, tile) for tile, _ in player.kongs]
    return OpponentView(
        list(player.river), list(player.melds) + kong_triplets, player.declared_at,
        is_dealer=seat == DEALER_SEAT,
        dealer_streak=player.dealer_streak if seat == DEALER_SEAT else 0,
        hand_count=sum(player.hand),
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


def _declared(player: Player) -> int:
    """Declared-set count for shanten/scoring: open melds plus kongs (each a set)."""
    return len(player.melds) + len(player.kongs)


def _kong_worsens_shanten(player: Player, tile: int, concealed: bool) -> bool:
    """Whether declaring this kong raises shanten (a kong fixes four tiles into
    one set, which can strand a tile the flexible hand still wanted)."""
    before = _cached_shanten(tuple(player.hand), _declared(player))
    post = list(player.hand)
    post[tile] -= 4 if concealed else 1  # concealed removes all four; added frees the pon's fourth
    after = _cached_shanten(tuple(post), _declared(player) + (1 if concealed else 0))
    return after > before


def _self_draw_kong_choice(player: Player, kong_policy: str) -> tuple[int, bool] | None:
    """Pick one sound self-draw kong (tile, concealed) or None.

    concealed 暗槓: four copies in hand. added 加槓: the just-held fourth copy of
    an existing pon. Both are only taken when they do not worsen shanten, so a
    bot never kongs itself away from tenpai. Lower tile index first for
    determinism. ``kong_policy`` "none" is handled by the caller.
    """
    for tile in range(34):
        if player.hand[tile] == 4 and not _kong_worsens_shanten(player, tile, True):
            return tile, True
    for tile, second, third in player.melds:
        if tile == second == third and player.hand[tile] >= 1 and not _kong_worsens_shanten(player, tile, False):
            return tile, False
    return None


def _declare_kong(player: Player, tile: int, concealed: bool, dead: list[int]) -> int:
    """Apply a kong and draw its replacement from the dead wall (no backfill from
    the live wall — a deliberate simplification). Returns the replacement tile."""
    if concealed:
        player.hand[tile] -= 4
    else:
        player.hand[tile] -= 1
        player.melds.remove((tile, tile, tile))  # the pon becomes a kong
    player.kongs.append((tile, concealed))
    replacement = dead.pop(0)
    player.hand[replacement] += 1
    return replacement


def _big_kong_caller(players: list[Player], discarder: int, tile: int, seat_kong: tuple[str, str, str, str]) -> int | None:
    """Closest downstream 'all'-policy seat that would 大明槓 the discard under a
    sound read: it holds three copies and the kong does not worsen its shanten."""
    for offset in range(1, 4):
        index = (discarder + offset) % 4
        player = players[index]
        if seat_kong[index] != "all" or player.declared or player.hand[tile] != 3:
            continue
        before = _cached_shanten(tuple(player.hand), _declared(player))
        post = list(player.hand)
        post[tile] -= 3
        if _cached_shanten(tuple(post), _declared(player) + 1) <= before:
            return index
    return None


def _apply_big_kong(player: Player, tile: int, dead: list[int]) -> int:
    """Declare a 大明槓 on a discard (three from hand + the discard) and draw the
    dead-wall replacement. Open, no bloom eligibility. Returns the replacement."""
    player.hand[tile] -= 3
    player.kongs.append((tile, False))
    replacement = dead.pop(0)
    player.hand[replacement] += 1
    return replacement


def _robbing_winners(
    players: list[Player],
    konger: int,
    tile: int,
    rules: RulesConfig = DEFAULT_RULES,
) -> tuple[int, ...]:
    """Seats that can ron an added-kong ``tile`` (搶槓), under ``rules``."""
    def can_win(index: int) -> bool:
        hand = players[index].hand
        completed = tuple(hand[:tile] + [hand[tile] + 1] + hand[tile + 1:])
        return _cached_shanten(completed, _declared(players[index])) == -1

    return resolve_ron_claims(konger, can_win, rules)


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
        total += sum(player.hand) + len(player.river) + sum(len(meld) for meld in player.melds) + 4 * len(player.kongs)
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
        for tile, _ in player.kongs:
            all_counts[tile] += 4
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


def _ev_aware_discard(
    player_index: int,
    analyses: tuple[DiscardAnalysis, ...],
    players: list[Player],
    scheme: ScoringScheme = DEFAULT_SCHEME,
    consume_calibration: bool = True,
) -> int:
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
    calibration = _default_calibration() if consume_calibration else None
    ranked: list[tuple[float, int, int]] = []
    for order, analysis in enumerate(candidates):
        post = list(player.hand)
        post[analysis.discard] -= 1
        relative_ukeire = analysis.total / best_ukeire if best_ukeire else 0.0
        attack = SHANTEN_WIN_WEIGHT.get(analysis.shanten_after, SHANTEN_FALLBACK_WEIGHT)
        attack *= relative_ukeire * (scheme.base_units + scheme.tai_units * EXPECTED_TAI_PROXY)
        risk = 0.0
        for index, opponent in opponents:
            danger = danger_by_candidate[analysis.discard][index]
            probability = calibration.deal_in_probability(danger) if calibration else None
            # The committed table normally supplies this.  The fallback only
            # keeps the simulator usable before a first calibration build.
            probability = 0.0 if probability is None else probability
            risk += probability * opponent_value_estimate(opponent, scheme) * _tenpai_factor(opponent)
        ranked.append((attack - risk, -order, analysis.discard))
    return max(ranked)[2]


def _choose_discard(
    player_index: int,
    drawn_tile: int | None,
    players: list[Player],
    scheme: ScoringScheme = DEFAULT_SCHEME,
    consume_calibration: bool = True,
) -> tuple[int, bool]:
    player = players[player_index]
    if player.declared:
        assert drawn_tile is not None
        return drawn_tile, False
    visible = _public_counts(players)
    analyses = _cached_analysis(tuple(player.hand), _declared(player), visible)
    assert analyses
    if player.policy == "ev_aware":
        return _ev_aware_discard(
            player_index,
            analyses,
            players,
            scheme,
            consume_calibration=consume_calibration,
        ), False
    fold_active = (
        player.policy == "cautious"
        and _cached_shanten(tuple(player.hand), _declared(player)) >= 2
        and any(other.declared or _declared(other) >= 4 for index, other in enumerate(players) if index != player_index)
    )
    if not fold_active:
        return analyses[0].discard, False
    threats = [index for index, other in enumerate(players) if index != player_index and (other.declared or _declared(other) >= 4)]
    ranked: list[tuple[float, int, int]] = []
    for order, analysis in enumerate(analyses):
        post = list(player.hand)
        post[analysis.discard] -= 1
        ranked.append((
            max(_danger_for(opponent, analysis.discard, post, players) * _cautious_dealer_weight(opponent, players) for opponent in threats),
            order, analysis.discard,
        ))
    return min(ranked)[2], True


def _cautious_dealer_weight(opponent: int, players: list[Player]) -> float:
    """Inflate a threat's danger when it is the (streaking) dealer.

    This is the cautious policy's own defense philosophy — distinct from
    ev_aware's EV mechanism (which prices the dealer via opponent_value_estimate)
    — so the streak experiment can compare the two. Read live for monkeypatching.
    """
    if opponent != DEALER_SEAT:
        return 1.0
    return 1.0 + CAUTIOUS_DEALER_BONUS * (1 + players[DEALER_SEAT].dealer_streak)


def _dealer_leg_premium(
    outcome: str,
    winner: int | None,
    discarder: int | None,
    dealer_streak: int,
    scheme: ScoringScheme = DEFAULT_SCHEME,
) -> int:
    """Extra units on the dealer's payment leg when a non-dealer wins.

    The premium is expressed in tai by the scoring table and converted through
    the same payout scheme as the hand. A dealer winner gets 0 here because
    their premium is baked into the hand value by ``score_hand`` (every leg
    pays it).
    """
    if winner is None or winner == DEALER_SEAT:
        return 0
    if outcome == "ron" and discarder != DEALER_SEAT:
        return 0
    return scheme.tai_units * (DEALER_TAI + STREAK_TAI_PER_WIN * dealer_streak)


def _settlement(
    outcome: str,
    winner: int | None,
    discarder: int | None,
    players: list[Player],
    winning_hand: tuple[int, ...] | None,
    winning_tile: int | None,
    dealer_streak: int = 0,
    scheme: ScoringScheme = DEFAULT_SCHEME,
    kong_bloom: bool = False,
    robbed_kong: bool = False,
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
            kong_bloom=kong_bloom,
            robbed_kong=robbed_kong,
        ),
        kongs=tuple(players[winner].kongs),
    ).value_in(scheme)
    premium = _dealer_leg_premium(outcome, winner, discarder, dealer_streak, scheme)
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


def _settle_ron_winners(
    winners: tuple[int, ...],
    discarder: int,
    players: list[Player],
    winning_hands: Mapping[int, tuple[int, ...]],
    winning_tile: int,
    dealer_streak: int = 0,
    scheme: ScoringScheme = DEFAULT_SCHEME,
    *,
    robbed_kong: bool = False,
) -> tuple[tuple[int, int, int, int], tuple[int, ...]]:
    """Settle every resolved ron claim; the discarder pays each winner."""
    if not winners:
        raise ValueError("ron settlement requires at least one winner")
    combined = [0, 0, 0, 0]
    values = []
    for winner in winners:
        deltas, value = _settlement(
            "ron",
            winner,
            discarder,
            players,
            winning_hands[winner],
            winning_tile,
            dealer_streak,
            scheme,
            robbed_kong=robbed_kong,
        )
        combined = [total + delta for total, delta in zip(combined, deltas)]
        values.append(value)
    assert sum(combined) == 0
    return tuple(combined), tuple(values)


def _policy_post_call_choice(player: Player, removed: tuple[int, int]) -> tuple[int, int] | None:
    """Bot policy: return its discard only when this call strictly improves shanten."""
    before = _cached_shanten(tuple(player.hand), _declared(player))
    candidate = list(player.hand)
    candidate[removed[0]] -= 1
    candidate[removed[1]] -= 1
    analyses = _cached_analysis(tuple(candidate), _declared(player) + 1, (0,) * 34)
    if not analyses or analyses[0].shanten_after >= before:
        return None
    return analyses[0].shanten_after, analyses[0].discard


def _legal_call_options(
    player: Player,
    tile: int,
    chi: bool,
) -> list[tuple[tuple[int, int], tuple[int, int, int]]]:
    """Enumerate every rule-legal pon or chi using two concealed tiles."""
    options: list[tuple[tuple[int, int], tuple[int, int, int]]] = []
    if not chi:
        if player.hand[tile] >= 2:
            options.append(((tile, tile), (tile, tile, tile)))
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
            options.append(((first, second), tuple(sorted((tile, first, second)))))
    return options


def _policy_call_options(
    player: Player,
    tile: int,
    chi: bool,
) -> list[tuple[tuple[int, int], tuple[int, int, int], int]]:
    """Filter legal pon/chi calls to the bot's strict shanten-improvement policy."""
    options: list[tuple[tuple[int, int], tuple[int, int, int], int]] = []
    for removed, meld in _legal_call_options(player, tile, chi):
        choice = _policy_post_call_choice(player, removed)
        if choice:
            options.append((removed, meld, choice[0]))
    return options


def _best_call(player: Player, tile: int, chi: bool) -> tuple[tuple[int, int], tuple[int, int, int]] | None:
    """Select the bot's preferred call from its policy-filtered options."""
    options = _policy_call_options(player, tile, chi)
    if not options:
        return None
    removed, meld, _ = min(options, key=lambda option: (option[2], option[1]))
    return removed, meld


def _seat_kong_policy(kong_policy: str | tuple[str, str, str, str], seat: int) -> str:
    """Broadcast a single kong policy to every seat, or index a per-seat tuple.

    A per-seat tuple lets an experiment enable kongs for one seat only and read
    that seat's marginal EV against otherwise identical opponents."""
    if isinstance(kong_policy, str):
        return kong_policy
    return kong_policy[seat]


def play_game(
    seed: int | None = None,
    policies: tuple[str, str, str, str] = ("attack", "cautious", "attack", "cautious"),
    snapshot_hook: Callable[[DecisionSnapshot], None] | None = None,
    dealer_streak: int = 0,
    kong_policy: str | tuple[str, str, str, str] = "none",
    config: GameConfig = DEFAULT_GAME_CONFIG,
    rules: RulesConfig = DEFAULT_RULES,
    consume_calibration: bool = True,
) -> GameResult:
    """Play one deterministic-seeded game and retain every discard event in memory.

    ``kong_policy`` gates kong declarations, either a single policy for all seats
    or a per-seat 4-tuple: "none" never kongs (identical to the pre-kong engine);
    "concealed_added" takes shanten-safe 暗槓/加槓; "all" additionally takes 大明槓
    on a discard (which the house rule scores at 0 tai and denies 槓上開花 — the
    experiment uses it to show it is strictly bad).
    """
    if len(policies) != 4 or any(policy not in POLICIES for policy in policies):
        raise ValueError("policies must name four entries from POLICIES")
    if not isinstance(consume_calibration, bool):
        raise ValueError("consume_calibration must be a boolean")
    if not isinstance(dealer_streak, int) or isinstance(dealer_streak, bool) or dealer_streak < 0:
        raise ValueError("dealer_streak must be a non-negative integer")
    seat_kong = tuple(_seat_kong_policy(kong_policy, seat) for seat in range(4))
    if any(policy not in KONG_POLICIES for policy in seat_kong):
        raise ValueError(f"kong_policy entries must be among {KONG_POLICIES}")
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
    kong_log: list[tuple[int, int, bool]] = []  # (seat, tile, concealed) per declared kong
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
                points, value = _settlement("draw", None, None, players, None, None, dealer_streak, config.scheme)
                return GameResult(events, "draw", None, None, actions, point_deltas=points, value_units=value, dealer_streak=dealer_streak, kong_log=tuple(kong_log))
            drawn_tile = wall.pop()
            player.hand[drawn_tile] += 1
            _assert_conservation(players, wall, dead)
            if _cached_shanten(tuple(player.hand), _declared(player)) == -1:
                winning_hand = tuple(player.hand)
                points, value = _settlement("tsumo", current, None, players, winning_hand, drawn_tile, dealer_streak, config.scheme)
                return GameResult(
                    events, "tsumo", current, None, actions, winning_hand, _declared(player), points, value,
                    dealer_streak, _dealer_leg_premium("tsumo", current, None, dealer_streak, config.scheme),
                    kongs=tuple(player.kongs), kong_log=tuple(kong_log),
                )
            # Self-draw kongs (concealed / added): declare, rob-check, draw a
            # dead-wall replacement, and re-check for a 槓上開花 tsumo. A robbed
            # added kong ends the hand as the robber's ron.
            while seat_kong[current] != "none" and dead:
                choice = _self_draw_kong_choice(player, seat_kong[current])
                if choice is None:
                    break
                kind_tile, concealed = choice
                if not concealed:
                    robbers = _robbing_winners(players, current, kind_tile, rules)
                    if robbers:
                        winning_hands = {}
                        for robber in robbers:
                            robbed_hand = list(players[robber].hand)
                            robbed_hand[kind_tile] += 1
                            winning_hands[robber] = tuple(robbed_hand)
                        points, values = _settle_ron_winners(
                            robbers,
                            current,
                            players,
                            winning_hands,
                            kind_tile,
                            dealer_streak,
                            config.scheme,
                            robbed_kong=True,
                        )
                        robber = robbers[0]
                        winning = winning_hands[robber]
                        return GameResult(
                            events, "ron", robber, current, actions, winning, _declared(players[robber]), points, values[0],
                            dealer_streak, _dealer_leg_premium("ron", robber, current, dealer_streak, config.scheme),
                            kongs=tuple(players[robber].kongs), robbed_kong=True, kong_log=tuple(kong_log),
                        )
                kong_log.append((current, kind_tile, concealed))
                drawn_tile = _declare_kong(player, kind_tile, concealed, dead)
                _assert_conservation(players, wall, dead)
                if _cached_shanten(tuple(player.hand), _declared(player)) == -1:
                    winning_hand = tuple(player.hand)
                    points, value = _settlement(
                        "tsumo", current, None, players, winning_hand, drawn_tile, dealer_streak, config.scheme, kong_bloom=True,
                    )
                    return GameResult(
                        events, "tsumo", current, None, actions, winning_hand, _declared(player), points, value,
                        dealer_streak, _dealer_leg_premium("tsumo", current, None, dealer_streak, config.scheme),
                        kongs=tuple(player.kongs), kong_bloom=True, kong_log=tuple(kong_log),
                    )
            if snapshot_hook is not None and not player.declared:
                snapshot_hook(_decision_snapshot(current, drawn_tile, players, len(wall)))

        tile, fold_active = _choose_discard(
            current,
            drawn_tile,
            players,
            config.scheme,
            consume_calibration=consume_calibration,
        )
        assert player.hand[tile] > 0
        origin = "tsumogiri" if drawn_tile == tile else "tedashi"
        player.hand[tile] -= 1
        turn = player.discards + 1
        true_tenpai = _cached_shanten(tuple(player.hand), _declared(player)) == 0
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
            "melds": _declared(player),
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

        def can_ron(index: int) -> bool:
            hand = players[index].hand
            completed = tuple(hand[:tile] + [hand[tile] + 1] + hand[tile + 1:])
            return _cached_shanten(completed, _declared(players[index])) == -1

        winners = resolve_ron_claims(current, can_ron, rules)
        if winners:
            winner = winners[0]
            event["dealt_in"] = True
            event["danger_score"] = dangers[winner]
            event["deal_in_winner"] = winner
            winning_hands = {}
            for ron_winner in winners:
                winning_hand = list(players[ron_winner].hand)
                winning_hand[tile] += 1
                winning = tuple(winning_hand)
                assert _cached_shanten(winning, _declared(players[ron_winner])) == -1
                winning_hands[ron_winner] = winning
            points, values = _settle_ron_winners(
                winners, current, players, winning_hands, tile, dealer_streak, config.scheme,
            )
            winning = winning_hands[winner]
            return GameResult(
                events, "ron", winner, current, actions, winning, _declared(players[winner]), points, values[0],
                dealer_streak, _dealer_leg_premium("ron", winner, current, dealer_streak, config.scheme),
                kongs=tuple(players[winner].kongs), kong_log=tuple(kong_log),
            )

        # A discard may be konged (大明槓) by a downstream seat whose policy is
        # "all", before pon/chi; the caller draws a replacement and no 槓上開花
        # applies (fourth tile came from a discard). It advances the hand like a
        # pon but fixes a full set.
        if dead and not player.declared:
            big_caller = _big_kong_caller(players, current, tile, seat_kong)
            if big_caller is not None:
                player.river.pop()  # the konged tile leaves the discarder's river
                kong_log.append((big_caller, tile, False))
                replacement = _apply_big_kong(players[big_caller], tile, dead)
                any_call = True
                _assert_conservation(players, wall, dead)
                if _cached_shanten(tuple(players[big_caller].hand), _declared(players[big_caller])) == -1:
                    winning_hand = tuple(players[big_caller].hand)
                    points, value = _settlement("tsumo", big_caller, None, players, winning_hand, replacement, dealer_streak, config.scheme)
                    return GameResult(
                        events, "tsumo", big_caller, None, actions, winning_hand, _declared(players[big_caller]), points, value,
                        dealer_streak, _dealer_leg_premium("tsumo", big_caller, None, dealer_streak, config.scheme),
                        kongs=tuple(players[big_caller].kongs), kong_log=tuple(kong_log),
                    )
                current = big_caller
                needs_draw = False
                continue

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


def play_games(
    games: int,
    seed: int | None = None,
    policies: tuple[str, str, str, str] = ("attack", "cautious", "attack", "cautious"),
    dealer_streak: int = 0,
    config: GameConfig = DEFAULT_GAME_CONFIG,
    rules: RulesConfig = DEFAULT_RULES,
    consume_calibration: bool = True,
) -> list[GameResult]:
    if not isinstance(games, int) or isinstance(games, bool) or games < 0:
        raise ValueError("games must be a non-negative integer")
    rng = Random(seed)
    return [
        play_game(
            rng.randrange(2**63),
            policies,
            dealer_streak=dealer_streak,
            config=config,
            rules=rules,
            consume_calibration=consume_calibration,
        )
        for _ in range(games)
    ]


def head_to_head(
    games: int,
    seed: int,
    dealer_streak: int = 0,
    config: GameConfig = DEFAULT_GAME_CONFIG,
    rules: RulesConfig = DEFAULT_RULES,
) -> HeadToHeadResult:
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
        game = play_game(
            seed + index,
            policies,
            dealer_streak=dealer_streak,
            config=config,
            rules=rules,
        )
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
