"""The declared list of modules that register rule implementations.

`bind_rules` resolves `implementation` keys through `RULE_IMPLEMENTATIONS`, which is populated by
import side effect. Whether a rule is bound would therefore depend on what happened to be imported
first, and `evgc validate-contracts` would report a different answer depending on its entry point.
Importing them from one place makes the set declared rather than incidental.

The failure mode if a module is missing from this list is a loud one — its rules resolve to neither
a registered nor a pending implementation and `bind_rules` raises — which is the right direction.
"""

from __future__ import annotations

from importlib import import_module

# Modules holding `@rule_implementation`-decorated functions, relative to the package root.
IMPLEMENTATION_MODULES = (
    "derive.classification",
    "derive.dates",
    "derive.engineered",
    "derive.epi",
    "derive.geo",
    "derive.partition",
    "derive.typing",
)


def load_rule_implementations() -> None:
    for name in IMPLEMENTATION_MODULES:
        import_module(f"enterovirus_genbank_curated.{name}")
