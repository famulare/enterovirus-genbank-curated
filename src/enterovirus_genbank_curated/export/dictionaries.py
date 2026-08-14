"""The four shipped data dictionaries, with every count measured rather than remembered.

These were carried from release 2.4.1 as opaque bytes, and by 2026-08-14 all four were wrong:

* `canonical_data_dictionary.tsv` froze `nonempty_count`/`row_count` at 24,301 against a built carve
  of 24,308, and still reported `sequence_scope` as 24,301-of-24,301 non-empty while the column
  shipped **empty on every row**. A dictionary that calls a column fully populated when it is
  entirely blank is worse than no dictionary.
* `audit_data_dictionary.tsv` documented `manual_decisions`, which has not shipped since the
  promotion, and `canonical_projection_provenance`, which ships as `projection_provenance.tsv.gz`.
  It pinned `rules` at 28 rows and 4 columns against 39 and 5, and omitted four tables that do ship
  — `classification_divergence`, `decision_applications`, `membership_rescue` and
  `release_file_manifest`.
* `controlled_vocabularies.tsv` declared seven field vocabularies and omitted `sample_origin`,
  `surveillance_stream`, `specimen_type` and `virus_type` — the four columns whose ledger assertions
  are written with no vocabulary check at all, which is precisely where a declared vocabulary earns
  its keep.
* `source_schema_dictionary.tsv` pinned per-table row counts from a parse the build now regenerates
  every run.

## The split: prose is declared data, numbers are measurements

The per-column prose is authored content and has to live somewhere, so it lives in
`registry/dictionaries/` beside `registry/rules.json` — hand-editable, diffable, and an *input* to
the build rather than a copy of its output. It was carried verbatim from what 2.4.1 shipped, because
it was hand-written and good.

Every **count** is computed here from the tables being written, in the build that writes them. That
is the whole difference between this module and the bytes it replaces: a number in a dictionary is
now a measurement of the release it ships with and has no second place to drift from.

Putting the prose in Python literals was tried first and rejected: 769 lines of long strings in a
module, exceeding the line limit and needing a lint exception, to hold data that `registry/` already
exists to hold.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

from enterovirus_genbank_curated.contracts import CANONICAL_COLUMNS, ContractError
from enterovirus_genbank_curated.export.source import write_tsv

REGISTRY_DIR = "registry/dictionaries"
CANONICAL_FIELDS_PATH = f"{REGISTRY_DIR}/canonical_fields.tsv"
AUDIT_FIELDS_PATH = f"{REGISTRY_DIR}/audit_fields.tsv"
SOURCE_FIELDS_PATH = f"{REGISTRY_DIR}/source_fields.tsv"
VOCABULARIES_PATH = f"{REGISTRY_DIR}/controlled_vocabularies.tsv"

CANONICAL_RELATIVE = "dictionaries/canonical_data_dictionary.tsv"
AUDIT_RELATIVE = "dictionaries/audit_data_dictionary.tsv"
SOURCE_RELATIVE = "dictionaries/source_schema_dictionary.tsv"
VOCABULARIES_RELATIVE = "dictionaries/controlled_vocabularies.tsv"

# The declared prose columns, and then the measured ones. Order is the shipped column order.
CANONICAL_PROSE_COLUMNS = (
    "column_name", "definition", "logical_type", "physical_type", "nullable", "key_role",
    "controlled_vocabulary", "missing_value_semantics", "unit", "source_or_curated", "derivation",
    "example", "ml_utility", "ml_leakage_risk",
)
CANONICAL_DICT_COLUMNS = (*CANONICAL_PROSE_COLUMNS, "nonempty_count", "row_count")

TABLE_PROSE_COLUMNS = (
    "table_name", "column_name", "definition", "logical_type", "physical_type", "nullable",
    "key_role",
)
TABLE_DICT_COLUMNS = (*TABLE_PROSE_COLUMNS, "row_count")

VOCABULARY_COLUMNS = ("field", "value", "definition")


def read_declared(path: Path, columns: Sequence[str]) -> list[dict[str, str]]:
    """A registry dictionary table, requiring its declared header exactly.

    Hand-parsed rather than through `csv`, for the same reason `registry/decisions.tsv` is: what
    these files are worth is that `cut -f2` and a spreadsheet import agree, and a quoted field would
    break the naive tools silently. A tab inside a definition is a hard error, not an escape.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ContractError(f"cannot read {path}: {exc}") from exc
    if '"' in text:
        raise ContractError(
            f"{path} contains a double quote, so some field is escaped and naive tab-splitting is "
            f"no longer safe; use typographic quotes in dictionary prose"
        )
    lines = text.rstrip("\n").split("\n")
    if tuple(lines[0].split("\t")) != tuple(columns):
        raise ContractError(f"{path} header is {lines[0].split(chr(9))}, not {list(columns)}")
    out: list[dict[str, str]] = []
    for number, line in enumerate(lines[1:], start=2):
        fields = line.split("\t")
        if len(fields) != len(columns):
            raise ContractError(
                f"{path}:{number} has {len(fields)} fields, not {len(columns)}"
            )
        out.append(dict(zip(columns, fields, strict=True)))
    return out


