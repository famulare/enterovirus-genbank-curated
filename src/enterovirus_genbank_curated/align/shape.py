"""The shape report, and the declared delta against the shipped 2.4.1 alignments.

This is the artifact a reviewer actually reads, so it is a first-class output rather than a log
line. Two halves:

* **Shape** — rows per tier, family and type; block widths; how many rows carry each block and the
  reason when one is absent; the residue-completeness distribution.
* **Declared delta** — for each artifact, which accessions the rebuild adds relative to the shipped
  file and which it drops, with a reason per dropped row from a closed vocabulary.

The delta is the point philosophically. Byte parity with the shipped alignments is impossible and
known to be: those bytes came from code that no longer exists in that form. Rather than treat that
as an excuse, this converts "we cannot reproduce the shipped bytes" into a checked statement about
exactly what changed — stronger than parity, because parity against artifacts built by vanished code
proves only that nobody has touched the file since.

Reading the shipped files needs a second Stockholm dialect: 2.4.1's anchored artifacts carry
`#=GS <id> AC <id>` after each sequence line and no `#=GF ID`, while the unified ones differ again.
Only the row ids are needed here, so `shipped_row_ids` reads ids and nothing else and is tolerant of
both — a full parse would be work for information the delta does not use.
"""

from __future__ import annotations

import gzip
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from enterovirus_genbank_curated.align import contract, segment
from enterovirus_genbank_curated.align import population as population_module
from enterovirus_genbank_curated.contracts import ContractError
from enterovirus_genbank_curated.oracle.parity import SHIPPED_RECORD_DISPOSITION
from enterovirus_genbank_curated.oracle.release import read_tsv_gz

SHIPPED_ALIGNMENT_DIR = "alignments"

# Why a shipped row is not in the rebuild. Closed, because "some other reason" is how a real
# regression hides among adjudicated ones.
REASON_GROUP_MOVED = "group_moved"
REASON_SEROTYPE_RELABELLED = "serotype_relabelled"
REASON_VIRUS_TYPE_LOST = "virus_type_lost"
REASON_CARVE_EXCLUDED = "carve_excluded"
REASON_ABSENT_FROM_CANONICAL = "absent_from_canonical"
DROP_REASONS = (
    REASON_GROUP_MOVED,
    REASON_SEROTYPE_RELABELLED,
    REASON_VIRUS_TYPE_LOST,
    REASON_CARVE_EXCLUDED,
    REASON_ABSENT_FROM_CANONICAL,
)


@dataclass(frozen=True)
class Delta:
    name: str
    shipped_rows: int
    rebuilt_rows: int
    added: tuple[str, ...]
    dropped: tuple[tuple[str, str], ...]  # (accession, reason)

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "shipped_rows": self.shipped_rows,
            "rebuilt_rows": self.rebuilt_rows,
            "n_added": len(self.added),
            "n_dropped": len(self.dropped),
            "added": list(self.added),
            "dropped": [{"accession": a, "reason": r} for a, r in self.dropped],
            "dropped_by_reason": dict(sorted(Counter(r for _a, r in self.dropped).items())),
        }


def shipped_row_ids(path: Path) -> tuple[str, ...]:
    """Row ids from a shipped Stockholm, in file order, tolerant of both 2.4.1 dialects."""
    ids: list[str] = []
    seen: set[str] = set()
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if line.startswith("#") or line.startswith("//") or not line.strip():
                continue
            name = line.split()[0]
            if name not in seen:
                seen.add(name)
                ids.append(name)
    return tuple(ids)


def carve_exclusions(repository_root: Path) -> dict[str, str]:
    """`{accession: exclusion_reason}` for records the curation ledger deliberately excluded.

    Consulted so a shipped row absent from the rebuild can be filed as `carve_excluded` — the real
    reason — rather than merely `absent_from_canonical`, which is the observation. Without this the
    `carve_excluded` vocabulary entry could never fire, and a vocabulary entry that cannot be
    reached is the same anti-pattern as a check that cannot fail.
    """
    header, rows = read_tsv_gz(repository_root / SHIPPED_RECORD_DISPOSITION)
    excluded: dict[str, str] = {}
    for row in rows:
        record = dict(zip(header, row, strict=False))
        if record.get("canonical_included") == "FALSE" and record.get("exclusion_reason"):
            excluded[record["accession"]] = record["exclusion_reason"]
    return excluded


