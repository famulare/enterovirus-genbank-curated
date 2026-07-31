"""The alignment acceptance gate: check written artifacts against metadata, not against themselves.

Every check here reads the *files* back — the Stockholm alignment, its FASTA projection, the
coverage sidecar — and compares them to populations derived independently from `final/canonical/`.
That is the point: an in-memory check of the object a builder just produced mostly restates the
builder, whereas re-reading catches a writer bug, and deriving the expected row set from metadata is
what makes "1-to-1 with final metadata" a checked statement rather than a claim.

Pure Python and no native toolchain, so this runs on every push while a build takes hours.

## What is deliberately *not* asserted

Byte parity with the shipped 2.4.1 alignments. Impossible and known to be: those bytes came from
code that no longer exists in that form, built at an unrecorded thread count with accidental
tie-breaking. Asserting parity against artifacts produced by vanished code would only prove nobody
touched the file. Stating exactly what changed instead is the stronger claim.

Also not asserted: that a block width equals any particular number. Widths are alignment outputs
and move with parameters; what must hold is that they are *consistent* — the three blocks sum to the
row width, every row is that width, and the coverage sidecar agrees row for row. The one exception
is the anchored stack, where the width is not a free parameter at all: every column is a reference
genome position, so the total is that genome's length, and that is checked.
"""

from __future__ import annotations

import gzip
from dataclasses import dataclass, field
from pathlib import Path

from enterovirus_genbank_curated.align import contract
from enterovirus_genbank_curated.align import population as population_module
from enterovirus_genbank_curated.contracts import ContractError
from enterovirus_genbank_curated.export.alignment import (
    COVERAGE_COLUMNS,
    COVERAGE_SUFFIX,
    FASTA_SUFFIX,
    STOCKHOLM_SUFFIX,
)

GAP = "-"
BLOCK_ORDER = ("5ncr", "cds", "3ncr")

# The two records whose curated `virus_group` moved them out of poliovirus. Named because they are
# the only group changes in the rebuild, so a silent regression there would read as a build bug.
RECLASSIFIED_TO_NON_POLIO = ("JX181922", "OR538735")


@dataclass
class Report:
    """Accumulated findings. Collected rather than raised one at a time so a single run says
    everything that is wrong, which is what makes a failure cheap to act on."""

    checks: int = 0
    failures: list[str] = field(default_factory=list)

    def check(self, ok: bool, message: str) -> None:
        self.checks += 1
        if not ok:
            self.failures.append(message)

    def merge(self, other: Report) -> None:
        self.checks += other.checks
        self.failures.extend(other.failures)

    @property
    def passed(self) -> bool:
        return not self.failures


@dataclass(frozen=True)
class LoadedArtifact:
    name: str
    accessions: tuple[str, ...]
    rows: dict[str, str]
    rf: str
    ss_cons: str
    width_nt: int
    block_widths: dict[str, int]
    coverage: tuple[dict[str, str], ...]


def _read_gzip_text(path: Path) -> str:
    try:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            return handle.read()
    except OSError as exc:
        raise ContractError(f"cannot read {path}: {exc}") from exc


def parse_stockholm(text: str) -> tuple[list[str], dict[str, str], str, str]:
    """Minimal Stockholm reader for this repository's own dialect.

    Deliberately not Biopython: the gate should fail if the writer drifts from the declared dialect,
    and a tolerant third-party parser would paper over exactly that. Row order is preserved, because
    it is a declared property.
    """
    order: list[str] = []
    rows: dict[str, str] = {}
    rf = ss = ""
    for line in text.splitlines():
        if not line or line == "//":
            continue
        if line.startswith("#=GC RF"):
            rf = line[len("#=GC RF") :].strip()
        elif line.startswith("#=GC SS_cons"):
            ss = line[len("#=GC SS_cons") :].strip()
        elif line.startswith("#"):
            continue
        else:
            parts = line.split()
            if len(parts) != 2:
                raise ContractError(f"unparseable Stockholm sequence line: {line[:60]!r}")
            name, residues = parts
            if name in rows:
                raise ContractError(f"{name} appears twice in the alignment")
            order.append(name)
            rows[name] = residues
    return order, rows, rf, ss


