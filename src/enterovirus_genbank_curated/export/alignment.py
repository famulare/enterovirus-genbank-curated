"""Write a stitched alignment: one Stockholm dialect, a faithful FASTA projection, and the
coverage sidecar — reusing `export.source`'s deterministic gzip writer rather than adding a second
one.

## The one Stockholm dialect

The shipped 2.4.1 alignments carried two independently-evolved Stockholm dialects — the unified
stack's `#=GF ID`/`#=GF DE`, a 10-wide id column, `SS_cons` before `RF`, uppercase-`U` RF; the
anchored stack's `#=GF SQ <n>`, a per-row `#=GS <id> AC <id>` after each sequence line, single-space
ids, `RF` before `SS_cons`, and `~` insert columns. That split was an artifact of two upstream
stacks writing Stockholm independently, not a design choice, and since this module now writes all
six artifacts, there is no reason to keep it: one dialect, `#=GF ID`/`DE`/`SQ`, a single id column
width computed from the widest label actually used, `-` for gaps throughout, `RF` then `SS_cons`,
and no per-row `#=GS` (`#=GS <id> AC <id>` merely restates the id already on the sequence line).

Verified safe for the only consumer: `site/pipeline/frame.py`'s `read_stockholm` skips every `#`
line except `#=GC`, so it never reads `#=GF` or `#=GS` and does not care about id column width; and
its `GAP_CHARACTERS = "-.~"` maps `-`, `.` and `~` alike to a gap, so dropping `~` from the RF line
changes nothing downstream.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from enterovirus_genbank_curated.align import contract
from enterovirus_genbank_curated.align.stitch import StitchedAlignment
from enterovirus_genbank_curated.export.source import deterministic_text_writer

STOCKHOLM_VERSION_LINE = "# STOCKHOLM 1.0"
END_OF_ALIGNMENT = "//"
GC_RF_LABEL = "#=GC RF"
GC_SS_CONS_LABEL = "#=GC SS_cons"

COVERAGE_COLUMNS = (
    "accession", "version", "tier", "family", "virus_type", "block", "present", "source_nt",
    "block_nt", "absence_reason",
)

STOCKHOLM_SUFFIX = ".sto.gz"
FASTA_SUFFIX = "_aln.fasta.gz"
COVERAGE_SUFFIX = ".coverage.tsv.gz"


@dataclass(frozen=True)
class StockholmDialect:
    """The one Stockholm dialect this module writes — declared as a record, not left implicit, so
    the format stays specified even though only one instance of it now exists."""

    version_line: str = STOCKHOLM_VERSION_LINE
    gap_character: str = "-"
    end_of_alignment: str = END_OF_ALIGNMENT


DIALECT = StockholmDialect()


def _label_width(accessions: tuple[str, ...]) -> int:
    widest = max((len(accession) for accession in accessions), default=0)
    widest = max(widest, len(GC_RF_LABEL), len(GC_SS_CONS_LABEL))
    return widest + 1


def render_stockholm(spec: contract.AlignmentSpec, stitched: StitchedAlignment) -> str:
    width = _label_width(stitched.accessions)
    lines = [
        DIALECT.version_line,
        f"#=GF ID {spec.name}",
        f"#=GF DE {spec.description}",
        f"#=GF SQ {len(stitched.accessions)}",
    ]
    for accession in stitched.accessions:
        lines.append(f"{accession:<{width}}{stitched.aligned_nt[accession]}")
    lines.append(f"{GC_RF_LABEL:<{width}}{stitched.rf}")
    lines.append(f"{GC_SS_CONS_LABEL:<{width}}{stitched.ss_cons}")
    lines.append(DIALECT.end_of_alignment)
    return "\n".join(lines) + "\n"


def render_fasta(stitched: StitchedAlignment) -> str:
    """A faithful projection of the Stockholm rows: same ids, same order, same gapped residues."""
    lines: list[str] = []
    for accession in stitched.accessions:
        lines.append(f">{accession}")
        lines.append(stitched.aligned_nt[accession])
    return "\n".join(lines) + "\n"


def render_coverage_tsv(stitched: StitchedAlignment) -> str:
    lines = ["\t".join(COVERAGE_COLUMNS)]
    for row in stitched.coverage:
        lines.append(
            "\t".join(
                [
                    row.accession,
                    row.version,
                    row.tier,
                    row.family,
                    row.virus_type,
                    row.block,
                    "TRUE" if row.present else "FALSE",
                    str(row.source_nt),
                    str(row.block_nt),
                    row.absence_reason or "",
                ]
            )
        )
    return "\n".join(lines) + "\n"


def write_alignment(
    output_dir: Path, spec: contract.AlignmentSpec, stitched: StitchedAlignment
) -> dict[str, Path]:
    """Write `<name>.sto.gz`, `<name>_aln.fasta.gz` and `<name>.coverage.tsv.gz`. Returns the three
    paths, keyed `"stockholm"`/`"fasta"`/`"coverage"`."""
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "stockholm": output_dir / f"{spec.name}{STOCKHOLM_SUFFIX}",
        "fasta": output_dir / f"{spec.name}{FASTA_SUFFIX}",
        "coverage": output_dir / f"{spec.name}{COVERAGE_SUFFIX}",
    }
    renderers = {
        "stockholm": lambda: render_stockholm(spec, stitched),
        "fasta": lambda: render_fasta(stitched),
        "coverage": lambda: render_coverage_tsv(stitched),
    }
    for key, path in paths.items():
        with deterministic_text_writer(path) as handle:
            handle.write(renderers[key]())
    return paths
