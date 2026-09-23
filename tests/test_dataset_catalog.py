"""The persisted-data inventory must stay complete enough to be actionable."""

from pathlib import Path
import tomllib


ROOT = Path(__file__).parents[1]
CATALOG = ROOT / "catalog" / "datasets.toml"
REQUIRED_FIELDS = {
    "id",
    "layer",
    "path",
    "optional",
    "format",
    "owner",
    "regeneration_command",
    "primary_key",
    "schema",
    "size_bytes",
    "update_frequency",
    "reproducible_from_recorded_seed",
}
LAYERS = {"raw_input", "generated_output", "curated_reference", "report_artifact"}


def test_dataset_catalog_contract_and_paths():
    catalog = tomllib.loads(CATALOG.read_text(encoding="utf-8"))
    datasets = catalog["datasets"]
    assert datasets, "the catalog must not be empty"
    assert len({entry["id"] for entry in datasets}) == len(datasets)

    for entry in datasets:
        missing = REQUIRED_FIELDS - entry.keys()
        assert not missing, f"{entry.get('id', '<unnamed>')} missing {sorted(missing)}"
        assert entry["layer"] in LAYERS
        assert entry["schema"], f"{entry['id']} must declare its schema/columns"
        assert entry["size_bytes"] >= 0
        if entry["owner"] == "unknown":
            assert entry.get("known_gap"), f"{entry['id']} must explain unknown provenance"
        if not entry["optional"]:
            path = ROOT / entry["path"]
            assert path.exists(), entry["path"]
            if path.is_dir():
                files = [candidate for candidate in path.rglob("*") if candidate.is_file()]
                # A frozen evidence bundle pins its exact count; a living bundle such as
                # the README screenshots pins a floor, so adding one does not fail the suite.
                if "expected_file_count" in entry:
                    assert len(files) == entry["expected_file_count"], entry["id"]
                elif "minimum_file_count" in entry:
                    assert len(files) >= entry["minimum_file_count"], entry["id"]
                else:
                    raise AssertionError(
                        f"{entry['id']} must declare expected_file_count or minimum_file_count"
                    )
                assert {candidate.suffix for candidate in files} <= set(entry["bundle_extensions"])
                for member in entry.get("required_members", []):
                    assert (path / member).is_file(), f"{entry['id']} missing {member}"
