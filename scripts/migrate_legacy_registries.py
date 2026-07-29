#!/usr/bin/env python3
"""One-time migration of the ten hand-curated registries into `registry/decisions.tsv`.

This is a historical tool, not a pipeline stage. It reads the private curation repository once and
leaves a committed public artifact behind; after that the ledger is the source of truth and nothing
in the build ever looks outside the clone again. Run it with `--source-dir` pointing at
`MAD-VDPV/data/genbank/working`.

## Decisions this migration encodes

**D1 — authors' raw cell text.** The release's `manual_decisions.tsv.gz` synthesizes reason and
evidence as `"{column}: {value} | {column}: {value}"`, whitespace-collapsed. The ledger instead
carries what the curator actually typed. Reason text therefore differs from the shipped artifact by
design. Parity is nevertheless full-fidelity rather than a projection: the release's synthesis is a
deterministic function of curator text, so `tests/test_decision_ledger.py` inverts it and compares
every shipped column. The only permitted difference is the six repaired reasons below, and only in
the direction of the ledger holding more text.

**D1 — repair `polio_recovery_confirmed.csv`.** Its header ends in a bare comma, creating an unnamed
5th column. Six rows contain an unescaped comma inside `note`, so the tail spilled into that column
and the release silently dropped it — one reason ends mid-phrase at "(<50nt", and KY748286 lost
" Nigeria 2015". The spilled remainder is rejoined here.

**Plain-TSV normalization — the one deliberate text deviation.** Curator `reason` text contains 70
ASCII double quotes across 35 rows. Written with csv's default quoting those fields get wrapped and
their inner quotes doubled, which is standards-correct but leaves escaping artifacts that `cut -f`
and other naive tools mishandle. They are converted to typographic pairs (`“ ”`) so a standard csv
writer has nothing to quote and the file is simultaneously RFC-correct and naive-tool-safe. Curator
text already contains em dashes, so this introduces no new Unicode class. Two characters change per
quoted phrase; nothing else does.

**D3 — `decision_id` drops `source_artifact` from the identity hash.** Previously the bare source
filename was hashed in, so moving a registry to a public path rehashed every id. Ids change once,
now, and are then stable against renames.

**D2 — CS406436 / CS406482 / CS406483.** These carried contradictory live decisions:
`classification=engineered` from the 2015 legacy override ("codon-deoptimized MEF1") and
`classification=wild` from the 2026 full-genome review. Measured divergence from MEF1 (AY238473) is
4 nt/6621 for CS406436 and 4-6 nt/7435 for the other two, which rules out codon deoptimization —
that rewrites synonymous codons wholesale. Adjudicated by the curator: the legacy rows become
`superseded`, and an explicit `engineered_or_construct=FALSE` is asserted, since these are parental
sequences deposited inside an engineering patent. Canonical already ships `wild`, so no scientific
output changes. This adds three rows, so the ledger is 2,756 rather than the historical 2,753.

## Column-mapping choices, stated rather than buried

Some source columns the release wrote into `evidence_reference` are not evidence. They are still
carried — dropping curator-recorded values would be data loss — but as **labelled attributes** in
`notes`, written `key=value; key=value`:

* `canonical_reference_confirmed.reference_label` and `.serotype` are attributes of the subject, not
  evidence for it. Both go to `notes` (`reference_label=Sabin1; serotype=1`). The label must be
  carried explicitly: it is only the `subject_key` for the single accession-less row (Lansing), so
  relying on `subject_key` would silently lose Sabin1/2/3, Brunhilde, MEF1, W2, Leon37, Saukett and
  CHAT.
* `isolate_linkage_manual_verified.linked_sibling` is an attribute (`linked_sibling=AJ783802`);
  `verification_evidence` is genuine evidence.
* `legacy_accession_classification_overrides.curation_source` is the constant
  `legacy_accession_override` for all 30 rows — pure provenance, already carried by
  `source_artifact`, so it is not duplicated.

Attributes keep their column name because `notes` has no schema: an unlabelled `2` preserves the
value while erasing what it means. This is not the synthetic prefixing that was stripped from
`reason`/`evidence_reference` — there the prefix wrapped the curator's own prose; here it names a
structured field that would otherwise be anonymous. `key=value` rather than `key: value` keeps the
two visually distinct.

Where a source has two prose columns (`reason` and `note`), the primary goes to `reason` and the
secondary to `notes`, rather than both being concatenated into one field with synthetic prefixes.

`status` is `active` except for the three D2 supersessions. `effective_from` and `effective_through`
stay blank: no source registry has a date, version or supersession column, and inventing one would
be fabrication. Supersession that predates this migration is unrecoverable — at least one reversed
call (`MK719554`) had its superseded row physically deleted.
"""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import sys
from dataclasses import dataclass, field
from pathlib import Path

