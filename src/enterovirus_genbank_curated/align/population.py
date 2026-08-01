"""Derive each alignment's row set, tier and family from the shipped metadata.

This module is what makes "1-to-1 with final metadata" true by construction rather than by
inspection: an artifact's membership is a filter over `virus_group` / `virus_type` and nothing else,
so a record cannot be missing because some upstream typing step lacked confidence in it.

Every path, column and parameter comes from `align.contract`, which itself imports its `final/`
paths from `oracle.parity` rather than naming them. Nothing here hardcodes one.
"""

from __future__ import annotations

import gzip
import hashlib
from dataclasses import dataclass
from pathlib import Path

from enterovirus_genbank_curated.align import contract
from enterovirus_genbank_curated.contracts import ContractError
from enterovirus_genbank_curated.derive.metadata import (
    SEQUENCE_RESCUED_INCLUSIONS,
    UNDECLARED_EXCLUSIONS,
)
from enterovirus_genbank_curated.oracle.release import read_tsv_gz


@dataclass(frozen=True)
class AlignedRecord:
    """One row of one alignment, before any aligner has seen it."""

    accession: str  # version-stripped; this is the alignment row id
    version: str
    virus_group: str
    virus_type: str
    family: str
    tier: str  # "backbone" | "addon"
    sequence: str
    length_nt: int

    @property
    def type_sort_key(self) -> str:
        """Sort key and display label for row order.

        A blank `virus_type` takes the sentinel for its *group*: `PV?` for poliovirus, `unknown` for
        non-polio. Using one sentinel for both would label 877 non-polio rows `PV?` and so assert
        they are poliovirus.
        """
        if self.virus_type:
            return self.virus_type
        return contract.BLANK_TYPE_SENTINEL_BY_GROUP[self.virus_group]


@dataclass(frozen=True)
class AlignmentPopulation:
    spec: contract.AlignmentSpec
    records: tuple[AlignedRecord, ...]

    @property
    def accessions(self) -> frozenset[str]:
        return frozenset(record.accession for record in self.records)

    def digest(self) -> str:
        """sha256 over the sorted row ids.

        Pins the population independently of any alignment content, which is the property this whole
        exercise is about: a provenance file carrying this can be checked for the right *membership*
        without re-running an aligner.
        """
        joined = "\n".join(sorted(self.accessions))
        return hashlib.sha256(joined.encode("utf-8")).hexdigest()

    def tier_counts(self) -> dict[str, int]:
        counts = {"backbone": 0, "addon": 0}
        for record in self.records:
            counts[record.tier] += 1
        return counts

    def family_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for record in self.records:
            counts[record.family] = counts.get(record.family, 0) + 1
        return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))

    def type_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for record in self.records:
            counts[record.type_sort_key] = counts.get(record.type_sort_key, 0) + 1
        return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def base_accession(accession: str) -> str:
    """Strip the `.N` version suffix. Alignment row ids are version-free, as upstream's were."""
    return accession.split(".", 1)[0]


def _indexed(header: list[str], rows: list[list[str]], label: str) -> dict[str, dict[str, str]]:
    missing = {contract.ACCESSION, contract.VERSION} - set(header)
    if missing:
        raise ContractError(f"{label} is missing required columns {sorted(missing)}")
    out: dict[str, dict[str, str]] = {}
    for row in rows:
        record = dict(zip(header, row, strict=False))
        key = base_accession(record[contract.ACCESSION])
        if key in out:
            raise ContractError(f"{label} has two rows for {key}; membership would be ambiguous")
        out[key] = record
    return out


def load_sequences(path: Path) -> dict[str, str]:
    """Read `sequences.fasta.gz` into {version-stripped accession: uppercase sequence}."""
    sequences: dict[str, str] = {}
    current: str | None = None
    chunks: list[str] = []
    try:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            for line in handle:
                line = line.rstrip("\n")
                if line.startswith(">"):
                    if current is not None:
                        sequences[current] = "".join(chunks).upper()
                    current = base_accession(line[1:].split()[0])
                    if current in sequences:
                        raise ContractError(f"{path} has two records for {current}")
                    chunks = []
                elif line:
                    chunks.append(line)
    except OSError as exc:
        raise ContractError(f"cannot read {path}: {exc}") from exc
    if current is not None:
        sequences[current] = "".join(chunks).upper()
    if not sequences:
        raise ContractError(f"{path} contains no records")
    return sequences


