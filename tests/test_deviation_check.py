"""``scripts/deviation_check.py`` must score a candidate exactly as the full
empirical game would.

The scorer tabulates only ``TDDD`` and its four candidate deviations instead
of every profile.  That shortcut is only safe if the worlds -- and so the
paired gains -- are identical to the full table's; if they drift, a
"candidate breaks the equilibrium" verdict would come from sampling, not play.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from taimahjong.empirical_game import STRATEGIES, build_game, efficiency, threat
from taimahjong.reference_ev import representative_reference_cases


PATH = Path(__file__).resolve().parents[1] / "scripts" / "deviation_check.py"
SPEC = importlib.util.spec_from_file_location("deviation_check", PATH)
deviation_check = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(deviation_check)

SMALL = representative_reference_cases()[:3]


def test_candidate_gain_matches_the_full_table():
    full = build_game(
        SMALL, sims=3, seed=1,
        strategies=("efficiency", "deal_in_risk", "threat"),
    )
    expected = full._deviation_gains(deviation_check.BASE)
    result = deviation_check.score(efficiency, SMALL, sims=3, seed=1, resamples=200)
    for row in result["roles"]:
        series = expected[(row["role"], "efficiency")]
        assert row["gain"] == pytest.approx(sum(series) / len(series), abs=1e-12)
    assert "candidate" not in STRATEGIES


def test_candidate_identical_to_the_base_gains_exactly_nothing():
    result = deviation_check.score(threat, SMALL, sims=3, seed=1, resamples=200)
    assert result["roles"][0]["gain"] == 0.0


def test_broken_candidate_is_reported_not_raised(tmp_path, capsys, monkeypatch):
    bad = tmp_path / "bad.py"
    bad.write_text("def policy(hand, belief, declared):\n    return 99\n")
    monkeypatch.setattr(
        deviation_check, "empirical_game_cases", lambda templates: SMALL,
    )
    monkeypatch.setattr(
        "sys.argv", ["deviation_check.py", "--candidate", str(bad), "--sims", "1"],
    )
    assert deviation_check.main() == 1
    assert json.loads(capsys.readouterr().out)["valid"] is False
    assert "candidate" not in STRATEGIES