from enterovirus_genbank_curated.contracts import (
    DECISIONS_SCHEMA_PATH,
    LEDGER_SORT_COLUMNS,
    ContractError,
    load_decision_contract,
    validate_decision_ledger,
)

# Identity tuple for decision_id, deliberately excluding source_artifact (D3) and the free-text
# reason/evidence/confirmed_by fields, so wording can be corrected without changing an id.
ID_COLUMNS = ("decision_type", "subject_key", "field_name", "new_value")

# The D2 adjudication is not a migration from any registry — it is a curator decision made during
# this migration. Attributing it to manual_review_overrides.csv would claim that file records an
# assertion it does not contain, so it names itself.
D2_SOURCE = "curator_adjudication_2026-07-29"
D2_ACCESSIONS = ("CS406436", "CS406482", "CS406483")
D2_EVIDENCE = (
    "measured 4 nt/6621 (CS406436) and 4-6 nt/7435 (CS406482, CS406483) from MEF1 AY238473, "
    "which rules out codon deoptimization"
)
# Distinct wording per status. Reusing one string left three status=active rows whose notes opened
# with the word "superseded", which is exactly the confusion the status vocabulary exists to avoid.
D2_SUPERSEDED_NOTE = (
    f"superseded 2026-07-29: {D2_EVIDENCE}; these are parental MEF1 deposits within patent "
    f"WO2006042156"
)
D2_ADDED_NOTE = (
    f"asserted 2026-07-29 when the contradictory legacy classification=engineered was superseded: "
    f"{D2_EVIDENCE}"
)


@dataclass(frozen=True)
class FieldSpec:
    """One asserted field. `source_column` empty means `constant` is asserted unconditionally."""

    source_column: str
    field_name: str
    constant: str = ""
    emit_when: str = "always"  # always | accession_present | accession_absent


@dataclass(frozen=True)
class SourceSpec:
    filename: str
    decision_type: str
    accession_column: str
    fields: tuple[FieldSpec, ...]
    reason_column: str = ""
    # Secondary prose, carried into `notes` verbatim.
    note_columns: tuple[str, ...] = ()
    # Structured attributes, carried into `notes` as `key=value` so each value keeps its name.
    attribute_columns: tuple[str, ...] = ()
    evidence_columns: tuple[str, ...] = ()
    confirmed_by_column: str = "confirmed_by"
    subject_label_column: str = ""
    repair_trailing_comma: bool = False
    extra: dict[str, str] = field(default_factory=dict)


