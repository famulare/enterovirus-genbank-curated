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

from enterovirus_genbank_curated.align import contract
from enterovirus_genbank_curated.align.population import AlignmentPopulation
from enterovirus_genbank_curated.align.stitch import BLOCK_CDS, StitchedAlignment

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
    "pass2_local_gap_open": (
        "-24.0. Upstream's shipped builds ran at MAFFT's default of -2.00 through every build, "
        "which shreds short addon fragments. This is the larger scientific change of the two."
    ),
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_provenance(
    repository_root: Path,
    population: AlignmentPopulation,
    stitched: StitchedAlignment,
    paths: dict[str, Path],
    *,
    tool_identity: dict[str, str],
    threads: int,
    seconds: float,
    over_length_cap: tuple[str, ...] = (),
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
                "cm_sha256": _sha256(model_path),
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
        "seconds": round(seconds, 1),
        "parameter_departures": PARAMETER_DEPARTURES,
        "artifact_sha256": {
            key: _sha256(path) for key, path in sorted(paths.items()) if path.is_file()
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
    else:
        document["codon"] = asdict(spec.codon)
        document["cds_codons"] = stitched.width_cds // 3
        document["cds_width_is_whole_codons"] = stitched.width_cds % 3 == 0
        document["blocks_present_cds"] = present[BLOCK_CDS]
    return document


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


def spec_summary() -> dict:
    """Every declared artifact's shape, for a reader who has no build output to hand."""
    return {
        name: {
            "stack": spec.stack,
            "expected_rows": spec.expected_rows,
            "virus_groups": list(spec.population.virus_groups),
            "virus_types": list(spec.population.virus_types or ()),
        }
        for name, spec in contract.ARTIFACTS.items()
    }
