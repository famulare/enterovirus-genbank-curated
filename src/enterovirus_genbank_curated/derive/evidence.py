"""Sequence evidence: the Sabin reference frame, and the distances measured against it.

Every column left pending in this pipeline was pending for the same reason — no stage compared a
record's sequence to a reference. This is that stage, and it needs no aligner binary and no
reference panel from outside the clone, because both inputs are already in `raw/`.

## The reference frame is derivable, not supplied

`AY184219`, `AY184220` and `AY184221` — Sabin 1, 2 and 3 — are in the frozen archive, each carrying
all eleven `mat_peptide` features. Their coordinates reproduce the shipped
`final/alignments/reference_region_coordinates.tsv` exactly for all three serotypes, VP1 included
(2480–3385, 2482–3384, 2477–3376). So the frame is computed here from the same GenBank features
everything else in this pipeline reads, and the shipped coordinate table is a comparison target
rather than an input — boundary 1, unchanged.

The only difference from the shipped table is the last three nucleotides of `3D`, where the table
includes the stop codon and the `mat_peptide` feature does not. Nothing here reads `3D`.

The capsid interval comes from the same features: VP4's start to VP1's end, the four structural
peptides being contiguous. VP4's start also fixes the polyprotein reading frame, and it equals the
`polyprotein` CDS start on all three references (743, 748, 743), so the phase is read off the
`mat_peptide` features rather than joining a second feature key to get it.

## Two distances, because they answer two different questions

`compare_vp1` measures **nucleotide** divergence over VP1, which is what the WHO classification
thresholds are defined on. `compare_capsid_aa` measures **amino-acid** p-distance over the capsid,
which is what membership is decided on, and the difference is not stylistic. Synonymous sites
saturate: a 1980s patent transcription of a Sabin cDNA clone can sit 20% away in nucleotide with its
protein essentially unchanged, and 20% nt is exactly where the `wild` threshold lives. On the
protein those same records sit at 0.2-3%. Nucleotide distance would read them as unrelated;
amino-acid distance reads them as what they are.

## Why k-mer diagonals instead of an alignment

No aligner is installed, and building one would be the wrong risk. What the classification rule
actually needs is a divergence percentage over VP1, and VP1 in poliovirus has no indels relative to
Sabin — so an ungapped comparison at a fixed offset is not an approximation of the answer, it *is*
the answer.

The offset is found by seeding: index every 12-mer of the reference, look up every 12-mer of the
query, and vote on `reference_position - query_position`. The winning diagonal is the offset. This
is the classic seed-and-extend first step, and at k=12 it stays sensitive across the ~20% divergence
that separates wild poliovirus from Sabin, because synonymous-site conservation leaves plenty of
exact 12-mers even there. Measured: it places every one of the 9,600-odd poliovirus records that
carry a serotype in their organism name.

**Both strands are tried.** 42 poliovirus records in the corpus are deposited on the minus strand,
and a forward-only search silently reports them as unmappable — which would then look like a
declined cell rather than a bug.

## What this stage does *not* do, and both are deliberate

**It does not serotype by sequence.** Measured against the release, a best-matching-Sabin call over
VP1 agrees with the shipped `virus_type` on 98.6% of the records it calls — and the 1.4% is not
noise. One Sabin per serotype is a poor stand-in for wild poliovirus, whose VP1 sits ~20% from all
three, so the nearest of the three is partly an accident of which window was deposited. The
organism name already agrees with the release on 99.95% of the rows it resolves (see
`derive/typing.py`), so using the sequence here would replace a better answer with a worse one. The
name picks the reference; the sequence measures the distance to it.

**It does not reconstruct `sequence_scope`.** The geometry needed for that — which reference regions
a record covers — is computable and was computed. It does not reproduce the shipped column: fitted
against every threshold combination, coverage geometry agrees with `record_type` on 86.7% of
poliovirus records, and the errors are systematic rather than at the boundary. 745 records the
release calls `other_fragment` have complete VP1, complete capsid, or a complete genome by coverage.
So `record_type` is not a function of coverage against Sabin VP1 alone, whatever else it is, and
fitting thresholds to 86.7% would assert a wrong determination on 1,332 records.
`sequence_scope` stays in `PENDING_COLUMNS`.
"""

from __future__ import annotations

import collections
from collections.abc import Mapping
from dataclasses import dataclass

from enterovirus_genbank_curated.derive.metadata import ENTEROVIRUS_GENUS_TAXON

