"""The legacy-decision migration must not quietly discard source columns."""

import subprocess
import sys
from pathlib import Path

from enterovirus_genbank_curated.contracts import DecisionContract, validate_decision_ledger

LEGACY_HEADER = "decision_type,accession,field_name,new_value,reason,confirmed_by"
LEGACY_ROWS = (
    "classification,AF000001,classification,wild,legacy assertion,curator",
    "location,AF000002,country,Pakistan,legacy assertion,curator",
)


def run_migration(repository_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    script = repository_root / "scripts/migrate_decisions.py"
    return subprocess.run(
        [sys.executable, str(script), "--repository-root", str(repository_root), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def write_legacy(tmp_path: Path, name: str, extra_column: str = "") -> Path:
    header = LEGACY_HEADER + (f",{extra_column}" if extra_column else "")
    rows = [row + (",dropped" if extra_column else "") for row in LEGACY_ROWS]
    path = tmp_path / name
    path.write_text("\n".join([header, *rows]) + "\n", encoding="utf-8")
    return path


def test_migration_produces_a_valid_ledger(
    tmp_path: Path, repository_root: Path, decision_contract: DecisionContract
) -> None:
    source = write_legacy(tmp_path, "legacy.csv")
    output = tmp_path / "decisions.tsv"
    result = run_migration(repository_root, str(source), "--output", str(output))
    assert result.returncode == 0, result.stderr

    summary = validate_decision_ledger(output, decision_contract)
    assert summary.rows == 2
    assert summary.active_rows == 2


def test_unmapped_legacy_columns_fail_closed(tmp_path: Path, repository_root: Path) -> None:
    source = write_legacy(tmp_path, "legacy.csv", extra_column="curator_scratch_note")
    output = tmp_path / "decisions.tsv"
    result = run_migration(repository_root, str(source), "--output", str(output))
    assert result.returncode == 1
    assert "no ledger destination" in result.stderr
    assert "curator_scratch_note" in result.stderr
    assert not output.exists()


def test_unmapped_columns_can_be_dropped_explicitly(
    tmp_path: Path, repository_root: Path, decision_contract: DecisionContract
) -> None:
    source = write_legacy(tmp_path, "legacy.csv", extra_column="curator_scratch_note")
    output = tmp_path / "decisions.tsv"
    result = run_migration(
        repository_root,
        str(source),
        "--output",
        str(output),
        "--drop-columns",
        "curator_scratch_note",
    )
    assert result.returncode == 0, result.stderr
    assert validate_decision_ledger(output, decision_contract).rows == 2
