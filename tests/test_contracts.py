from pathlib import Path

import pytest

from enterovirus_genbank_curated.contracts import (
    ContractError,
    validate_contracts,
    validate_decision_ledger,
)

ROOT = Path(__file__).resolve().parents[1]


def test_repository_contracts_validate() -> None:
    validate_contracts(ROOT)


def test_fixture_ledger_is_human_readable_and_valid() -> None:
    summary = validate_decision_ledger(ROOT / "tests/fixtures/decisions.tsv")
    assert summary.rows == 2
    assert summary.active_rows == 2


def test_duplicate_active_assertions_fail_closed(tmp_path: Path) -> None:
    fixture = (ROOT / "tests/fixtures/decisions.tsv").read_text(encoding="utf-8")
    duplicate = fixture.replace("AF000002\tAF000002\tcountry", "AF000001\tAF000001\tclassification")
    path = tmp_path / "duplicate.tsv"
    path.write_text(duplicate, encoding="utf-8")
    with pytest.raises(ContractError, match="duplicate active assertion"):
        validate_decision_ledger(path)