SABIN_REFERENCES = {"PV1": "AY184219.1", "PV2": "AY184220.1", "PV3": "AY184221.1"}
VP1_PRODUCT = "VP1"
VP4_PRODUCT = "VP4"
MAT_PEPTIDE = "mat_peptide"
PRODUCT_QUALIFIER = "product"

# Seed length. Long enough that a 12-mer is rarely shared by chance across 7.4 kb (4^12 = 16.8M
# possibilities against ~7,400 positions), short enough to survive ~20% divergence.
SEED = 12
# A divergence measured over a handful of nucleotides is not a measurement. 300 nt is a third of VP1
# and the floor below which this stage reports nothing rather than a number.
MIN_VP1_NT = 300
# Anchors the winning diagonal must carry. Without a floor, a record that does not overlap VP1 at
# all still wins some diagonal on one chance 12-mer, and the resulting comparison reports ~74%
# divergence — the value for unrelated sequence — which then reads as `wild`. Measured: 73 records
# the release calls `Sabin-like` were being called `wild` this way, all of them at 73-74%. A genuine
# match over 300 nt at under 20% divergence carries dozens of exact 12-mers, so 5 is a low bar that
# nonetheless excludes every chance hit.
MIN_DIAGONAL_ANCHORS = 5
# Above this the two sequences are not homologous over the compared window and no alignment is
# being measured. Enterovirus VP1 across *genera* stays well below it; 74% is the unrelated-sequence
# expectation. A result this far out is reported as no measurement rather than as a large number.
IMPLAUSIBLE_DIVERGENCE_PCT = 40.0

_COMPLEMENT = str.maketrans("ACGTacgtNn", "TGCAtgcaNn")

# The standard genetic code, for translating the polyprotein reading frame. A codon containing an
# ambiguity character is absent here and is skipped rather than guessed at, so an `N` reduces the
# number of codons compared instead of counting as a difference.
CODON_TABLE = {
    "TTT": "F", "TTC": "F", "TTA": "L", "TTG": "L",
    "CTT": "L", "CTC": "L", "CTA": "L", "CTG": "L",
    "ATT": "I", "ATC": "I", "ATA": "I", "ATG": "M",
    "GTT": "V", "GTC": "V", "GTA": "V", "GTG": "V",
    "TCT": "S", "TCC": "S", "TCA": "S", "TCG": "S",
    "CCT": "P", "CCC": "P", "CCA": "P", "CCG": "P",
    "ACT": "T", "ACC": "T", "ACA": "T", "ACG": "T",
    "GCT": "A", "GCC": "A", "GCA": "A", "GCG": "A",
    "TAT": "Y", "TAC": "Y", "TAA": "*", "TAG": "*",
    "CAT": "H", "CAC": "H", "CAA": "Q", "CAG": "Q",
    "AAT": "N", "AAC": "N", "AAA": "K", "AAG": "K",
    "GAT": "D", "GAC": "D", "GAA": "E", "GAG": "E",
    "TGT": "C", "TGC": "C", "TGA": "*", "TGG": "W",
    "CGT": "R", "CGC": "R", "CGA": "R", "CGG": "R",
    "AGT": "S", "AGC": "S", "AGA": "R", "AGG": "R",
    "GGT": "G", "GGC": "G", "GGA": "G", "GGG": "G",
}


def reverse_complement(sequence: str) -> str:
    return sequence.translate(_COMPLEMENT)[::-1]


@dataclass(frozen=True)
class ReferenceFrame:
    """One Sabin reference: its sequence, its VP1 and capsid intervals, and its seed index."""

    serotype: str
    version: str
    sequence: str
    vp1_start: int  # 0-based, inclusive
    vp1_end: int  # 0-based, exclusive
    capsid_start: int  # 0-based, inclusive; VP4 start, which is also the polyprotein CDS start
    index: Mapping[str, tuple[int, ...]]

    @property
    def vp1_length(self) -> int:
        return self.vp1_end - self.vp1_start

    @property
    def capsid_end(self) -> int:
        """The capsid is VP4-VP2-VP3-VP1 contiguously, so it ends where VP1 does."""
        return self.vp1_end


def _seed_index(sequence: str) -> dict[str, tuple[int, ...]]:
    positions: dict[str, list[int]] = {}
    for offset in range(len(sequence) - SEED + 1):
        positions.setdefault(sequence[offset : offset + SEED], []).append(offset)
    return {seed: tuple(found) for seed, found in positions.items()}


