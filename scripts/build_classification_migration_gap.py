"""Regenerate `docs/classification-migration-gap.tsv` from the preserved 2.4.1 fixture.

The table it writes used to be maintained by hand, and it drifted twice: it claimed 536 differing
records when there were 529, then 512, and two records sat in no category at all while the file's
own headline was that every row has one. A reconciliation nobody can recompute is a reconciliation
nobody is checking — the same lesson `oracle/parity.py`'s transition contract exists for.

So the table is derived now, and `tests/test_classification_migration_gap.py` asserts the committed
file is what this script produces. Run it after any change that moves
`poliovirus_classification`:

    pixi run -e align python scripts/build_classification_migration_gap.py

Every category is a function of the *provenance*, not of a hand-read of the record. That is what
makes the categorisation reproducible, and it is why `uncategorised` is impossible rather than
merely asserted to be zero: a difference whose provenance this script does not recognise raises.
"""

from __future__ import annotations

import csv
import gzip
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "releases/2.4.1/canonical/sequence_metadata.tsv.gz"
BUILT = ROOT / "final/canonical/sequence_metadata.tsv.gz"
PROVENANCE = ROOT / "final/audit/projection_provenance.tsv.gz"
OUTPUT = ROOT / "docs/classification-migration-gap.tsv"

FIELD = "poliovirus_classification"
COLUMNS = (
    "version", "accession", "release_classification", "built_classification",
    "unresolved_reason", "category",
)

# A declined cell's category is its own reason, renamed to read as a category. Every reason
# `derive/classification.py` can emit must appear here or this script raises.
CATEGORY_BY_REASON = {
    "too_little_sequence_compared_to_measure_divergence": "declined_too_little_sequence",
    "no_serotype_in_organism_name_to_choose_a_reference": "declined_no_serotype_in_name",
    "follows_unresolved_virus_group": "declined_membership_undecided",
    "curated_value_outside_controlled_vocabulary": "declined_uncontrolled_curated_value",
}

# A resolved cell that differs is categorised by *what settled it here*, which is the honest axis:
# it says whether this pipeline is disagreeing on a measurement, refining beyond the release, or
# reading something the release did not.
CATEGORY_BY_BASIS = {
    "curated_classification": "ledger_refines_beyond_the_release",
    "vdpv_refinement_in_record_text": "record_text_refines_beyond_the_release",
    "text_classification_no_sequence_signal": "record_text_refines_beyond_the_release",
    "isolate_linked_inference": "sibling_inference_disagrees_with_release",
    "named_wild_reference_strain": "named_wild_reference_strain",
    "vp1_divergence_in_vaccine_derived_band": "sequence_band_disagrees_with_release",
    "vp1_divergence_below_sabin_like_threshold": "sequence_band_disagrees_with_release",
    "vp1_divergence_at_or_above_wild_threshold": "sequence_band_disagrees_with_release",
    "capsid_divergence_in_vaccine_derived_band": "sequence_band_disagrees_with_release",
    "capsid_divergence_below_sabin_like_threshold": "sequence_band_disagrees_with_release",
    "capsid_divergence_at_or_above_wild_threshold": "sequence_band_disagrees_with_release",
}


def read_gz(path: Path) -> list[dict[str, str]]:
    csv.field_size_limit(1 << 30)
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def build_rows() -> list[dict[str, str]]:
    baseline = {row["version"]: row for row in read_gz(BASELINE)}
    built = {row["version"]: row for row in read_gz(BUILT)}
    provenance = {
        row["version"]: row for row in read_gz(PROVENANCE) if row["canonical_field"] == FIELD
    }

    rows: list[dict[str, str]] = []
    for version in sorted(set(baseline) & set(built)):
        release_value = baseline[version][FIELD]
        built_value = built[version][FIELD]
        if release_value == built_value:
            continue
        trace = provenance[version]
        reason, basis = trace["unresolved_reason"], trace["evidence_basis"]
        if reason:
            category = CATEGORY_BY_REASON.get(reason)
        elif not built_value:
            # A determined blank against a release value: outside poliovirus by the partition.
            category = "determined_outside_poliovirus"
        else:
            category = CATEGORY_BY_BASIS.get(basis)
        if category is None:
            raise SystemExit(
                f"{version}: no category for reason={reason!r} basis={basis!r}. Add it to "
                f"CATEGORY_BY_REASON or CATEGORY_BY_BASIS rather than leaving a row uncategorised."
            )
        rows.append(
            {
                "version": version,
                "accession": version.split(".", 1)[0],
                "release_classification": release_value,
                "built_classification": built_value,
                "unresolved_reason": reason,
                "category": category,
            }
        )
    return rows


def render(rows: list[dict[str, str]]) -> str:
    lines = ["\t".join(COLUMNS)]
    lines.extend("\t".join(row[column] for column in COLUMNS) for row in rows)
    return "\n".join(lines) + "\n"


def main() -> int:
    rows = build_rows()
    OUTPUT.write_text(render(rows), encoding="utf-8")
    tally = Counter(row["category"] for row in rows)
    print(f"{len(rows)} differing records, {len(tally)} categories\n", file=sys.stderr)
    for category, count in tally.most_common():
        print(f"  {count:5d}  {category}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
