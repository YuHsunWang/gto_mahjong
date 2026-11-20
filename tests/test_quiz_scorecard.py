"""Tied top-pair picks earn best credit without charging sampling noise."""

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from server import api
from taimahjong.analysis import AnalysisContext


@pytest.mark.parametrize("ranking_state", ["uncertain", "marginal", "clear"])
@pytest.mark.parametrize("chosen_tile", [0, 1, 2])
def test_trainer_scorecard_credits_only_the_tied_top_pair(monkeypatch, ranking_state, chosen_tile):
    class Decision:
        position = None

    current = Decision()

    def generator():
        yield current
        yield current

    play = generator()
    assert next(play) is current
    session = api._TrainerSession(1, 0, 0, play, current, AnalysisContext())
    feedback = {
        "verdict": "best" if chosen_tile == 0 else "good",
        "ev_loss": 0.0 if chosen_tile == 0 else 0.2,
        "ranking_state": ranking_state,
        "chosen": {"discard": chosen_tile},
        "top1_vs_top2": {"top_discard": 0, "runner_up_discard": 1},
    }
    monkeypatch.setattr(api, "TrainerDecision", Decision)
    monkeypatch.setattr(api, "_get_session", lambda _id: session)
    monkeypatch.setattr(api, "grade", lambda *_args: SimpleNamespace(**feedback))
    monkeypatch.setattr(api, "_grade_payload", lambda _result: feedback)
    monkeypatch.setattr(api, "_session_payload", lambda _id, value: value.score)

    score = api.trainer_act("session", api.TrainerActRequest(
        step=0, action="discard", tile=chosen_tile,
    ))

    tied = ranking_state != "clear" and chosen_tile in (0, 1)
    assert score == {
        "decisions": 1,
        "best": int(chosen_tile == 0 or tied),
        "loss": 0.0 if tied else feedback["ev_loss"],
    }


@pytest.mark.parametrize("mode", ["quiz", "trainer", "endgame"])
def test_browser_scorecard_credits_ties_and_preserves_worse_pick_loss(mode):
    stats_url = (Path(__file__).resolve().parents[1] / "server/static/js/stats.js").as_uri()
    script = """
import assert from 'node:assert/strict';
const stored = new Map();
globalThis.localStorage = {
  getItem: key => stored.get(key) ?? null,
  setItem: (key, value) => stored.set(key, value),
};
const { record, summary } = await import(process.argv[1]);
const mode = process.argv[2];
for (const ranking_state of ['uncertain', 'marginal']) {
  for (const discard of [0, 1]) {
    record(mode, {
      verdict: discard === 0 ? 'best' : 'good', ev_loss: 0.2,
      ranking_state, chosen: { discard },
      top1_vs_top2: { top_discard: 0, runner_up_discard: 1 },
    }, '3-1');
  }
}
assert.equal(summary(mode, '3-1').best, 4);
assert.equal(summary(mode, '3-1').loss, 0);
for (const ranking_state of ['uncertain', 'clear']) {
  record(mode, {
    verdict: 'mistake', ev_loss: 1.5, ranking_state,
    chosen: { discard: 2 },
    top1_vs_top2: { top_discard: 0, runner_up_discard: 1 },
  }, '3-1');
}
record(mode, 'best', 0, '3-1'); // Call/kong and legacy scalar grading.
assert.equal(summary(mode, '3-1').decisions, 7);
assert.equal(summary(mode, '3-1').best, 5);
assert.equal(summary(mode, '3-1').loss, 3);
"""
    result = subprocess.run(
        ["node", "--input-type=module",
         "-e", script, stats_url, mode],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr


def test_hand_review_counts_one_hand_like_the_stored_totals():
    """The hand score must agree with the review rows the player reads.

    A row is shown unranked only for a pick inside the unresolved top pair; any
    other pick keeps its verdict colour even when the top pair is unresolved,
    so it must count toward the hand's quality score by that verdict.
    """
    stats_url = (Path(__file__).resolve().parents[1] / "server/static/js/stats.js").as_uri()
    script = """
import assert from 'node:assert/strict';
const stored = new Map();
globalThis.localStorage = {
  getItem: key => stored.get(key) ?? null,
  setItem: (key, value) => stored.set(key, value),
};
const { record, summary, handSummary } = await import(process.argv[1]);
const pair = { top_discard: 0, runner_up_discard: 1 };
const hand = [
  { verdict: 'best', ev_loss: 0, ranking_state: 'clear', chosen: { discard: 0 }, top1_vs_top2: pair },
  { verdict: 'good', ev_loss: 0.2, ranking_state: 'clear', chosen: { discard: 3 }, top1_vs_top2: pair },
  { verdict: 'mistake', ev_loss: 1.5, ranking_state: 'clear', chosen: { discard: 2 }, top1_vs_top2: pair },
  // Tied top-pair pick: unresolved, no loss charged.
  { verdict: 'good', ev_loss: 0.3, ranking_state: 'uncertain', chosen: { discard: 1 }, top1_vs_top2: pair },
  { kind: 'call', verdict: 'inaccuracy', ev_loss: 0.6, ranking_state: 'clear' },
  // Unresolved top pair, but the pick is outside it: still a plain mistake.
  { verdict: 'mistake', ev_loss: 1.5, ranking_state: 'uncertain', chosen: { discard: 2 }, top1_vs_top2: pair },
];
hand.forEach(grade => record('trainer', grade, '3-1'));
const one = handSummary(hand);
assert.deepEqual(one.counts, { best: 1, good: 1, inaccuracy: 1, mistake: 2 });
assert.equal(one.unresolved, 1);
assert.equal(one.separable, 5);
assert.equal(one.qualityScore, 40);
assert.equal(one.decisions, 6);
assert.equal(one.loss, summary('trainer', '3-1').loss); // same tie rule for loss
assert.equal(Math.round(one.loss * 100), 380);
"""
    result = subprocess.run(
        ["node", "--input-type=module",
         "-e", script, stats_url],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr
