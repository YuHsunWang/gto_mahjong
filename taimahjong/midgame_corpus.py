"""Independent all-attack hand clusters, sampled before undeclared discards.

The initial live wall has 58 tiles (136 - 4*16 - 14). Fixed thirds:
late 0..19, mid 20..38, early 39..57 at a normal post-draw decision
(58 is also early at a post-call decision). Kongs do not move the cut points.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
from random import Random

from .config import GameConfig, RulesConfig
from .danger import DeclaredKong, DeclaredMeld, RiverEntry
from .selfplay import DEALER_SEAT, GameState, Player, _assert_conservation, play_game


def stage_for(wall_remaining: int) -> str:
    if not 0 <= wall_remaining <= 58:
        raise ValueError("wall_remaining must be between 0 and 58")
    return "late" if wall_remaining <= 19 else "mid" if wall_remaining <= 38 else "early"


@dataclass
class MidgameCase:
    game_seed: int
    decision_index: int
    eligible_decisions: int
    state: GameState
    original_payoffs: tuple[int, int, int, int]

    @property
    def wall_remaining(self) -> int:
        return len(self.state.wall)

    @property
    def stage(self) -> str:
        return stage_for(self.wall_remaining)


def sample_case(game_seed: int, selection_seed: int, *, kong_policy: str = "concealed_added", eligible_stages: frozenset[str] | None = None, max_wall: int | None = None) -> MidgameCase:
    """Reservoir-sample exactly one eligible decision, including after calls.

    Selection RNG is separate from the engine's deal RNG. The default keeps
    selfplay's shanten-safe concealed/added kongs enabled for every strategy.
    """
    rng = Random(selection_seed)
    selected = None
    chosen = 0
    count = 0

    def capture(state: GameState) -> None:
        nonlocal selected, chosen, count
        if any(player.declared for player in state.players):
            return
        if eligible_stages is not None and stage_for(len(state.wall)) not in eligible_stages:
            return
        if max_wall is not None and len(state.wall) > max_wall:
            return
        count += 1
        if rng.randrange(count) == 0:
            selected, chosen = deepcopy(state), count

    result = play_game(game_seed, ("attack",) * 4, kong_policy=kong_policy, state_hook=capture)
    if selected is None:
        raise ValueError("game ended before any eligible decision")
    return MidgameCase(game_seed, chosen, count, selected, result.point_deltas)


def build_corpus(cases: int, seed: int, *, max_wall: int | None = None) -> tuple[MidgameCase, ...]:
    """One case per independently seeded game; reject games with no decision.

    ``max_wall`` keeps only decisions with at most that many live-wall tiles.
    """
    if cases < 1:
        raise ValueError("cases must be positive")
    rng = Random(seed)
    result = []
    while len(result) < cases:
        game_seed, selection_seed = rng.getrandbits(64), rng.getrandbits(64)
        try:
            result.append(sample_case(game_seed, selection_seed, max_wall=max_wall))
        except ValueError as error:
            if str(error) != "game ended before any eligible decision":
                raise
    return tuple(result)


def build_stratified_corpus(per_stage: int, seed: int) -> tuple[MidgameCase, ...]:
    """Uniform over all eligible points in still-needed stages, one per game.

    The needed stages are fixed before each independent all-attack game.
    Reservoir sampling gives every undeclared decision in their union equal
    probability, including post-call decisions. Reject games with no such
    point; stop once each stage has exactly per_stage cases. This intentionally
    does not weight stages equally while multiple stages still need cases.
    """
    if per_stage < 1:
        raise ValueError("per_stage must be positive")
    rng = Random(seed)
    counts = dict.fromkeys(("early", "mid", "late"), 0)
    result = []
    while any(count < per_stage for count in counts.values()):
        needed = frozenset(stage for stage, count in counts.items() if count < per_stage)
        game_seed, selection_seed = rng.getrandbits(64), rng.getrandbits(64)
        try:
            case = sample_case(game_seed, selection_seed, eligible_stages=needed)
        except ValueError as error:
            if str(error) != "game ended before any eligible decision":
                raise
            continue
        result.append(case)
        counts[case.stage] += 1
    return tuple(result)


def case_document(case: MidgameCase) -> dict:
    """JSON-safe true state, retaining meld/kong and river provenance."""
    data = asdict(case)
    data.update(wall_remaining=case.wall_remaining, stage=case.stage, dealer_seat=DEALER_SEAT)
    data["state"]["config"] = {"scheme_id": case.state.config.scheme_id}
    return data


def case_from_document(data: dict) -> MidgameCase:
    if data["dealer_seat"] != DEALER_SEAT:
        raise ValueError("selfplay requires dealer seat 0")
    raw = deepcopy(data["state"])
    players = []
    for item in raw.pop("players"):
        item["river"] = [RiverEntry(**entry) for entry in item["river"]]
        item["melds"] = [
            DeclaredMeld(**{**meld, "tiles": tuple(meld["tiles"])})
            if isinstance(meld, dict) else tuple(meld) for meld in item["melds"]
        ]
        item["kongs"] = [DeclaredKong(**kong) if isinstance(kong, dict) else tuple(kong) for kong in item["kongs"]]
        players.append(Player(**item))
    raw["config"] = GameConfig.from_id(raw["config"]["scheme_id"])
    raw["rules"]["claim_priority"] = tuple(raw["rules"]["claim_priority"])
    raw["rules"] = RulesConfig(**raw["rules"])
    raw["seat_kong"] = tuple(raw["seat_kong"])
    raw["kong_log"] = [tuple(entry) for entry in raw["kong_log"]]
    for event in raw["events"]:
        event["danger_by_opponent"] = {int(seat): value for seat, value in event["danger_by_opponent"].items()}
    state = GameState(players=players, **raw)
    _assert_conservation(state.players, state.wall, state.dead)
    if any(player.declared for player in players):
        raise ValueError("corpus cases cannot contain declarations")
    case = MidgameCase(data["game_seed"], data["decision_index"], data["eligible_decisions"], state, tuple(data["original_payoffs"]))
    if data["wall_remaining"] != case.wall_remaining or data["stage"] != case.stage:
        raise ValueError("inconsistent stage/wall metadata")
    return case