def tier_of(metadata_row: dict[str, str], evidence_row: dict[str, str] | None) -> str:
    """Backbone if this record's group-appropriate confidence column is TRUE, else addon.

    Which column governs is decided by canonical `virus_group`, and that is the one place the
    rebuild knowingly differs from the shipped `EV_unified`. Applied to the shipped row sets this
    predicate reproduces `POLIO_unified` (8,736/1,252) and `NPEV_unified` (10,418/3,632) exactly
    under the shipped partition, but gives EV 19,155/4,883 against a shipped 19,154/4,884, and
    POLIO 8,737/1,251 once canonical's own groups govern. The single differing record is
    `JX181922`: the shipped alignment tiered it as poliovirus, canonical calls it
    `non_polio_enterovirus`/`CVA1`, and its two confidence columns disagree
    (`serotype_sequence_confident=FALSE`, `enterovirus_type_sequence_confident=TRUE`), so changing
    which column governs it flips it backbone-ward. Deriving that +1/-1 is the honest test;
    asserting exactness on all three would be asserting something false.
    """
    column = contract.TIER_COLUMN_BY_GROUP.get(metadata_row[contract.VIRUS_GROUP])
    if column is None:
        raise ContractError(
            f"{metadata_row[contract.ACCESSION]} has unknown "
            f"{contract.VIRUS_GROUP}={metadata_row[contract.VIRUS_GROUP]!r}; "
            f"membership and tiering are both undefined for it"
        )
    if evidence_row is None:
        # Only reachable for the nine records `assert_evidence_covers_the_carve` declares, all of
        # them 70-1,181 nt patent fragments plus one 7,378 nt Simian agent 5 genome, none of which
        # the 2.4.1 evidence pass ever measured. `addon` is the honest tier for a record with no
        # sequence-typing evidence at all — it is what an explicit FALSE would give — but it must
        # be reached by declaration rather than by a missing dictionary key, which is what the
        # caller's check enforces.
        return "addon"
    # A blank third state exists — 125 non-polio records — and falls to addon, which is upstream's
    # `== TRUE`-else-addon behaviour. Made explicit rather than incidental.
    return "backbone" if evidence_row.get(column, "") == contract.BACKBONE_VALUE else "addon"


def assert_evidence_covers_the_carve(
    metadata: dict[str, dict[str, str]], evidence: dict[str, dict[str, str]]
) -> None:
    """The tier oracle is a 2.4.1 artifact; its gap against the carve must be the declared one.

    `final/audit/sequence_evidence.tsv.gz` is carried, not rebuilt: `derive/evidence.py` writes a
    deliberately narrower schema and computes no `*_sequence_confident` predicate, so there is no
    4.0.0-native successor to it (measured: the best native candidate — annotated CDS presence, or
    an ORF-length floor — reproduces the shipped tiers only 90% of the time for poliovirus and 79%
    for non-polio, which is a guess wearing a rule's clothes).

    Carrying it is defensible; carrying it *silently* is not. It covers 24,301 records and the
    carve holds 24,308, and `tier_of` reads a missing row as `addon` — so nine records would take
    a tier by default, with nothing saying they had. That is the shape of defect this repository
    keeps finding: a real decision expressed as an absent key.

    The gap is not arbitrary and does not need a pin of its own. It is exactly the two residual sets
    `derive/metadata.py` already declares and `oracle` already checks against the release: the nine
    the carve holds and 2.4.1 excluded, and the two 2.4.1 shipped that the carve cannot reach.
    Requiring equality means a record drifting out of evidence coverage for any *other* reason fails
    here instead of quietly becoming an addon.
    """
    uncovered = frozenset(
        metadata[key][contract.VERSION] for key in metadata if key not in evidence
    )
    orphaned = frozenset(
        row[contract.VERSION] for key, row in evidence.items() if key not in metadata
    )
    if uncovered != UNDECLARED_EXCLUSIONS:
        raise ContractError(
            f"{len(uncovered)} carved records have no row in {contract.SEQUENCE_EVIDENCE} and "
            f"would take a tier by default. Expected exactly the declared "
            f"UNDECLARED_EXCLUSIONS; unexpected: {sorted(uncovered - UNDECLARED_EXCLUSIONS)}, "
            f"newly covered: {sorted(UNDECLARED_EXCLUSIONS - uncovered)}"
        )
    if orphaned != SEQUENCE_RESCUED_INCLUSIONS:
        raise ContractError(
            f"{contract.SEQUENCE_EVIDENCE} carries rows for records the carve does not hold, "
            f"beyond the declared SEQUENCE_RESCUED_INCLUSIONS: "
            f"{sorted(orphaned - SEQUENCE_RESCUED_INCLUSIONS)}"
        )


