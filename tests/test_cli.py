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


def test_ev_cli_scores_five_meld_single_wait_without_an_18_tile_hand(
    monkeypatch, capsys,
):
    monkeypatch.setattr(sys, "argv", [
        "taimahjong",
        "123m456m789m123p456p1z2z",
        "--ev",
        "--opp-river", "3m1m9m",
        "--opp-declared", "0",
        "--turns", "6",
        "--sims", "24",
        "--seed", "1",
    ])

    cli.main()

    output = capsys.readouterr()
    assert "Discard  Net EV" in output.out
    assert "concealed hand has 18 tiles" not in output.err


@pytest.mark.parametrize("discard_counts", [None, (6, 7, 8)])
def test_ev_cli_forwards_total_discards_for_each_opponent(discard_counts, monkeypatch):
    captured = []

    def capture_rank(_hand, opponents, _visible, *_args, **_kwargs):
        captured.extend(opponents)
        return []

    flags = []
    for index, prefix in enumerate(("opp", "opp2", "opp3")):
        flags.extend([f"--{prefix}-river", "1234m"])
        if discard_counts is not None:
            flags.extend([f"--{prefix}-discard-count", str(discard_counts[index])])
    monkeypatch.setattr(cli, "ev_rank", capture_rank)
    monkeypatch.setattr(sys, "argv", [
        "taimahjong", "123m123p123s11122233z", "--ev",
        "--turns", "1", "--sims", "1", *flags,
    ])

    cli.main()

    # Called-away tiles still count toward the next-discard lookup key.
    expected = (4, 4, 4) if discard_counts is None else discard_counts
    assert tuple(opponent.discard_count for opponent in captured) == expected
    assert tuple(opponent.lookup_turn for opponent in captured) == tuple(
        count + 1 for count in expected
    )


@pytest.mark.parametrize("prefix", ["opp", "opp2", "opp3"])
def test_ev_cli_discard_count_requires_river(prefix, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", [
        "taimahjong", "123m123p123s11122233z", "--ev",
        f"--{prefix}-discard-count", "6",
    ])

    with pytest.raises(SystemExit) as error:
        cli.main()

    assert error.value.code == 2
    assert f"opponent state requires --{prefix}-river" in capsys.readouterr().err