def parse_coverage(text: str) -> tuple[dict[str, str], ...]:
    lines = text.splitlines()
    header = lines[0].split("\t")
    if tuple(header) != COVERAGE_COLUMNS:
        raise ContractError(f"coverage columns {header} != declared {list(COVERAGE_COLUMNS)}")
    rows = []
    for number, line in enumerate(lines[1:], start=2):
        fields = line.split("\t")
        if len(fields) != len(header):
            raise ContractError(
                f"coverage line {number} has {len(fields)} fields, not {len(header)}: {line[:60]!r}"
            )
        rows.append(dict(zip(header, fields, strict=True)))
    return tuple(rows)


def load_artifact(output_dir: Path, name: str) -> LoadedArtifact:
    order, rows, rf, ss = parse_stockholm(_read_gzip_text(output_dir / f"{name}{STOCKHOLM_SUFFIX}"))
    coverage = parse_coverage(_read_gzip_text(output_dir / f"{name}{COVERAGE_SUFFIX}"))
    widths: dict[str, int] = {}
    for row in coverage:
        block, block_nt = row["block"], int(row["block_nt"])
        if widths.setdefault(block, block_nt) != block_nt:
            raise ContractError(
                f"{name}: coverage disagrees on the {block} block width "
                f"({widths[block]} and {block_nt}) — a block has one width by definition"
            )
    return LoadedArtifact(
        name=name, accessions=tuple(order), rows=rows, rf=rf, ss_cons=ss,
        width_nt=len(rf), block_widths=widths, coverage=coverage,
    )


