"""Reproducible multiple-sequence alignment: population derivation, segmentation, and assembly.

Not a `derive`/`export`/`genbank`/`registry` build tree, and deliberately not enforced by
`tests/test_module_boundaries.py`'s "no build module names `final/`" rule. `align/`'s charter is to
derive alignment inputs from the shipped release because the pipeline stages that would produce them
natively (`derive`, `curate`, and an eventual alignment-specific stage) do not exist yet — the same
justification `oracle/` has for reading `final/`, just aimed at derivation rather than comparison.
`align/contract.py` consumes `final/` paths through `oracle.parity`'s declarations rather than
naming its own, so there is exactly one place each path is spelled.
"""
