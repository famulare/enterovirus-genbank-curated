"""`sequence_scope` — which part of the genome a deposit covers.

This was the last unwritten canonical column, and it was unwritten for the wrong reason.

## What the column is not

`docs/reproducibility.md` recorded it as blocked: the sequence stage exists, it builds the Sabin
1/2/3 reference frame from the archive's own `mat_peptide` features, and coverage geometry against
Sabin VP1 *does not reproduce the shipped column*. Fitted against every threshold combination it
agreed on 86.7% of poliovirus records, and the 13.3% were systematic rather than boundary errors —
745 records the release calls `other_fragment` have a complete VP1, capsid or genome. The
conclusion drawn was that the determinant was unknown, and a rule fitted to 86.7% would assert a
wrong determination on some thirteen hundred records.

The measurement was right and the conclusion was wrong. `sequence_scope` is not a function of
coverage at all, so no threshold on coverage was ever going to find it.

## What it is

A seven-branch precedence over the record's **annotation and its own text**, plus three length
floors. The frozen upstream stage computed it as `record_type` and the release writer mapped that
onto the shipped vocabulary; the mapping is one-to-one and is reproduced in `SCOPE_BY_RECORD_TYPE`
below. Ported here, it reproduces 2.4.1's column on **24,296 of 24,296 rows** — every row the two
releases share. The other 9 of the built carve's 24,305 are not in 2.4.1 at all, so there is nothing
to reproduce for them; a claim over 24,301 would be a claim over a population that does not exist on
both sides.

That also explains the 745 that looked like errors. `other_fragment` is where the final `else`
lands, and the `else` is reached by a record whose annotations and definition name no region at
all — regardless of how much sequence it has. A 7,000 nt deposit annotated only with `source` is
`other_fragment`, correctly, because the column describes what the deposit *says it is*. Reading it
as a completeness measure is what made those records look like a defect in the shipped data.

## Two inputs that are the stage's own, not the canonical columns

The cascade needs to know whether a record is poliovirus and which serotype. Both come from the
frozen stage's own text inference rather than from canonical `virus_group` / `virus_type`, and the
difference is measurable:

* using canonical `virus_type` for the serotype costs 308 rows, because the VP1 length floor is
  serotype-specific (906/903/900) and the curated type is not always what the deposit's text says;
* the *partition gate*, though, is the canonical `virus_group` — R-SCOPE-1 scoped on
  `dataset_partition`, and three records differ between the two.

So the gate is curated and everything inside it is textual. Getting that split backwards is worth
exactly those 311 rows, and it was measured rather than reasoned.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

from enterovirus_genbank_curated.derive.outcome import RecordView, RuleOutcome
from enterovirus_genbank_curated.derive.partition import POLIOVIRUS, resolved_partition
from enterovirus_genbank_curated.registry.rules import rule_implementation

DEFINITION_FIELD = "definition"
ORGANISM_FIELD = "organism_name"
LENGTH_FIELD = "sequence_length_nt"

# The upstream `record_type` vocabulary mapped onto the shipped `sequence_scope` one. Both
# `non_VP1_region` and `other` map to `other_fragment`: the distinction was internal to the stage
# that produced it and never reached a canonical value.
SCOPE_BY_RECORD_TYPE = {
    "whole_genome": "complete_genome",
    "P1": "capsid",
    "VP1_complete": "vp1_complete",
    "VP1_partial": "vp1_partial",
    "non_VP1_region": "other_fragment",
    "other": "other_fragment",
}

BASIS_WHOLE_GENOME = "whole_genome_length_or_text"
BASIS_CAPSID = "capsid_precursor_feature_or_text"
BASIS_VP1_COMPLETE = "vp1_feature_at_canonical_length"
BASIS_VP1_PARTIAL = "vp1_named_below_canonical_length"
BASIS_NON_VP1 = "named_non_capsid_region"
BASIS_NO_REGION_NAMED = "no_region_named"
BASIS_OUTSIDE_POLIOVIRUS = "not_determined_outside_poliovirus"

UNRESOLVED_FOLLOWS_PARTITION = "follows_an_undecided_virus_group"

VP1_LABEL = r"(^|[^A-Z0-9])VP[- ]?1([^A-Z0-9]|$)"
VP1_TEXT = r"\bVP[- ]?1\b"
P1_LABELS = (
    r"(^|[^A-Z0-9])P1([^A-Z0-9]|$)",
    r"capsid precursor",
    r"capsid protein precursor",
)
P1_TEXT = (r"\bP1\b", r"capsid precursor", r"whole capsid", r"complete capsid")
POLYPROTEIN_LABEL = "polyprotein"
POLYPROTEIN_TEXT = (r"polyprotein", r"complete coding sequence", r"complete cds")
WHOLE_GENOME_TEXT = (r"complete genome", r"whole genome")
NON_VP1_TEXT = (
    r"5[' ]?utr", r"5[' ]?ncr", r"3d", r"polymerase",
    r"2a", r"2b", r"2c", r"3a", r"3b", r"3c", r"3[' ]?ncr",
)

# The stage's own poliovirus test, in its own order: two exclusions first, then three ways in.
NOT_POLIOVIRUS = (r"poliovirus receptor", r"\bcd155\b", r"\bpvr\b", r"pvr-related")
NOT_POLIOVIRUS_SYNTHETIC = (r"synthetic .*anti-?poliovirus", r"anti-?polio virus antibod")
POLIOVIRUS_ORGANISM = r"(^|\b)(human )?poliovirus( |-|$)"
POLIOVIRUS_CORROBORATION = (r"\bvp1\b", r"\bpolyprotein\b", r"\bcapsid\b", r"\bcomplete genome\b")

# Deliberately *not* shared with `derive/typing.py`'s `_SEROTYPE`, which looks almost identical and
# is not the same rule. The two are ports of two different frozen upstream stages, and each column
# is pinned cell-for-cell against 2.4.1's own value for it, so merging them would move one of the
# two columns to match the other's regex. The visible differences are real: this one accepts
# `\s*` where typing requires `\s+`, and typing carries a `(?![0-9])` guard this one does not need
# because `\b` already ends the group. If they ever should be one function, that is a measured
# change to both columns, not a tidy-up.
SEROTYPE_PATTERNS = (
    r"\bpoliovirus\s*(?:type\s*)?([123])\b",
    r"\bpolio\s*virus\s*(?:type\s*)?([123])\b",
    r"\btype\s*([123])\s+(?:poliovirus|oral poliovirus|sabin)",
    r"\bPV\s*-?\s*([123])\b",
    r"\bOPV\s*-?\s*([123])\b",
    r"\bSabin\s*([123])\b",
)
# Named strains that fix a serotype without stating a digit. Leon is type 3, Mahoney and Brunhilde
# type 1, MEF-1 and Lansing type 2, Saukett type 3.
SEROTYPE_BY_STRAIN = (
    (r"\bLeon\s*37\b", "3"),
    (r"\bMahoney\b", "1"),
    (r"\bBrunhilde\b", "1"),
    (r"\bMEF-?1\b", "2"),
    (r"\bLansing\b", "2"),
    (r"\bSaukett\b", "3"),
)
SEROTYPE_FIELDS = ("serotype", "strain", "isolate", "note")
UNKNOWN_SEROTYPE = "unknown"


def _matches(text: str, patterns: Iterable[str]) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def _is_poliovirus_by_text(view: RecordView) -> bool:
    """The frozen stage's own inference, reproduced in its own precedence."""
    source_text = " ".join(view.qualifiers.values())
    feature_text = " ".join(feature["label"] for feature in view.features[:20])
    blob = " ".join(
        (
            view.record.get(ORGANISM_FIELD, ""),
            view.record.get(DEFINITION_FIELD, ""),
            source_text,
            feature_text,
        )
    ).lower()
    if _matches(blob, NOT_POLIOVIRUS) or _matches(blob, NOT_POLIOVIRUS_SYNTHETIC):
        return False
    organism = view.record.get(ORGANISM_FIELD, "").lower()
    if re.search(POLIOVIRUS_ORGANISM, organism) or "unidentified poliovirus" in organism:
        return True
    if re.search(r"\bpoliovirus [123]\b", blob):
        return True
    return bool(re.search(r"\bpoliovirus\b", blob)) and _matches(blob, POLIOVIRUS_CORROBORATION)