SOURCES: tuple[SourceSpec, ...] = (
    SourceSpec(
        "manual_review_overrides.csv", "manual_override", "accession",
        tuple(
            FieldSpec(c, c)
            for c in (
                "origin_class", "sampling_frame", "classification", "engineered_or_construct",
                "reference_label", "canonical_reference", "epi_context", "specimen_type",
                "serotype",
            )
        ),
        reason_column="note", evidence_columns=("source",),
    ),
    SourceSpec(
        "carve_exclusions_confirmed.csv", "carve_exclusion", "accession",
        (FieldSpec("", "carve_excluded", "TRUE"),),
        reason_column="reason", note_columns=("note",),
    ),
    SourceSpec(
        "membership_exclusions_confirmed.csv", "membership_exclusion", "accession",
        (FieldSpec("", "membership_excluded", "TRUE"),),
        reason_column="reason", note_columns=("note",),
    ),
    SourceSpec(
        "isolate_linkage_manual_verified.csv", "isolate_linkage_approval", "accession",
        (FieldSpec("verified_classification", "verified_classification"),
         FieldSpec("serotype", "serotype")),
        evidence_columns=("verification_evidence",), attribute_columns=("linked_sibling",),
    ),
    SourceSpec(
        "canonical_reference_confirmed.csv", "canonical_reference_confirmation",
        "canonical_accession",
        (FieldSpec("", "canonical_reference", "TRUE", emit_when="accession_present"),
         FieldSpec("", "canonical_reference_available", "FALSE", emit_when="accession_absent")),
        reason_column="note", attribute_columns=("reference_label", "serotype"),
        subject_label_column="reference_label",
    ),
    SourceSpec(
        "legacy_accession_classification_overrides.csv", "legacy_classification_override",
        "accession",
        (FieldSpec("classification", "classification"),),
        reason_column="notes",
    ),
    SourceSpec(
        "date_review_overrides.csv", "date_override", "accession",
        (FieldSpec("collection_date_curated", "collection_date_curated"),
         FieldSpec("collection_year_curated", "collection_year_curated")),
        reason_column="note", evidence_columns=("source",),
    ),
    SourceSpec(
        "membership_poliovirus_confirmed.csv", "membership_confirmation_polio", "accession",
        (FieldSpec("", "is_poliovirus", "TRUE"),),
        reason_column="note", evidence_columns=("evidence",),
    ),
    SourceSpec(
        "membership_not_poliovirus_confirmed.csv", "membership_confirmation_not_polio", "accession",
        (FieldSpec("", "is_poliovirus", "FALSE"), FieldSpec("corrected_type", "corrected_type")),
        reason_column="note", evidence_columns=("evidence",),
    ),
    SourceSpec(
        "polio_recovery_confirmed.csv", "polio_recovery_confirmation", "accession",
        (FieldSpec("confirmed_serotype", "confirmed_serotype"),),
        reason_column="note", repair_trailing_comma=True,
    ),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-dir", required=True, type=Path,
        help="the private curation working directory (MAD-VDPV/data/genbank/working)",
    )
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, default=Path("registry/decisions.tsv"))
    return parser.parse_args()


OVERFLOW_KEYS = (None, "")

LEFT_QUOTE = "“"
RIGHT_QUOTE = "”"


def normalize_for_plain_tsv(value: str, *, where: str) -> str:
    """Make `value` safe to write with a standard csv writer without any field being quoted.

    The goal is a ledger that naive tools handle correctly: `cut -f5`, `awk -F'\\t'`, a spreadsheet
    import, and `pandas.read_csv(sep='\\t')` should all agree, with no escaping artifacts for a
    reader to trip over.

    The only obstacle in this corpus is the ASCII double quote — 70 of them across 35 `reason`
    fields, e.g. `paper title explicitly says "circulating"`. Written with csv's default
    QUOTE_MINIMAL those fields get wrapped and their inner quotes doubled; written with QUOTE_NONE
    the writer refuses outright. So the quotes are converted to typographic pairs, which read
    identically to a human and are not special to any parser. Curator text already contains em
    dashes, so this is not introducing Unicode where there was none.

    This is a deliberate, curator-approved deviation from verbatim text, and the only one: it
    changes two characters per quoted phrase and nothing else. Every occurrence in this corpus is
    balanced (zero fields have an odd count), so pairing is unambiguous; an odd count raises rather
    than guessing which end a lone quote is.
    """
    if any(ch in value for ch in "\t\r\n"):
        raise ContractError(
            f"{where}: contains a tab or newline, which a plain-TSV ledger cannot represent: "
            f"{value!r}"
        )
    if LEFT_QUOTE in value or RIGHT_QUOTE in value:
        raise ContractError(
            f"{where}: already contains a typographic quote, so pairing ASCII quotes around it "
            f"could produce unbalanced output: {value!r}"
        )
    count = value.count('"')
    if not count:
        return value
    if count % 2:
        raise ContractError(
            f"{where}: has {count} double quotes, an odd number, so open/close pairing is "
            f"ambiguous: {value!r}"
        )
    out: list[str] = []
    opening = True
    for ch in value:
        if ch == '"':
            out.append(LEFT_QUOTE if opening else RIGHT_QUOTE)
            opening = not opening
        else:
            out.append(ch)
    return "".join(out)