def build_reference_frames(
    tables: Mapping[str, list[dict[str, str]]], sequences: Mapping[str, str]
) -> dict[str, ReferenceFrame]:
    """The three Sabin frames, with VP1 taken from each record's own `mat_peptide` features.

    Raises if a reference or its VP1 feature is absent, rather than proceeding with two frames: a
    silently missing serotype would make every record of that serotype decline, which reads as a
    data gap rather than as the broken input it is.
    """
    record_id = {row["version"]: row["record_id"] for row in tables["records"]}
    features_by_record: dict[str, list[str]] = {}
    feature_key = {}
    for row in tables["features"]:
        feature_key[row["feature_id"]] = row["feature_key"]
        features_by_record.setdefault(row["record_id"], []).append(row["feature_id"])
    product: dict[str, str] = {}
    for row in tables["feature_qualifiers"]:
        if row["qualifier_name"] == PRODUCT_QUALIFIER:
            product.setdefault(row["feature_id"], row["qualifier_value"])
    span: dict[str, tuple[int, int]] = {}
    for row in tables["feature_location_parts"]:
        start, end = int(row["start_1based"]), int(row["end_1based_inclusive"])
        if row["feature_id"] in span:
            known = span[row["feature_id"]]
            span[row["feature_id"]] = (min(known[0], start), max(known[1], end))
        else:
            span[row["feature_id"]] = (start, end)

    frames: dict[str, ReferenceFrame] = {}
    for serotype, version in SABIN_REFERENCES.items():
        if version not in record_id or version not in sequences:
            raise ValueError(f"{serotype} reference {version} is not in the corpus")
        sequence = sequences[version].upper()
        peptides = {
            product.get(feature_id, "").strip(): span[feature_id]
            for feature_id in features_by_record.get(record_id[version], ())
            if feature_key.get(feature_id) == MAT_PEPTIDE
        }
        vp1 = [interval for name, interval in peptides.items() if name.endswith(VP1_PRODUCT)]
        vp4 = [interval for name, interval in peptides.items() if name.endswith(VP4_PRODUCT)]
        if len(vp1) != 1:
            raise ValueError(
                f"{version} carries {len(vp1)} VP1 mat_peptide features, not exactly one; the "
                f"reference frame cannot be derived from it"
            )
        if len(vp4) != 1:
            raise ValueError(
                f"{version} carries {len(vp4)} VP4 mat_peptide features, not exactly one; the "
                f"capsid reading frame cannot be derived from it"
            )
        start, end = vp1[0]
        # VP4 begins the polyprotein, so its start is both the capsid start and the reading frame's
        # phase. Measured against the three references: VP4's start equals the `polyprotein` CDS
        # start in all three (743, 748, 743), so this reads the frame off the same features the VP1
        # interval comes from rather than joining a second feature key to get it.
        capsid_start = vp4[0][0]
        frames[serotype] = ReferenceFrame(
            serotype=serotype,
            version=version,
            sequence=sequence,
            vp1_start=start - 1,
            vp1_end=end,
            capsid_start=capsid_start - 1,
            index=_seed_index(sequence),
        )
    return frames


def _best_diagonal(frame: ReferenceFrame, candidate: str, lo: int, hi: int) -> int | None:
    """The offset with most exact-seed support inside `[lo, hi)`, or None below the anchor floor."""
    votes: collections.Counter[int] = collections.Counter()
    for offset in range(max(0, len(candidate) - SEED + 1)):
        for found in frame.index.get(candidate[offset : offset + SEED], ()):
            if lo <= found < hi:
                votes[found - offset] += 1
    if not votes:
        return None
    diagonal, anchors = votes.most_common(1)[0]
    return diagonal if anchors >= MIN_DIAGONAL_ANCHORS else None


@dataclass(frozen=True)
class Vp1Comparison:
    """VP1 divergence of one record from one Sabin reference."""

    serotype: str
    reference_version: str
    divergence_pct: float
    compared_nt: int
    strand: str


def compare_vp1(frame: ReferenceFrame, sequence: str) -> Vp1Comparison | None:
    """Ungapped VP1 divergence at the best-supported offset, or None below `MIN_VP1_NT`.

    Anchors are restricted to VP1 before the vote. Using a genome-wide offset would let a
    recombinant's non-capsid region choose the diagonal, and in poliovirus that region routinely
    comes from a different serotype than the capsid does.
    """
    best: Vp1Comparison | None = None
    for strand, candidate in (("+", sequence.upper()), ("-", reverse_complement(sequence.upper()))):
        diagonal = _best_diagonal(frame, candidate, frame.vp1_start, frame.vp1_end)
        if diagonal is None:
            continue
        first = max(frame.vp1_start, diagonal)
        last = min(frame.vp1_end, len(frame.sequence), len(candidate) + diagonal)
        compared = last - first
        if compared < MIN_VP1_NT or (best is not None and compared <= best.compared_nt):
            continue
        mismatches = sum(
            1
            for position in range(first, last)
            if candidate[position - diagonal] != frame.sequence[position]
        )
        if mismatches / compared * 100 > IMPLAUSIBLE_DIVERGENCE_PCT:
            continue
        best = Vp1Comparison(
            serotype=frame.serotype,
            reference_version=frame.version,
            divergence_pct=mismatches / compared * 100,
            compared_nt=compared,
            strand=strand,
        )
    return best