def _serotype_by_text(view: RecordView) -> str:
    blob = " ".join(
        (
            view.record.get(ORGANISM_FIELD, ""),
            view.record.get(DEFINITION_FIELD, ""),
            *(view.qualifier(field) for field in SEROTYPE_FIELDS),
        )
    )
    for pattern in SEROTYPE_PATTERNS:
        found = re.search(pattern, blob, flags=re.IGNORECASE)
        if found:
            return found.group(1)
    for pattern, serotype in SEROTYPE_BY_STRAIN:
        if re.search(pattern, blob, flags=re.IGNORECASE):
            return serotype
    return UNKNOWN_SEROTYPE


@rule_implementation(
    "derive.scope.sequence_scope_v2",
    parameters=(
        "whole_genome_nt",
        "capsid_nt",
        "polyprotein_nt",
        "vp1_nt_by_serotype",
        "non_poliovirus_scope",
    ),
    evidence_bases=(
        BASIS_WHOLE_GENOME,
        BASIS_CAPSID,
        BASIS_VP1_COMPLETE,
        BASIS_VP1_PARTIAL,
        BASIS_NON_VP1,
        BASIS_NO_REGION_NAMED,
        BASIS_OUTSIDE_POLIOVIRUS,
    ),
)
def sequence_scope(parameters: Mapping[str, Any], view: RecordView) -> RuleOutcome:
    """The scope cascade, gated on the curated partition."""
    partition = resolved_partition(view)
    if not partition:
        return RuleOutcome(
            value="",
            evidence_basis="",
            source_field=DEFINITION_FIELD,
            source_value="",
            unresolved_reason=UNRESOLVED_FOLLOWS_PARTITION,
        )
    if partition != POLIOVIRUS:
        # Not a decline. `record_type` is derived against Sabin coordinates, so no scope
        # determination exists outside poliovirus and `unknown` is the determined value saying so —
        # which is what the release ships on every one of these rows.
        return RuleOutcome(
            value=parameters["non_poliovirus_scope"],
            evidence_basis=BASIS_OUTSIDE_POLIOVIRUS,
            source_field="virus_group",
            source_value=partition,
        )

    definition = view.record.get(DEFINITION_FIELD, "")
    blob = " ".join([definition, *(feature["text"] for feature in view.features)]).lower()
    length = int(view.record.get(LENGTH_FIELD, "0") or 0)

    if not _is_poliovirus_by_text(view):
        # The stage never ran its cascade on a record its own text did not identify, so the record
        # took `record_type = "other"` by default. Reproduced rather than improved: this is the
        # single largest source of `other_fragment`, and 308 rows depend on it.
        return RuleOutcome(
            value=SCOPE_BY_RECORD_TYPE["other"],
            evidence_basis=BASIS_NO_REGION_NAMED,
            source_field=ORGANISM_FIELD,
            source_value=view.record.get(ORGANISM_FIELD, ""),
        )

    serotype = _serotype_by_text(view)
    by_serotype = parameters["vp1_nt_by_serotype"]
    vp1_nt = int(by_serotype.get(serotype, by_serotype[UNKNOWN_SEROTYPE]))
    vp1 = [f for f in view.features if re.search(VP1_LABEL, f["label"], flags=re.IGNORECASE)]
    capsid = [f for f in view.features if _matches(f["label"], P1_LABELS)]
    polyprotein = [f for f in view.features if POLYPROTEIN_LABEL in f["label"].lower()]

    whole_genome_nt = int(parameters["whole_genome_nt"])
    capsid_nt = int(parameters["capsid_nt"])
    polyprotein_nt = int(parameters["polyprotein_nt"])

    if length >= whole_genome_nt or _matches(blob, WHOLE_GENOME_TEXT):
        record_type, basis, source = "whole_genome", BASIS_WHOLE_GENOME, definition
    elif any(int(f["length"]) >= capsid_nt for f in capsid) or (
        length >= capsid_nt and _matches(blob, P1_TEXT)
    ):
        record_type, basis, source = "P1", BASIS_CAPSID, definition
    elif any(int(f["length"]) >= polyprotein_nt for f in polyprotein) or (
        length >= polyprotein_nt and _matches(blob, POLYPROTEIN_TEXT)
    ):
        # The upstream stage resolved this branch by length, not by the feature: a polyprotein is
        # a genome if the record is genome-length and the capsid otherwise. Here it can only ever
        # be the capsid, because reaching this `elif` entails `length < whole_genome_nt` — the
        # branch above tests exactly that. The port's two-way form is not reproduced, since a
        # conditional whose other arm is unreachable reads as a live case and is not one.
        record_type, basis, source = "P1", BASIS_CAPSID, definition
    elif any(int(f["length"]) >= vp1_nt for f in vp1):
        record_type, basis, source = "VP1_complete", BASIS_VP1_COMPLETE, definition
    elif vp1 or re.search(VP1_TEXT, blob, flags=re.IGNORECASE):
        longest = max([int(f["length"]) for f in vp1] + [length])
        record_type = "VP1_partial" if longest < vp1_nt else "other"
        basis = BASIS_VP1_PARTIAL if record_type == "VP1_partial" else BASIS_NO_REGION_NAMED
        source = definition
    elif _matches(blob, NON_VP1_TEXT):
        record_type, basis, source = "non_VP1_region", BASIS_NON_VP1, definition
    else:
        record_type, basis, source = "other", BASIS_NO_REGION_NAMED, definition

    return RuleOutcome(
        value=SCOPE_BY_RECORD_TYPE[record_type],
        evidence_basis=basis,
        source_field=DEFINITION_FIELD,
        source_value=source,
    )