def canonical_dictionary_rows(
    declared: Sequence[Mapping[str, str]], rows: Sequence[Mapping[str, str]]
) -> list[dict[str, str]]:
    """One row per canonical column, with `nonempty_count` measured over `rows`.

    Both directions are checked. A canonical column with no declared prose would otherwise ship a
    blank definition, and a documented column the table does not have would describe nothing — which
    is how `manual_decisions` stayed in the audit dictionary for three releases after it stopped
    being written.
    """
    prose = {row["column_name"]: row for row in declared}
    undocumented = [column for column in CANONICAL_COLUMNS if column not in prose]
    if undocumented:
        raise ContractError(
            f"these canonical columns have no dictionary entry: {undocumented}. A shipped column "
            f"with no definition is a column nobody can read."
        )
    orphaned = sorted(set(prose) - set(CANONICAL_COLUMNS))
    if orphaned:
        raise ContractError(
            f"{CANONICAL_FIELDS_PATH} documents columns the canonical table does not have: "
            f"{orphaned}"
        )
    total = len(rows)
    return [
        {
            **{name: prose[column][name] for name in CANONICAL_PROSE_COLUMNS},
            "nonempty_count": str(sum(1 for row in rows if row.get(column, ""))),
            "row_count": str(total),
        }
        for column in CANONICAL_COLUMNS
    ]


def table_dictionary_rows(
    declared: Sequence[Mapping[str, str]],
    shapes: Mapping[str, tuple[Sequence[str], int]],
    where: str,
) -> list[dict[str, str]]:
    """Per-table column documentation plus that table's measured row count.

    `shapes` maps table name to `(columns, row_count)` as actually written. Every documented table
    must be present and every present table documented, and within a table every column must be
    documented — the three ways this file went stale, each now a build failure.
    """
    documented = {(row["table_name"], row["column_name"]) for row in declared}
    documented_tables = {row["table_name"] for row in declared}
    missing_tables = sorted(set(shapes) - documented_tables)
    extra_tables = sorted(documented_tables - set(shapes))
    if missing_tables or extra_tables:
        raise ContractError(
            f"{where} documents tables {extra_tables} that are not written and omits "
            f"{missing_tables} that are"
        )
    gaps = sorted(
        (table, column)
        for table, (columns, _) in shapes.items()
        for column in columns
        if (table, column) not in documented
    )
    if gaps:
        raise ContractError(f"{where} has no entry for these written columns: {gaps}")
    stale = sorted(
        (table, column)
        for table, column in documented
        if column not in shapes[table][0]
    )
    if stale:
        raise ContractError(f"{where} documents columns that are not written: {stale}")
    return [
        {
            **{name: row[name] for name in TABLE_PROSE_COLUMNS},
            "row_count": str(shapes[row["table_name"]][1]),
        }
        for row in declared
    ]


def source_table_shapes(
    tables: Mapping[str, Sequence[Mapping[str, str]]],
) -> dict[str, tuple[Sequence[str], int]]:
    """`(columns, rows)` per normalized source table, from the parser's own declaration.

    `TABLE_COLUMNS` is what the writer uses, so reading the shape from the same place means a table
    gaining a column cannot leave its dictionary entry behind — the check in
    `table_dictionary_rows` fires instead.
    """
    from enterovirus_genbank_curated.genbank.parse import TABLE_COLUMNS

    return {name: (TABLE_COLUMNS[name], len(tables[name])) for name in TABLE_COLUMNS}