@dataclass(frozen=True)
class CapsidComparison:
    """Capsid amino-acid p-distance of one record from one Sabin reference."""

    serotype: str
    reference_version: str
    distance_pct: float
    compared_codons: int
    strand: str


def compare_capsid_aa(frame: ReferenceFrame, sequence: str) -> CapsidComparison | None:
    """Amino-acid p-distance over the capsid, translated in the reference's own reading frame.

    Amino acids rather than nucleotides, because this is a *membership* question and not a distance
    within poliovirus. Synonymous sites saturate: a patent-era cDNA clone re-transcribed with a
    different codon bias can sit 20% away in nucleotide while its protein is unchanged, and 20% nt
    is exactly where the wild threshold lives. The protein keeps the signal where the third position
    has stopped carrying one.

    The reading frame is the reference's, taken from `capsid_start`, so both codons are read in the
    same phase and no frame has to be guessed for the query. Codons containing an ambiguity
    character are skipped by `CODON_TABLE`, which shrinks the denominator rather than inventing a
    difference.
    """
    best: CapsidComparison | None = None
    for strand, candidate in (("+", sequence.upper()), ("-", reverse_complement(sequence.upper()))):
        diagonal = _best_diagonal(frame, candidate, frame.capsid_start, frame.capsid_end)
        if diagonal is None:
            continue
        first = max(frame.capsid_start, diagonal)
        last = min(frame.capsid_end, len(frame.sequence), len(candidate) + diagonal)
        # Advance to the next codon boundary *of the reference frame*, so position `first` is read
        # in the same phase the polyprotein is translated in.
        start = first + (-(first - frame.capsid_start)) % 3
        same = compared = 0
        for position in range(start, last - 2, 3):
            reference_aa = CODON_TABLE.get(frame.sequence[position : position + 3])
            query_aa = CODON_TABLE.get(candidate[position - diagonal : position - diagonal + 3])
            if reference_aa is None or query_aa is None:
                continue
            compared += 1
            same += reference_aa == query_aa
        if compared == 0:
            continue
        distance = (compared - same) / compared * 100
        if distance > IMPLAUSIBLE_DIVERGENCE_PCT:
            continue
        # Nearest reference wins, and the tie-break is codon count. Ordering by codon count first
        # picked the *wrong* serotype on E00768: PV1 covered 371 codons at 22.9% and PV2 covered 370
        # at 0.81%, so one extra codon outranked a 22-point difference in distance.
        if best is None or (distance, -compared) < (best.distance_pct, -best.compared_codons):
            best = CapsidComparison(
                serotype=frame.serotype,
                reference_version=frame.version,
                distance_pct=distance,
                compared_codons=compared,
                strand=strand,
            )
    return best


MEMBERSHIP_BY_BYTES = "byte_identical_to_a_carved_enterovirus_record"
MEMBERSHIP_BY_CAPSID_AA = "capsid_aa_distance_below_rescue_threshold"

MEMBERSHIP_COLUMNS = (
    "accession",
    "version",
    "organism_name",
    "membership_basis",
    "reference_serotype",
    "reference_version",
    "capsid_aa_distance_pct",
    "capsid_codons_compared",
    "byte_identical_twin",
)


@dataclass(frozen=True)
class MembershipRescue:
    """Why one record outside the Enterovirus lineage nonetheless belongs in the carve."""

    version: str
    basis: str
    reference_serotype: str = ""
    reference_version: str = ""
    distance_pct: str = ""
    compared_codons: str = ""
    twin_version: str = ""


