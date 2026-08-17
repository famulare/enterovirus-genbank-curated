"""Seed-only clade exemplars: reference polyproteins that hold a column frame open for a species
this corpus cannot seed from itself, and that are removed before anything is written.

## The gap they close

`align.codon.choose_seed` takes its exemplars from the carve, at `CodonSpec.seed_min_aa` (2,000 aa).
No Rhinovirus A or Rhinovirus B record in this corpus can ever reach that floor — the longest RV-A
ORF here is 142 aa and the longest RV-B ORF is 151 aa, because every RV-A/RV-B deposit in a
poliovirus-derived carve is a short VP4/VP2 or VP1 typing amplicon. So 344 RV-A rows and 112 RV-B
rows were aligned against a seed containing no member of their own species, with nothing but
distant enterovirus proteins to anchor to.

Measured on release 5.0.0's shipped `EV_unified`: a row whose *type* has no seed exemplar has
residues placed more than 200 codon columns away from its own main block at **8.4%**, against
**0.14%** for a row whose type does — a 60x difference, and the largest single source of fake indel
structure in the file. `MF160251` is the clean instance: a 318 nt RV-A101 VP1 amplicon whose first
98 residues land correctly in VP1 columns 787-1035 and whose trailing eight (`IGHVVLQY`) are flung
1,115 columns downstream into 3C. That one jump is what generates RV-A101's and RV-A49's apparent
210-codon deletion at codon 1941, and eleven more like it.

## Why they are safe to add

An exemplar is not a carve record and must never become a row. It enters the seed amino-acid
alignment, stays through both `--add` passes so the clade's columns exist while fragments are being
placed, and is dropped from the amino-acid alignment before `backtranslate` ever sees it — after
which any column *only* an exemplar occupied is dropped too, so the shipped width never pays for a
sequence that is not in the release. `align.codon.drop_exemplar_only_columns` is that step, and it
is separate from `drop_unsequenced_codon_columns` on purpose: one removes columns nobody sequenced,
this one removes columns nobody in the population occupies at all.

## Why the input of record is nucleotide, not amino acid

The committed file holds each exemplar's polyprotein CDS *nucleotides*, whole codons with the
trailing stop removed, and this module translates them with `align.segment.translate` — the same
translator the carve's own records go through. Committing the amino acids directly would have made
the protein an assertion; committing the codons makes it a derivation anyone can re-run, and it is
checked here against the length `clade_exemplars.tsv` declares.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from enterovirus_genbank_curated.align.seeds import SEED_DIR
from enterovirus_genbank_curated.contracts import ContractError

EXEMPLAR_FASTA = "clade_exemplars.fa"
EXEMPLAR_TABLE = "clade_exemplars.tsv"

# The row name an exemplar carries inside the aligner's files. It is not a valid accession in any
# form this repository uses, which is the point: `assert_disjoint_from` turns "an exemplar could
# collide with a carve record" from a thing to worry about into a thing that fails loudly.
EXEMPLAR_PREFIX = "EXEMPLAR__"


@dataclass(frozen=True)
class CladeExemplar:
    exemplar_id: str
    anchors_family: str
    organism: str
    orf_nt: str
    aa: str

    @property
    def row_name(self) -> str:
        return f"{EXEMPLAR_PREFIX}{self.exemplar_id}"


def is_exemplar_row(name: str) -> bool:
    return name.startswith(EXEMPLAR_PREFIX)


def _read_fasta(path: Path) -> dict[str, str]:
    sequences: dict[str, str] = {}
    current: str | None = None
    chunks: list[str] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ContractError(f"cannot read {path}: {exc}") from exc
    for line in text.splitlines():
        if line.startswith(">"):
            if current is not None:
                sequences[current] = "".join(chunks)
            current = line[1:].split()[0]
            if current in sequences:
                raise ContractError(f"{path} has two records for {current}")
            chunks = []
        elif line.strip():
            chunks.append(line.strip().upper())
    if current is not None:
        sequences[current] = "".join(chunks)
    if not sequences:
        raise ContractError(f"{path} contains no records")
    return sequences


def load_clade_exemplars(repository_root: Path) -> tuple[CladeExemplar, ...]:
    """Every committed exemplar, translated and checked against its declared lengths.

    The check is not decoration. These files have no producer inside this repository — they are
    inputs of record like the covariance models beside them — so the only thing standing between a
    truncated FASTA and a silently worse alignment is that the table and the sequence have to agree.
    """
    seed_dir = repository_root / SEED_DIR
    sequences = _read_fasta(seed_dir / EXEMPLAR_FASTA)
    table_path = seed_dir / EXEMPLAR_TABLE
    try:
        lines = table_path.read_text(encoding="utf-8").splitlines()
        rows = list(csv.DictReader(lines, delimiter="\t"))
    except OSError as exc:
        raise ContractError(f"cannot read {table_path}: {exc}") from exc
    if not rows:
        raise ContractError(f"{table_path} declares no exemplars")

    declared = {row["exemplar_id"] for row in rows}
    if declared != set(sequences):
        raise ContractError(
            f"{EXEMPLAR_TABLE} and {EXEMPLAR_FASTA} disagree — "
            f"declared but absent {sorted(declared - set(sequences))}, "
            f"present but undeclared {sorted(set(sequences) - declared)}"
        )

    # Imported here rather than at module scope: `align.segment` imports nothing from this module,
    # and keeping the edge one-directional is what lets `segment` stay the leaf it is.
    from enterovirus_genbank_curated.align.segment import translate

    exemplars: list[CladeExemplar] = []
    for row in sorted(rows, key=lambda r: r["exemplar_id"]):
        exemplar_id = row["exemplar_id"]
        orf_nt = sequences[exemplar_id]
        if len(orf_nt) % 3:
            raise ContractError(
                f"{exemplar_id}: {len(orf_nt)} nt is not a whole number of codons"
            )
        if len(orf_nt) != int(row["orf_nt"]):
            raise ContractError(
                f"{exemplar_id}: {EXEMPLAR_FASTA} holds {len(orf_nt)} nt, "
                f"{EXEMPLAR_TABLE} declares orf_nt={row['orf_nt']}"
            )
        aa = translate(orf_nt)
        if len(aa) != int(row["orf_aa"]):
            raise ContractError(
                f"{exemplar_id}: translates to {len(aa)} aa, "
                f"{EXEMPLAR_TABLE} declares orf_aa={row['orf_aa']}"
            )
        if "*" in aa:
            raise ContractError(
                f"{exemplar_id}: translation carries {aa.count('*')} stop codon(s); an exemplar "
                f"polyprotein must be a clean single ORF with its trailing stop already removed"
            )
        exemplars.append(
            CladeExemplar(
                exemplar_id=exemplar_id,
                anchors_family=row["anchors_family"],
                organism=row["organism"],
                orf_nt=orf_nt,
                aa=aa,
            )
        )
    return tuple(exemplars)


def assert_disjoint_from(exemplars: tuple[CladeExemplar, ...], accessions: frozenset[str]) -> None:
    """No exemplar row name may be reachable as a population accession.

    `EXEMPLAR_PREFIX` makes a collision essentially impossible, which is exactly why this is worth
    asserting rather than assuming: if the prefix is ever changed to something accession-shaped,
    the failure mode is an exemplar quietly overwriting a real record's row, and that is not a
    thing to discover from the shipped bytes.
    """
    collisions = sorted(accession for accession in accessions if is_exemplar_row(accession))
    if collisions:
        raise ContractError(
            f"{len(collisions)} population accession(s) start with {EXEMPLAR_PREFIX!r} and would "
            f"collide with a seed exemplar row: {collisions[:5]}"
        )
    named = {exemplar.exemplar_id for exemplar in exemplars} & accessions
    if named:
        raise ContractError(
            f"seed exemplar(s) {sorted(named)} are also carve records; an exemplar must be "
            f"outside the population it anchors"
        )
