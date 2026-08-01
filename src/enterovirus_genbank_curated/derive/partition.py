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
which the sequence stage now implements for carve membership. Within the carve the ledger resolves
some: 17 by an explicit `is_poliovirus` decision, and a further 259 because a curated
*classification* entails membership — see `_membership`. R-MEMBERSHIP-AA-1's own two-sided band
resolves more of the rest directly: a record named only `Enterovirus C`, `Enterovirus sp.`,
`unidentified` or `synthetic construct` (`UNINFORMATIVE_ORGANISMS`) whose capsid sits under 8%
amino- acid distance from the nearest poliovirus reference *is* poliovirus, and one at or above 15%
is not — `derive.evidence.measure_poliovirus_membership_band`, read here as
`RecordView.membership_evidence`. The 8-15% middle, and anything below the 50-codon floor, stays
declined; nothing here is a guess standing in for a name that would not commit.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from enterovirus_genbank_curated.derive.outcome import (
    MEMBERSHIP_BAND_CODONS_KEY,
    MEMBERSHIP_BAND_DISTANCE_KEY,
    MEMBERSHIP_BAND_KEY,
    MEMBERSHIP_BAND_REFERENCE_KEY,
    MEMBERSHIP_BAND_SEROTYPE_KEY,
    RecordView,
    RuleOutcome,
)
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
# R-MEMBERSHIP-AA-1's two-sided band, consulted only when the organism name itself decided nothing.
BASIS_MEMBERSHIP_AA = "capsid_aa_membership_band"
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
    # `Human enterovirus C` was the pre-2016 ICTV name of the polio-containing species, so the
    # unqualified form sits above the type level exactly as the genus does. 95 records carry it, and
    # one of them ships as EV-C96 — inside that very species — which is why it cannot be read as
    # "some enterovirus that is not poliovirus".
    "Human enterovirus": "the pre-2016 species name, unqualified: above the type level",
    # A strain epithet is not a type: these four name an isolate, not a deciding taxon.
    "Human Enterovirus Mumbai4-03": "a strain name, not a type",
    "Human Enterovirus Pune6-03": "a strain name, not a type",
    "Human enterovirus Hangzhou13-02": "a strain name, not a type",
    "Human enterovirus Ningbo3-02": "a strain name, not a type",
    # Not a virus identification at all: the deposit names the host, a construct, or nothing.
    "unidentified": "no organism was identified",
    "synthetic construct": "names the construct, not the virus it encodes",
    "Homo sapiens": "names the host, not the virus",
}

LEDGER_MEMBERSHIP_FIELD = "is_poliovirus"
LEDGER_MEMBERSHIP_VALUES = frozenset({"TRUE", "FALSE"})

# Fields whose very presence entails poliovirus membership, because the column they project —
# `poliovirus_classification` — has a poliovirus-only vocabulary. See `_membership`.
LEDGER_CLASSIFICATION_FIELDS = ("verified_classification", "classification")