def load_all_records(repository_root: Path) -> dict[str, AlignedRecord]:
    """Build every canonical record once, shared by all six artifacts.

    Segmentation and tiering are per-record and artifact-independent, so this runs once rather than
    once per artifact — upstream ran a mirrored copy per view and merged caches.
    """
    header, rows = read_tsv_gz(repository_root / contract.CANONICAL_METADATA)
    metadata = _indexed(header, rows, contract.CANONICAL_METADATA)

    ev_header, ev_rows = read_tsv_gz(repository_root / contract.SEQUENCE_EVIDENCE)
    evidence = _indexed(ev_header, ev_rows, contract.SEQUENCE_EVIDENCE)

    assert_evidence_covers_the_carve(metadata, evidence)

    sequences = load_sequences(repository_root / contract.CANONICAL_FASTA)

    records: dict[str, AlignedRecord] = {}
    for key, row in metadata.items():
        sequence = sequences.get(key)
        if sequence is None:
            raise ContractError(
                f"{key} is in {contract.CANONICAL_METADATA} but not "
                f"{contract.CANONICAL_FASTA}; the population would not be 1-to-1"
            )
        declared_length = int(row[contract.SEQUENCE_LENGTH_NT])
        if len(sequence) != declared_length:
            raise ContractError(
                f"{key} is {len(sequence)} nt in {contract.CANONICAL_FASTA} but "
                f"{contract.SEQUENCE_LENGTH_NT} declares {declared_length}"
            )
        actual_sha = hashlib.sha256(sequence.encode("ascii")).hexdigest()
        if actual_sha != row[contract.SEQUENCE_SHA256]:
            raise ContractError(
                f"{key} sequence sha256 {actual_sha} does not match "
                f"{contract.SEQUENCE_SHA256} {row[contract.SEQUENCE_SHA256]}"
            )
        virus_type = row[contract.VIRUS_TYPE]
        records[key] = AlignedRecord(
            accession=key,
            version=row[contract.VERSION],
            virus_group=row[contract.VIRUS_GROUP],
            virus_type=virus_type,
            family=contract.family_of(virus_type),
            tier=tier_of(row, evidence.get(key)),
            sequence=sequence,
            length_nt=declared_length,
        )
    return records


def select(records: dict[str, AlignedRecord], spec: contract.AlignmentSpec) -> AlignmentPopulation:
    """Filter the shared record set down to one artifact, in declared row order."""
    wanted_groups = set(spec.population.virus_groups)
    wanted_types = spec.population.virus_types
    chosen = [
        record
        for record in records.values()
        if record.virus_group in wanted_groups
        and (wanted_types is None or record.virus_type in wanted_types)
    ]
    chosen.sort(key=lambda record: (record.type_sort_key, record.accession))
    return AlignmentPopulation(spec=spec, records=tuple(chosen))


def load_population(repository_root: Path, name: str) -> AlignmentPopulation:
    try:
        spec = contract.ARTIFACTS[name]
    except KeyError:
        raise ContractError(
            f"unknown alignment {name!r}; declared: {sorted(contract.ARTIFACTS)}"
        ) from None
    return select(load_all_records(repository_root), spec)


def load_populations(repository_root: Path) -> dict[str, AlignmentPopulation]:
    records = load_all_records(repository_root)
    return {name: select(records, spec) for name, spec in contract.ARTIFACTS.items()}