def verify_artifact(
    artifact: LoadedArtifact,
    population: population_module.AlignmentPopulation,
    sequences: dict[str, str],
    output_dir: Path,
) -> Report:
    report = Report()
    name = artifact.name
    spec = population.spec
    expected = tuple(record.accession for record in population.records)

    # 1. Row-id set equals the metadata-derived population, both directions.
    missing = sorted(set(expected) - set(artifact.accessions))
    extra = sorted(set(artifact.accessions) - set(expected))
    report.check(not missing, f"{name}: {len(missing)} metadata record(s) absent: {missing[:10]}")
    report.check(not extra, f"{name}: {len(extra)} row(s) not in metadata: {extra[:10]}")

    # 2. Count, and the declared tripwire recounted from metadata rather than trusted.
    report.check(
        len(artifact.accessions) == len(expected),
        f"{name}: {len(artifact.accessions)} rows against {len(expected)} in the population",
    )
    report.check(
        len(expected) == spec.expected_rows,
        f"{name}: population is {len(expected)} but the spec declares {spec.expected_rows}",
    )

    # 5. Ids unique, version-stripped, and every one present in the shipped sequences.
    report.check(
        len(set(artifact.accessions)) == len(artifact.accessions), f"{name}: duplicate row ids"
    )
    versioned = [a for a in artifact.accessions if "." in a]
    report.check(not versioned, f"{name}: {len(versioned)} versioned id(s): {versioned[:5]}")
    absent = [a for a in artifact.accessions if a not in sequences]
    report.check(
        not absent, f"{name}: {len(absent)} id(s) absent from sequences.fasta.gz: {absent[:5]}"
    )

    # Row order is the declared one.
    report.check(
        artifact.accessions == expected,
        f"{name}: row order differs from the declared (type_sort_key, accession) order",
    )

    # 11. Widths: three blocks summing to the row width, and every row that width.
    report.check(
        set(artifact.block_widths) == set(BLOCK_ORDER),
        f"{name}: coverage blocks {sorted(artifact.block_widths)} != {list(BLOCK_ORDER)}",
    )
    summed = sum(artifact.block_widths.get(block, 0) for block in BLOCK_ORDER)
    report.check(
        summed == artifact.width_nt,
        f"{name}: blocks sum to {summed} but rows are {artifact.width_nt} wide",
    )
    ragged = [a for a, row in artifact.rows.items() if len(row) != artifact.width_nt]
    report.check(not ragged, f"{name}: {len(ragged)} row(s) not {artifact.width_nt} wide")
    report.check(
        len(artifact.ss_cons) == artifact.width_nt,
        f"{name}: SS_cons is {len(artifact.ss_cons)} against width {artifact.width_nt}",
    )

    # One declared alphabet: DNA. Infernal emits RNA, so this is a live risk, not a formality.
    with_uracil = [a for a, row in artifact.rows.items() if "U" in row]
    report.check(
        not with_uracil,
        f"{name}: {len(with_uracil)} row(s) contain U; the declared alphabet is DNA: "
        f"{with_uracil[:5]}",
    )

    # 12. Gap semantics: an absent block is a full contiguous gap span, and coverage agrees.
    offsets: dict[str, int] = {}
    running = 0
    for block in BLOCK_ORDER:
        offsets[block] = running
        running += artifact.block_widths.get(block, 0)

    disagreements: list[str] = []
    for row in artifact.coverage:
        accession, block = row["accession"], row["block"]
        aligned = artifact.rows.get(accession)
        if aligned is None:
            continue
        start = offsets[block]
        span = aligned[start : start + artifact.block_widths[block]]
        all_gap = span.count(GAP) == len(span)
        present = row["present"] == "TRUE"
        if present and all_gap and span:
            disagreements.append(f"{accession}/{block} present but all-gap")
        if not present and not all_gap:
            disagreements.append(f"{accession}/{block} absent but carries residues")
        if not present and not row["absence_reason"]:
            disagreements.append(f"{accession}/{block} absent with no reason")
        if present and row["absence_reason"]:
            disagreements.append(f"{accession}/{block} present but carries a reason")
    report.check(
        not disagreements,
        f"{name}: {len(disagreements)} coverage/alignment disagreement(s): {disagreements[:6]}",
    )
    report.check(
        len(artifact.coverage) == len(expected) * len(BLOCK_ORDER),
        f"{name}: {len(artifact.coverage)} coverage rows against "
        f"{len(expected) * len(BLOCK_ORDER)} expected",
    )

    # 13. The FASTA is a faithful projection: same ids, same order, same residues.
    fasta_text = _read_gzip_text(output_dir / f"{name}{FASTA_SUFFIX}")
    fasta_order: list[str] = []
    fasta_rows: dict[str, str] = {}
    current: str | None = None
    chunks: list[str] = []
    for line in fasta_text.splitlines():
        if line.startswith(">"):
            if current is not None:
                fasta_rows[current] = "".join(chunks)
            current = line[1:].split()[0]
            fasta_order.append(current)
            chunks = []
        elif line:
            chunks.append(line)
    if current is not None:
        fasta_rows[current] = "".join(chunks)
    report.check(
        tuple(fasta_order) == artifact.accessions,
        f"{name}: FASTA id order differs from the Stockholm",
    )
    mismatched = [a for a in artifact.accessions if fasta_rows.get(a) != artifact.rows.get(a)]
    report.check(
        not mismatched,
        f"{name}: {len(mismatched)} FASTA row(s) differ from the Stockholm: {mismatched[:5]}",
    )

    # 9/10. Stack-specific reference recovery.
    if spec.stack == "anchored":
        assert spec.anchor is not None
        reference = spec.anchor.reference_accession
        genome = sequences.get(reference, "").upper()
        row = artifact.rows.get(reference)
        report.check(
            row is not None and row == genome,
            f"{name}: the {reference} row does not equal its own genome exactly",
        )
        report.check(
            artifact.rf == genome,
            f"{name}: #=GC RF does not equal the {reference} genome",
        )
        report.check(
            artifact.width_nt == len(genome),
            f"{name}: width {artifact.width_nt} != {reference} genome length {len(genome)}",
        )
    else:
        cds_start = offsets["cds"]
        cds_width = artifact.block_widths["cds"]
        report.check(
            cds_width % 3 == 0, f"{name}: CDS block width {cds_width} is not a multiple of three"
        )
        # The Sabin PV1 reference is a member of every unified population, so it is a fixed point to
        # check the codon frame against without needing a per-artifact expectation.
        sabin = contract.SABIN_REFERENCE["PV1"]
        row = artifact.rows.get(sabin)
        if row is not None:
            block = row[cds_start : cds_start + cds_width].replace(GAP, "")
            report.check(
                block.startswith("ATG"),
                f"{name}: the {sabin} CDS block starts {block[:3]!r}, not 'ATG'",
            )
            report.check(
                len(block) % 3 == 0,
                f"{name}: the {sabin} ungapped CDS block is not a whole number of codons",
            )

    return report


