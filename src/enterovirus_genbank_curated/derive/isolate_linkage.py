"""Isolate-linked classification inference — MAD-VDPV's own `isolate_linked_inference`.

A whole-corpus pass, not a per-record rule. `derive.classification.poliovirus_classification`
sees one `RecordView` at a time and structurally cannot know what a sibling accession's own
classification resolved to. This runs once, after every `poliovirus_classification` row has
already been projected, and answers the one question a per-record rule cannot: does the record
group sharing this record's own stated isolate name already have an answer?

## Why this recovers only the residual, not a competing answer

GenBank frequently splits one physical sample's gene regions across separate accessions from the
same study — a non-capsid fragment deposited separately from the capsid-covered one. A record with
no divergence measurement and no text label to fall back to (`UNRESOLVED_INSUFFICIENT_SEQUENCE`
after both branches of the rule above have already tried and failed) may still have a sibling
accession naming the same isolate that did clear a measurement. This pass looks for exactly that,
scoped to records already declined by both — it never reconsiders a record either branch already
answered, ledger decision included (an active decision resolves before either branch even runs).

## The key, and why a short one needs corroboration

`isolate` (the depositor's own qualifier) if present, else `strain` — the same "the record states
this itself" standard `classification._record_text` already holds text to, read directly rather
than mined from `definition` text: GenBank's own `P05`/`P05 (2)` clone convention survives a
structured qualifier read and does not survive a length-floor regex over free text. A key three
alphanumeric characters or shorter (`L1`, `P05`, `V14`) recurs across unrelated studies by chance,
so it is only honoured across accessions in the same deposit batch — same alphabetic prefix, same
digit width, within 200 accession numbers of this one, MAD-VDPV's own same-batch heuristic — never
as a bare match on a short string alone.

## What counts as a sibling with an answer

Only a sibling whose own `poliovirus_classification` came from a real divergence measurement
(`BASIS_SABIN_LIKE`, `BASIS_VDPV`, `BASIS_WILD`, or a text refinement read over one of those bands,
`BASIS_TEXT_REFINEMENT`) counts — not a ledger decision, and not the reference-title text fallback.
Both of those are themselves already a step removed from a measurement, and propagating a decision
or a guess onto a second record would compound whichever one is wrong rather than carry forward an
actual measurement, which is the one thing this mechanism exists to do.

Applied only when every qualifying sibling in the group agrees on a single label; disagreement
declines rather than guessing which one is right, the same as the group it is a fallback for.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

from enterovirus_genbank_curated.derive.classification import (
    BASIS_SABIN_LIKE,
    BASIS_TEXT_REFINEMENT,
    BASIS_VDPV,
    BASIS_WILD,
    ISOLATE_QUALIFIER,
    ORGANISM_FIELD,
    STRAIN_QUALIFIER,
    UNRESOLVED_INSUFFICIENT_SEQUENCE,
)
from enterovirus_genbank_curated.derive.outcome import RecordView
from enterovirus_genbank_curated.derive.partition import POLIOVIRUS, resolved_partition
from enterovirus_genbank_curated.derive.typing import serotype_from_name

CLASSIFICATION_FIELD = "poliovirus_classification"
LINKED_BASIS = "isolate_linked_inference"

# Measured, not guessed: propagating either of these to a second record would compound whichever
# one is wrong rather than carry forward an actual measurement. See the module docstring.
FIRM_BASES = frozenset({BASIS_SABIN_LIKE, BASIS_VDPV, BASIS_WILD, BASIS_TEXT_REFINEMENT})

# MAD-VDPV's own floor: a key this short recurs across unrelated studies by chance, so it is not
# corroboration on its own.
SHORT_KEY_MAX_ALNUM = 3
# MAD-VDPV's own same-batch window: two deposits from the same study land within this many
# accession numbers of each other, sharing a prefix and digit width.
BATCH_ACCESSION_WINDOW = 200
_ACCESSION_SHAPE = re.compile(r"^([A-Za-z]+)(\d+)$")


def _isolate_key(view: RecordView) -> str:
    return view.qualifier(ISOLATE_QUALIFIER).strip() or view.qualifier(STRAIN_QUALIFIER).strip()


def _accession_shape(accession: str) -> tuple[str, int, int] | None:
    match = _ACCESSION_SHAPE.match(accession)
    if not match:
        return None
    prefix, digits = match.groups()
    return prefix, int(digits), len(digits)


def _same_batch(accession: str, sibling_accessions: Sequence[str]) -> bool:
    shape = _accession_shape(accession)
    if shape is None:
        return False
    prefix, number, width = shape
    for sibling in sibling_accessions:
        sibling_shape = _accession_shape(sibling)
        if (
            sibling_shape is not None
            and sibling_shape[0] == prefix
            and sibling_shape[2] == width
            and abs(sibling_shape[1] - number) <= BATCH_ACCESSION_WINDOW
        ):
            return True
    return False


def apply_isolate_linked_inference(
    views: Sequence[RecordView], provenance: Sequence[Mapping[str, str]]
) -> list[dict[str, str]]:
    """The `poliovirus_classification` provenance, with every isolate-linkable decline resolved.

    Returns a new list the same length and order as `provenance`; every row not eligible for
    linkage — every canonical field but `poliovirus_classification`, and every classification row
    that is not declined for `UNRESOLVED_INSUFFICIENT_SEQUENCE` — passes through unchanged.
    """
    view_by_version = {view.version: view for view in views}
    classification_by_version = {
        row["version"]: row for row in provenance if row["canonical_field"] == CLASSIFICATION_FIELD
    }

    # Grouped over every poliovirus-partition record, not just the declined ones: a sibling with
    # the answer is as likely to sit outside today's candidate set as inside it.
    groups: dict[tuple[str, str], list[str]] = {}
    for view in views:
        if resolved_partition(view) != POLIOVIRUS:
            continue
        key = _isolate_key(view)
        if not key:
            continue
        serotype = serotype_from_name(view.record.get(ORGANISM_FIELD, ""))
        groups.setdefault((key, serotype), []).append(view.version)

    linked: dict[str, dict[str, str]] = {}
    for version, row in classification_by_version.items():
        if row.get("unresolved_reason") != UNRESOLVED_INSUFFICIENT_SEQUENCE:
            continue
        view = view_by_version[version]
        key = _isolate_key(view)
        if not key:
            continue
        serotype = serotype_from_name(view.record.get(ORGANISM_FIELD, ""))
        sibling_versions = [v for v in groups.get((key, serotype), ()) if v != version]
        firm = [
            (v, classification_by_version[v]["final_value"])
            for v in sibling_versions
            # `BASIS_SABIN_LIKE` is also the basis two *decline* branches of the rule above use
            # (no serotype; no divergence measurement) — checking the basis name alone would count
            # a declined sibling as an answer. `unresolved_reason` empty is what actually means
            # "this sibling has a value", the same distinction `RuleOutcome.resolved` makes.
            if classification_by_version[v]["evidence_basis"] in FIRM_BASES
            and not classification_by_version[v]["unresolved_reason"]
        ]
        labels = {value for _, value in firm}
        if len(labels) != 1:
            continue
        proposed = next(iter(labels))
        agreeing_versions = sorted(v for v, value in firm if value == proposed)
        alnum_key = re.sub(r"[^A-Za-z0-9]", "", key)
        if len(alnum_key) <= SHORT_KEY_MAX_ALNUM and not _same_batch(
            view.accession, [view_by_version[v].accession for v in agreeing_versions]
        ):
            continue
        source_field = ISOLATE_QUALIFIER if view.qualifier(ISOLATE_QUALIFIER).strip() else STRAIN_QUALIFIER
        linked[version] = {
            **row,
            "final_value": proposed,
            "source_field": source_field,
            "source_value": ";".join(agreeing_versions),
            "evidence_basis": LINKED_BASIS,
            "unresolved_reason": "",
        }

    return [
        linked[row["version"]]
        if row["canonical_field"] == CLASSIFICATION_FIELD and row["version"] in linked
        else dict(row)
        for row in provenance
    ]
