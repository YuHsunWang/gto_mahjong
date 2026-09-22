"""MJ-005 product claims stay within the implemented model scope."""

from pathlib import Path
import re
import tomllib


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
    # These words are barred because they are not true yet, not because they are
    # forbidden. Production still runs a fixed deterministic policy at every
    # seat, and reference_ev.py remains an outcome/payment oracle over draw
    # orders rather than a game-theoretic solve (see its module docstring).
    #
    # Since 2026-08-24 best_response.py does solve one acting seat's best
    # response in the <=4-tile endgame and reports its exploitability, which is
    # what earns the scoped wording in docs/equilibrium-plan.md. That is still
    # not an equilibrium: no seat best-responds to a best-responding opponent,
    # and nothing production serves is solved. So every bar below stays.
    #
    # To lift a bar, earn it and scope the wording to what was actually solved --
    # e.g. computing an equilibrium for the shallow-endgame subgame would license
    # "GTO-solved in the <=N-tile endgame", not a bare "GTO trainer".
    # docs/equilibrium-plan.md records what has and has not been done.
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


def test_readme_python_badges_match_declared_floor():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    floor = project["project"]["requires-python"].removeprefix(">=")
    for name in ("README.md", "README.en.md"):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert f"python-{floor}%2B" in text


def test_p_win_is_not_labeled_as_self_draw():
    feedback = (ROOT / "server" / "static" / "js" / "feedback.js").read_text(encoding="utf-8")
    main = (ROOT / "server" / "static" / "js" / "main.js").read_text(encoding="utf-8")
    assert "P(自摸)" not in feedback
    assert "P(自摸)" not in main


def test_frontend_fold_principles_cover_backend_contract():
    from taimahjong.ev import FOLD_PRINCIPLE_KEYS

    feedback = (ROOT / "server" / "static" / "js" / "feedback.js").read_text(encoding="utf-8")
    match = re.search(r"const FOLD_PRINCIPLES = \{(.*?)\n\};", feedback, re.DOTALL)
    assert match is not None
    frontend_keys = set(re.findall(r"^\s{2}([a-z_]+):", match.group(1), re.MULTILINE))
    assert frontend_keys == set(FOLD_PRINCIPLE_KEYS)


def test_tile_face_module_exports_cover_imports_and_no_generator_overwrites_it():
    tile_faces = (ROOT / "server" / "static" / "js" / "tile-faces.js").read_text(encoding="utf-8")
    tiles = (ROOT / "server" / "static" / "js" / "tiles.js").read_text(encoding="utf-8")
    import_match = re.search(
        r"import\s*\{(?P<names>.*?)\}\s*from\s*['\"]\./tile-faces\.js['\"]\s*;",
        tiles,
        re.DOTALL,
    )
    assert import_match is not None
    imported = import_match.group("names")
    imported_names = {name.strip() for name in imported.split(",")}
    exported_names = set(re.findall(r"^export (?:const|function) (\w+)", tile_faces, re.MULTILINE))
    assert imported_names <= exported_names

    for script in (ROOT / "scripts").glob("*.py"):
        assert "server/static/js/tile-faces.js" not in script.read_text(encoding="utf-8")