def _drop_reason(
    accession: str,
    name: str,
    records: dict[str, population_module.AlignedRecord],
    shipped_serotype: str | None,
    excluded: dict[str, str],
) -> str:
    """Why a shipped row is absent from the rebuild.

    Precedence is declared rather than incidental, because one accession can satisfy two reasons at
    once: `OR538735` both changed group and lost its type. Group first, since that is the coarser
    determination and the one that moved the record out of this artifact's population.
    """
    record = records.get(accession)
    if record is None:
        return REASON_CARVE_EXCLUDED if accession in excluded else REASON_ABSENT_FROM_CANONICAL
    spec = contract.ARTIFACTS[name]
    if record.virus_group not in spec.population.virus_groups:
        return REASON_GROUP_MOVED
    if not record.virus_type:
        return REASON_VIRUS_TYPE_LOST
    if shipped_serotype is not None and record.virus_type != shipped_serotype:
        return REASON_SEROTYPE_RELABELLED
    # Present in canonical and inside this artifact's population, yet absent from the rebuild: not
    # an adjudicated change, so it must not be filed under one.
    raise ContractError(
        f"{name}/{accession}: shipped row is absent from the rebuild but matches the population "
        f"rule, so no declared reason applies — this is a build defect, not a declared delta"
    )


def compute_delta(
    repository_root: Path,
    name: str,
    rebuilt_ids: tuple[str, ...],
    records: dict[str, population_module.AlignedRecord],
) -> Delta:
    spec = contract.ARTIFACTS[name]
    shipped_path = repository_root / "final" / SHIPPED_ALIGNMENT_DIR / f"{name}.sto.gz"
    if not shipped_path.is_file():
        raise ContractError(f"no shipped alignment to compare against: {shipped_path}")
    shipped = shipped_row_ids(shipped_path)

    shipped_serotype = None
    if spec.stack == "anchored" and spec.anchor is not None:
        shipped_serotype = spec.anchor.serotype
    excluded = carve_exclusions(repository_root)

    rebuilt_set, shipped_set = set(rebuilt_ids), set(shipped)
    added = tuple(sorted(rebuilt_set - shipped_set))
    dropped = tuple(
        (accession, _drop_reason(accession, name, records, shipped_serotype, excluded))
        for accession in sorted(shipped_set - rebuilt_set)
    )
    return Delta(
        name=name, shipped_rows=len(shipped), rebuilt_rows=len(rebuilt_ids),
        added=added, dropped=dropped,
    )


def shape_of(
    population: population_module.AlignmentPopulation, artifact
) -> dict:
    """Counts a reviewer wants, recomputed from the artifact and its population."""
    by_accession = {r.accession: r for r in population.records}
    rows = artifact.rows
    present = Counter()
    reasons: Counter[str] = Counter()
    for row in artifact.coverage:
        if row["present"] == "TRUE":
            present[row["block"]] += 1
        elif row["absence_reason"]:
            reasons[f"{row['block']}:{row['absence_reason']}"] += 1

    occupancy = sorted(len(r) - r.count("-") for r in rows.values())
    translation = _translation_qc(rows, artifact.block_widths)

    def percentile(fraction: float) -> int:
        if not occupancy:
            return 0
        return occupancy[min(len(occupancy) - 1, int(fraction * len(occupancy)))]

    return {
        "rows": len(rows),
        "width_nt": artifact.width_nt,
        "block_widths": dict(sorted(artifact.block_widths.items())),
        "blocks_present": dict(sorted(present.items())),
        "absence_reasons": dict(sorted(reasons.items())),
        "tiers": dict(sorted(Counter(by_accession[a].tier for a in rows).items())),
        "families": dict(sorted(Counter(by_accession[a].family for a in rows).items())),
        "types": dict(sorted(Counter(by_accession[a].type_sort_key for a in rows).items())),
        "cds_translation": translation,
        "residue_occupancy": {
            "min": occupancy[0] if occupancy else 0,
            "p10": percentile(0.10),
            "median": percentile(0.50),
            "p90": percentile(0.90),
            "max": occupancy[-1] if occupancy else 0,
        },
    }


# A near-complete enterovirus polyprotein ORF is about 6,600 nt. This selects whole genomes in both
# stacks, and it is an *absolute* length rather than a fraction of the block for a reason worth
# recording: an earlier version used "at least 99% of the block occupied", which works for the
# anchored stack — where the block is the reference genome, so a complete genome fills it — and
# silently selects nothing at all for the unified stack, whose CDS block is 7,839 columns wide while
# the longest ungapped ORF in it is 6,669 nt, or 85%. A metric that quietly measures zero rows on
# half the artifacts is the same anti-pattern as a check that cannot fail.
NEAR_COMPLETE_ORF_NT = 6000


