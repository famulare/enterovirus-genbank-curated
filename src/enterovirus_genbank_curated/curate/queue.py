"""Turn declined rows into curation work, grouped by the input the rule could not decide from.

A rule that declines has done its job; the value still has to come from somewhere. This is that
somewhere. Without it, `unresolved_reason` is a note nobody acts on and the honest-declining design
just produces a permanently emptier table than the release.

## Grouped by input, not listed by record

Declined rows collapse into a few hundred groups, because records decline for the *same* reason:
every record whose `/isolation_source` is `conjunctival swab` is one decision, not 462. The queue is
keyed on the input the rule examined, so a curator resolving one group resolves every record in it —
**as long as that input is non-empty**.

The exception is load-bearing and was wrong first time round. The largest group is ~10,000 records
that deposited no `/isolation_source` at all, sharing only the *absence* of an input. One decision
cannot resolve those and no pattern change can either, so a blank input gets its own
`unresolved_reason` and is kept out of `RULE_PARAMETER_REASONS`. Advising a rule change there was
wrong on most of the queue.

`queue_id` is `Q-` plus twelve hex characters of a SHA-256 over `rule_id | canonical_field |
group_key`. Content-derived rather than sequential, so re-running the build does not renumber an
in-flight worksheet — the same ambiguity keeps the same id even as the corpus grows around it.

## Two columns that are not conveniences

`registry_field` is the ledger `field_name` a resolution must be written under, and it is **not**
the canonical column. A curator resolving `sample_origin` has to write `origin_class`; a decision
filed against the canonical name would validate, sit in the ledger, and change nothing. That is the
D2 failure in miniature, and omitting this column would rebuild the conditions for it.

`suggested_resolution_kind` keeps `docs/pipeline.md` boundary 3 operational. A call about one
subject is a `decision` in the ledger. A mapping that would generalize — "`conjunctival swab` always
means this category" — is a `rule_parameter` change with a `rule_version` bump, because encoding it
as 2,000 identical decisions would bury a rule inside curation history. The rule declares which it
expects; the curator can disagree, but has to do so deliberately.

## What this file is not

It is not a diff against the release. Every row here is knowable from `raw/` and `registry/` alone,
at build time, with no `final/` present. The list of places the rewrite *disagrees* with the shipped
values is a different artifact from a different command; mixing them would let the release become a
pipeline input with a human as the transport.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

QUEUE_COLUMNS = (
    "queue_id",
    "canonical_field",
    "registry_field",
    "winning_rule_id",
    "unresolved_reason",
    "group_key",
    "record_count",
    "example_versions",
    "suggested_resolution_kind",
)

RESOLUTION_DECISION = "decision"
RESOLUTION_RULE_PARAMETER = "rule_parameter"

# Canonical column -> the ledger `field_name` a resolution must use. Absent means the two names
# coincide; wrong or missing and a curator's decision lands where nothing reads it.
#
# Only fields that can actually reach the queue are listed. An entry for a field whose declines are
# structurally impossible — `curation_status`, whose declines `CONSEQUENTIAL_REASONS` guarantees are
# never queued — would document how to file a resolution this file guarantees will never be asked
# for. Add a field when its rule lands, not before. `tests/test_curation_queue.py` checks every
# target against the ledger's real `field_name` vocabulary.
REGISTRY_FIELD_FOR_CANONICAL = {
    "sample_origin": "origin_class",
    "specimen_type": "specimen_type",
    "virus_group": "is_poliovirus",
}

# Which unresolved reasons a *rule parameter* would fix, rather than a per-record decision. A
# missing keyword generalizes; a source naming two specimens does not, and neither does an organism
# name that only sequence evidence can settle.
RULE_PARAMETER_REASONS = frozenset(
    {
        "no_specimen_keyword_in_isolation_source",
    }
)

# Declines that are *consequences* of another field declining, not work of their own.
# `curation_status` is release policy over `virus_group`: resolving the membership resolves the
# status too. Queueing both would ask for twice the decisions that exist, and a queue that
# overstates its own size is worse than no queue.
CONSEQUENTIAL_REASONS = frozenset({"follows_unresolved_virus_group"})

EXAMPLES_PER_GROUP = 3


@dataclass(frozen=True)
class QueueGroup:
    queue_id: str
    canonical_field: str
    registry_field: str
    winning_rule_id: str
    unresolved_reason: str
    group_key: str
    versions: tuple[str, ...]

    @property
    def suggested_resolution_kind(self) -> str:
        return (
            RESOLUTION_RULE_PARAMETER
            if self.unresolved_reason in RULE_PARAMETER_REASONS
            else RESOLUTION_DECISION
        )

    def as_row(self) -> dict[str, str]:
        return {
            "queue_id": self.queue_id,
            "canonical_field": self.canonical_field,
            "registry_field": self.registry_field,
            "winning_rule_id": self.winning_rule_id,
            "unresolved_reason": self.unresolved_reason,
            "group_key": self.group_key,
            "record_count": str(len(self.versions)),
            "example_versions": " ".join(self.versions[:EXAMPLES_PER_GROUP]),
            "suggested_resolution_kind": self.suggested_resolution_kind,
        }


def queue_id(rule_id: str, canonical_field: str, group_key: str) -> str:
    digest = hashlib.sha256(f"{rule_id}|{canonical_field}|{group_key}".encode()).hexdigest()
    return f"Q-{digest[:12]}"


def build_queue(rows: Iterable[Mapping[str, str]]) -> list[QueueGroup]:
    """Group every declined provenance row. Returns groups in a deterministic order.

    Sorted by `queue_id` rather than by size or by first appearance: a size ordering reshuffles the
    whole worksheet when one group grows, and insertion order depends on corpus order, which is not
    a property a curator should have to think about.
    """
    grouped: dict[tuple[str, str, str, str], list[str]] = {}
    for row in rows:
        reason = row.get("unresolved_reason", "")
        if not reason or reason in CONSEQUENTIAL_REASONS:
            continue
        key = (row["canonical_field"], row["winning_rule_id"], reason, row["source_value"])
        grouped.setdefault(key, []).append(row["version"])

    groups = [
        QueueGroup(
            queue_id=queue_id(rule_id, field, group_key),
            canonical_field=field,
            registry_field=REGISTRY_FIELD_FOR_CANONICAL.get(field, field),
            winning_rule_id=rule_id,
            unresolved_reason=reason,
            group_key=group_key,
            versions=tuple(sorted(versions)),
        )
        for (field, rule_id, reason, group_key), versions in grouped.items()
    ]
    return sorted(groups, key=lambda group: group.queue_id)
