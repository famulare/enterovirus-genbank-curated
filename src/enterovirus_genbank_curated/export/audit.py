"""Write the `audit/` release views.

Only the rule view exists so far. It matters more than its size suggests: it is generated from
`registry/rules.json` and must come out **byte-identical** to the shipped
`final/audit/rules.tsv.gz`, which is what turns the new catalog from a plausible-looking data file
into one demonstrably describing the release. The four shipped columns are a projection of the
catalog's seven; `implementation`, `parameters` and `status` are the rewrite's own additions and are
deliberately not in the view, because the view has to reproduce a frozen artifact.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path

from enterovirus_genbank_curated.contracts import BASELINE_RELEASE
from enterovirus_genbank_curated.curate.apply import APPLICATION_COLUMNS, DecisionApplication
from enterovirus_genbank_curated.derive.evidence import MEMBERSHIP_COLUMNS, MembershipRescue
from enterovirus_genbank_curated.export.source import write_tsv
from enterovirus_genbank_curated.registry.rules import RuleSpec

RULES_VIEW_RELATIVE = "audit/rules.tsv.gz"
RULES_VIEW_COLUMNS = ("rule_id", "rule_version", "field_name", "description")

# Deliberately not the shipped name. The release's own projection-provenance table carries fourteen
# canonical fields; this holds only the fields whose rule is implemented, so it is written under its
# own name with the covered set declared alongside it — the same reason the transport is not written
# as `sequence_metadata.tsv.gz`.
PROVENANCE_RELATIVE = "audit/projection_provenance.tsv.gz"
PROVENANCE_COLUMNS = (
    "accession",
    "version",
    "canonical_field",
    "final_value",
    "source_field",
    "source_value",
    "winning_rule_id",
    "evidence_basis",
    "manual_override",
)

# The rewrite's own tenth column, alongside the nine the release ships. A rule that declines has to
# say so somewhere, and the alternative — inferring "declined" from a blank `final_value` — cannot
# distinguish it from a value the rule deliberately blanked, which `locality` does 23,251 times.
UNRESOLVED_REASON_COLUMN = "unresolved_reason"
PROVENANCE_OUTPUT_COLUMNS = (*PROVENANCE_COLUMNS, UNRESOLVED_REASON_COLUMN)


def write_rules_view(output_dir: Path, specs: Iterable[RuleSpec]) -> int:
    """Project the catalog onto the four shipped columns, in catalog order.

    Only rules carrying the baseline's own `rule_version` are emitted. That is what lets the catalog
    grow — and lets a rule be *superseded* — while this view stays byte-identical to the frozen
    `rules.tsv.gz`. A rule the rewrite adds or corrects gets a real semver instead, so it is visibly
    not part of the release it postdates.

    Filtering on a data field rather than on a hardcoded id list keeps release knowledge out of the
    build: this writer never needs to know which rules 2.4.1 happened to contain.
    """
    rows = [
        {column: getattr(spec, column) for column in RULES_VIEW_COLUMNS}
        for spec in specs
        if spec.rule_version == BASELINE_RELEASE
    ]
    return write_tsv(output_dir / RULES_VIEW_RELATIVE, RULES_VIEW_COLUMNS, rows)


def write_projection_provenance(output_dir: Path, rows: list[dict[str, str]]) -> int:
    """Write the projection rows exactly as the rules produced them, in emission order."""
    return write_tsv(output_dir / PROVENANCE_RELATIVE, PROVENANCE_OUTPUT_COLUMNS, rows)


APPLICATIONS_RELATIVE = "audit/decision_applications.tsv.gz"


def write_decision_applications(output_dir: Path, applications: list[DecisionApplication]) -> int:
    """One row per decision per canonical field it can reach, in ledger order."""
    return write_tsv(
        output_dir / APPLICATIONS_RELATIVE,
        APPLICATION_COLUMNS,
        [application.as_row() for application in applications],
    )


MEMBERSHIP_RESCUE_RELATIVE = "audit/membership_rescue.tsv"


def write_membership_rescue(
    output_dir: Path,
    rescued: Mapping[str, MembershipRescue],
    records: Iterable[Mapping[str, str]],
) -> int:
    """One row per record admitted to the carve despite its GenBank lineage.

    Written uncompressed and small on purpose: this is the artifact a reviewer opens to ask "why is
    a `synthetic construct` record in a poliovirus table", and every row carries the distance and
    codon count, or the twin's version, that answers it.
    """
    organism = {record["version"]: record["organism_name"] for record in records}
    rows = [
        {
            "accession": rescue.version.rsplit(".", 1)[0],
            "version": rescue.version,
            "organism_name": organism.get(rescue.version, ""),
            "membership_basis": rescue.basis,
            "reference_serotype": rescue.reference_serotype,
            "reference_version": rescue.reference_version,
            "capsid_aa_distance_pct": rescue.distance_pct,
            "capsid_codons_compared": rescue.compared_codons,
            "byte_identical_twin": rescue.twin_version,
        }
        for rescue in sorted(rescued.values(), key=lambda rescue: rescue.version)
    ]
    return write_tsv(output_dir / MEMBERSHIP_RESCUE_RELATIVE, MEMBERSHIP_COLUMNS, rows)