def repair_spilled_reason(value: str) -> str:
    """Recover the tail of a reason that a prior tool split on a comma and stringified.

    `polio_recovery_confirmed.csv` does not merely have a malformed header — the file on disk
    literally contains a Python list repr in its unnamed fifth column, e.g.

        KY748286,2,Mike,tier1 field AFP detection — Sabin2/VDPV2-like,[' Nigeria 2015']

    Some earlier script split the note on commas, wrote element 0 into `note`, and wrote
    `repr(rest)` into the overflow column. The release then dropped the overflow, so six reasons
    ship truncated — one ends mid-phrase at "(<50nt". Parsed with `ast.literal_eval`, never `eval`,
    and rejoined with the comma that was the original split point.
    """
    text = value.strip()
    if not text:
        return ""
    if not (text.startswith("[") and text.endswith("]")):
        raise ContractError(
            f"spilled reason payload is not the expected list repr, so its structure is unknown "
            f"and concatenating it would corrupt the reason: {value!r}"
        )
    try:
        parsed = ast.literal_eval(text)
    except (ValueError, SyntaxError) as exc:
        raise ContractError(f"cannot parse spilled reason payload {value!r}: {exc}") from exc
    if not isinstance(parsed, list) or not all(isinstance(p, str) for p in parsed):
        raise ContractError(f"unexpected spilled reason payload: {value!r}")
    # Rejoin on a bare comma and do NOT strip or drop elements. The split was on ",", so each
    # element still carries the space that followed it; stripping and rejoining on ", " would insert
    # a second space, and dropping an empty element would swallow one of the original commas.
    return ",".join(parsed)


def read_registry(path: Path, spec: SourceSpec) -> list[dict[str, str]]:
    """Read one registry, repairing the spilled reason column where declared."""
    with path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))

    if not spec.repair_trailing_comma:
        for row in rows:
            for key in OVERFLOW_KEYS:
                if row.get(key):
                    raise ContractError(
                        f"{path.name}: row {row.get(spec.accession_column)!r} carries data in an "
                        f"unnamed column ({key!r}), and this source is not declared as repairable"
                    )
        return rows

    repaired = []
    for row in rows:
        # Collect from EVERY overflow slot, not just the first non-empty one. `spilled or ...`
        # discarded the real tail whenever both the named-empty column and the restkey were
        # populated — which is what happens as soon as a note contains a second comma.
        payloads = [str(row.pop(key)) for key in OVERFLOW_KEYS if row.get(key)]
        for key in OVERFLOW_KEYS:
            row.pop(key, None)
        if len(payloads) > 1:
            raise ContractError(
                f"{path.name}: row {row.get(spec.accession_column)!r} has data in more than one "
                f"overflow slot ({payloads!r}); rejoin order is ambiguous"
            )
        spilled = repair_spilled_reason(payloads[0]) if payloads else ""
        if not spilled:
            continue
        row[spec.reason_column] = f"{row.get(spec.reason_column, '')},{spilled}"
        repaired.append(f"{row.get(spec.accession_column)}: ...{spilled[:40]}")
    if repaired:
        print(f"  repaired {len(repaired)} truncated reason(s) in {path.name}:", file=sys.stderr)
        for line in repaired:
            print(f"      {line}", file=sys.stderr)
    return rows


