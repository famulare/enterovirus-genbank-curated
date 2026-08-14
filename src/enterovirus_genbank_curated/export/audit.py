"""Write the `audit/` release views.

Five views, and they fall into three kinds. The kind decides the *filename*, which is the only part
of an audit artifact a consumer reads before trusting it.

**One publishes the rules the build ran.** `write_rules_view` is generated from
`registry/rules.json` and carries every rule in it. It used to carry only the 28 whose
`rule_version` was 2.4.1's, so that it came out byte-identical to that release's frozen
`rules.tsv.gz` — correct while `final/` held 2.4.1, and wrong from the moment it stopped, because
the release then published a rule table describing a *different* release and withheld its own. It
emits five of the catalog's seven columns; `implementation` and `parameters` stay out as build
internals, and `status` is in precisely because a full catalog contains deprecated rules a consumer
has to be able to skip.

**Two have a shipped counterpart and cover less of it, so they carry their own names.** A partial
table under a frozen table's filename would be read as that table, and no `notes` column undoes a
filename. `PROVENANCE_RELATIVE` and `CLASSIFICATION_DIVERGENCE_RELATIVE` each declare what they do
cover at the point the name is chosen.

**Two have no shipped counterpart at all.** `APPLICATIONS_RELATIVE` and
`MEMBERSHIP_RESCUE_RELATIVE` are the rewrite's own audit trail — what became of each curator
decision, and why a record outside the GenBank lineage is nonetheless in the carve.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

from enterovirus_genbank_curated.contracts import ContractError
from enterovirus_genbank_curated.curate.apply import APPLICATION_COLUMNS, DecisionApplication
from enterovirus_genbank_curated.derive.evidence import (
    EVIDENCE_COLUMNS,
    MEMBERSHIP_COLUMNS,
    MembershipRescue,
)
from enterovirus_genbank_curated.derive.metadata import CURATION_STATUS_EXCLUDED
from enterovirus_genbank_curated.export.source import write_tsv
from enterovirus_genbank_curated.registry.rules import RuleSpec

RULES_VIEW_RELATIVE = "audit/rules.tsv.gz"
# `status` is the fifth column, added 2026-08-12 with the un-pinning below. Once the view carries
# every rule rather than one release's subset, a consumer has to be able to tell `R-DATE-1`
# (deprecated, superseded by R-DATE-2) from a rule that actually decided something — and the four
# 2.4.1 columns give no way to.
RULES_VIEW_COLUMNS = ("rule_id", "rule_version", "field_name", "description", "status")

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
    """Publish the rule catalog this build actually ran, in catalog order.

    Until 2026-08-12 this filtered on `rule_version == BASELINE_RELEASE`, so the view stayed
    byte-identical to 2.4.1's frozen `rules.tsv.gz` while the catalog grew underneath it. That was
    right while `final/` *held* 2.4.1 and byte-parity was the gate. It stopped being right at the
    promotion, and the cost was measured: the release published 28 rules, none of which decided any
    of its values, while **267,388 of 316,004 rows in `projection_provenance.tsv.gz` — 84.6% —
    carried a `winning_rule_id` that resolved to nothing in the table shipped beside it.** Ten of
    the twelve rules that produced the release were absent, `R-CLASS-2` and `R-DATE-2` among them.

    A release whose provenance table cites rules its own rule table does not contain is not
    traceable, which is the property `README.md` claims for it. So the view is the catalog now, and
    `test_every_winning_rule_id_resolves_in_the_shipped_view` is what keeps the two joined —
    a check the byte-parity arrangement made impossible to write.
    """
    rows = [{column: getattr(spec, column) for column in RULES_VIEW_COLUMNS} for spec in specs]
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


# Deliberately not the shipped name, for the same reason `PROVENANCE_RELATIVE` is not. The release's
# `final/audit/sequence_evidence.tsv.gz` is 21 columns over all 24,301 carved records: a sequence-
# derived serotype and its confidence, a classification tier and basis, capsid amino-acid p-distance
# and codon count, a VP1/capsid agreement flag, a CDS frameshift flag, recombinant junction and
# breakpoint, Sabin-segment divergence, and an independent enterovirus type call.
#
# `measure_sequence_evidence` produces exactly one of those measurements, Sabin-facing nucleotide
# divergence (VP1-first, whole-capsid fallback — a `basis` column names which, per row), over the
# carved records whose organism name names a serotype to pick a reference with. `accession` and
# `version` are the only two column names the two tables have in common, so this is not a projection
# of the shipped table the way the rule view is a projection of `rules.tsv.gz`; it is a different,
# smaller measurement that answers one of the shipped table's questions. Under the shipped name it
# would promise nineteen columns of evidence it does not have, over most of the records it reaches.
RECORD_DISPOSITION_RELATIVE = "audit/record_disposition.tsv.gz"
RECORD_DISPOSITION_COLUMNS = (
    "accession", "version", "candidate_query_member", "virus_group", "curation_status",
    "canonical_included", "exclusion_reason", "sequence_sha256",
)
# Every record in `raw/` was returned by the GenBank query that produced the archive, so this is
# `TRUE` on all 25,727 rows. Kept as a column rather than dropped because it is the denominator: the
# table's claim is "what became of every candidate", and a reader needs to see the candidate set
# stated rather than inferred from the row count.
CANDIDATE_QUERY_MEMBER = "TRUE"


def write_record_disposition(
    output_dir: Path,
    canonical: Sequence[Mapping[str, str]],
    excluded: Sequence[Mapping[str, str]],
    partitions: Mapping[str, str],
) -> int:
    """One row per candidate record, in corpus order, saying what became of it and why.

    Carried from 2.4.1 until 2026-08-14 because no build wrote it, and the carried copy left
    **1,253 of its 1,426 exclusions with a blank `exclusion_reason`** (backlog B34). A disposition
    table whose explaining column is empty on 88% of the rows it exists to explain cannot be acted
    on: a reader cannot tell a curator's deliberate carve-out from a record GenBank never called an
    enterovirus. Both reasons are recorded now, on every excluded row, because `transport_metadata`
    records them where the decision is made.

    `partitions` supplies `virus_group` for a curator-excluded record, whose exclusion says why it
    is out and nothing about what it is. A lineage-excluded record already carries `non_ev_other`,
    which the exclusion itself establishes.
    """
    rows = [
        {
            "accession": row["accession"],
            "version": row["version"],
            "candidate_query_member": CANDIDATE_QUERY_MEMBER,
            "virus_group": row["virus_group"],
            "curation_status": row["curation_status"],
            "canonical_included": "TRUE",
            "exclusion_reason": "",
            "sequence_sha256": row["sequence_sha256"],
        }
        for row in canonical
    ]
    rows += [
        {
            "accession": row["accession"],
            "version": row["version"],
            "candidate_query_member": CANDIDATE_QUERY_MEMBER,
            "virus_group": row["virus_group"] or partitions.get(row["version"], ""),
            "curation_status": CURATION_STATUS_EXCLUDED,
            "canonical_included": "FALSE",
            "exclusion_reason": row["exclusion_reason"],
            "sequence_sha256": row["sequence_sha256"],
        }
        for row in excluded
    ]
    missing = [row["version"] for row in rows if not row["virus_group"]]
    if missing:
        raise ContractError(
            f"{len(missing)} disposition rows have no virus_group ({missing[:5]}); every candidate "
            f"is an enterovirus by lineage, a curator exclusion whose organism name the partition "
            f"rule reads, or a carved record that already has one"
        )
    rows.sort(key=lambda row: row["version"])
    write_tsv(output_dir / RECORD_DISPOSITION_RELATIVE, RECORD_DISPOSITION_COLUMNS, rows)
    return len(rows)


CLASSIFICATION_DIVERGENCE_RELATIVE = "audit/classification_divergence.tsv.gz"


def write_classification_divergence(
    output_dir: Path, measured: Mapping[str, Mapping[str, str]]
) -> int:
    """The divergence measurement R-CLASS-2 decided from, in the carve's own row order.

    Written because the rule's *input* was being thrown away. `poliovirus_classification` is decided
    by comparing this divergence to the thresholds the catalog publishes, and the canonical table
    carries only the verdict — so a reader who wanted to check a `VDPV` call against the 1% boundary
    had the call and the threshold with no number in between. `unresolved_reason` already says when
    no measurement was possible; this says what it was when one was.

    Emission order rather than a re-sort: `measure_sequence_evidence` walks the carved rows, so the
    keys already arrive in the canonical table's own order, and sorting them again would only invent
    a second ordering to keep in step with the first.
    """
    rows = [
        {"accession": version.rsplit(".", 1)[0], "version": version, **fields}
        for version, fields in measured.items()
    ]
    return write_tsv(output_dir / CLASSIFICATION_DIVERGENCE_RELATIVE, EVIDENCE_COLUMNS, rows)
