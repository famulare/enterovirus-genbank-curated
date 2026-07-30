import json
from pathlib import Path

import pytest

from enterovirus_genbank_curated.contracts import (
    DECISION_COLUMNS,
    DECISIONS_SCHEMA_PATH,
    ContractError,
    DecisionContract,
    load_decision_contract,
    validate_decision_ledger,
)
from enterovirus_genbank_curated.oracle.release import validate_contracts


def rewrite_fixture(tmp_path: Path, source: Path, *replacements: tuple[str, str]) -> Path:
    text = source.read_text(encoding="utf-8")
    for old, new in replacements:
        assert old in text, f"fixture no longer contains {old!r}"
        text = text.replace(old, new, 1)
    path = tmp_path / "ledger.tsv"
    path.write_text(text, encoding="utf-8")
    return path


def test_repository_contracts_validate(repository_root: Path) -> None:
    validate_contracts(repository_root)


def test_shape_only_validation_is_available(repository_root: Path) -> None:
    validate_contracts(repository_root, verify_baseline=False)


def test_ledger_contract_is_derived_from_the_published_schema(
    decision_contract: DecisionContract,
) -> None:
    assert decision_contract.columns == DECISION_COLUMNS
    assert decision_contract.non_blank_columns == {
        "decision_type",
        "subject_key",
        "field_name",
        "new_value",
        "source_artifact",
    }
    assert dict(decision_contract.enums)["status"] == {"active", "superseded", "retired"}
    assert [name for name, _ in decision_contract.patterns] == ["decision_id"]


def test_fixture_ledger_is_human_readable_and_valid(
    fixture_ledger: Path, decision_contract: DecisionContract
) -> None:
    summary = validate_decision_ledger(fixture_ledger, decision_contract)
    assert summary.rows == 2
    assert summary.active_rows == 2


@pytest.mark.parametrize(
    ("replacements", "expected"),
    [
        pytest.param(
            (("D-fedcba9876543210", "D-NOT-HEX"),),
            "does not match",
            id="malformed_decision_id",
        ),
        pytest.param(
            (("D-fedcba9876543210", "D-0123456789abcdef"),),
            "duplicate decision_id",
            id="duplicate_decision_id",
        ),
        pytest.param(
            (("legacy/location.csv\tactive", "legacy/location.csv\tprovisional"),),
            "invalid status",
            id="invalid_status",
        ),
        pytest.param(
            (("\tlocation\t", "\taaa_first\t"),),
            "not in deterministic sort order",
            id="out_of_order",
        ),
        pytest.param(
            (("AF000002\tAF000002\tcountry", "AF000001\tAF000001\tclassification"),),
            "duplicate active assertion",
            id="duplicate_active_assertion",
        ),
        pytest.param(
            (("\tlegacy/location.csv\t", "\t\t"),),
            "source_artifact must not be blank",
            id="blank_source_artifact",
        ),
        pytest.param(
            (("\tcountry\tPakistan\t", "\tcountry\t\t"),),
            "new_value must not be blank",
            id="blank_new_value",
        ),
        pytest.param(
            (("decision_id\tdecision_type", "id\tdecision_type"),),
            "columns must exactly match",
            id="renamed_column",
        ),
        pytest.param(
            (("legacy/location.csv\tactive\t\t\t", "legacy/location.csv\tactive\t\t\t\textra"),),
            "more fields than the header",
            id="extra_field",
        ),
        pytest.param(
            (("legacy/location.csv\tactive\t\t\t", "legacy/location.csv\tactive"),),
            "fewer fields than the header",
            id="missing_field",
        ),
    ],
)
def test_ledger_fails_closed(
    tmp_path: Path,
    fixture_ledger: Path,
    decision_contract: DecisionContract,
    replacements: tuple[tuple[str, str], ...],
    expected: str,
) -> None:
    path = rewrite_fixture(tmp_path, fixture_ledger, *replacements)
    with pytest.raises(ContractError, match=expected):
        validate_decision_ledger(path, decision_contract)


def test_missing_ledger_fails_closed(
    tmp_path: Path, decision_contract: DecisionContract
) -> None:
    with pytest.raises(ContractError, match="cannot read decision ledger"):
        validate_decision_ledger(tmp_path / "absent.tsv", decision_contract)


def test_schema_column_drift_fails_closed(tmp_path: Path, repository_root: Path) -> None:
    """The published schema and the documented column order cannot diverge silently."""
    schema = json.loads(
        (repository_root / DECISIONS_SCHEMA_PATH).read_text(encoding="utf-8")
    )
    schema["required"] = list(reversed(schema["required"]))
    path = tmp_path / "decisions.schema.json"
    path.write_text(json.dumps(schema), encoding="utf-8")
    with pytest.raises(ContractError, match="must match the documented ledger column order"):
        load_decision_contract(path)
