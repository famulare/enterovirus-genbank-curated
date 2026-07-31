"""`virus_type` — the enterovirus type, read out of the organism name.

The shipped `R-TYPE-1` projects a curated `enterovirus_type` or `serotype` and records
`name_derived` as the basis for 12,792 of its rows. That basis is the whole method, and it is
recoverable: the NCBI organism name a depositor chose *is* the type, in a naming convention regular
enough to parse.

Measured over the shipped release: of the 223 distinct organism names on `name_derived` rows, **220
map to exactly one type**. The three that do not are `Enterovirus A`, `Enterovirus B` and
`Enterovirus C` — bare species names, which carry no type at all and were typed upstream from the
sequence. So the name determines the type wherever the name states one, and states nothing where it
does not. That is the cleanest split in this whole rewrite.

## The convention, and the four traps in it

| organism name | type |
|---|---|
| `Coxsackievirus A24`, `Human coxsackievirus A21 Coe` | `CVA24`, `CVA21` |
| `Echovirus E11` | `E11` |
| `Enterovirus A71`, `enterovirus D68` | `EV-A71`, `EV-D68` |
| `rhinovirus C40` | `RV-C40` |
| `Poliovirus 1`, `Human poliovirus 2 strain Sabin` | `PV1`, `PV2` |

Case is not meaningful — `Enterovirus D68` and `enterovirus D68` both occur. Everything after the
type number is not part of the type: `Human coxsackievirus A20a` is `CVA20`, `rhinovirus A1B` is
`RV-A1`, `Human coxsackievirus A24v Marseille/2012/1` is `CVA24`.

Four things this must not do, each of them a real name in the corpus:

1. **`Human poliovirus 30/ROU/2008` is PV2, not PV3.** The `30` is an isolate number. So the
   serotype digit is anchored: one character from `123` with no digit after it. Getting this wrong
   would silently mistype records under a rule that looked right.
2. **`Enterovirus 6`, `Enterovirus 19`, `Enterovirus 103` carry no type.** A bare number with no
   species letter is the pre-2016 numbering, and the release leaves all of them blank. The pattern
   requires the species letter, so they do not match.
3. **`Enterovirus J115` and `Simian enterovirus SV46` carry no type in this vocabulary.** `J` is a
   simian species; the human typing scheme runs `A`–`D`. Restricting the species letter to `A`–`D`
   is what excludes them, and the release agrees — blank on all 17 `J115` records.
4. **`Human rhinovirus 1A` is not `RV-A1`.** Digits-then-letter is the old serial numbering, not the
   species-and-number form. The pattern requires letter-then-digits, so it does not match, and again
   the release ships blank.

## Where it declines, and why that is not the release's blank

A name that states no type is a decline, not a blank. The distinction matters because the release's
blanks are two different things: `Enterovirus C` on 685 records really is "the name does not say,
and nothing else was consulted", while the release *did* type 548 other `Enterovirus C` records from
their sequence. Sequence typing is a stage this clone does not have, so the honest output for a
species-level name is an unresolved cell with the reason attached, and the record joins the curation
queue grouped by the organism name that failed to decide it.

Three named consequences of declining rather than guessing:

* `Enterovirus coxsackiepol` — 82 records the release types `PV2`. The name is a chimera label with
  no serotype in it. A rule that read `pol` and emitted `PV2` would be pattern-matching a single
  string, so this declines.
* `synthetic construct`, `unidentified`, `unidentified poliovirus` — the release types a handful of
  these from sequence. The name cannot.
* `Human poliovirus sp.` — the release ships blank here too, and for the same reason the rule
  declines: nothing states which serotype.

## The ledger's typing fields, and their vocabulary

Three fields reach this column, and they do not speak in canonical values. `serotype` and
`confirmed_serotype` hold a bare `1`, `2`, `3` or `unknown`; `corrected_type` holds an
organism-style name (`Coxsackievirus A18`) or the non-answer `non-polio enterovirus`. So a decision
is normalized through the same parser as a deposited name rather than written straight into the
column, and a curator's `unknown` declines — it is a recorded determination that the type is
undetermined, which is exactly what an unresolved cell means.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from enterovirus_genbank_curated.derive.outcome import RecordView, RuleOutcome
from enterovirus_genbank_curated.registry.rules import rule_implementation

ORGANISM_FIELD = "organism_name"

LEDGER_CORRECTED_TYPE = "corrected_type"
LEDGER_CONFIRMED_SEROTYPE = "confirmed_serotype"
LEDGER_SEROTYPE = "serotype"
# Most specific first: an explicit correction outranks a confirmation, which outranks the original.
LEDGER_TYPE_FIELDS = (LEDGER_CORRECTED_TYPE, LEDGER_CONFIRMED_SEROTYPE, LEDGER_SEROTYPE)
LEDGER_UNKNOWN = "unknown"

BASIS_LEDGER = "curated_type"
BASIS_SEROTYPE_NAME = "poliovirus_serotype_in_organism_name"
BASIS_TYPE_NAME = "enterovirus_type_in_organism_name"

UNRESOLVED_NO_TYPE_IN_NAME = "organism_name_states_no_type"
UNRESOLVED_CURATED_UNKNOWN = "curated_type_is_unknown"

# `(?![0-9])` is load-bearing: `Human poliovirus 30/ROU/2008` is PV2, and the 30 is an isolate.
_SEROTYPE = re.compile(r"\bpoliovirus\s+(?:type\s+)?([123])(?![0-9])")
# Species letter then number, in that order. `A1B` yields A1; `1A` matches nothing.
_COXSACKIE = re.compile(r"\bcoxsackievirus\s+([ab])\s*([0-9]+)")
_ECHO = re.compile(r"\bechovirus\s+e?\s*([0-9]+)")
_ENTERO = re.compile(r"\benterovirus\s+([a-d])\s*([0-9]+)")
_RHINO = re.compile(r"\brhinovirus\s+([a-c])\s*([0-9]+)")


def serotype_from_name(name: str) -> str:
    """`PV1`/`PV2`/`PV3` if the name states a poliovirus serotype, else empty."""
    match = _SEROTYPE.search(name.lower())
    return f"PV{match.group(1)}" if match else ""


def type_from_name(name: str) -> str:
    """The canonical enterovirus type the organism name states, or empty if it states none.

    Ordered most-specific-first so that a name carrying both a genus and a species letter is read as
    the genus form the vocabulary uses — `Coxsackievirus A24` is `CVA24`, never `EV-A24`.
    """
    text = name.lower()
    if serotype := serotype_from_name(text):
        return serotype
    if match := _COXSACKIE.search(text):
        return f"CV{match.group(1).upper()}{match.group(2)}"
    if match := _ECHO.search(text):
        return f"E{match.group(1)}"
    if match := _ENTERO.search(text):
        return f"EV-{match.group(1).upper()}{match.group(2)}"
    if match := _RHINO.search(text):
        return f"RV-{match.group(1).upper()}{match.group(2)}"
    return ""


def _curated_type(view: RecordView) -> tuple[str, str, str]:
    """The ledger's answer as (field, raw value, canonical type). Canonical is empty if unusable."""
    for field in LEDGER_TYPE_FIELDS:
        asserted = view.decisions.get(field, "")
        if not asserted:
            continue
        if asserted in {"1", "2", "3"}:
            return field, asserted, f"PV{asserted}"
        return field, asserted, type_from_name(asserted)
    return "", "", ""


