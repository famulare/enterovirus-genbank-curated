"""`validation.alignment`: the acceptance gate, and a mutation per check proving it fires.

The working agreement's rule is that an assertion without a recorded mutation is not evidence — a
check that cannot fail is worse than no check, because it reads as coverage. So every check below is
exercised twice: once against a well-formed artifact, and once against an artifact corrupted in
exactly the way the check exists to catch.

The fixtures are written by hand rather than built, so this file needs no aligner and runs on every
push.
"""

from __future__ import annotations

import gzip
import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from enterovirus_genbank_curated.align import contract
from enterovirus_genbank_curated.align import population as population_module
from enterovirus_genbank_curated.align.provenance import PROVENANCE_SUFFIX
from enterovirus_genbank_curated.export import alignment as export_alignment
from enterovirus_genbank_curated.export.alignment import (
    COVERAGE_SUFFIX,
    FASTA_SUFFIX,
    STOCKHOLM_SUFFIX,
)
from enterovirus_genbank_curated.validation import alignment as gate

NAME = "PV3_unified"


# --- the parsers ---------------------------------------------------------------------------------


def test_parse_stockholm_keeps_row_order_and_reads_both_gc_lines() -> None:
    text = (
        "# STOCKHOLM 1.0\n#=GF ID X\n"
        "ZZZ  AC-T\nAAA  ACGT\n"
        "#=GC RF      ACGT\n#=GC SS_cons ((.)\n//\n"
    )
    order, rows, rf, ss = gate.parse_stockholm(text)
    assert order == ["ZZZ", "AAA"]  # file order, not sorted
    assert rows == {"ZZZ": "AC-T", "AAA": "ACGT"}
    assert rf == "ACGT"
    assert ss == "((.)"


def test_parse_stockholm_refuses_a_duplicate_row() -> None:
    text = "# STOCKHOLM 1.0\nA  ACGT\nA  ACGT\n#=GC RF ACGT\n//\n"
    with pytest.raises(Exception, match="twice"):
        gate.parse_stockholm(text)


def test_parse_coverage_refuses_unexpected_columns() -> None:
    with pytest.raises(Exception, match="coverage columns"):
        gate.parse_coverage("accession\tblock\nA\tcds\n")


# --- a hand-built, well-formed artifact ----------------------------------------------------------


@pytest.fixture(scope="module")
def pv3(repository_root: Path) -> population_module.AlignmentPopulation:
    return population_module.load_population(repository_root, NAME)


@pytest.fixture(scope="module")
def sequences(repository_root: Path) -> dict[str, str]:
    records = population_module.load_all_records(repository_root)
    return {accession: record.sequence for accession, record in records.items()}