def measure_membership_rescue(
    tables: Mapping[str, list[dict[str, str]]],
    sequences: Mapping[str, str],
    excluded_accessions: frozenset[str],
    parameters: Mapping[str, str],
) -> dict[str, MembershipRescue]:
    """R-MEMBERSHIP-AA-1 over every record the lineage predicate rejects.

    Two bases, checked in that order because the first is exact and the second is a measurement:

    1. **Byte identity.** A record whose sequence digest matches a record the lineage predicate
       accepts is the same sequence, and membership is a property of the sequence. This needs no
       threshold. It is also the only basis that reaches the five 70-nt patent oligos, which do not
       overlap the capsid at all and so have no amino-acid distance to measure.
    2. **Capsid amino-acid p-distance** below the catalog's `rescue_below_pct` over at least
       `min_codons_compared` codons.

    Scoped to the records the lineage predicate *rejects*, so this can only ever add rows. A record
    the ledger actively excludes is not reconsidered: an exclusion decision is a curator overriding
    the sequence, and re-including it here would silently reverse them.
    """
    rescue_below = float(parameters["rescue_below_pct"])
    min_codons = int(parameters["min_codons_compared"])

    lineage = {}
    for row in tables["record_taxonomy"]:
        lineage.setdefault(row["record_id"], set()).add(row["taxon_name"])

    carved: set[str] = set()
    candidates: list[dict[str, str]] = []
    for record in tables["records"]:
        if record["accession"] in excluded_accessions:
            continue
        if ENTEROVIRUS_GENUS_TAXON in lineage.get(record["record_id"], set()):
            carved.add(record["sequence_sha256"])
        else:
            candidates.append(record)

    twin_of: dict[str, str] = {}
    for record in tables["records"]:
        if record["accession"] in excluded_accessions:
            continue
        if ENTEROVIRUS_GENUS_TAXON in lineage.get(record["record_id"], set()):
            twin_of.setdefault(record["sequence_sha256"], record["version"])

    frames = build_reference_frames(tables, sequences)
    rescued: dict[str, MembershipRescue] = {}
    for record in candidates:
        version = record["version"]
        if record["sequence_sha256"] in carved:
            rescued[version] = MembershipRescue(
                version=version,
                basis=MEMBERSHIP_BY_BYTES,
                twin_version=twin_of[record["sequence_sha256"]],
            )
            continue
        sequence = sequences.get(version)
        if sequence is None:
            continue
        calls = [
            call
            for call in (compare_capsid_aa(frame, sequence) for frame in frames.values())
            if call
        ]
        if not calls:
            continue
        best = min(calls, key=lambda call: (call.distance_pct, -call.compared_codons))
        if best.compared_codons < min_codons or best.distance_pct >= rescue_below:
            continue
        rescued[version] = MembershipRescue(
            version=version,
            basis=MEMBERSHIP_BY_CAPSID_AA,
            reference_serotype=best.serotype,
            reference_version=best.reference_version,
            distance_pct=f"{best.distance_pct:.3f}",
            compared_codons=str(best.compared_codons),
        )
    return rescued


# The schema of `audit/vp1_divergence.tsv.gz`, which `export/audit.write_vp1_divergence` writes. It
# is deliberately not the shipped `final/audit/sequence_evidence.tsv.gz` schema, and the choice of
# name is argued where the name is chosen rather than here.
EVIDENCE_COLUMNS = (
    "accession",
    "version",
    "vp1_reference_serotype",
    "vp1_reference_version",
    "vp1_divergence_pct",
    "vp1_compared_nt",
    "vp1_strand",
)


def measure_sequence_evidence(
    tables: Mapping[str, list[dict[str, str]]],
    sequences: Mapping[str, str],
    rows: list[dict[str, str]],
) -> dict[str, dict[str, str]]:
    """VP1 evidence for every carved record whose organism name names a serotype.

    Scoped to those records on purpose. The organism name is what picks the reference — this stage
    does not serotype by sequence, for the reason the module docstring gives — so a record with no
    name serotype has nothing to be measured *against*, and measuring it against all three would be
    inventing the very call that was declined.
    """
    from enterovirus_genbank_curated.derive.typing import serotype_from_name

    frames = build_reference_frames(tables, sequences)
    measured: dict[str, dict[str, str]] = {}
    for row in rows:
        serotype = serotype_from_name(row.get("organism_name", ""))
        frame = frames.get(serotype)
        if frame is None:
            continue
        sequence = sequences.get(row["version"])
        if sequence is None:
            continue
        comparison = compare_vp1(frame, sequence)
        if comparison is None:
            continue
        measured[row["version"]] = {
            "vp1_reference_serotype": comparison.serotype,
            "vp1_reference_version": comparison.reference_version,
            # Three decimals, so 1/903 nt reads as 0.111 rather than as a float repr that differs
            # across platforms. The threshold comparison is done on `Decimal` of this string, so the
            # number the rule decided on is exactly the number the provenance row cites.
            "vp1_divergence_pct": f"{comparison.divergence_pct:.3f}",
            "vp1_compared_nt": str(comparison.compared_nt),
            "vp1_strand": comparison.strand,
        }
    return measured
