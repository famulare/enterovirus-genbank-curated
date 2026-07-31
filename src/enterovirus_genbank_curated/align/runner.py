"""The tool-invocation boundary: the only module that calls `subprocess`.

Every alignment stage that needs `mafft` or `cmalign` calls `run_tool`, never `subprocess` itself
— that is what makes `sandbox_exec.ToolGuard`'s arm token meaningful (see its module docstring):
a single call site is the thing that arms it, so any other code path that tried to shell out
directly would find itself unarmed and refused.

`run_tool` does its own argv/output checks *before* touching `sandbox_exec` at all. That is
deliberate duplication, not redundancy: the guard's checks are what hold even if `run_tool` were
bypassed, and these checks are what turn a violation into a clear `ToolRunError` naming the actual
mistake instead of a guard refusal several stack frames away from where the caller went wrong.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from enterovirus_genbank_curated.align.scratch import Scratch
from enterovirus_genbank_curated.align.toolchain import Toolchain
from enterovirus_genbank_curated.contracts import ContractError
from enterovirus_genbank_curated.sandbox_exec import REQUIRED_CHILD_ENV_KEYS, ToolGuard, arm

STDERR_NAME = "stderr.log"
DISCARDED_STDOUT_NAME = "stdout.discarded"

# Generous per-tool ceiling. The point is to fail rather than hang forever on a pathological input;
# the measured `mafft --add` extrapolation for the largest artifact is well inside this.
DEFAULT_TIMEOUT_S = 6 * 60 * 60
# Eight, and measured rather than guessed — see "Threads are not the memory problem" in
# `align/build.py`. A literal constant, never `os.cpu_count()`: the thread count is a declared
# parameter recorded in provenance, and deriving it from the machine would make an artifact's inputs
# depend on where it was built.
DEFAULT_THREADS = 8
# Both live here rather than in `align/build.py` because they are per-invocation parameters of this
# boundary, and because `cli.py` needs the thread count for its `--threads` default. Reaching it
# through `align.build` made `build_parser()` — which every `evgc` invocation runs — import the
# whole alignment stack for one integer: 16 `align` modules instead of 4. Not a Biopython question
# either way; `genbank/parse.py` imports that on every invocation regardless.


class ToolRunError(ContractError):
    """A tool invocation was refused before running, or did not produce what it declared."""


@dataclass(frozen=True)
class ToolResult:
    tool: str
    argv: tuple[str, ...]
    returncode: int
    run_dir: Path
    stdout_path: Path | None
    stderr_path: Path


def _validate_basename(token: str, *, role: str) -> None:
    if os.path.isabs(token) or os.sep in token or ".." in token.split(os.sep):
        raise ToolRunError(
            f"{role} {token!r} is not a bare filename; run_tool only accepts basenames so a tool "
            f"has no path by which to reach anything outside its scratch run directory"
        )


def run_tool(
    toolchain: Toolchain,
    name: str,
    args: list[str],
    *,
    scratch: Scratch,
    index: int,
    label: str,
    inputs: dict[str, Path],
    outputs: list[str],
    stdout_to: str | None = None,
    threads: int,
    timeout_s: int,
    guard: ToolGuard,
) -> ToolResult:
    """Materialize declared inputs, exec one tool, collect declared outputs.

    Refuses before any exec if the request is malformed: an unknown tool name, an argv or input
    basename that is not a bare filename, or a call with no declared output at all — silently
    producing nothing is exactly how the shipped alignments' provenance gap (backlog B7's sibling
    problem) happens. Refuses after exec on a non-zero exit or a missing declared output.
    """
    if name not in toolchain.tools:
        raise ToolRunError(f"{name!r} is not in the resolved toolchain: {sorted(toolchain.tools)}")
    if not outputs and stdout_to is None:
        raise ToolRunError(
            f"{name}: no declared output and no stdout_to — a tool call with no declared product "
            f"is exactly the shape of a build step that silently produces nothing"
        )
    for token in args:
        _validate_basename(token, role="argv token")
    for basename in inputs:
        _validate_basename(basename, role="input basename")
    for basename in outputs:
        _validate_basename(basename, role="output basename")
    if stdout_to is not None:
        _validate_basename(stdout_to, role="stdout_to basename")

    run_dir = scratch.run_dir(index, label)
    for basename, source in inputs.items():
        shutil.copy2(source, run_dir / basename)

    tool = toolchain.tools[name]
    argv = [tool.path.name, *args]
    env = {
        "PATH": toolchain.child_path(),
        "HOME": str(run_dir),
        "TMPDIR": str(run_dir),
        "LC_ALL": "C",
        "OMP_NUM_THREADS": str(threads),
        "MKL_NUM_THREADS": str(threads),
        "OPENBLAS_NUM_THREADS": str(threads),
    }
    assert set(env) == REQUIRED_CHILD_ENV_KEYS, (
        "run_tool's own env construction drifted from what the tool guard requires"
    )

    stdout_path = run_dir / stdout_to if stdout_to else None
    stderr_path = run_dir / STDERR_NAME
    # subprocess.DEVNULL would have `_get_devnull()` open /dev/null in the parent — outside the
    # write roots the guard enforces, and refused for it. Discard into scratch instead.
    stdout_sink = stdout_path if stdout_path is not None else run_dir / DISCARDED_STDOUT_NAME

    arm(guard)
    with open(stderr_path, "wb") as stderr_handle, open(stdout_sink, "wb") as stdout_handle:
        completed = subprocess.run(
            argv, cwd=run_dir, env=env, stdout=stdout_handle, stderr=stderr_handle,
            timeout=timeout_s, check=False,
        )

    if completed.returncode != 0:
        tail = stderr_path.read_text(encoding="utf-8", errors="replace")[-2000:]
        raise ToolRunError(f"{name} exited {completed.returncode}:\n{tail}")

    missing = [o for o in outputs if not (run_dir / o).is_file()]
    if missing:
        raise ToolRunError(f"{name} did not produce declared output(s): {missing}")

    return ToolResult(
        tool=name,
        argv=tuple(argv),
        returncode=completed.returncode,
        run_dir=run_dir,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
    )