def _write(output_dir: Path, name: str, sto: str, fasta: str, coverage: str) -> None:
    """Write the three gzipped artifacts plus a provenance file that agrees with them, since the
    gate now cross-checks the two and a fixture missing one is not well-formed."""
    output_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}
    for key, suffix, text in (
        ("stockholm", STOCKHOLM_SUFFIX, sto),
        ("fasta", FASTA_SUFFIX, fasta),
        ("coverage", COVERAGE_SUFFIX, coverage),
    ):
        path = output_dir / f"{name}{suffix}"
        with path.open("wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as gz:
            gz.write(text.encode("utf-8"))
        written[key] = path

    order, rows, rf, _ss = gate.parse_stockholm(sto)
    widths: dict[str, int] = {}
    for row in gate.parse_coverage(coverage):
        widths[row["block"]] = int(row["block_nt"])
    (output_dir / f"{name}{PROVENANCE_SUFFIX}").write_text(
        json.dumps(
            {
                "rows": len(order),
                "width_nt": len(rf),
                "block_widths": widths,
                "artifact_sha256": {
                    key: hashlib.sha256(path.read_bytes()).hexdigest()
                    for key, path in written.items()
                },
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _tiny_population(
    pv3: population_module.AlignmentPopulation, sequences: dict[str, str], count: int = 3
) -> population_module.AlignmentPopulation:
    """A few real records plus the Sabin reference, with `expected_rows` adjusted to match so the
    declared-count check is satisfied by the fixture rather than skipped."""
    reference = contract.SABIN_REFERENCE["PV3"]
    chosen = [r for r in pv3.records if r.accession == reference]
    chosen += [r for r in pv3.records if r.accession != reference][:count]
    chosen.sort(key=lambda r: (r.type_sort_key, r.accession))
    spec = replace(pv3.spec, expected_rows=len(chosen))
    return replace(pv3, spec=spec, records=tuple(chosen))


def _wellformed(
    population: population_module.AlignmentPopulation, sequences: dict[str, str]
) -> tuple[str, str, str]:
    """An anchored artifact whose reference row is the genome and whose other rows are all-gap in
    the CDS: the shape the real builder produces for a fragment, so the gate should accept it."""
    reference = population.spec.anchor.reference_accession
    genome = sequences[reference].upper()
    # One block layout that sums to the genome: 5'NCR + CDS + 3'NCR from the derived regions.
    width5, width_cds = 742, 6621
    width3 = len(genome) - width5 - width_cds
    accessions = [r.accession for r in population.records]

    rows = {}
    for accession in accessions:
        rows[accession] = genome if accession == reference else "-" * len(genome)

    label = max(len(a) for a in accessions + ["#=GC SS_cons"]) + 1
    sto_lines = ["# STOCKHOLM 1.0", f"#=GF ID {population.spec.name}",
                 f"#=GF DE {population.spec.description}", f"#=GF SQ {len(accessions)}"]
    sto_lines += [f"{a:<{label}}{rows[a]}" for a in accessions]
    sto_lines.append(f"{'#=GC RF':<{label}}{genome}")
    sto_lines.append(f"{'#=GC SS_cons':<{label}}{'.' * len(genome)}")
    sto_lines.append("//")
    sto = "\n".join(sto_lines) + "\n"

    fasta = "".join(f">{a}\n{rows[a]}\n" for a in accessions)

    by_accession = {r.accession: r for r in population.records}
    cov = ["\t".join(export_alignment.COVERAGE_COLUMNS)]
    for accession in accessions:
        record = by_accession[accession]
        for block, width in (("5ncr", width5), ("cds", width_cds), ("3ncr", width3)):
            present = accession == reference
            cov.append("\t".join([
                accession, record.version, record.tier, record.family, record.type_sort_key,
                block, "TRUE" if present else "FALSE", "0", str(width),
                "" if present else "no_cds_overlap",
            ]))
    return sto, fasta, "\n".join(cov) + "\n"


@pytest.fixture
def artifact_dir(
    tmp_path: Path, pv3: population_module.AlignmentPopulation, sequences: dict[str, str]
) -> tuple[Path, population_module.AlignmentPopulation]:
    population = _tiny_population(pv3, sequences)
    sto, fasta, coverage = _wellformed(population, sequences)
    _write(tmp_path, NAME, sto, fasta, coverage)
    return tmp_path, population


def _run(
    output_dir: Path, population: population_module.AlignmentPopulation, sequences: dict[str, str]
) -> gate.Report:
    artifact = gate.load_artifact(output_dir, NAME)
    return gate.verify_artifact(artifact, population, sequences, output_dir)


def test_a_wellformed_artifact_passes_every_check(
    artifact_dir: tuple[Path, population_module.AlignmentPopulation], sequences: dict[str, str]
) -> None:
    output_dir, population = artifact_dir
    report = _run(output_dir, population, sequences)
    assert report.passed, report.failures
    assert report.checks > 10, "a gate that runs almost no checks is not a gate"


# --- the mutation battery: one corruption per check ----------------------------------------------


def _mutate(
    output_dir: Path, population: population_module.AlignmentPopulation,
    sequences: dict[str, str], transform,
) -> gate.Report:
    sto, fasta, coverage = _wellformed(population, sequences)
    sto, fasta, coverage = transform(sto, fasta, coverage)
    _write(output_dir, NAME, sto, fasta, coverage)
    return _run(output_dir, population, sequences)


def _fails_with(report: gate.Report, fragment: str) -> bool:
    return any(fragment in failure for failure in report.failures)


def test_a_dropped_row_is_caught(
    artifact_dir: tuple[Path, population_module.AlignmentPopulation], sequences: dict[str, str]
) -> None:
    output_dir, population = artifact_dir
    victim = population.records[-1].accession

    def transform(sto, fasta, coverage):
        kept = [line for line in sto.splitlines() if not line.startswith(victim)]
        return "\n".join(kept) + "\n", fasta, coverage

    report = _mutate(output_dir, population, sequences, transform)
    assert _fails_with(report, "metadata record(s) absent")


def test_an_extra_row_is_caught(
    artifact_dir: tuple[Path, population_module.AlignmentPopulation], sequences: dict[str, str]
) -> None:
    output_dir, population = artifact_dir
    width = len(sequences[population.spec.anchor.reference_accession])

    def transform(sto, fasta, coverage):
        lines = sto.splitlines()
        lines.insert(4, f"{'NOTREAL':<20}{'-' * width}")
        return "\n".join(lines) + "\n", fasta, coverage

    report = _mutate(output_dir, population, sequences, transform)
    assert _fails_with(report, "not in metadata")


def test_a_corrupted_reference_row_is_caught(
    artifact_dir: tuple[Path, population_module.AlignmentPopulation], sequences: dict[str, str]
) -> None:
    """Acceptance assertion 9. If this cannot fail, every column number in the artifact is
    unverified."""
    output_dir, population = artifact_dir
    reference = population.spec.anchor.reference_accession

    def transform(sto, fasta, coverage):
        genome = sequences[reference].upper()
        return sto.replace(genome, "A" + genome[1:]), fasta, coverage

    report = _mutate(output_dir, population, sequences, transform)
    assert _fails_with(report, "does not equal its own genome") or _fails_with(report, "#=GC RF")


def test_a_ragged_row_is_caught(
    artifact_dir: tuple[Path, population_module.AlignmentPopulation], sequences: dict[str, str]
) -> None:
    output_dir, population = artifact_dir
    victim = population.records[-1].accession

    def transform(sto, fasta, coverage):
        out = []
        for line in sto.splitlines():
            out.append(line[:-5] if line.startswith(victim) else line)
        return "\n".join(out) + "\n", fasta, coverage

    report = _mutate(output_dir, population, sequences, transform)
    assert _fails_with(report, "wide")


def test_uracil_is_caught(
    artifact_dir: tuple[Path, population_module.AlignmentPopulation], sequences: dict[str, str]
) -> None:
    """The real defect this exists for: cmalign emits RNA, so a row could arrive in the wrong
    alphabet while being the right length and content."""
    output_dir, population = artifact_dir
    reference = population.spec.anchor.reference_accession
    genome = sequences[reference].upper()

    def transform(sto, fasta, coverage):
        rna = genome.replace("T", "U")
        return sto.replace(genome, rna), fasta.replace(genome, rna), coverage

    report = _mutate(output_dir, population, sequences, transform)
    assert _fails_with(report, "contain U")


def test_a_fasta_that_diverges_from_the_stockholm_is_caught(
    artifact_dir: tuple[Path, population_module.AlignmentPopulation], sequences: dict[str, str]
) -> None:
    """Assertion 13 — believed of the shipped artifacts, never checked."""
    output_dir, population = artifact_dir

    def transform(sto, fasta, coverage):
        return sto, fasta.replace("-", "N", 1), coverage

    report = _mutate(output_dir, population, sequences, transform)
    assert _fails_with(report, "FASTA row(s) differ")


def test_a_reordered_fasta_is_caught(
    artifact_dir: tuple[Path, population_module.AlignmentPopulation], sequences: dict[str, str]
) -> None:
    output_dir, population = artifact_dir

    def transform(sto, fasta, coverage):
        blocks = [b for b in fasta.split(">") if b]
        return sto, ">" + ">".join(reversed(blocks)), coverage

    report = _mutate(output_dir, population, sequences, transform)
    assert _fails_with(report, "FASTA id order")


def test_coverage_claiming_an_all_gap_block_is_present_is_caught(
    artifact_dir: tuple[Path, population_module.AlignmentPopulation], sequences: dict[str, str]
) -> None:
    """Exactly the defect the first real build shipped: `present` standing in for "has an entry"
    rather than "has residues"."""
    output_dir, population = artifact_dir

    def transform(sto, fasta, coverage):
        lines = coverage.splitlines()
        fixed = [lines[0]]
        for line in lines[1:]:
            parts = line.split("\t")
            if parts[5] == "cds" and parts[6] == "FALSE":
                parts[6], parts[9] = "TRUE", ""
            fixed.append("\t".join(parts))
        return sto, fasta, "\n".join(fixed) + "\n"

    report = _mutate(output_dir, population, sequences, transform)
    assert _fails_with(report, "present but all-gap")


def test_an_absent_block_with_no_reason_is_caught(
    artifact_dir: tuple[Path, population_module.AlignmentPopulation], sequences: dict[str, str]
) -> None:
    output_dir, population = artifact_dir

    def transform(sto, fasta, coverage):
        return sto, fasta, coverage.replace("no_cds_overlap", "")

    report = _mutate(output_dir, population, sequences, transform)
    assert _fails_with(report, "absent with no reason")


def test_block_widths_that_do_not_sum_to_the_row_width_are_caught(
    artifact_dir: tuple[Path, population_module.AlignmentPopulation], sequences: dict[str, str]
) -> None:
    output_dir, population = artifact_dir

    def transform(sto, fasta, coverage):
        lines = coverage.splitlines()
        fixed = [lines[0]]
        for line in lines[1:]:
            parts = line.split("\t")
            if parts[5] == "3ncr":
                parts[8] = str(int(parts[8]) + 1)
            fixed.append("\t".join(parts))
        return sto, fasta, "\n".join(fixed) + "\n"

    report = _mutate(output_dir, population, sequences, transform)
    assert _fails_with(report, "blocks sum to")


def test_a_provenance_that_describes_a_different_build_is_caught(
    artifact_dir: tuple[Path, population_module.AlignmentPopulation], sequences: dict[str, str]
) -> None:
    """A stale provenance is worse than none: it reads as a record of these exact bytes. Here the
    row count is left describing a previous build."""
    output_dir, population = artifact_dir
    path = output_dir / f"{NAME}{PROVENANCE_SUFFIX}"
    document = json.loads(path.read_text())
    document["rows"] = document["rows"] + 1
    path.write_text(json.dumps(document), encoding="utf-8")
    report = _run(output_dir, population, sequences)
    assert _fails_with(report, "provenance says")


def test_a_provenance_hash_that_does_not_match_the_file_is_caught(
    artifact_dir: tuple[Path, population_module.AlignmentPopulation], sequences: dict[str, str]
) -> None:
    output_dir, population = artifact_dir
    path = output_dir / f"{NAME}{PROVENANCE_SUFFIX}"
    document = json.loads(path.read_text())
    document["artifact_sha256"]["stockholm"] = "0" * 64
    path.write_text(json.dumps(document), encoding="utf-8")
    report = _run(output_dir, population, sequences)
    assert _fails_with(report, "provenance sha256")


def test_a_missing_provenance_is_caught(
    artifact_dir: tuple[Path, population_module.AlignmentPopulation], sequences: dict[str, str]
) -> None:
    output_dir, population = artifact_dir
    (output_dir / f"{NAME}{PROVENANCE_SUFFIX}").unlink()
    report = _run(output_dir, population, sequences)
    assert _fails_with(report, "is absent")


def test_a_local_path_in_an_artifact_is_caught(
    repository_root: Path, artifact_dir: tuple[Path, population_module.AlignmentPopulation]
) -> None:
    """Assertion 18, over the whole-directory entry point rather than one artifact."""
    output_dir, _population = artifact_dir
    path = output_dir / f"{NAME}{COVERAGE_SUFFIX}"
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        text = handle.read()
    # Leaked into a real field, which is how such a path would actually arrive — a scratch prefix
    # written into a reason string — rather than as a stray comment line.
    leaked = text.replace("no_cds_overlap", "no_cds_overlap /Users/someone/scratch", 1)
    with path.open("wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as gz:
        gz.write(leaked.encode("utf-8"))
    report = gate.verify(repository_root, output_dir, (NAME,))
    assert _fails_with(report, "contains the local path")


# --- cross-artifact ------------------------------------------------------------------------------


def _loaded(name: str, accessions: list[str]) -> gate.LoadedArtifact:
    return gate.LoadedArtifact(
        name=name, accessions=tuple(accessions), rows=dict.fromkeys(accessions, "-"),
        rf="-", ss_cons="-", width_nt=1, block_widths={}, coverage=(),
    )


def test_cross_artifact_requires_ev_to_be_the_union() -> None:
    report = gate.verify_cross_artifact({
        "POLIO_unified": _loaded("POLIO_unified", ["P1"]),
        "NPEV_unified": _loaded("NPEV_unified", ["N1"]),
        "EV_unified": _loaded("EV_unified", ["P1"]),  # N1 missing
    })
    assert _fails_with(report, "not exactly POLIO_unified union NPEV_unified")


def test_cross_artifact_refuses_an_overlap_between_polio_and_npev() -> None:
    report = gate.verify_cross_artifact({
        "POLIO_unified": _loaded("POLIO_unified", ["X"]),
        "NPEV_unified": _loaded("NPEV_unified", ["X"]),
        "EV_unified": _loaded("EV_unified", ["X"]),
    })
    assert _fails_with(report, "overlap")


def test_cross_artifact_requires_a_reclassified_record_to_sit_in_npev() -> None:
    accession = gate.RECLASSIFIED_TO_NON_POLIO[0]
    report = gate.verify_cross_artifact({
        "POLIO_unified": _loaded("POLIO_unified", [accession]),
        "NPEV_unified": _loaded("NPEV_unified", []),
        "EV_unified": _loaded("EV_unified", [accession]),
    })
    assert _fails_with(report, f"{accession} is curated non-polio")


def test_cross_artifact_requires_each_serotype_to_sit_inside_polio() -> None:
    report = gate.verify_cross_artifact({
        "POLIO_unified": _loaded("POLIO_unified", ["A"]),
        "NPEV_unified": _loaded("NPEV_unified", []),
        "EV_unified": _loaded("EV_unified", ["A"]),
        "PV1_unified": _loaded("PV1_unified", ["A"]),
        "PV2_unified": _loaded("PV2_unified", ["OUTSIDE"]),
        "PV3_unified": _loaded("PV3_unified", []),
    })
    assert _fails_with(report, "absent from POLIO_unified")


def test_verify_reports_a_missing_artifact_rather_than_raising(
    repository_root: Path, tmp_path: Path
) -> None:
    report = gate.verify(repository_root, tmp_path, (NAME,))
    assert _fails_with(report, "is absent")