def written_audit_shapes(output_dir: Path) -> dict[str, tuple[Sequence[str], int]]:
    """`(columns, rows)` per audit table, read back off what this build just wrote.

    Deliberately measured from the artifacts rather than from the writers' column constants. The
    dictionary's job is to describe the tables it ships beside, and the only way to be sure it does
    is to open them. It also means a table that stops being written fails here — `manual_decisions`
    vanished three releases ago and the dictionary went on describing 2,912 rows of it.

    The file set comes from `BUILD_ARTIFACT_RELATIVES`, not from listing the directory. An earlier
    draft globbed `audit/` and the undeclared-input guard stopped the build on
    `record_disposition.tsv.gz` — a *carried* file, sitting in `final/audit/` and written by
    nothing.
    Globbing a build destination is how you read the previous release by accident, which is the one
    thing this pipeline must never do.

    So this documents what `build-metadata` writes, which is not everything under `final/audit/`.
    Two files ship there without a producer and are deliberately absent from the dictionary rather
    than described from a remembered shape: `sequence_evidence.tsv.gz`, carried until the deferred
    EV reference-panel pass gives it one, and `release_file_manifest.tsv`, which is the manifest
    rather than an audit table and declares its own columns while hashing the rest. Describing
    a carried file from a remembered shape is how this dictionary went wrong in the first place.
    `record_disposition.tsv.gz` joins as soon as it has a writer.
    """
    import csv
    import gzip

    from enterovirus_genbank_curated.export.release import BUILD_ARTIFACT_RELATIVES

    csv.field_size_limit(1 << 30)
    shapes: dict[str, tuple[Sequence[str], int]] = {}
    for relative in BUILD_ARTIFACT_RELATIVES:
        if not relative.startswith("audit/") or relative.endswith(".json"):
            continue
        path = output_dir / relative
        opener = gzip.open if path.suffix == ".gz" else open
        with opener(path, "rt", encoding="utf-8", newline="") as handle:  # type: ignore[operator]
            reader = csv.DictReader(handle, delimiter="\t")
            shapes[path.name.split(".")[0]] = (
                tuple(reader.fieldnames or ()),
                sum(1 for _ in reader),
            )
    return shapes


def write_dictionaries(
    repository_root: Path,
    output_dir: Path,
    canonical_rows: Sequence[Mapping[str, str]],
    source_shapes: Mapping[str, tuple[Sequence[str], int]],
    audit_shapes: Mapping[str, tuple[Sequence[str], int]],
) -> dict[str, int]:
    """Write all four dictionaries. Returns row counts for the build manifest."""
    canonical = canonical_dictionary_rows(
        read_declared(repository_root / CANONICAL_FIELDS_PATH, CANONICAL_PROSE_COLUMNS),
        canonical_rows,
    )
    write_tsv(output_dir / CANONICAL_RELATIVE, CANONICAL_DICT_COLUMNS, canonical)

    source = table_dictionary_rows(
        read_declared(repository_root / SOURCE_FIELDS_PATH, TABLE_PROSE_COLUMNS),
        source_shapes,
        SOURCE_FIELDS_PATH,
    )
    write_tsv(output_dir / SOURCE_RELATIVE, TABLE_DICT_COLUMNS, source)

    audit = table_dictionary_rows(
        read_declared(repository_root / AUDIT_FIELDS_PATH, TABLE_PROSE_COLUMNS),
        audit_shapes,
        AUDIT_FIELDS_PATH,
    )
    write_tsv(output_dir / AUDIT_RELATIVE, TABLE_DICT_COLUMNS, audit)

    vocabularies = read_declared(repository_root / VOCABULARIES_PATH, VOCABULARY_COLUMNS)
    write_tsv(output_dir / VOCABULARIES_RELATIVE, VOCABULARY_COLUMNS, vocabularies)

    return {
        "canonical_dictionary_rows": len(canonical),
        "source_dictionary_rows": len(source),
        "audit_dictionary_rows": len(audit),
        "controlled_vocabulary_rows": len(vocabularies),
    }