def verify_cross_artifact(loaded: dict[str, LoadedArtifact]) -> Report:
    """Assertion 3, stated artifact-to-artifact.

    Against metadata-derived sets these would be tautologies — a partition sums to its parent by
    construction — so they earn their place only as statements about the written row sets.
    """
    report = Report()
    if not {"POLIO_unified", "NPEV_unified", "EV_unified"} <= set(loaded):
        return report

    polio = set(loaded["POLIO_unified"].accessions)
    npev = set(loaded["NPEV_unified"].accessions)
    ev = set(loaded["EV_unified"].accessions)

    report.check(ev == polio | npev, "EV_unified is not exactly POLIO_unified union NPEV_unified")
    report.check(not (polio & npev), f"POLIO and NPEV overlap on {sorted(polio & npev)[:5]}")

    for accession in RECLASSIFIED_TO_NON_POLIO:
        if accession in ev:
            report.check(
                accession in npev and accession not in polio,
                f"{accession} is curated non-polio, so it belongs to NPEV and not POLIO",
            )

    serotypes = [f"{s}_unified" for s in contract.POLIO_TYPES]
    if all(name in loaded for name in serotypes):
        union: set[str] = set()
        for name in serotypes:
            rows = set(loaded[name].accessions)
            report.check(
                rows <= polio, f"{name} has {len(rows - polio)} row(s) absent from POLIO_unified"
            )
            report.check(not (union & rows), f"{name} overlaps another serotype")
            union |= rows
        # The remainder is the blank-`virus_type` poliovirus records, which are members of POLIO and
        # of no serotype. Counted from the artifacts rather than hardcoded.
        report.check(
            union <= polio,
            f"the serotype union has {len(union - polio)} row(s) outside POLIO_unified",
        )
    return report


def verify(
    repository_root: Path, output_dir: Path, names: tuple[str, ...] | None = None
) -> Report:
    """Load every requested artifact and run every check. Raises only on a structural read failure;
    findings come back in the report."""
    wanted = names if names is not None else tuple(contract.ARTIFACTS)
    unknown = [n for n in wanted if n not in contract.ARTIFACTS]
    if unknown:
        raise ContractError(f"unknown alignment artifact(s) {sorted(unknown)}")

    records = population_module.load_all_records(repository_root)
    sequences = {accession: record.sequence for accession, record in records.items()}

    report = Report()
    loaded: dict[str, LoadedArtifact] = {}
    for name in wanted:
        path = output_dir / f"{name}{STOCKHOLM_SUFFIX}"
        if not path.is_file():
            report.check(False, f"{name}: {path} is absent")
            continue
        artifact = load_artifact(output_dir, name)
        loaded[name] = artifact
        population = population_module.select(records, contract.ARTIFACTS[name])
        report.merge(verify_artifact(artifact, population, sequences, output_dir))

    report.merge(verify_cross_artifact(loaded))

    # 18. No committed artifact may name a local path.
    for name in loaded:
        for suffix in (STOCKHOLM_SUFFIX, FASTA_SUFFIX, COVERAGE_SUFFIX):
            text = _read_gzip_text(output_dir / f"{name}{suffix}")
            for needle in ("/Users/", "/home/", "/private/", str(repository_root)):
                report.check(
                    needle not in text, f"{name}{suffix} contains the local path {needle!r}"
                )
    return report
