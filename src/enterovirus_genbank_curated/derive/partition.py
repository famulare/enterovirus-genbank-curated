"""Poliovirus membership, and the two canonical columns that follow from it.

`virus_group` gates `sequence_scope`, `curation_status`, `poliovirus_classification` and the whole
epi partition, so getting it wrong quietly would make four later columns look right for the wrong
reason. That is why this rule returns **unresolved** rather than a default.

## The predicate, and why "not named poliovirus" is not the same as "not poliovirus"

Poliovirus sits inside one enterovirus species: *Enterovirus C*, which ICTV has since renamed
*Enterovirus coxsackiepol*. So a GenBank organism name determines polio membership only when it
names something at or below the type level:

* a name containing `poliovirus` determines **poliovirus**;
* a specific non-polio type (`Coxsackievirus A24`, `Echovirus 6`, `Enterovirus D68`) determines
  **non-polio**, and so does a species that cannot contain poliovirus (`Enterovirus B`);
* a name that is the polio-containing species itself, the bare genus, or not a virus identification
  at all determines **nothing**. Those are `UNINFORMATIVE_ORGANISMS`.

An earlier draft of this rule defaulted the uninformative names to non-polio. Measured against the
release that scores 98.3%, which looks like success and is a guess on 414 records — and the guess
would then be inherited by four downstream columns. The uninformative population is **1,765
records**, not 414; 414 is merely where the guess would have landed wrong. Sizing the ambiguity by
its disagreements rather than by its inputs is the mistake this docstring exists to prevent.

Upstream resolved these by capsid amino-acid distance to a poliovirus reference (R-MEMBERSHIP-AA-1),
which needs the sequence stage. Until then the ledger's `is_poliovirus` decisions resolve 17 of them
and the rest are declined.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from enterovirus_genbank_curated.derive.outcome import RecordView, RuleOutcome
from enterovirus_genbank_curated.registry.rules import rule_implementation

POLIOVIRUS = "poliovirus"
NON_POLIO_ENTEROVIRUS = "non_polio_enterovirus"
VOUCHED = "vouched"
PROVISIONAL = "provisional"

# The release's own name for the non-polio partition, which differs from the canonical value.
# Carried as `source_value` because that is what the shipped provenance records.
PARTITION_SOURCE_FIELD = "dataset_partition"
PARTITION_LABELS = {
    POLIOVIRUS: "poliovirus",
    NON_POLIO_ENTEROVIRUS: "enterovirus_excluding_confirmed_poliovirus",
}

BASIS_PARTITION = "partition"
BASIS_RELEASE_POLICY = "release_policy"
UNRESOLVED_UNINFORMATIVE = "organism_name_does_not_determine_membership"
# `curation_status` declines only because `virus_group` did. Naming that distinctly keeps it out of
# the curation queue, which would otherwise ask for the same decision twice under two field names.
UNRESOLVED_FOLLOWS_PARTITION = "follows_unresolved_virus_group"

POLIO_NAME_FRAGMENTS = ("poliovirus", "polio virus")

# Organism names that cannot decide polio membership, with the reason each cannot. Found by looking
# at which names the release ever ships as poliovirus, but every entry stands on taxonomy rather
# than on that observation — which is the difference between using an oracle to form a hypothesis
# and using it as an input.
UNINFORMATIVE_ORGANISMS = {
    # The species that contains poliovirus, under both its old and current ICTV names. A record
    # labelled only at this level may be a poliovirus or a coxsackievirus A.
    "Enterovirus C": "the species containing poliovirus, at species level",
    "Enterovirus coxsackiepol": "the same species under its current ICTV name",
    # Genus level, and below it nothing is determined.
    "Enterovirus sp.": "genus level only",
    # Not a virus identification at all: the deposit names the host, a construct, or nothing.
    "unidentified": "no organism was identified",
    "synthetic construct": "names the construct, not the virus it encodes",
    "Homo sapiens": "names the host, not the virus",
}

LEDGER_MEMBERSHIP_FIELD = "is_poliovirus"


def _membership(view: RecordView) -> tuple[str, bool]:
    """`(partition, came_from_a_decision)`, or `("", False)` when nothing determines it.

    The ledger is consulted first. A curator who has adjudicated membership has adjudicated it: a
    text predicate that overrode them would make the decision ornamental, which is the D2 failure.
    """
    asserted = view.decisions.get(LEDGER_MEMBERSHIP_FIELD)
    if asserted == "TRUE":
        return POLIOVIRUS, True
    if asserted == "FALSE":
        return NON_POLIO_ENTEROVIRUS, True

    organism = view.record.get("organism_name", "")
    if any(fragment in organism.lower() for fragment in POLIO_NAME_FRAGMENTS):
        return POLIOVIRUS, False
    if organism in UNINFORMATIVE_ORGANISMS:
        return "", False
    return NON_POLIO_ENTEROVIRUS, False


def resolved_partition(view: RecordView) -> str:
    """The partition, or `""` when nothing determines it — for rules that are scoped by it.

    Public because the epi rules are partition-scoped: `sample_origin` is curated for poliovirus and
    out of scope elsewhere, and a record whose membership is undecided cannot be scoped either way.
    """
    partition, _ = _membership(view)
    return partition


@rule_implementation(
    "derive.partition.virus_group",
    parameters=("groups",),
    evidence_bases=(BASIS_PARTITION,),
)
def virus_group(parameters: Mapping[str, Any], view: RecordView) -> RuleOutcome:
    partition, from_decision = _membership(view)
    if not partition:
        return RuleOutcome(
            value="",
            evidence_basis=BASIS_PARTITION,
            source_field=PARTITION_SOURCE_FIELD,
            # On a declined row `source_value` records the input the rule examined and could not
            # decide from, which is what lets the queue group by it. Declined rows are never
            # compared against the release, so this cannot affect parity.
            source_value=view.record.get("organism_name", ""),
            unresolved_reason=UNRESOLVED_UNINFORMATIVE,
        )
    declared = parameters["groups"]
    if partition not in declared:
        raise ValueError(f"{partition!r} is not one of the declared groups {declared}")
    return RuleOutcome(
        value=partition,
        evidence_basis=BASIS_PARTITION,
        source_field=PARTITION_SOURCE_FIELD,
        source_value=PARTITION_LABELS[partition],
        manual_override=from_decision,
    )


@rule_implementation(
    "derive.partition.curation_status",
    parameters=("poliovirus_status", "non_poliovirus_status", "carve_excluded_status"),
    evidence_bases=(BASIS_RELEASE_POLICY,),
)
def curation_status(parameters: Mapping[str, Any], view: RecordView) -> RuleOutcome:
    """Release policy over the partition. `carve_excluded_status` never applies to a carved row.

    `manual_override` is `FALSE` even on the seventeen records whose partition came from a decision,
    matching the release: the curator adjudicated membership, not the vouching policy that follows
    from it.
    """
    partition, _ = _membership(view)
    if not partition:
        return RuleOutcome(
            value="",
            evidence_basis=BASIS_RELEASE_POLICY,
            source_field=PARTITION_SOURCE_FIELD,
            source_value=view.record.get("organism_name", ""),
            unresolved_reason=UNRESOLVED_FOLLOWS_PARTITION,
        )
    status = (
        parameters["poliovirus_status"]
        if partition == POLIOVIRUS
        else parameters["non_poliovirus_status"]
    )
    return RuleOutcome(
        value=status,
        evidence_basis=BASIS_RELEASE_POLICY,
        source_field=PARTITION_SOURCE_FIELD,
        source_value=PARTITION_LABELS[partition],
    )
