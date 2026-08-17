"""Per-artifact provenance, with every value recomputed from the rows that were actually written.

The shipped 2.4.1 provenance files were ad hoc — three different shapes across six files, some
counts copied from a log rather than recounted, and `md5_sto` where the rest of the repository is
sha256. This module writes one shape for all six, and it recounts rather than reports: a tier count
here is derived by counting rows, so it cannot disagree with the artifact it describes.

Two things it deliberately records rather than hides:

* **The parameter departures.** `pass1_gap_open` is 4.5 for every artifact where upstream used 3.0
  for polio, and `pass2_local_gap_open` is -24.0 where upstream's shipped builds ran at MAFFT's
  default. Presenting the current numbers as "what built the shipped file" would be false, so the
  departure is a field.
* **No absolute paths.** The shipped `EV_unified.provenance.json` recorded a reused covariance model
  as a local build path. Here a model is identified by its declared repository-relative path and its
  sha256, which is what a reader can actually check.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from enterovirus_genbank_curated.align.population import AlignmentPopulation
from enterovirus_genbank_curated.align.stitch import BLOCK_CDS, StitchedAlignment
from enterovirus_genbank_curated.contracts import sha256_file

SCHEMA = 1
PROVENANCE_SUFFIX = ".provenance.json"

# Recorded so a reader can see the two places this build knowingly differs from what produced the
# shipped bytes, rather than inferring it from a parameter table.
PARAMETER_DEPARTURES = {
    "pass1_gap_open": (
        "4.5 for every unified artifact. Upstream used 3.0 for polio, which its own source "
        "documents as producing a deterministic CDS width blowup with no benefit; 4.5 was applied "
        "once as a command-line override and never propagated into the script."
    ),
    "gap_extend": (
        "0.5 on both --add passes. Upstream never set MAFFT's --ep at all, so gap *extension* sat "
        "at the default 0.123 through every build, which is what let a single unalignable fragment "
        "open a wide insertion block: opening the gap is paid for once and widening it is nearly "
        "free. Measured on POLIO_unified's real pass-1 input, CDS width goes 2465 -> 2300 aa at "
        "--ep 0.5 with --op unchanged. Raising --op instead makes it *wider* (2883 aa at 6.0), so "
        "the penalty pair is not monotonic in width and --op 4.5 is kept because it measures best."
    ),
    "pass2_local_gap_open": (
        "-24.0. Upstream's shipped builds ran at MAFFT's default of -2.00 through every build, "
        "which shreds short addon fragments. This is the larger scientific change of the two."
    ),
    "inferred_frame_by_homology": (
        "The 6-frame fallback picks the candidate ORF with the highest 6-mer containment against "
        "the corpus's own annotated proteins, where upstream picked the longest stop-free run "
        "regardless of whether it read as protein. On release 5.0.0's shipped bytes that rule "
        "chose a wrong frame for 51 EV_unified rows and 20 NPEV_unified rows, including the whole "
        "OR538731-OR538740 PV3 cluster."
    ),
    "noncoding_records_leave_the_cds_block": (
        "A record no frame of which reads as protein is `noncoding`: it contributes no CDS row and "
        "its whole sequence is offered to the 5'NCR block instead. Upstream gave each of them a "
        "spurious >=20 aa ORF in the CDS block AND excluded them from the NCR blocks. 1,281 "
        "EV_unified rows and 855 NPEV_unified rows are affected, and 99.9% of the ones that map to "
        "a reference at all are 5'UTR amplicons."
    ),
    "clade_exemplars_in_the_seed": (
        "Four RefSeq rhinovirus polyproteins join the seed alignment and are removed before "
        "backtranslation. No RV-A or RV-B record in this corpus can reach seed_min_aa, so 456 rows "
        "were aligned with no member of their own species in the seed; measured on 5.0.0, a type "
        "with no seed exemplar has residues exiled more than 200 codon columns from its own block "
        "at 8.4% against 0.14% for a type that has one."
    ),
    "padded_assembly_gaps_leave_the_orf": (
        "A run of 30 or more wholly-ambiguous codons is dropped from the ORF before alignment. "
        "MAFFT places an X-run as residues and drags real sequence with it: PX242098 carries a "
        "731-codon run and had 537 of 1,486 residues placed 821 columns from the rest. The count "
        "survives per record in the coverage sidecar's unsequenced_nt."
    ),
}




def build_provenance(
    repository_root: Path,
    population: AlignmentPopulation,
    stitched: StitchedAlignment,
    paths: dict[str, Path],
    *,
    tool_identity: dict[str, str],
    threads: int,
    over_length_cap: tuple[str, ...] = (),
    anchored_rows: tuple = (),
    segmentations: dict | None = None,
    homology_pool=None,
    codon_block=None,
) -> dict:
    spec = population.spec
    by_accession = {record.accession: record for record in population.records}

    tiers = Counter(by_accession[a].tier for a in stitched.accessions)
    families = Counter(by_accession[a].family for a in stitched.accessions)
    types = Counter(by_accession[a].type_sort_key for a in stitched.accessions)

    present = Counter()
    absence_reasons: Counter[str] = Counter()
    for row in stitched.coverage:
        if row.present:
            present[row.block] += 1
        elif row.absence_reason:
            absence_reasons[f"{row.block}:{row.absence_reason}"] += 1

    models: dict[str, dict[str, str]] = {}
    if spec.ncr is not None:
        for side, side_spec in (("5p", spec.ncr.five_prime), ("3p", spec.ncr.three_prime)):
            model_path = repository_root / side_spec.cm_path
            models[side] = {
                "cm_path": side_spec.cm_path,
                "cm_sha256": sha256_file(model_path),
                "pop_min_nt": side_spec.pop_min_nt,
                "pop_max_nt": side_spec.pop_max_nt,
            }

    document: dict = {
        "schema": SCHEMA,
        "name": spec.name,
        "stack": spec.stack,
        "description": spec.description,
        "rows": len(stitched.accessions),
        "expected_rows": spec.expected_rows,
        "width_nt": stitched.width_nt,
        "block_widths": {
            "5ncr": stitched.width_5ncr,
            "cds": stitched.width_cds,
            "3ncr": stitched.width_3ncr,
        },
        "blocks_present": dict(sorted(present.items())),
        "absence_reasons": dict(sorted(absence_reasons.items())),
        "tiers": dict(sorted(tiers.items())),
        "families": dict(sorted(families.items())),
        "types": dict(sorted(types.items())),
        # Pins the row set independently of alignment content: the same population under different
        # parameters keeps this hash, and a population change moves it even if widths coincide.
        "population_sha256": population_sha256(stitched.accessions),
        "covariance_models": models,
        "tool_identity": dict(sorted(tool_identity.items())),
        "threads": threads,
        # No wall-clock duration. It was here as `"seconds"` until 2026-08-14, rounded to a tenth,
        # which made a committed artifact depend on how fast the machine that built it happened to
        # be: two byte-identical alignments from the same inputs produced two different provenance
        # files. `threads` stays because it is a declared build parameter that changes the output;
        # elapsed time is a property of the hardware, and `evgc alignment-build` still reports it on
        # stderr for the operator who wants it.
        "parameter_departures": PARAMETER_DEPARTURES,
        "artifact_sha256": {
            key: sha256_file(path) for key, path in sorted(paths.items()) if path.is_file()
        },
    }
    if spec.stack == "anchored":
        assert spec.anchor is not None
        document["anchor"] = {
            **{k: v for k, v in asdict(spec.anchor).items() if k != "pdist_guard_bypass"},
            "pdist_guard_bypass": sorted(spec.anchor.pdist_guard_bypass),
        }
        document["n_reference_columns"] = stitched.width_nt
        # `length_cap` is a declared reporting threshold rather than a filter (see AnchorSpec), so
        # it has to actually report: an empty list is the finding that nothing exceeded it, and a
        # threshold whose result appears nowhere would be the same anti-pattern as a check that
        # cannot fail.
        document["over_length_cap"] = list(over_length_cap)
        document["anchored_audit"] = anchored_audit(anchored_rows)
    else:
        document["codon"] = asdict(spec.codon)
        document["cds_codons"] = stitched.width_cds // 3
        document["cds_width_is_whole_codons"] = stitched.width_cds % 3 == 0
        document["blocks_present_cds"] = present[BLOCK_CDS]
        if codon_block is not None:
            document["clade_exemplars"] = {
                "exemplars": list(codon_block.clade_exemplars),
                "codons_dropped_after_removal": codon_block.exemplar_only_codons_dropped,
                "unsequenced_codons_dropped": codon_block.unsequenced_codons_dropped,
            }
    if segmentations is not None:
        document["segmentation"] = segmentation_audit(
            segmentations, stitched.accessions, homology_pool
        )
    return document


def segmentation_audit(
    segmentations: dict, accessions: tuple[str, ...], homology_pool=None
) -> dict:
    """How this artifact's rows were segmented, counted over the rows actually written.

    Recorded because the segmentation decisions are now the largest single influence on what the
    CDS block contains, and none of them is visible in the alignment itself. `noncoding` in
    particular is a claim about a record — "no frame of this reads as enterovirus protein" — and a
    claim a reader cannot count is a claim they cannot check.
    """
    rows = [segmentations[accession] for accession in accessions]
    audit = {
        "methods": dict(sorted(Counter(row.method for row in rows).items())),
        "strands": dict(sorted(Counter(row.strand for row in rows).items())),
        "noncoding_offered_to_5ncr": sum(
            1 for row in rows if row.method == "noncoding" and row.ncr5
        ),
        # An inferred record's `ncr5` is empty unless `segment._boundary_cut` measured a 5'UTR head
        # on the front of its ORF, so its length *is* the count — see `Segmentation`'s docstring for
        # why that does not need a field of its own.
        "inferred_utr_head_cut": sum(1 for row in rows if row.method == "inferred" and row.ncr5),
        "inferred_utr_head_nt": sum(
            len(row.ncr5) for row in rows if row.method == "inferred"
        ),
        "rows_with_unsequenced_run_dropped": sum(1 for row in rows if row.unsequenced_nt),
        "unsequenced_nt_dropped": sum(row.unsequenced_nt for row in rows),
    }
    if homology_pool is not None:
        audit["homology_pool"] = {
            "proteins": homology_pool.n_proteins,
            "protein_kmers": len(homology_pool.protein),
            "protein_kmer_size": homology_pool.protein_kmer,
            "ncr5_kmers": len(homology_pool.ncr5),
            "ncr5_kmer_size": homology_pool.ncr5_kmer,
        }
    return audit


def anchored_audit(rows: tuple) -> dict:
    """Aggregates over the anchored stack's per-row decisions.

    Recorded because the alignment itself does not show which path produced a row, and a ported
    mechanism nobody can observe is a mechanism nobody can tell is dead. In particular this is how a
    reader learns whether the frameshift-recovery path ever fires: `method` counts `recovered`
    against `nt_cds_fallback` (recovery attempted and failed), and `nt_better` counts the times the
    do-no-harm guard preferred the plain nucleotide anchor.
    """
    if not rows:
        return {}
    return {
        "methods": dict(sorted(Counter(row.method for row in rows).items())),
        "strands": dict(sorted(Counter(row.strand for row in rows).items())),
        "rows_with_internal_stop": sum(1 for row in rows if row.internal_stop),
        "frameshift_recovered": sum(1 for row in rows if row.recovered is True),
        "frameshift_recovery_failed": sum(1 for row in rows if row.recovered is False),
        # A non-multiple-of-three CDS deletion inside a covered span implies a frameshift no real
        # poliovirus carries, so a nonzero count here is a sequencing or annotation signal.
        "rows_with_non_multiple_of_three_cds_gap": sum(
            1 for row in rows if row.n_cds_gap_non_multiple_of_three
        ),
        "rows_with_misphased_cds_gap": sum(1 for row in rows if row.n_cds_gap_misphased),
    }


def population_sha256(accessions: tuple[str, ...]) -> str:
    """Hash of the row set in row order — so it pins both membership and the declared ordering."""
    digest = hashlib.sha256()
    for accession in accessions:
        digest.update(accession.encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def write_provenance(output_dir: Path, name: str, document: dict) -> Path:
    path = output_dir / f"{name}{PROVENANCE_SUFFIX}"
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def tool_identity(toolchain) -> dict[str, str]:
    """`{tool: "package version build"}`, from the already-resolved toolchain."""
    return {
        name: f"{tool.package} {tool.version} {tool.build}"
        for name, tool in toolchain.tools.items()
    }