@rule_implementation(
    "derive.typing.virus_type",
    parameters=(),
    evidence_bases=(BASIS_LEDGER, BASIS_SEROTYPE_NAME, BASIS_TYPE_NAME),
)
def virus_type(parameters: Mapping[str, Any], view: RecordView) -> RuleOutcome:
    """A curated type first, then the type the organism name states, else decline."""
    del parameters

    field, raw, curated = _curated_type(view)
    if field:
        if not curated:
            return RuleOutcome(
                value="",
                evidence_basis=BASIS_LEDGER,
                source_field=field,
                source_value=raw,
                unresolved_reason=UNRESOLVED_CURATED_UNKNOWN,
                manual_override=True,
            )
        return RuleOutcome(
            value=curated,
            evidence_basis=BASIS_LEDGER,
            source_field=field,
            source_value=raw,
            manual_override=True,
        )

    organism = view.record.get(ORGANISM_FIELD, "")
    serotype = serotype_from_name(organism)
    derived = serotype or type_from_name(organism)
    if not derived:
        return RuleOutcome(
            value="",
            evidence_basis=BASIS_TYPE_NAME,
            source_field=ORGANISM_FIELD,
            source_value=organism,
            unresolved_reason=UNRESOLVED_NO_TYPE_IN_NAME,
        )
    return RuleOutcome(
        value=derived,
        evidence_basis=BASIS_SEROTYPE_NAME if serotype else BASIS_TYPE_NAME,
        source_field=ORGANISM_FIELD,
        source_value=organism,
    )
