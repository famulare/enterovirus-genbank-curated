"""`export.alignment`: the one Stockholm dialect, the FASTA projection, and the coverage sidecar."""

from __future__ import annotations

import gzip
from pathlib import Path

from Bio import AlignIO

from enterovirus_genbank_curated.align import contract
from enterovirus_genbank_curated.align.stitch import CoverageRow, StitchedAlignment
from enterovirus_genbank_curated.export import alignment as export_alignment

SPEC = contract.AlignmentSpec(
    name="TEST_unified", stack="unified",
    population=contract.PopulationSpec(virus_groups=(contract.POLIOVIRUS,)),
    expected_rows=2, description="A test alignment, for these tests only",
)


def make_coverage_row(accession: str, block: str, present: bool = True) -> CoverageRow:
    return CoverageRow(
        accession=accession, version=f"{accession}.1", tier="backbone", family="PV",
        virus_type="PV1", block=block, present=present, source_nt=10, block_nt=10,
        absence_reason=None if present else "no_cds_untranslatable",
    )


def make_stitched() -> StitchedAlignment:
    aligned_nt = {"SHORT": "AC-GT", "LONGERACC": "ACTGT"}
    coverage = tuple(
        make_coverage_row(acc, block)
        for acc in ("SHORT", "LONGERACC")
        for block in ("5ncr", "cds", "3ncr")
    )
    return StitchedAlignment(
        accessions=("SHORT", "LONGERACC"),
        width_5ncr=0, width_cds=5, width_3ncr=0, width_nt=5,
        aligned_nt=aligned_nt, rf="ACTGT", ss_cons=".....", coverage=coverage,
    )


# --- render_stockholm ---------------------------------------------------------------------------


def test_render_stockholm_has_the_declared_header_lines() -> None:
    text = export_alignment.render_stockholm(SPEC, make_stitched())
    lines = text.splitlines()
    assert lines[0] == "# STOCKHOLM 1.0"
    assert lines[1] == "#=GF ID TEST_unified"
    assert lines[2] == "#=GF DE A test alignment, for these tests only"
    assert lines[3] == "#=GF SQ 2"
    assert lines[-1] == "//"


def test_render_stockholm_rows_and_gc_lines_are_present() -> None:
    text = export_alignment.render_stockholm(SPEC, make_stitched())
    assert "SHORT" in text
    assert "AC-GT" in text
    assert "LONGERACC" in text
    assert "ACTGT" in text
    assert "#=GC RF" in text
    assert "#=GC SS_cons" in text
    assert "#=GS" not in text  # no per-row #=GS -- it would only restate the id


def test_render_stockholm_columns_align_to_the_widest_label() -> None:
    """Sequence rows and the `#=GC` tag lines all pad their label to the same column width, so
    the sequence data itself lines up regardless of whether an id or a tag is longer."""
    stitched = make_stitched()
    text = export_alignment.render_stockholm(SPEC, stitched)
    width = export_alignment._label_width(stitched.accessions)
    lines = text.splitlines()
    seq_lines = [line for line in lines if line.startswith(("SHORT", "LONGERACC"))]
    rf_line = next(line for line in lines if line.startswith("#=GC RF"))
    ss_line = next(line for line in lines if line.startswith("#=GC SS_cons"))
    assert len(seq_lines) == 2
    for line in [*seq_lines, rf_line, ss_line]:
        assert line[width:] in {"AC-GT", "ACTGT", "....."}


def test_render_stockholm_round_trips_through_biopython(tmp_path: Path) -> None:
    text = export_alignment.render_stockholm(SPEC, make_stitched())
    sto_path = tmp_path / "test.sto"
    sto_path.write_text(text)
    parsed = AlignIO.read(sto_path, "stockholm")
    ids = {record.id for record in parsed}
    assert ids == {"SHORT", "LONGERACC"}
    rows = {record.id: str(record.seq) for record in parsed}
    assert rows["SHORT"] == "AC-GT"
    assert rows["LONGERACC"] == "ACTGT"
    assert parsed.column_annotations["reference_annotation"] == "ACTGT"
    assert parsed.column_annotations["secondary_structure"] == "....."


# --- render_fasta -------------------------------------------------------------------------------


def test_render_fasta_is_a_faithful_projection() -> None:
    text = export_alignment.render_fasta(make_stitched())
    assert text == ">SHORT\nAC-GT\n>LONGERACC\nACTGT\n"


# --- render_coverage_tsv -------------------------------------------------------------------------


def test_render_coverage_tsv_header_and_row_shape() -> None:
    text = export_alignment.render_coverage_tsv(make_stitched())
    lines = text.splitlines()
    assert lines[0].split("\t") == list(export_alignment.COVERAGE_COLUMNS)
    assert len(lines) == 1 + 6  # header + 2 accessions * 3 blocks


def test_render_coverage_tsv_present_and_absent_rows() -> None:
    stitched = make_stitched()
    text = export_alignment.render_coverage_tsv(stitched)
    lines = text.splitlines()[1:]
    present_row = next(line for line in lines if line.startswith("SHORT\t"))
    fields = present_row.split("\t")
    assert fields[6] == "TRUE"  # present
    assert fields[9] == ""  # no absence_reason when present


def test_render_coverage_tsv_absent_row_carries_its_reason() -> None:
    coverage = (make_coverage_row("A", "cds", present=False),)
    stitched = StitchedAlignment(
        accessions=("A",), width_5ncr=0, width_cds=3, width_3ncr=0, width_nt=3,
        aligned_nt={"A": "---"}, rf="...", ss_cons="...", coverage=coverage,
    )
    text = export_alignment.render_coverage_tsv(stitched)
    row = text.splitlines()[1]
    fields = row.split("\t")
    assert fields[6] == "FALSE"
    assert fields[9] == "no_cds_untranslatable"


# --- write_alignment -----------------------------------------------------------------------------


def test_write_alignment_writes_three_gzipped_files_with_the_right_names(tmp_path: Path) -> None:
    paths = export_alignment.write_alignment(tmp_path, SPEC, make_stitched())
    assert paths["stockholm"] == tmp_path / "TEST_unified.sto.gz"
    assert paths["fasta"] == tmp_path / "TEST_unified_aln.fasta.gz"
    assert paths["coverage"] == tmp_path / "TEST_unified.coverage.tsv.gz"
    for path in paths.values():
        assert path.is_file()
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            assert handle.read()  # decompresses cleanly and is non-empty


def test_write_alignment_gzip_bytes_are_deterministic_across_two_writes(tmp_path: Path) -> None:
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"
    first = export_alignment.write_alignment(first_dir, SPEC, make_stitched())
    second = export_alignment.write_alignment(second_dir, SPEC, make_stitched())
    for key in first:
        assert first[key].read_bytes() == second[key].read_bytes()
