"""Reproducible multiple-sequence alignment: population derivation, segmentation, and assembly.

Not a `derive`/`export`/`genbank`/`registry` build tree, and deliberately not enforced by
`tests/test_module_boundaries.py`'s "no build module names `final/`" rule. `align/`'s charter is to
derive alignment inputs from the shipped 2.4.1 release — the same justification `oracle/` has for
reading `final/`, just aimed at derivation rather than comparison. `align/contract.py` consumes
`final/` paths through `oracle.parity`'s declarations rather than naming its own, so there is
exactly one place each path is spelled.

The original reason was that the stages producing these inputs natively did not exist. They do now:
`derive/` and `curate/` build a full canonical table into `release/<version>/`. Reading `final/` is
therefore a *pinning* decision rather than a gap — this layer is anchored to 2.4.1, whose row set
and `virus_group`/`virus_type` values differ from what the pipeline now produces, and whose
`audit/sequence_evidence.tsv.gz` supplies a tier predicate the new `derive/evidence.py` does not
compute. `docs/reproducibility.md` measures both, under "The alignment layer's anchor".
"""
