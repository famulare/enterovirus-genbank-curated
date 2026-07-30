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


def write_rules_view(output_dir: Path, specs: Iterable[RuleSpec]) -> int:
    """Project the catalog onto the four shipped columns, in catalog order."""
    rows = [
        {column: getattr(spec, column) for column in RULES_VIEW_COLUMNS} for spec in specs
    ]
    return write_tsv(output_dir / RULES_VIEW_RELATIVE, RULES_VIEW_COLUMNS, rows)
