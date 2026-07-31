"""Assemble the canonical metadata table from transported columns and projected fields.

Until now the pipeline wrote no canonical table at all — only the thirteen-column transport plus
provenance — so there was no artifact anyone could use as a release. This is that artifact: all
twenty-six columns in the declared order, one row per carved record.

## A blank cell means one of two things, and the provenance says which

A canonical cell can be blank because a rule *chose* blank (a `locality` that would repeat `admin1`,
a `collection_year_earliest` on a record that is not a range) or because a rule **declined** and no
value is known. The table cannot express that difference — it is one empty string either way — and
that is exactly why `audit/projection_provenance.tsv.gz` ships beside it carrying
`unresolved_reason`, and why the curation queue carries a row per declined cell.

So the honest reading of this file is: a blank is not a claim. Anyone treating blank as "absent from
nature" rather than "not determined here" will be wrong on tens of thousands of cells, which is what
the `coverage` block in the sidecar JSON exists to say up front.

## Columns with no rule yet are blank for every row

Not silently. `write_canonical_table` refuses to run unless every canonical column is either
transported, projected, or named in `PENDING_COLUMNS` with a reason — so a column cannot become
quietly empty by being forgotten, only by being declared unfinished.
"""

from __future__ import annotations

import gzip
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from enterovirus_genbank_curated.contracts import CANONICAL_COLUMNS, ContractError
from enterovirus_genbank_curated.derive.metadata import PENDING_COLUMNS, TRANSPORTED_COLUMNS
from enterovirus_genbank_curated.export.source import deterministic_text_writer, write_tsv

CANONICAL_RELATIVE = "canonical/sequence_metadata.tsv.gz"
VOUCHED_RELATIVE = "canonical/sequence_metadata_vouched.tsv.gz"
SEQUENCES_RELATIVE = "canonical/sequences.fasta.gz"
CURATION_STATUS_COLUMN = "curation_status"
VOUCHED = "vouched"
FASTA_WRAP = 70


def assemble_canonical_rows(
    transport: Iterable[Mapping[str, str]], provenance: Iterable[Mapping[str, str]]
) -> list[dict[str, str]]:
    """One 26-column row per carved record, transported values plus projected values.

    A declined projection contributes nothing — the cell stays blank — because a declined cell has
    no value by definition. `RuleOutcome.__post_init__` already guarantees an unresolved outcome
    carries no value, so this cannot silently drop one that did.
    """
    projected: dict[str, dict[str, str]] = {}
    for row in provenance:
        if row["canonical_field"] not in CANONICAL_COLUMNS:
            raise ContractError(
                f"rule {row['winning_rule_id']} projects {row['canonical_field']!r}, which is not "
                f"a canonical column; its values would land in no column at all"
            )
        if row.get("unresolved_reason"):
            continue
        projected.setdefault(row["version"], {})[row["canonical_field"]] = row["final_value"]

    rows: list[dict[str, str]] = []
    for source in transport:
        row = dict.fromkeys(CANONICAL_COLUMNS, "")
        row.update({c: source[c] for c in TRANSPORTED_COLUMNS})
        row.update(projected.get(source["version"], {}))
        rows.append(row)
    return rows


def assert_every_column_is_accounted_for(rows: list[dict[str, str]]) -> dict[str, int]:
    """Every canonical column is transported, projected, or declared pending. Returns fill counts.

    Without this a column dropped from the rule catalog would ship as 24,285 blanks and look like a
    column whose values happen to be empty.
    """
    filled = {c: sum(1 for row in rows if row[c]) for c in CANONICAL_COLUMNS}
    unexplained = [
        c
        for c in CANONICAL_COLUMNS
        if not filled[c] and c not in TRANSPORTED_COLUMNS and c not in PENDING_COLUMNS
    ]
    if unexplained:
        raise ContractError(
            f"these canonical columns are blank on every row and are neither transported nor "
            f"declared pending: {unexplained}. A column cannot become empty by being forgotten."
        )
    return filled


def write_canonical_table(
    output_dir: Path,
    rows: list[dict[str, str]],
    sequences: Mapping[str, str],
) -> dict[str, Any]:
    """Write the canonical table, the vouched subset and the FASTA payload.

    The vouched subset is recomputed from `curation_status` rather than tracked separately, which is
    the same reason `oracle/release.py` recounts it instead of inferring it by subtraction.
    """
    assert_every_column_is_accounted_for(rows)
    write_tsv(output_dir / CANONICAL_RELATIVE, CANONICAL_COLUMNS, rows)
    vouched = [row for row in rows if row[CURATION_STATUS_COLUMN] == VOUCHED]
    write_tsv(output_dir / VOUCHED_RELATIVE, CANONICAL_COLUMNS, vouched)

    missing = [row["version"] for row in rows if row["version"] not in sequences]
    if missing:
        raise ContractError(
            f"{len(missing)} carved records have no sequence to write ({missing[:5]}); the FASTA "
            f"payload and the metadata table must cover the same records exactly"
        )
    path = output_dir / SEQUENCES_RELATIVE
    path.parent.mkdir(parents=True, exist_ok=True)
    with deterministic_text_writer(path) as handle:
        for row in rows:
            sequence = sequences[row["version"]]
            handle.write(f">{row['version']}\n")
            for start in range(0, len(sequence), FASTA_WRAP):
                handle.write(sequence[start : start + FASTA_WRAP] + "\n")
    return {"canonical_rows": len(rows), "vouched_rows": len(vouched)}


def read_canonical_table(output_dir: Path) -> list[dict[str, str]]:
    """Read a written canonical table back, requiring the declared header exactly."""
    import csv

    path = output_dir / CANONICAL_RELATIVE
    try:
        with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle, delimiter="\t", quoting=csv.QUOTE_MINIMAL)
            if tuple(reader.fieldnames or ()) != CANONICAL_COLUMNS:
                raise ContractError(f"{path} header is {reader.fieldnames}, not CANONICAL_COLUMNS")
            return list(reader)
    except OSError as exc:
        raise ContractError(f"cannot read {path}: {exc}") from exc
