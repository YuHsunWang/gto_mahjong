"""MJ-005 product claims stay within the implemented model scope."""

from pathlib import Path


ROOT = Path(__file__).parents[1]
CLAIM_FILES = [
    ROOT / "README.md",
    ROOT / "README.en.md",
    ROOT / "docs" / "ui-plan.md",
    ROOT / "server" / "static" / "js" / "main.js",
    ROOT / "server" / "static" / "js" / "quiz.js",
    ROOT / "server" / "static" / "js" / "feedback.js",
    ROOT / "taimahjong" / "selfplay.py",
    ROOT / "taimahjong" / "trainer.py",
]


def test_ui_readmes_and_metadata_do_not_make_unqualified_solver_claims():
    combined = "\n".join(path.read_text(encoding="utf-8") for path in CLAIM_FILES)
    lowered = combined.lower()
    assert "gto" not in lowered
    assert "理論最佳" not in combined
    assert "最佳解" not in combined
    assert "所有機率" not in combined
    assert "所有的機率" not in combined
    assert "all probabilities" not in lowered
    assert "theoretically best" not in lowered


def test_zh_and_en_methodology_cards_disclose_the_same_four_boundaries():
    zh = (ROOT / "README.md").read_text(encoding="utf-8")
    en = (ROOT / "README.en.md").read_text(encoding="utf-8")
    for phrase in ("Outcomes", "未建模", "Calibration domain", "Sampling uncertainty"):
        assert phrase in zh
    for phrase in ("Outcomes", "Not modeled", "Calibration domain", "Sampling uncertainty"):
        assert phrase in en
    assert "模型工程 owner" in zh
    assert "model-engineering owner" in en
