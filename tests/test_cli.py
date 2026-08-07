"""Command-line wiring for multi-opponent EV input."""

import sys

import pytest

from taimahjong import __main__ as cli


@pytest.mark.parametrize(
    ("flags", "expected"),
    [
        (["--opp-river", "9m"], 1),
        (
            [
                "--opp-river", "9m",
                "--opp2-river", "9p", "--opp2-melds", "111p",
                "--opp3-river", "1z", "--opp3-dealer", "--opp3-streak", "2",
            ],
            3,
        ),
    ],
)
def test_ev_cli_forwards_legacy_or_three_opponents(
    flags, expected, monkeypatch, capsys,
):
    captured = {}

    def capture_rank(_hand, opponents, _visible, *_args, **_kwargs):
        captured["opponents"] = opponents
        return []

    monkeypatch.setattr(cli, "ev_rank", capture_rank)
    monkeypatch.setattr(sys, "argv", [
        "taimahjong",
        "123m123p123s11122233z",
        "--ev",
        "--turns", "1",
        "--sims", "1",
        *flags,
    ])

    cli.main()

    assert len(captured["opponents"]) == expected
    assert "Discard  Net EV" in capsys.readouterr().out
    if expected == 3:
        assert captured["opponents"][1].melds
        assert captured["opponents"][2].is_dealer