def _translation_qc(
    rows: dict[str, str], block_widths: dict[str, int], min_orf_nt: int = NEAR_COMPLETE_ORF_NT
) -> dict:
    """Do the near-complete CDS blocks actually translate?

    The structural gate checks widths and alphabets; only translation tells you the codon frame is
    *right*. Gaps become `N` rather than being stripped, which preserves frame in both stacks: every
    gap is a codon-aligned triplet, since `align.codon`'s backtranslation maps each amino-acid gap
    to exactly `"---"` and the anchored projection sits on the reference's own codon frame.

    Measured: `POLIO_unified` gives 2,024 of 2,024 clean, `PV1_unified` 403 of 407. Three of that
    stack's four exceptions are `FV537075`-`FV537077`, the bisulfite-converted Mahoney strings
    already adjudicated as not poliovirus genomes — a C-to-T converted genome *should* fail to
    translate, so surfacing them is the metric working. They are absent from the unified count
    because `align.segment` rejects their annotated frame, and the inferred ORF it falls back to is
    far shorter than the floor.
    """
    width_cds = block_widths.get("cds", 0)
    offset = block_widths.get("5ncr", 0)
    if not width_cds:
        return {"near_complete_rows": 0, "no_internal_stop": 0, "with_internal_stop": []}

    clean = 0
    offenders: list[dict[str, int | str]] = []
    for accession in sorted(rows):
        block = rows[accession][offset : offset + width_cds]
        if len(block) - block.count("-") < min_orf_nt:
            continue
        aa = segment.translate(block.replace("-", "N"))
        internal = aa[:-1].count("*")
        if internal:
            offenders.append({"accession": accession, "internal_stops": internal})
        else:
            clean += 1
    return {
        "near_complete_rows": clean + len(offenders),
        "no_internal_stop": clean,
        "with_internal_stop": offenders,
    }


def build_report(
    repository_root: Path, output_dir: Path, names: tuple[str, ...] | None = None
) -> dict:
    """The whole report: shape per artifact plus the declared delta against 2.4.1."""
    from enterovirus_genbank_curated.validation import alignment as gate

    wanted = names if names is not None else tuple(contract.ARTIFACTS)
    records = population_module.load_all_records(repository_root)

    artifacts: dict[str, dict] = {}
    for name in wanted:
        if not (output_dir / f"{name}.sto.gz").is_file():
            continue
        artifact = gate.load_artifact(output_dir, name)
        population = population_module.select(records, contract.ARTIFACTS[name])
        entry = {"shape": shape_of(population, artifact)}
        delta = compute_delta(repository_root, name, artifact.accessions, records)
        entry["delta_vs_2_4_1"] = delta.as_dict()
        artifacts[name] = entry

    return {
        "schema": 1,
        "note": (
            "Byte parity with the shipped 2.4.1 alignments is not claimed and is not possible: "
            "those bytes came from code that no longer exists in that form, built at an unrecorded "
            "thread count. The delta below states exactly what changed instead."
        ),
        "drop_reason_vocabulary": list(DROP_REASONS),
        "artifacts": artifacts,
    }


def render(report: dict) -> str:
    lines = ["# Alignment shape report", "", report["note"], ""]
    for name, entry in sorted(report["artifacts"].items()):
        shape, delta = entry["shape"], entry["delta_vs_2_4_1"]
        lines.append(f"## {name}")
        lines.append("")
        widths = ", ".join(f"{block} {width}" for block, width in shape["block_widths"].items())
        lines.append(f"- {shape['rows']} rows x {shape['width_nt']} nt ({widths})")
        lines.append(f"- tiers: {shape['tiers']}")
        lines.append(f"- blocks present: {shape['blocks_present']}")
        if shape["absence_reasons"]:
            lines.append(f"- absences: {shape['absence_reasons']}")
        translation = shape["cds_translation"]
        if translation["near_complete_rows"]:
            offenders = translation["with_internal_stop"]
            lines.append(
                f"- CDS translation: {translation['no_internal_stop']} of "
                f"{translation['near_complete_rows']} near-complete rows have no internal stop"
                + (
                    f"; exceptions {[o['accession'] for o in offenders]}" if offenders else ""
                )
            )
        occupancy = shape["residue_occupancy"]
        lines.append(
            f"- residue occupancy: median {occupancy['median']}, p10 {occupancy['p10']}, "
            f"p90 {occupancy['p90']}, max {occupancy['max']}"
        )
        lines.append(
            f"- vs 2.4.1: {delta['shipped_rows']} shipped -> {delta['rebuilt_rows']} rebuilt "
            f"(+{delta['n_added']} / -{delta['n_dropped']})"
        )
        if delta["dropped_by_reason"]:
            lines.append(f"- dropped by reason: {delta['dropped_by_reason']}")
        lines.append("")
    return "\n".join(lines)


def write_report(output_dir: Path, report: dict) -> tuple[Path, Path]:
    json_path = output_dir / "shape_report.json"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md_path = output_dir / "shape_report.md"
    md_path.write_text(render(report), encoding="utf-8")
    return json_path, md_path
