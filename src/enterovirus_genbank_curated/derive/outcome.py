"""What a rule returns, and the per-record inputs it is given.

Every rule returns a `RuleOutcome` rather than a bare value. Three properties then hold structurally
instead of by discipline:

* **Provenance is not optional.** `export/audit.py` writes the projection-provenance table directly
  from the outcomes, so a canonical value without a provenance row is not expressible — which is
  `docs/pipeline.md` boundary 5.
* **The branch label is checkable.** `evidence_basis` names which way the rule went, and
  `derive/apply.py` refuses a basis the rule did not declare, so an undeclared branch fails closed.
* **"I could not decide" is representable.** This is the one that matters most. A rule that can only
  return a value will return its best guess, and a best guess scores well against the oracle while
  being a fabrication. `unresolved_reason` is how a rule declines, and a table containing any
  unresolved cell must not be written under a release filename.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

NO_EVIDENCE: Mapping[str, str] = MappingProxyType({})

# The keys of a `RecordView.membership_evidence` mapping. Declared here, not in `derive/evidence.py`
# where they are produced or `derive/partition.py` where they are consumed, because those two
# modules otherwise import each other: `evidence.py` needs `partition.py`'s
# `UNINFORMATIVE_ORGANISMS` to know which records to measure, and `partition.py` needs
# `evidence.py`'s keys to read the result. Both already import this module for `RecordView` itself,
# so the keys live where the cycle cannot form.
MEMBERSHIP_BAND_KEY = "membership_band"
MEMBERSHIP_BAND_SEROTYPE_KEY = "reference_serotype"
MEMBERSHIP_BAND_REFERENCE_KEY = "reference_version"
MEMBERSHIP_BAND_DISTANCE_KEY = "capsid_aa_distance_pct"
MEMBERSHIP_BAND_CODONS_KEY = "compared_codons"


@dataclass(frozen=True)
class RecordView:
    """One record's declared inputs, as the rules see them.

    `qualifiers` holds the first value of each qualifier on the record's `source` feature — the same
    "first source feature that carries it wins" rule the transport uses, which matters because five
    records in the corpus have two `source` features.

    `byte_identical` holds every *source* record sharing this record's `sequence_sha256`, itself
    included, carved or not. A rule needs it when the property it decides belongs to the genotype
    rather than to the deposit: `organism_name` is depositor metadata, and the same 70 nt deposited
    in two patents carries `synthetic construct` in one and `Enterovirus C` in the other, so a rule
    reading only its own row assigns two different answers to one sequence.

    `evidence` holds whatever the sequence stage measured for this record — VP1 divergence from the
    matching Sabin reference, and how many nucleotides that was measured over. It is a mapping of
    strings rather than a typed object because it is written straight into a provenance
    `source_value`, and a rule that reads a number it cannot cite is a rule whose answer cannot be
    checked.

    `reference_titles` holds every GenBank `REFERENCE` block title on the record, concatenated — the
    cited paper's own title, not the deposit's own fields. It is a study-level statement rather than
    a depositor's record-level one, which is why no other rule reads it: only the
    text-classification fallback does, and only for a record with no sequence signal of its own to
    ask instead.

    `membership_evidence` holds `derive.evidence.measure_poliovirus_membership_band`'s result for a
    record whose organism name is one of `derive.partition.UNINFORMATIVE_ORGANISMS` — the capsid
    amino-acid distance to the nearest poliovirus reference, banded into `poliovirus` or
    `non_polio_enterovirus`, or absent if neither band was reached. Only
    `derive.partition.virus_group` reads it, and only when the organism name itself could not decide
    membership.
    """

    version: str
    accession: str
    record: Mapping[str, str]
    qualifiers: Mapping[str, str]
    decisions: Mapping[str, str]
    byte_identical: tuple[Mapping[str, str], ...] = ()
    evidence: Mapping[str, str] = NO_EVIDENCE
    reference_titles: str = ""
    membership_evidence: Mapping[str, str] = NO_EVIDENCE

    def qualifier(self, name: str) -> str:
        return self.qualifiers.get(name, "")


@dataclass(frozen=True)
class RuleOutcome:
    value: str
    evidence_basis: str
    source_field: str
    source_value: str
    unresolved_reason: str = ""
    # Set by a rule that reached its value through an active ledger decision. The rule knows this,
    # and nothing downstream can infer it, which is why it belongs on the outcome rather than being
    # reconstructed by joining afterwards.
    manual_override: bool = False

    @property
    def resolved(self) -> bool:
        return not self.unresolved_reason

    def __post_init__(self) -> None:
        if self.unresolved_reason and self.value:
            raise ValueError(
                f"an unresolved outcome must not carry a value: {self.value!r} with reason "
                f"{self.unresolved_reason!r}"
            )
