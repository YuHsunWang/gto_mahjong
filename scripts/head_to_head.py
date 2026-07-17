"""Run one reproducible, alternating-seat ev_aware-versus-attack batch."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from taimahjong.selfplay import head_to_head


parser = argparse.ArgumentParser()
parser.add_argument("--games", type=int, required=True)
parser.add_argument("--seed", type=int, required=True)
args = parser.parse_args()
result = head_to_head(args.games, args.seed)
differences = [ev - attack for ev, attack in result.game_deltas]
print(json.dumps({
    "games": result.games,
    "seed": result.seed_start,
    "ev_sum": sum(ev for ev, _ in result.game_deltas),
    "attack_sum": sum(attack for _, attack in result.game_deltas),
    "difference_sum": sum(differences),
    "difference_squared_sum": sum(value * value for value in differences),
}))
