# Curation registry contract

`registry/decisions.tsv` will be the sole authoritative ledger of human curation decisions.
It is intentionally an uncompressed UTF-8 TSV so that it remains readable in GitHub, a text
editor, a spreadsheet, and command-line tools. Generated files under `final/audit/` are release
views and must never be edited by hand.

PR 1 defines the contract but does **not** yet add the migrated ledger. The migration is complete
only when the public ledger reproduces the 2,753 decisions in release 2.1.5 and passes the full
parity gate.

## Required columns

The exact order is:

```text
decision_id decision_type subject_key accession field_name new_value reason
evidence_reference confirmed_by source_artifact status effective_from effective_through notes
```

The real file is tab-delimited. The wrapped display above is only for readability.

- `decision_id` is a stable `D-<lowercase hex>` identifier.
- `subject_key` is always populated. It is the accession when one exists; otherwise it is a stable
  reference, family, or other accession-less subject label.
- `accession` is unversioned and may be blank.
- `reason`, `evidence_reference`, and `confirmed_by` preserve recorded text. Missing historical
  information stays blank; it is never reconstructed or embellished.
- `source_artifact` records the legacy or current registry source of the assertion.
- `status` is `active`, `superseded`, or `retired`.
- effective boundaries are explicit strings and may be blank until release-scoped semantics are
  required.

## Ordering and conflicts

Rows are sorted by `decision_type`, `subject_key`, `field_name`, then `decision_id`. Row order never
controls precedence. Two active assertions for the same subject and field are invalid until an
explicit versioned conflict policy exists. Unknown subjects, fields, decision types, or controlled
values fail closed.

## Generated audit relationship

The future pipeline will generate:

- `final/audit/manual_decisions.tsv.gz`: normalized release view of the ledger;
- `final/audit/decision_applications.tsv.gz`: each decision's resolved output effects, including
  before and after values and a non-silent application status;
- `final/audit/canonical_projection_provenance.tsv.gz`: field-level deterministic and manual
  provenance.

CI will require equality of decision-ID sets between the ledger and generated manual-decision
audit, and will reject omitted, duplicated, conflicting, or silently ignored decisions.

## Local validation

After the migrated ledger is added:

```bash
evgc validate-ledger registry/decisions.tsv
```

The record-level schema is `registry/schemas/decisions.schema.json`. Deterministic rules are a
separate concern governed by `registry/schemas/rules.schema.json`; human assertions must not be
encoded as executable special cases.
