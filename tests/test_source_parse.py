"""The source layer must reproduce the shipped release from `raw/` alone.

Two tiers, deliberately separated:

* fast — a synthetic three-record flat file exercising the parse and write contracts;
* slow (`-m slow`) — the real 25,727-record corpus, byte-compared against the shipped release.

The slow tier is the one that actually proves the claim, so it runs in CI. The fast tier is what
makes the parser tractable to iterate on.
"""

from __future__ import annotations

import csv
import gzip
import warnings
from pathlib import Path

import pytest
from Bio import BiopythonParserWarning

from enterovirus_genbank_curated import build as build_module
from enterovirus_genbank_curated.build import (
    build_source_layer,
    reject_immutable_output,
)
from enterovirus_genbank_curated.contracts import ContractError
from enterovirus_genbank_curated.export.source import write_source_tsv, write_tsv
from enterovirus_genbank_curated.genbank.parse import (
    EXPECTED_PARSER_WARNINGS,
    RAW_COLUMNS,
    TABLE_COLUMNS,
    collapse,
    parse_source_tables,
    sha256_text,
    split_authors,
    verbatim,
)
from enterovirus_genbank_curated.oracle.parity import verify_source_parity

SYNTHETIC_GENBANK = """\
LOCUS       TEST0001                  12 bp    RNA     linear   VRL 01-JAN-2020
DEFINITION  Test virus  with   collapsed   spacing, isolate T/1.
ACCESSION   TEST0001 TEST9999
VERSION     TEST0001.1
DBLINK      BioSample: SAMN00000001
KEYWORDS    alpha; beta.
SOURCE      Test virus
  ORGANISM  Test virus
            Viruses; Riboviria; Enterovirus.
REFERENCE   1  (bases 1 to 12)
  AUTHORS   Smith,A.B. and Jones,C.
  TITLE     A title
            spanning lines
  JOURNAL   Test J 1, 1-2 (2020)
   PUBMED   12345678
COMMENT     A free-text comment
            over two lines.
            ##Assembly-Data-START##
            Assembly Method :: Test Assembler v. 1.0
            Sequencing Technology :: Illumina
            ##Assembly-Data-END##
FEATURES             Location/Qualifiers
     source          1..12
                     /organism="Test virus"
                     /db_xref="taxon:12345"
                     /isolate="T/1"
                     /host="Homo sapiens"
                     /geo_loc_name="Nigeria: Kano, North"
     CDS             join(1..6,7..12)
                     /product="polyprotein"
ORIGIN
        1 acgtacgtac gt
//
LOCUS       TEST0002                   6 bp    RNA     linear   VRL 02-JAN-2020
DEFINITION  Minimal record.
ACCESSION   TEST0002
VERSION     TEST0002.2
SOURCE      Test virus
  ORGANISM  Test virus
            Viruses.
FEATURES             Location/Qualifiers
     source          1..6
ORIGIN
        1 acgtac
//
"""


@pytest.fixture(scope="module")
def synthetic(tmp_path_factory: pytest.TempPathFactory) -> dict[str, list[dict[str, str]]]:
    path = tmp_path_factory.mktemp("gb") / "synthetic.gb"
    path.write_text(SYNTHETIC_GENBANK, encoding="utf-8")
    return parse_source_tables(path)


def test_every_declared_table_has_rows_for_this_fixture(
    synthetic: dict[str, list[dict[str, str]]],
) -> None:
    """`set(synthetic) == set(TABLE_COLUMNS)` is true by construction, so assert content instead.

    The fixture is built to exercise every relation; a table that comes back empty means the
    parser stopped populating it.
    """
    empty = sorted(name for name, rows in synthetic.items() if not rows)
    assert empty == [], f"fixture produced no rows for {empty}"


def test_rows_only_use_declared_columns(synthetic: dict[str, list[dict[str, str]]]) -> None:
    for name, rows in synthetic.items():
        for row in rows:
            undeclared = set(row) - set(TABLE_COLUMNS[name])
            assert not undeclared, f"{name} produced undeclared columns {sorted(undeclared)}"


def test_record_identity_and_sequence_hash(synthetic: dict[str, list[dict[str, str]]]) -> None:
    records = {r["version"]: r for r in synthetic["records"]}
    assert set(records) == {"TEST0001.1", "TEST0002.2"}
    first = records["TEST0001.1"]
    assert first["accession"] == "TEST0001"
    assert first["record_ordinal"] == "1"
    assert first["sequence_length_nt"] == "12"
    assert first["sequence_sha256"] == sha256_text("ACGTACGTACGT")
    assert first["ncbi_taxid"] == "12345"


def test_definition_is_verbatim_but_locus_is_collapsed(
    synthetic: dict[str, list[dict[str, str]]],
) -> None:
    """`definition` is submitter prose and must keep its spacing; identifiers are normalized."""
    first = next(r for r in synthetic["records"] if r["version"] == "TEST0001.1")
    assert "with   collapsed   spacing" in first["definition"]
    assert first["locus_name"] == "TEST0001"


