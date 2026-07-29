import json
from pathlib import Path

from enterovirus_genbank_curated.contracts import EXPECTED_BASELINE_COUNTS

ROOT = Path(__file__).resolve().parents[1]


def test_parity_spec_records_frozen_release_counts() -> None:
    spec = json.loads((ROOT / "releases/2.1.5/parity.json").read_text(encoding="utf-8"))
    assert spec["expected_counts"] == EXPECTED_BASELINE_COUNTS


def test_parity_spec_never_treats_final_as_input() -> None:
    spec = json.loads((ROOT / "releases/2.1.5/parity.json").read_text(encoding="utf-8"))
    assert spec["policy"]["existing_final_is_pipeline_input"] is False
    assert spec["policy"]["baseline_release_mutable"] is False
