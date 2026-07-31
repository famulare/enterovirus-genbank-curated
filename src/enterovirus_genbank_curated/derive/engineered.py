"""`engineered_or_construct` — the re-adjudicated rule, not the shipped one.

The shipped `R-CONSTRUCT-1` projects the column straight out of the curated master under
`evidence_basis=canonical_projection`, so the release records no reason for any of its 543 TRUEs.
The reason exists; it is just upstream, and
[`docs/engineered-full-population-readjudication.md`](../../../docs/engineered-full-population-readjudication.md)
took it apart record by record and the curator answered ten questions about it. This module is that
answer in code.

## What the upstream rule actually tested

`engineered_or_construct = bool(construct) and not real_human_capture(row)`, where `construct` was
one case-insensitive regex from a list of 18 hitting anywhere in a blob of **twenty** concatenated
fields — including the database `division` code as free text, the paper titles and the author list.

`\bPAT\b` is in that list, and `division` is in that blob. So **every one of the 862 patent-division
records matched**, and 506 of them are in the carve, and all 506 ship TRUE. The column was
overwhelmingly reporting *where a sequence was deposited*, not what it is. `\bclone\b` matched
ordinary molecular cloning of a PCR product; `\boligo\b` matched a reagent; `\bmutant\b` matched any
paper title containing the word. The `and not real_human_capture(row)` veto fired on any parseable
`/collection_date`, which made the column a function of metadata completeness — a genuinely
synthetic construct that carried a collection date would have been silently FALSE.

## The criterion the curator settled (Q1, 2026-07-29)

> someone deliberately produced this specific genotype for a stated purpose, either by **physical
> assembly** or by **directed selection under an applied selective pressure**.

And explicitly *not* engineered merely because it was patent-deposited, arose spontaneously without
directed selection (a defective-interfering particle is real and worth tagging, not engineered), or
is an ordinary lab-stock or passage-lineage variant.

## The rule, and why it has two stages

Stage 1 is two structured tests instead of eighteen regexes over prose: `division == "SYN"`, and
`organism_name` exactly equal to `synthetic construct` — NCBI's controlled name for taxid 32630. In
the source layer 105 records match `/synthetic/i` on `organism_name` and every one is that exact
string, so an exact match loses nothing and cannot drift onto a paper title.

Stage 2 promotes the signal across byte-identical records, and it is not optional.
`organism_name` is depositor metadata, and the corpus proves it is not consistent across identical
bytes: the same 70 nt is `synthetic construct` in `JA792237` and `Enterovirus C` in `FB743426`; the
same again for `JA792249`/`FB743423`. Stage 1 alone therefore hands two different answers to one
genotype — the same *category* of error as the `\bPAT\b` bug, a value driven by who deposited the
record. Promotion is what makes it a claim about the sequence. Measured: stage 1 alone leaves 7
byte-identical groups disagreeing, stage 1 plus promotion leaves 2, and both residuals are ledger
rows this pass retires.

There is no veto conjunct. With a narrow positive test there is nothing to veto, and
`real_human_capture` stays where it legitimately belongs, in origin inference.

## The one thing this rule declines

`LY501105`/`LZ216100` — the CAVA cold-adaptation patent pair. Same patent family and same stated
directed-selection purpose as `LY501107`/`LZ216102`, which the curator's Q1 answer keeps TRUE, but
with a weaker signature: 11 nt from MEF-1, 10 of the 11 attested in nature. §5.1 and the Appendix B
addendum both record it as **open, not decided in either direction**. A structural FALSE would be
this rule asserting a decision the curator explicitly withheld, so the rule declines and the pair
goes to the curation queue where an undecided cell belongs.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from enterovirus_genbank_curated.derive.outcome import RecordView, RuleOutcome
from enterovirus_genbank_curated.registry.rules import rule_implementation

DIVISION_FIELD = "division"
ORGANISM_FIELD = "organism_name"
DIGEST_FIELD = "sequence_sha256"
LEDGER_ENGINEERED_FIELD = "engineered_or_construct"

TRUE = "TRUE"
FALSE = "FALSE"

BASIS_LEDGER = "curated_adjudication"
BASIS_STRUCTURAL = "synthetic_division_or_organism"
BASIS_STRUCTURAL_GROUP = "synthetic_byte_identical_group"
BASIS_NO_SIGNAL = "no_structural_synthetic_signal"

UNRESOLVED_CURATOR_OPEN = "adjudication_open_directed_selection"

# §5.1 and Appendix B leave exactly this pair undecided. Named rather than inferred, because a rule
# cannot derive "the curator has not ruled on this" from the record.
ADJUDICATION_OPEN = frozenset({"LY501105", "LZ216100"})


def _structural(record: Mapping[str, str]) -> bool:
    return (
        record.get(DIVISION_FIELD, "") == "SYN"
        or record.get(ORGANISM_FIELD, "").strip().lower() == "synthetic construct"
    )


@rule_implementation(
    "derive.engineered.engineered_or_construct",
    parameters=(),
    evidence_bases=(BASIS_LEDGER, BASIS_STRUCTURAL, BASIS_STRUCTURAL_GROUP, BASIS_NO_SIGNAL),
)
def engineered_or_construct(parameters: Mapping[str, Any], view: RecordView) -> RuleOutcome:
    """Curated adjudication first, then the structured signal promoted across identical bytes."""
    del parameters

    asserted = view.decisions.get(LEDGER_ENGINEERED_FIELD)
    if asserted:
        return RuleOutcome(
            value=asserted,
            evidence_basis=BASIS_LEDGER,
            source_field=LEDGER_ENGINEERED_FIELD,
            source_value=asserted,
            manual_override=True,
        )

    if view.accession in ADJUDICATION_OPEN:
        return RuleOutcome(
            value="",
            evidence_basis=BASIS_NO_SIGNAL,
            source_field=DIVISION_FIELD,
            source_value=view.record.get(DIVISION_FIELD, ""),
            unresolved_reason=UNRESOLVED_CURATOR_OPEN,
        )

    if _structural(view.record):
        signal = (
            f"{DIVISION_FIELD}={view.record.get(DIVISION_FIELD, '')}, "
            f"{ORGANISM_FIELD}={view.record.get(ORGANISM_FIELD, '')}"
        )
        return RuleOutcome(
            value=TRUE,
            evidence_basis=BASIS_STRUCTURAL,
            source_field=DIVISION_FIELD,
            source_value=signal,
        )

    twins = [record for record in view.byte_identical if _structural(record)]
    if twins:
        return RuleOutcome(
            value=TRUE,
            evidence_basis=BASIS_STRUCTURAL_GROUP,
            source_field=DIGEST_FIELD,
            source_value=twins[0]["version"],
        )

    return RuleOutcome(
        value=FALSE,
        evidence_basis=BASIS_NO_SIGNAL,
        source_field=DIVISION_FIELD,
        source_value=view.record.get(DIVISION_FIELD, ""),
    )