def test_secondary_accessions_are_roled_and_deduplicated(
    synthetic: dict[str, list[dict[str, str]]],
) -> None:
    rows = [r for r in synthetic["record_accessions"] if r["record_id"] == "TEST0001.1"]
    assert [(r["accession"], r["accession_role"]) for r in rows] == [
        ("TEST0001", "primary"),
        ("TEST9999", "secondary"),
    ]


def test_compound_location_yields_one_part_per_span(
    synthetic: dict[str, list[dict[str, str]]],
) -> None:
    cds = next(r for r in synthetic["features"] if r["feature_key"] == "CDS")
    parts = [
        p for p in synthetic["feature_location_parts"] if p["feature_id"] == cds["feature_id"]
    ]
    spans = [(p["start_1based"], p["end_1based_inclusive"]) for p in parts]
    assert spans == [("1", "6"), ("7", "12")]
    assert {p["strand"] for p in parts} == {"+"}


def test_dblink_biosample_is_split_on_the_first_colon(
    synthetic: dict[str, list[dict[str, str]]],
) -> None:
    xrefs = [r for r in synthetic["record_xrefs"] if r["record_id"] == "TEST0001.1"]
    assert [(r["database_name"], r["identifier"]) for r in xrefs] == [
        ("BioSample", "SAMN00000001")
    ]


def test_comment_is_captured_and_records_without_one_are_absent(
    synthetic: dict[str, list[dict[str, str]]],
) -> None:
    ids = {c["record_id"] for c in synthetic["comments"]}
    assert ids == {"TEST0001.1"}


def test_author_split_is_a_convenience_over_a_lossless_field() -> None:
    assert split_authors("Smith,A.B. and Jones,C.") == ["Smith", "A.B. and Jones", "C."]


def test_collapse_and_verbatim_differ_exactly_where_intended() -> None:
    assert collapse("  a \n b  ") == "a b"
    assert verbatim("  a \n b  ") == "  a \n b  "
    assert collapse(None) == ""
    assert verbatim(None) == ""


def test_written_tsv_round_trips_and_is_deterministic(
    tmp_path: Path, synthetic: dict[str, list[dict[str, str]]]
) -> None:
    first = write_source_tsv(tmp_path / "a", synthetic)
    second = write_source_tsv(tmp_path / "b", synthetic)
    assert first == second
    for name in TABLE_COLUMNS:
        a = (tmp_path / "a" / "normalized_tsv" / f"{name}.tsv.gz").read_bytes()
        b = (tmp_path / "b" / "normalized_tsv" / f"{name}.tsv.gz").read_bytes()
        assert a == b, f"{name} is not byte-reproducible"


def test_declared_schema_matches_the_shipped_release(repository_root: Path) -> None:
    """Cheap drift check that does not require re-parsing 25,727 records."""
    for name, columns in TABLE_COLUMNS.items():
        shipped = repository_root / f"final/source/normalized_tsv/{name}.tsv.gz"
        with gzip.open(shipped, "rt", encoding="utf-8", newline="") as handle:
            header = next(csv.reader(handle, delimiter="\t", quoting=csv.QUOTE_MINIMAL))
        assert tuple(header) == columns, f"{name} declared schema differs from the release"


def test_raw_columns_are_a_subset_of_declared_columns() -> None:
    for name, raw in RAW_COLUMNS.items():
        assert name in TABLE_COLUMNS
        assert raw <= set(TABLE_COLUMNS[name]), f"{name} marks undeclared columns as raw"


@pytest.mark.slow
def test_raw_columns_covers_every_column_the_release_stores_unnormalized(
    repository_root: Path,
) -> None:
    """The direction that actually matters, checked against real data.

    Any column whose shipped values differ from `collapse(value)` is prose and MUST be declared in
    `RAW_COLUMNS`; otherwise the writer would whitespace-collapse it and silently lose formatting.
    Testing that `RAW_COLUMNS` names exist (above) cannot catch an omission.

    Marked slow on 2026-07-30: it reads all twelve shipped TSVs in full, 4.2 s, which was the second
    largest cost in the fast tier. Nothing is lost in CI, which runs both tiers on every push. It is
    kept as its own check rather than left to byte-parity — a `RAW_COLUMNS` omission *would* fail
    parity, but as a byte diff pointing at the writer instead of a named column pointing at the
    declaration.
    """
    undeclared: dict[str, set[str]] = {}
    for name, columns in TABLE_COLUMNS.items():
        declared = RAW_COLUMNS.get(name, frozenset())
        shipped = repository_root / f"final/source/normalized_tsv/{name}.tsv.gz"
        with gzip.open(shipped, "rt", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle, delimiter="\t", quoting=csv.QUOTE_MINIMAL)
            for row in reader:
                for column in columns:
                    value = row[column]
                    if column not in declared and value != collapse(value):
                        undeclared.setdefault(name, set()).add(column)
    assert undeclared == {}, f"stored unnormalized but absent from RAW_COLUMNS: {undeclared}"


def test_parse_source_tables_rejects_a_non_path(tmp_path: Path) -> None:
    """A bare string used to take the iterable branch and yield twelve empty tables silently."""
    with pytest.raises(FileNotFoundError):
        parse_source_tables("")
    with pytest.raises(FileNotFoundError):
        parse_source_tables(tmp_path / "absent.gb")


