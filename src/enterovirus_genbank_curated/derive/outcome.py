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
    """

    version: str
    accession: str
    record: Mapping[str, str]
    qualifiers: Mapping[str, str]
    decisions: Mapping[str, str]
    byte_identical: tuple[Mapping[str, str], ...] = ()

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
