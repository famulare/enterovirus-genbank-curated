"""Write the `audit/` release views.

Only the rule view exists so far. It matters more than its size suggests: it is generated from
`registry/rules.json` and must come out **byte-identical** to the shipped
`final/audit/rules.tsv.gz`, which is what turns the new catalog from a plausible-looking data file
into one demonstrably describing the release. The four shipped columns are a projection of the
catalog's seven; `implementation`, `parameters` and `status` are the rewrite's own additions and are
deliberately not in the view, because the view has to reproduce a frozen artifact.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from enterovirus_genbank_curated.export.source import write_tsv
from enterovirus_genbank_curated.registry.rules import RuleSpec

RULES_VIEW_RELATIVE = "audit/rules.tsv.gz"
RULES_VIEW_COLUMNS = ("rule_id", "rule_version", "field_name", "description")

# Deliberately not the shipped name. The release's own projection-provenance table carries fourteen
# canonical fields; this holds only the fields whose rule is implemented, so it is written under its
# own name with the covered set declared alongside it — the same reason the transport is not written
# as `sequence_metadata.tsv.gz`.
PROVENANCE_RELATIVE = "audit/projection_provenance.tsv.gz"
PROVENANCE_COLUMNS = (
    "accession",
    "version",
    "canonical_field",
    "final_value",
    "source_field",
    "source_value",
    "winning_rule_id",
    "evidence_basis",
    "manual_override",
)

# The rewrite's own tenth column, alongside the nine the release ships. A rule that declines has to
# say so somewhere, and the alternative — inferring "declined" from a blank `final_value` — cannot
# distinguish it from a value the rule deliberately blanked, which `locality` does 23,251 times.
UNRESOLVED_REASON_COLUMN = "unresolved_reason"
PROVENANCE_OUTPUT_COLUMNS = (*PROVENANCE_COLUMNS, UNRESOLVED_REASON_COLUMN)


def write_rules_view(output_dir: Path, specs: Iterable[RuleSpec]) -> int:
    """Project the catalog onto the four shipped columns, in catalog order."""
    rows = [
        {column: getattr(spec, column) for column in RULES_VIEW_COLUMNS} for spec in specs
    ]
    return write_tsv(output_dir / RULES_VIEW_RELATIVE, RULES_VIEW_COLUMNS, rows)


def write_projection_provenance(output_dir: Path, rows: list[dict[str, str]]) -> int:
    """Write the projection rows exactly as the rules produced them, in emission order."""
    return write_tsv(output_dir / PROVENANCE_RELATIVE, PROVENANCE_OUTPUT_COLUMNS, rows)
