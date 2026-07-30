"""The only package permitted to read the shipped release.

`docs/pipeline.md` boundary 1 — existing `final/` files are comparison targets, never pipeline
inputs — used to be enforced by nothing but care, with release reads sitting in the same modules as
build code. Every stage added from here on adds comparison points, so the reads live in one package
and the build lives outside it.

The boundary is enforced three ways, weakest to strongest: `tests/test_module_boundaries.py` refuses
a `final/` literal or an `oracle` import anywhere under `derive/`, `curate/`, `export/` or
`registry/`; `sandbox.install_input_guard` refuses to *read* `final/` at all in a guarded build;
and the `parity-*` verbs run the build in a guarded child and compare in the unguarded parent, so a
build that read the release cannot hide behind the comparison that follows it.
"""