def test_build_refuses_to_write_into_the_immutable_trees(repository_root: Path) -> None:
    """Case-only variants resolve differently but hit the same inode on a case-insensitive disk."""
    for candidate in (
        "final/source",
        "final/SOURCE",
        "final",
        "final/source/normalized_tsv",
        "final/source/..",
        "raw",
        "./final/source/.",
    ):
        with pytest.raises(ContractError, match="immutable parity target"):
            reject_immutable_output(repository_root, repository_root / candidate)


def test_build_allows_an_ordinary_destination(repository_root: Path, tmp_path: Path) -> None:
    reject_immutable_output(repository_root, tmp_path / "out")


def test_partial_write_leaves_no_file(tmp_path: Path) -> None:
    """A crash mid-write must not leave a short file that still decompresses cleanly."""
    target = tmp_path / "t.tsv.gz"

    class Boom(Exception):
        pass

    def exploding_rows():
        yield {"id": "a"}
        raise Boom

    with pytest.raises(Boom):
        write_tsv(target, ("id",), list(exploding_rows()))
    assert not target.exists()
    assert list(tmp_path.iterdir()) == []


def test_writer_rejects_non_string_values(tmp_path: Path) -> None:
    with pytest.raises(TypeError, match="expected str from the parser"):
        write_tsv(tmp_path / "t.tsv.gz", ("n",), [{"n": 7}])


def test_writer_rejects_undeclared_columns(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="undeclared columns"):
        write_tsv(tmp_path / "t.tsv.gz", ("a",), [{"a": "1", "b": "2"}])


def test_writer_preserves_prose_whitespace_without_re_collapsing(tmp_path: Path) -> None:
    """The writer must not re-apply collapse(); the parser already chose per column."""
    target = tmp_path / "t.tsv.gz"
    write_tsv(target, ("text",), [{"text": "a  b\tc\nd"}])
    with gzip.open(target, "rt", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t", quoting=csv.QUOTE_MINIMAL))
    assert rows[0]["text"] == "a  b\tc\nd"


@pytest.mark.slow
def test_source_layer_reproduces_the_shipped_release(repository_root: Path) -> None:
    """The claim itself: raw/ alone regenerates every source artifact byte-identically.

    Asserts a floor on coverage, not just that whatever was compared matched. Twelve TSVs plus
    twelve Parquet files; only genbank_source.duckdb is excluded, whose bytes are genuinely not
    reproducible.
    """
    results = verify_source_parity(repository_root)
    assert all(v == "match" for v in results.values()), results
    tsvs = {k for k in results if k.endswith(".tsv.gz")}
    parquet = {k for k in results if k.endswith(".parquet")}
    assert tsvs == {f"source/normalized_tsv/{n}.tsv.gz" for n in TABLE_COLUMNS}
    assert parquet == {f"source/parquet/{n}.parquet" for n in TABLE_COLUMNS}


@pytest.mark.slow
def test_parser_data_loss_is_pinned(repository_root: Path) -> None:
    """Biopython silently drops malformed structured-comment lines; pin how much.

    If a Biopython upgrade changes what is discarded, that is a change in shipped scientific data
    and must surface as a failure rather than as a quiet diff.
    """
    from enterovirus_genbank_curated.build import extracted_flat_file

    with extracted_flat_file(repository_root) as flat_file, warnings.catch_warnings(
        record=True
    ) as caught:
        warnings.simplefilter("always")
        parse_source_tables(flat_file)
    parser_warnings = [w for w in caught if w.category is BiopythonParserWarning]
    assert len(parser_warnings) == EXPECTED_PARSER_WARNINGS


def test_record_count_mismatch_fails_closed(
    repository_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A truncated or non-GenBank input must raise, not emit twelve header-only tables.

    The count is pinned twice over — `validate_parity_spec` ties `raw_input.record_count` to the
    frozen baseline constant, so it cannot be relaxed by editing the spec. This exercises the
    remaining path: the archive is authentic and says 25,727, but the parse yields fewer.
    """
    monkeypatch.setattr(
        build_module, "parse_source_tables", lambda _path: {n: [] for n in TABLE_COLUMNS}
    )
    with pytest.raises(ContractError, match="but the authenticated archive declares"):
        build_module.build_source_layer(repository_root, tmp_path / "out", relational=False)
    assert not (tmp_path / "out").exists(), "a failed build must not leave partial output"


@pytest.mark.slow
def test_full_build_is_byte_reproducible_across_runs(
    tmp_path: Path, repository_root: Path
) -> None:
    first = build_source_layer(repository_root, tmp_path / "one", relational=False)
    second = build_source_layer(repository_root, tmp_path / "two", relational=False)
    assert first.row_counts == second.row_counts
    for name in TABLE_COLUMNS:
        a = (tmp_path / "one" / "normalized_tsv" / f"{name}.tsv.gz").read_bytes()
        b = (tmp_path / "two" / "normalized_tsv" / f"{name}.tsv.gz").read_bytes()
        assert a == b
