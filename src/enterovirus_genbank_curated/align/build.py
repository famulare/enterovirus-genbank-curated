"""Drive one artifact's build end to end, and the whole set strictly one at a time.

## Why this module is aggressively sequential

Measured on this machine (2026-07-30), peak RSS per step, pinned to one CPU:

| step | scale | peak |
|---|---|---|
| `mafft-linsi` seed | 40 of 140 aa sequences, ~2,200 aa each | 0.10 GB |
| `mafft --add` | 4,040 rows × 2,281 columns | 0.34 GB |
| `cmalign` | 500 of 4,242 NCR sequences, 738-state model | 0.57 GB |
| `cmalign`, threads unpinned | the same 500 | 0.76 GB |
| anchored pairwise, one full genome | 7,441 × 7,694 nt | 0.29 GB |

No single step is expensive. What *is* expensive is running several at once: a build attempt that
fanned artifacts out in parallel reached roughly 50 GB and froze the machine outright. Upstream
carried the same warning ("do not run two multithreaded MAFFTs concurrently") and satisfied it only
by convention. Here it is satisfied by construction: `build_all` loops, `build_one` awaits each
`run_tool` before the next, and the thread count is a declared argument rather than a machine
property. There is deliberately no parallel option to pass.

That is also why `cmalign --cpu` is pinned in `align.structural` rather than left to Infernal: an
unpinned worker count is a determinism hole, since the number of workers would be a property of the
machine rather than of the declaration.

## Threads are not the memory problem, and one thread is a trap

The first version of this module defaulted to one thread, reasoning from the 50 GB freeze. That
conflated two different things and cost hours. Measured on the real `POLIO_unified` pass-2 input
(8,736 profile rows plus 1,250 fragments):

| threads | `pairlocalalign` CPU | RSS | outcome |
|---|---|---|---|
| 1 | 97% (one core) | 58 MB | still in MAFFT's all-to-all stage after 90 minutes |
| 8 | 770% (eight cores) | 582 MB | the same stage saturating eight cores |

MAFFT's `--addfragments` builds a guide tree with an all-to-all pairwise stage over the *combined*
set, which is the dominant cost of a large build and is threaded. Pinning one thread does not reduce
peak memory in any way that matters — 58 MB against 582 MB, both negligible — it only serialises
the one stage that parallelises, turning a half-hour build into an all-day one.

So the rule is per-*artifact* sequencing, not per-core starvation: one artifact at a time, and
inside it as many threads as declared. Upstream reached the same setting (`min(8, cpu_count)`); the
count is a literal here because a declared parameter should not depend on the host.

## One guard per process, not one per artifact

`sandbox_exec.install_tool_guard` uses `sys.addaudithook`, and an audit hook cannot be uninstalled.
Installing a second guard therefore leaves the first one permanently armed-less, refusing the very
execs it was supposed to permit — the failure `tests/test_align_runner.py` is structured around. So
the guard, the toolchain and the scratch tree are created **once** for a whole run and threaded
through every artifact, and each artifact gets a disjoint band of run-directory indices
(`_STEP_BAND` apart) so their scratch directories cannot collide inside the shared root.

## What a build produces

Three files per artifact, from `export.alignment`: the Stockholm alignment, its FASTA projection,
and the coverage sidecar that says which blocks each record actually got and why any are absent.
Nothing is written into `final/` — the output directory is the caller's, so promotion into a release
stays a separate, reviewed step.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from enterovirus_genbank_curated import sandbox_exec
from enterovirus_genbank_curated.align import (
    anchored,
    codon,
    contract,
    segment,
    stitch,
    structural,
)
from enterovirus_genbank_curated.align import population as population_module
from enterovirus_genbank_curated.align import (
    provenance as provenance_module,
)
from enterovirus_genbank_curated.align import scratch as scratch_module
from enterovirus_genbank_curated.align import toolchain as toolchain_module
from enterovirus_genbank_curated.align.stitch import StitchedAlignment
from enterovirus_genbank_curated.contracts import ContractError
from enterovirus_genbank_curated.export import alignment as export_alignment

# Generous per-tool ceiling. The point is to fail rather than hang forever on a pathological input;
# the measured `mafft --add` extrapolation for the largest artifact is well inside this.
DEFAULT_TIMEOUT_S = 6 * 60 * 60
# Eight, and measured rather than guessed — see "Threads are not the memory problem" below. A
# literal constant, never `os.cpu_count()`: the thread count is a declared parameter recorded in
# provenance, and deriving it from the machine would make an artifact's inputs depend on where it
# was built.
DEFAULT_THREADS = 8

# Within one artifact's band: the CDS stage, then the two NCR sides.
_STEP_CODON = 0
_STEP_NCR = 4
# Artifacts are spaced this far apart so a shared scratch root never sees a duplicate index.
_STEP_BAND = 100


@dataclass(frozen=True)
class BuildContext:
    """The one-per-process tool environment, shared by every artifact in a run."""

    toolchain: toolchain_module.Toolchain
    scratch: scratch_module.Scratch
    guard: sandbox_exec.ToolGuard


@dataclass(frozen=True)
class BuildResult:
    name: str
    stitched: StitchedAlignment
    paths: dict[str, Path]
    seconds: float


def create_context(repository_root: Path) -> BuildContext:
    """Install the tool guard for this process. Call once; see the module docstring."""
    scratch = scratch_module.create()
    toolchain = toolchain_module.resolve(
        repository_root,
        environment=toolchain_module.ENV_ALIGN,
        tools=toolchain_module.ROUTINE_TOOLS,
        scratch=scratch.root,
    )
    guard = sandbox_exec.install_tool_guard(
        repository_root,
        scratch_root=scratch.root,
        allowed_executables=frozenset(str(tool.path) for tool in toolchain.tools.values()),
    )
    return BuildContext(toolchain=toolchain, scratch=scratch, guard=guard)


def build_one(
    repository_root: Path,
    name: str,
    output_dir: Path,
    *,
    context: BuildContext,
    records: dict[str, population_module.AlignedRecord],
    segmentations: dict[str, segment.Segmentation],
    anchor_inputs: anchored.AnchorInputs,
    threads: int = DEFAULT_THREADS,
    timeout_s: int = DEFAULT_TIMEOUT_S,
    step_base: int = 0,
) -> BuildResult:
    started = time.monotonic()
    spec = contract.ARTIFACTS.get(name)
    if spec is None:
        raise ContractError(f"unknown alignment artifact {name!r}")
    population = population_module.select(records, spec)

    if spec.stack == "anchored":
        anchored_block = anchored.build_anchored_cds_block(population, inputs=anchor_inputs)
        cds_block: stitch.CdsBlock = anchored_block
        # Every column of an anchored CDS block *is* a reference position, so RF is the reference
        # itself rather than a consensus over the rows.
        cds_rf: str | None = anchored_block.reference_row
        over_length_cap = anchored_block.over_length_cap
    else:
        cds_block = codon.build_codon_block(
            population, segmentations, context.toolchain, context.scratch, context.guard,
            threads=threads, timeout_s=timeout_s, step_offset=step_base + _STEP_CODON,
        )
        cds_rf = None
        over_length_cap = ()

    five_prime, three_prime = structural.build_ncr_blocks(
        population, segmentations, context.toolchain, context.scratch, context.guard,
        repository_root, threads=threads, timeout_s=timeout_s, step_offset=step_base + _STEP_NCR,
    )

    stitched = stitch.stitch(
        population, segmentations, cds_block, five_prime, three_prime, cds_rf=cds_rf
    )
    paths = export_alignment.write_alignment(output_dir, spec, stitched)
    seconds = time.monotonic() - started
    document = provenance_module.build_provenance(
        repository_root, population, stitched, paths,
        tool_identity=provenance_module.tool_identity(context.toolchain),
        threads=threads, seconds=seconds, over_length_cap=over_length_cap,
    )
    paths["provenance"] = provenance_module.write_provenance(output_dir, name, document)
    return BuildResult(name=name, stitched=stitched, paths=paths, seconds=seconds)


def build_all(
    repository_root: Path,
    output_dir: Path,
    *,
    names: tuple[str, ...] | None = None,
    threads: int = DEFAULT_THREADS,
    timeout_s: int = DEFAULT_TIMEOUT_S,
    on_event: Callable[[str, str, BuildResult | None], None] | None = None,
) -> list[BuildResult]:
    """Every requested artifact, one at a time. See the module docstring for why never in parallel.

    The corpus is loaded and segmented once and shared: it is pure computation over the same 24,301
    records, holds no tool memory, and repeating it per artifact would be the one avoidable cost
    here.
    """
    wanted = names if names is not None else tuple(contract.ARTIFACTS)
    unknown = [name for name in wanted if name not in contract.ARTIFACTS]
    if unknown:
        raise ContractError(f"unknown alignment artifact(s) {sorted(unknown)}")

    def emit(stage: str, name: str, result: BuildResult | None = None) -> None:
        if on_event is not None:
            on_event(stage, name, result)

    emit("load", "")
    records = population_module.load_all_records(repository_root)
    emit("segment", "")
    segmentations = segment.segment_all(repository_root, records, contract.CodonSpec())
    # Read every `final/` table the anchored stack needs now, before the guard is armed — it shares
    # `sandbox`'s path rules and refuses reads of the shipped release once installed.
    anchor_inputs = anchored.load_anchor_inputs(repository_root)

    context = create_context(repository_root)
    results: list[BuildResult] = []
    for ordinal, name in enumerate(wanted):
        emit("start", name)
        result = build_one(
            repository_root, name, output_dir,
            context=context, records=records, segmentations=segmentations,
            anchor_inputs=anchor_inputs,
            threads=threads, timeout_s=timeout_s, step_base=ordinal * _STEP_BAND,
        )
        results.append(result)
        emit("done", name, result)

    # Checked once at the end rather than per artifact: the guard accumulates across the whole run,
    # so this is a statement about every exec the run made.
    sandbox_exec.assert_no_violations(context.guard)
    return results