def joined(row: dict[str, str], columns: tuple[str, ...]) -> str:
    """Join curator prose from several columns with '; ', dropping blanks.

    Ambiguity warning for future edits: 210 curator cells in the columns this currently feeds
    already contain a ';'. Every present call spans exactly ONE column, so nothing is ambiguous
    today — but adding a second column to any prose tuple makes the joined field unsplittable. Use
    `labelled()` instead when a field needs to carry more than one thing.
    """
    if len(columns) > 1:
        raise ContractError(
            f"joined() over multiple prose columns {columns} would be unsplittable because curator "
            f"text contains ';' — use labelled() so each value keeps its name"
        )
    values = [str(row.get(c, "") or "").strip() for c in columns]
    return "; ".join(v for v in values if v)


def labelled(row: dict[str, str], columns: tuple[str, ...]) -> str:
    """Render structured attributes as `key=value; key=value`, dropping blanks.

    `notes` has no schema, so an unlabelled `2` preserves the value and erases its meaning. Naming
    each field is what keeps `serotype=2` distinguishable from `linked_sibling=AJ783802`.
    """
    parts = []
    for column in columns:
        value = str(row.get(column, "") or "").strip()
        if not value:
            continue
        if any(ch in value for ch in ";="):
            raise ContractError(
                f"attribute {column}={value!r} contains ';' or '=', which would make the labelled "
                f"notes field ambiguous"
            )
        parts.append(f"{column}={value}")
    return "; ".join(parts)