def _membership(view: RecordView) -> tuple[str, bool, Mapping[str, str] | None]:
    """`(partition, came_from_a_decision, membership_evidence)`, or `("", False, None)` when nothing
    determines it. `membership_evidence` is set only when the partition came from
    `RecordView.membership_evidence` rather than from a decision or the organism name — see the band
    check at the bottom of this function.

    The ledger is consulted first. A curator who has adjudicated membership has adjudicated it: a
    text predicate that overrode them would make the decision ornamental, which is the D2 failure.

    ## A classification decision is a membership decision

    `is_poliovirus` is not the only ledger field that settles this. A curator asserting
    `classification=cVDPV` has asserted the record is a poliovirus, because the vocabulary that
    value comes from is poliovirus-specific — there is no non-polio reading of `cVDPV`, `Sabin-like`
    or `nOPV-L`. Not inferring it discarded 259 hard-won calls: their organism names are
    `Enterovirus C` or `Enterovirus coxsackiepol`, which name the polio-*containing* species and so
    are `UNINFORMATIVE_ORGANISMS`, and the earlier order declined the partition and then declined
    `poliovirus_classification` for "following" it — throwing away the paper-based judgement on the
    grounds that a weaker signal was silent.

    Those 259 are the substance of it: 187 `cVDPV`, 28 `nOPV-L`, 17 `wild`, 11 `cVDPV-n`, 7 `Sabin`,
    5 `engineered/lab`, 2 `Sabin-like`, 2 `VDPV-n`, each carrying a PMID or an adjudication document
    in `evidence_reference`. The release ships all 259 as `poliovirus`/`vouched`, so this recovers
    three columns at once and moves all three *toward* parity.

    Falsified before it was relied on: of the 2,047 accessions carrying an active classification
    decision, the release ships **2,047** as `virus_group=poliovirus` and none otherwise, and no
    accession carries both a classification decision and `is_poliovirus=FALSE`. The entailment is
    read off the field name rather than the value, so a malformed value cannot smuggle in a
    membership claim the vocabulary would have rejected — `is_poliovirus` still outranks it, and
    R-CLASS-2 still refuses to *emit* a value outside its controlled list.
    """
    asserted = view.decisions.get(LEDGER_MEMBERSHIP_FIELD)
    if asserted:
        # Refuse anything outside the vocabulary rather than falling through. The ledger schema
        # constrains `new_value` only to `minLength: 1`, so `True` in Python casing validates; the
        # earlier code then ignored the decision, re-declined the record, and put it back in the
        # curation queue with no error anywhere. A decision that cannot be read is a build failure.
        if asserted not in LEDGER_MEMBERSHIP_VALUES:
            raise ValueError(
                f"{view.version}: {LEDGER_MEMBERSHIP_FIELD}={asserted!r} is not one of "
                f"{sorted(LEDGER_MEMBERSHIP_VALUES)}"
            )
        return (POLIOVIRUS if asserted == "TRUE" else NON_POLIO_ENTEROVIRUS), True, None

    # `False`, not `True`, and the parity gate is what established that. Returning `True` marked
    # `manual_override` on all 2,046 records carrying a classification decision, against a shipped
    # `FALSE` on every one of them — 2,046 disagreements for a column the release says no human
    # touched. It is right: membership here is *entailed* by the decision, not *stated* by it. The
    # curator adjudicated the classification; nobody adjudicated the partition. This is the same
    # distinction `curation_status` already draws for the vouching policy that follows from
    # membership. `is_poliovirus` above still reports `True`, because that decision does state it.
    if any(view.decisions.get(field) for field in LEDGER_CLASSIFICATION_FIELDS):
        return POLIOVIRUS, False, None

    organism = view.record.get("organism_name", "")
    if any(fragment in organism.lower() for fragment in POLIO_NAME_FRAGMENTS):
        return POLIOVIRUS, False, None
    if organism in UNINFORMATIVE_ORGANISMS:
        # The name cannot decide it, but R-MEMBERSHIP-AA-1's capsid band might: see
        # `derive.evidence.measure_poliovirus_membership_band`. Absent (no compared codons, or the
        # 8-15% band neither side of the threshold reaches) leaves this exactly the prior "", False.
        band = view.membership_evidence.get(MEMBERSHIP_BAND_KEY, "")
        if band:
            return band, False, view.membership_evidence
        return "", False, None
    return NON_POLIO_ENTEROVIRUS, False, None


def resolved_partition(view: RecordView) -> str:
    """The partition, or `""` when nothing determines it — for rules that are scoped by it.

    Public because the epi rules are partition-scoped: `sample_origin` is curated for poliovirus and
    out of scope elsewhere, and a record whose membership is undecided cannot be scoped either way.
    """
    partition, _, _ = _membership(view)
    return partition


@rule_implementation(
    "derive.partition.virus_group",
    parameters=("groups",),
    evidence_bases=(BASIS_PARTITION, BASIS_MEMBERSHIP_AA),
)
def virus_group(parameters: Mapping[str, Any], view: RecordView) -> RuleOutcome:
    partition, from_decision, membership_evidence = _membership(view)
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
    if membership_evidence:
        distance = membership_evidence[MEMBERSHIP_BAND_DISTANCE_KEY]
        codons = membership_evidence[MEMBERSHIP_BAND_CODONS_KEY]
        serotype = membership_evidence[MEMBERSHIP_BAND_SEROTYPE_KEY]
        reference = membership_evidence[MEMBERSHIP_BAND_REFERENCE_KEY]
        return RuleOutcome(
            value=partition,
            evidence_basis=BASIS_MEMBERSHIP_AA,
            source_field=MEMBERSHIP_BAND_DISTANCE_KEY,
            source_value=f"{distance}% over {codons} capsid codons vs {serotype} ({reference})",
        )
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
    partition, _, _ = _membership(view)
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