def emit_rows(spec: SourceSpec, rows: list[dict[str, str]]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for row in rows:
        accession = str(row.get(spec.accession_column, "") or "").strip()
        label = str(row.get(spec.subject_label_column, "") or "").strip()
        subject_key = accession or label
        if not subject_key:
            raise ContractError(
                f"{spec.filename}: a row has neither {spec.accession_column} nor a subject label"
            )
        for field_spec in spec.fields:
            if field_spec.emit_when == "accession_present" and not accession:
                continue
            if field_spec.emit_when == "accession_absent" and accession:
                continue
            if field_spec.source_column:
                value = str(row.get(field_spec.source_column, "") or "").strip()
                if not value:
                    continue
            else:
                value = field_spec.constant
            out.append(
                {
                    "decision_type": spec.decision_type,
                    "subject_key": subject_key,
                    "accession": accession,
                    "field_name": field_spec.field_name,
                    "new_value": value,
                    "reason": str(row.get(spec.reason_column, "") or "").strip()
                    if spec.reason_column
                    else "",
                    "evidence_reference": joined(row, spec.evidence_columns),
                    "confirmed_by": str(row.get(spec.confirmed_by_column, "") or "").strip(),
                    "source_artifact": spec.filename,
                    "status": "active",
                    "effective_from": "",
                    "effective_through": "",
                    "notes": "; ".join(
                        x
                        for x in (
                            joined(row, spec.note_columns),
                            labelled(row, spec.attribute_columns),
                        )
                        if x
                    ),
                }
            )
    return out


def apply_d2(decisions: list[dict[str, str]]) -> list[dict[str, str]]:
    """Supersede the legacy `engineered` calls and assert `engineered_or_construct=FALSE`.

    The added rows are built field by field rather than copied from a neighbouring assertion. An
    earlier version spread `{**anchor}`, which inherited that row's `reason`, `evidence_reference`
    and `source_artifact` — attributing a 2026 adjudication to a registry that does not record it,
    and making the result depend on which `manual_review_overrides.csv` row happened to come first.
    """
    superseded = 0
    for row in decisions:
        if (
            row["decision_type"] == "legacy_classification_override"
            and row["subject_key"] in D2_ACCESSIONS
            and row["field_name"] == "classification"
            and row["new_value"] == "engineered"
        ):
            row["status"] = "superseded"
            row["notes"] = "; ".join(x for x in (row["notes"], D2_SUPERSEDED_NOTE) if x)
            superseded += 1
    if superseded != len(D2_ACCESSIONS):
        raise ContractError(
            f"D2 expected to supersede {len(D2_ACCESSIONS)} legacy rows, matched {superseded}"
        )

    for accession in D2_ACCESSIONS:
        # Confirm the subject exists and is unambiguous, but inherit nothing from it.
        anchors = [
            r for r in decisions
            if r["subject_key"] == accession and r["decision_type"] == "manual_override"
        ]
        if not anchors:
            raise ContractError(f"D2: no manual_override rows for {accession}")
        if len({r["accession"] for r in anchors}) != 1:
            raise ContractError(f"D2: {accession} resolves to several accessions")
        decisions.append(
            {
                "decision_type": "manual_override",
                "subject_key": accession,
                "accession": anchors[0]["accession"],
                "field_name": "engineered_or_construct",
                "new_value": "FALSE",
                "reason": "parental MEF1 deposit within patent WO2006042156; not an engineered "
                          "construct",
                "evidence_reference": D2_EVIDENCE,
                "confirmed_by": "Mike",
                "source_artifact": D2_SOURCE,
                "status": "active",
                "effective_from": "",
                "effective_through": "",
                "notes": D2_ADDED_NOTE,
            }
        )
    return decisions


# Which registry governs when two of them assert the same field for the same subject. Declared
# because the ledger forbids two *active* assertions per (subject_key, field_name) and something has
# to break the tie; documented because an undocumented precedence rule is exactly the stop-condition
# this migration is supposed to respect.
#
# 1. canonical_reference_confirmed.csv — the purpose-built registry for canonical-reference calls,
#    so it governs those over a general-purpose override sheet that happens to carry the column.
# 2. manual_review_overrides.csv — current, actively maintained human curation.
# 3. legacy_accession_classification_overrides.csv — machine-generated 2015 legacy bridge.
SOURCE_PRECEDENCE = (
    "canonical_reference_confirmed.csv",
    "manual_review_overrides.csv",
    "legacy_accession_classification_overrides.csv",
)


def resolve_duplicate_assertions(decisions: list[dict[str, str]]) -> list[dict[str, str]]:
    """Retire redundant duplicates; refuse to guess when two registries actually disagree.

    Measured on this corpus: 17 (subject, field) pairs are asserted by two registries and **all 17
    agree on the value**. They are the same human judgment recorded twice, not a conflict, so the
    lower-precedence row is marked `retired` — withdrawn from force without having been contradicted
    — rather than `superseded`, which is reserved for a call that was actually overturned (D2).

    A disagreement raises. Adjudicating one silently is how a curation database acquires an opinion
    nobody chose.
    """
    groups: dict[tuple[str, str], list[dict[str, str]]] = {}
    for row in decisions:
        if row["status"] == "active":
            groups.setdefault((row["subject_key"], row["field_name"]), []).append(row)

    retired = 0
    for (subject, field_name), rows in sorted(groups.items()):
        if len(rows) < 2:
            continue
        values = {r["new_value"] for r in rows}
        if len(values) > 1:
            detail = "; ".join(f"{r['new_value']!r} from {r['source_artifact']}" for r in rows)
            raise ContractError(
                f"{subject}/{field_name}: registries disagree — {detail}. This needs explicit "
                f"adjudication, not a precedence rule."
            )
        unknown = [
            r["source_artifact"] for r in rows if r["source_artifact"] not in SOURCE_PRECEDENCE
        ]
        if unknown:
            raise ContractError(
                f"{subject}/{field_name}: no declared precedence for {sorted(set(unknown))}"
            )
        rows.sort(key=lambda r: SOURCE_PRECEDENCE.index(r["source_artifact"]))
        governing = rows[0]
        for row in rows[1:]:
            row["status"] = "retired"
            row["notes"] = "; ".join(
                x for x in (
                    row["notes"],
                    f"retired: same assertion is governed by {governing['source_artifact']}, "
                    f"which records the identical value {governing['new_value']!r}",
                ) if x
            )
            retired += 1
    if retired:
        print(f"  retired {retired} redundant duplicate assertion(s)", file=sys.stderr)
    return decisions


def assign_ids(decisions: list[dict[str, str]]) -> list[dict[str, str]]:
    """Content-stable ids. Occurrence suffixes break ties between identical identity tuples."""
    decisions.sort(
        key=lambda r: (
            *(r[c] for c in ID_COLUMNS), r["reason"], r["evidence_reference"], r["confirmed_by"]
        )
    )
    seen: dict[str, int] = {}
    for row in decisions:
        digest = hashlib.sha256(
            "|".join(row[c] for c in ID_COLUMNS).encode("utf-8")
        ).hexdigest()[:12]
        seen[digest] = seen.get(digest, 0) + 1
        row["decision_id"] = f"D-{digest}" if seen[digest] == 1 else f"D-{digest}-{seen[digest]}"
    return decisions


def main() -> int:
    args = parse_args()
    root = args.repository_root.resolve()
    contract = load_decision_contract(root / DECISIONS_SCHEMA_PATH)

    decisions: list[dict[str, str]] = []
    for spec in SOURCES:
        path = args.source_dir / spec.filename
        if not path.is_file():
            raise ContractError(f"missing source registry: {path}")
        rows = read_registry(path, spec)
        emitted = emit_rows(spec, rows)
        print(f"  {spec.filename:48} {len(rows):>5} rows -> {len(emitted):>5} decisions")
        decisions.extend(emitted)

    print(f"  {'baseline total':48} {'':>5}         {len(decisions):>5} decisions")
    decisions = apply_d2(decisions)
    decisions = resolve_duplicate_assertions(decisions)

    # Normalize BEFORE hashing. Ids are derived from subject_key/field_name/new_value, so
    # normalizing afterwards would leave an id that no longer matches the text it labels. No value
    # in an id column currently contains a quote, but the ordering should not depend on that.
    normalized = 0
    for row in decisions:
        for column, value in row.items():
            clean = normalize_for_plain_tsv(value, where=f"{row['subject_key']}.{column}")
            if clean != value:
                row[column] = clean
                normalized += 1
    if normalized:
        print(f"  normalized quotes in {normalized} field(s) for plain-TSV safety", file=sys.stderr)

    decisions = assign_ids(decisions)
    decisions.sort(key=lambda r: tuple(r[c] for c in LEDGER_SORT_COLUMNS))

    output = root / args.output if not args.output.is_absolute() else args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=list(contract.columns), delimiter="\t", lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(decisions)

    # The point of the normalization above: a standard writer was used, and it still had nothing to
    # quote. Assert that, so the plain-TSV guarantee is enforced rather than hoped for.
    written = output.read_text(encoding="utf-8")
    if '"' in written:
        raise ContractError(
            "the written ledger contains a double quote, so some field was escaped and naive "
            "tab-splitting would no longer be safe"
        )
    lines = written.splitlines()
    widths = {len(line.split("\t")) for line in lines}
    if widths != {len(contract.columns)}:
        raise ContractError(f"naive tab-split yields inconsistent field counts: {sorted(widths)}")

    summary = validate_decision_ledger(output, contract)
    print(f"wrote {summary.rows} decisions ({summary.active_rows} active) to {output}")
    return 0


if __name__ == "__main__":
    try:
        code = main()
    except ContractError as error:
        print(f"migration failed: {error}", file=sys.stderr)
        code = 1
    raise SystemExit(code)
