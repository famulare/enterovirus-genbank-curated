"""Permit exec of a pinned binary set, and nothing else.

This is a **weaker** guard than `sandbox.install_input_guard`, deliberately and visibly. It exists
because the alignment stage cannot run under the stronger one: `sandbox.ESCAPE_EVENTS` refuses
every way of starting a child process, for the stated reason that a child is unguarded and could
read anything. The alignment stage genuinely needs to run `mafft` and `cmalign`, so the honest
move is a second, differently-named mechanism with its own "what it does not prove" list — not a
flag on the first one that quietly reinterprets what it promises.

## What is shared, and what is not

Every path decision — what counts as `final/`, what counts as the frozen legacy tree, what counts
as scratch — comes from `sandbox._path_rule_set`, the same function `install_input_guard` uses. A
second copy of those tables would be the exact failure `sandbox.py` exists to prevent. Only the
*exec* decision differs: where the input guard refuses every child-process event unconditionally,
this guard permits exactly one call shape — the one `align.runner.run_tool` makes — and refuses
everything else, including all the ways `sandbox.ESCAPE_EVENTS` already refuses.

## One event, not two — a design correction made by measuring, not assuming

An earlier draft of this module keyed the argv/cwd/env checks on `subprocess.Popen` and the binary
allowlist on `_posixsubprocess.fork_exec`, on the strength of an initial measurement (CPython
3.14.6, macOS) showing both fire, in order, for one `subprocess.run(...)` call. Running the exact
same probe under the pixi `align` environment's actual interpreter — CPython **3.12.13**, the
version this repository is pinned to — showed `_posixsubprocess.fork_exec` **never fires at all**.
Confirmed a second time against an unrelated CPython 3.12.13 build (`uv`-managed, not
conda-forge's), so this is a 3.12-vs-3.14 CPython behaviour difference, not an artefact of one
distribution. Had the two-event design shipped, the binary allowlist it depended on would have
silently never run on the one interpreter version this repository actually uses — a gap that would
have passed every test written against 3.14 and failed open in production.

So the design is one event: `subprocess.Popen`, carrying `(executable, argv, cwd, env)` where
`executable` is the **bare name as passed**, not resolved against `PATH`. Everything —
cwd/env/argv checks and the binary allowlist — is checked there. The allowlist check resolves
`executable` against `env["PATH"]` **in Python**, replicating what `execvpe` does: split `PATH` on
`os.pathsep`, take the first candidate directory whose `executable`-named file exists and is
executable, and require that path — after symlink resolution — to be in the allowlist. This is
strictly more portable than depending on `_posixsubprocess.fork_exec`'s candidate tuple: it needs
nothing from the interpreter beyond the one event every measured CPython version raises for
`subprocess.Popen`.

`os.posix_spawn`, `os.fork`, `os.forkpty`, `os.vfork`, `os.system` and `os.exec*` are refused
unconditionally, on every platform, regardless of arming — `align.runner.run_tool` only ever calls
`subprocess.run`, so there is no legitimate call this guard needs to admit through any of them.

## What this proves

Within a single `run_tool` call: the executable, resolved against the declared `PATH` the same way
the child's own loader would resolve it, was inside the pinned allowlist after symlink resolution;
`cwd` was inside the declared scratch directory; the environment held exactly the declared keys,
no more and no fewer; argv contained no absolute path, path separator, or `..`, so the child had no
path by which to name anything outside its own scratch directory; every other way of starting a
child — `os.system`, `os.exec*`, `os.spawn*`, an unarmed `subprocess.Popen`, a bare `os.fork` — was
refused exactly as it is under `install_input_guard`; and network access, writes into
`final/`/`raw/`, and reads of the frozen legacy tree were all refused too, via the same
`sandbox._path_rule_set` tables.

## What this does not prove

- **The child is not guarded. It is starved.** No audit hook exists inside the child process, so
  nothing observes what it reads once it starts. The property under test is that the child was
  *handed no path* by which to reach `final/` — a scratch cwd and basename-only argv — not that it
  was prevented from constructing one by some other means.
- **The process tree below the first child is unconstrained.** `mafft` and `mafft-xinsi` are shell
  scripts that invoke sibling binaries by bare name, resolved against whatever `PATH` the child
  inherits. Narrowing that `PATH` to the pinned prefix bounds *which* binaries those siblings can
  be; it does not audit them the way this module audits the first exec.
- **The allowlist check resolves `PATH` itself; it does not observe what the kernel resolves.**
  Between this check and the actual `execve`, `PATH`-directory contents could change (a genuine
  TOCTOU window), and — more importantly — this module's own resolution could disagree with the
  C library's if the two ever implement `PATH` search differently. Both are real, if narrow,
  residual gaps; the mitigation is the same one `sandbox._within` already relies on for symlinks:
  this guard is aimed at an accidental undeclared dependency, not an adversary racing the
  filesystem.
- **The arm token is a cooperative signal, not a security boundary.** Any in-process code that can
  reach the guard's thread-local — which any code running inside the guarded process legitimately
  can, since Python enforces no privacy — could set it without going through `run_tool`. The honest
  claim is "`run_tool` is the only call site that does not have to work at it", not "the only
  possible exec site". `sandbox.InputGuard`'s own docstring makes the same distinction for its
  now-removed kill switch.
- **It says nothing about determinism or correctness.** Access and exec scope only, exactly as for
  `install_input_guard`. Whether the alignment output is right is a separate, later gate.
"""

from __future__ import annotations

import os
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path

from enterovirus_genbank_curated.contracts import ContractError
from enterovirus_genbank_curated.sandbox import (
    _WRITE_FLAGS,
    ESCAPE_EVENTS,
    MUTATION_EVENTS,
    NETWORK_EVENTS,
    ScratchRootError,
    _as_path_str,
    _describe,
    _mutation_problem,
    _path_rule_set,
    _safe_scratch_root,
    _within,
)

# Refused unconditionally, on every platform, regardless of the arm token. `align.runner.run_tool`
# never calls any of these directly — only `subprocess.run`, which raises `subprocess.Popen` (see
# the module docstring for why that is the only event this guard needs).
ALWAYS_REFUSED_EVENTS = ESCAPE_EVENTS - {"subprocess.Popen"}

POPEN_EVENT = "subprocess.Popen"

# The exact environment keys a child may see. Exact equality, not a subset: a dict with one extra
# key (`LD_PRELOAD`, an inherited `PYTHONPATH`, a `MAFFT_BINARIES` pointing elsewhere) is the leak,
# and a subset check would let it through.
REQUIRED_CHILD_ENV_KEYS = frozenset({
    "PATH", "HOME", "TMPDIR", "LC_ALL",
    "OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS",
})


class ToolExecError(ContractError):
    """An exec attempt did not match the one shape `run_tool` is permitted to make."""


@dataclass
class ToolGuard:
    """The record of what a guarded process was permitted to exec.

    No enable/disable flag, for the same reason `sandbox.InputGuard` has none: a flag reachable
    from build code is a flag build code can clear by accident. `_thread_state` is not that: it is
    a *narrower* grant, not a kill switch — clearing it (which `arm()` alone does, and only for one
    call) refuses exec entirely rather than permitting more of it, so build code reaching in and
    mutating it can only ever make the guard stricter, never weaker.

    The thread-local lives here, as a real field, rather than in a closure `install_tool_guard`
    hands back separately — so `arm()` has one obvious place to reach, instead of a second hidden
    object a reader has to go find. It holds two flags: `busy` (hook reentrancy, same purpose as
    `install_input_guard`'s) and the one-shot `pending` token `arm()` sets.
    """

    repository_root: Path
    scratch_root: Path
    allowed_executables: frozenset[str]
    violations: list[str] = field(default_factory=list)
    execs: list[dict[str, object]] = field(default_factory=list)
    _thread_state: threading.local = field(
        default_factory=threading.local, repr=False, compare=False
    )

    def record(self, message: str) -> None:
        if message not in self.violations:
            self.violations.append(message)


def _resolve_against_path(executable: str, path_value: str) -> str | None:
    """Replicate `execvpe`'s search: the first `PATH` entry containing an executable file wins.

    Done in Python because the audit event carrying `PATH`-resolved candidates
    (`_posixsubprocess.fork_exec`) does not fire on CPython 3.12 — see the module docstring. If
    `executable` already contains a path separator, `execvpe` does not search `PATH` at all; the
    caller passes it through unchanged in that case, which the argv/absolute-path rule downstream
    still governs.
    """
    if os.sep in executable:
        return executable if os.path.isfile(executable) else None
    for directory in path_value.split(os.pathsep):
        if not directory:
            continue
        candidate = os.path.join(directory, executable)
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def install_tool_guard(
    repository_root: Path, *, scratch_root: Path, allowed_executables: frozenset[str]
) -> ToolGuard:
    """Install the audit hook. Irreversible, like `install_input_guard` — a guarded build is its
    own process.

    `scratch_root` must live inside the default scratch tree (`$TMPDIR`, resolved the same way
    `install_input_guard` resolves it) — `align.scratch.Scratch` always creates one via
    `tempfile.mkdtemp()`, which guarantees this. The constraint is enforced rather than assumed: a
    caller-supplied `scratch_root` outside that tree would be readable under `_path_rule_set`'s
    `read_roots` (which include the whole scratch tree) but not writable, since `write_roots` is
    computed from the same tree and nothing here widens it — a silent, confusing failure mode this
    guard refuses up front instead.
    """
    root = repository_root.resolve()
    scratch = _safe_scratch_root()
    if scratch is None:
        raise ScratchRootError(
            "$TMPDIR resolves inside the home directory, which the input guard already refuses to "
            "trust; the tool guard inherits the same refusal rather than silently trusting it."
        )

    resolved_scratch_root = str(scratch_root.resolve())
    if not _within(resolved_scratch_root, (os.path.realpath(scratch),)):
        raise ToolExecError(
            f"scratch_root {resolved_scratch_root} is not inside the default scratch tree "
            f"({os.path.realpath(scratch)}); create it with tempfile.mkdtemp() (see "
            f"align.scratch.Scratch), not an arbitrary directory"
        )

    rules = _path_rule_set(root, scratch)
    resolved_allowlist = frozenset(
        os.path.realpath(str(root / executable)) if not os.path.isabs(executable)
        else os.path.realpath(executable)
        for executable in allowed_executables
    )
    for path in resolved_allowlist:
        if not _within(path, (os.path.realpath(str(root)),)):
            raise ToolExecError(
                f"allowlisted executable {path!r} is outside the clone; the alignment toolchain "
                f"must live inside the repository (see registry/toolchain.json and pixi.toml)"
            )

    guard = ToolGuard(
        repository_root=root, scratch_root=Path(resolved_scratch_root),
        allowed_executables=resolved_allowlist,
    )
    local = guard._thread_state

    def refuse(message: str) -> None:
        guard.record(message)
        raise ToolExecError(message)

    def hook(event: str, args: tuple[object, ...]) -> None:
        if getattr(local, "busy", False):
            return

        if event in NETWORK_EVENTS:
            local.busy = True
            try:
                guard.record(f"network access is not a declared input: {event}{args!r:.200}")
            finally:
                local.busy = False
            raise ToolExecError(guard.violations[-1])

        if event in ALWAYS_REFUSED_EVENTS:
            local.busy = True
            try:
                guard.record(
                    f"refused unconditionally, regardless of arming: {event}{args!r:.200}"
                )
            finally:
                local.busy = False
            raise ToolExecError(guard.violations[-1])

        if event in MUTATION_EVENTS:
            local.busy = True
            try:
                found = []
                for index in MUTATION_EVENTS[event]:
                    if index >= len(args):
                        continue
                    path = _as_path_str(args[index])
                    if path is None:
                        continue
                    trouble = _mutation_problem(path, rules)
                    if trouble:
                        found.append(f"{event} would mutate an undeclared path: {trouble}")
                for message in found:
                    guard.record(message)
            finally:
                local.busy = False
            if found:
                raise ToolExecError(found[0])
            return

        # `open` is not in any event-name table above, so without an explicit branch for it this
        # hook silently never sees a plain `Path.write_text()` into `final/` or a plain
        # `Path.read_bytes()` from `registry/legacy/` — both go through `open`, not through any of
        # `NETWORK_EVENTS`/`ESCAPE_EVENTS`/`MUTATION_EVENTS`. Found by a falsification test that
        # planted exactly those two writes/reads and watched them pass with a clean guard; ported
        # from `install_input_guard`'s own `open` handling, against the same `rules`.
        if event == "open":
            local.busy = True
            try:
                raw_path, mode, flags = (list(args) + [None, None, None])[:3]
                path = _as_path_str(raw_path)
                if path is None:
                    return
                writing = (isinstance(mode, str) and any(c in mode for c in "wxa+")) or (
                    isinstance(flags, int) and bool(flags & _WRITE_FLAGS)
                )
                problem = ""
                if _within(path, rules.frozen):
                    problem = (
                        f"the frozen legacy registries are carried for provenance and read by "
                        f"nothing; the build may not open them: {_describe(path)}"
                    )
                elif not writing and _within(path, rules.read_refused):
                    problem = (
                        f"the shipped release is a comparison target, never a pipeline input; "
                        f"the build may not read it: {_describe(path)}"
                    )
                elif os.path.isdir(path) and (
                    _within(path, rules.immutable) or _within(path, rules.frozen)
                ):
                    problem = (
                        f"refusing to open a directory inside a protected tree, because a "
                        f"directory descriptor bypasses every path check this guard makes: "
                        f"{_describe(path)}"
                    )
                elif writing and _within(path, rules.immutable):
                    problem = (
                        f"refusing to write into an immutable release tree: {_describe(path)}"
                    )
                elif writing and not _within(path, rules.write_roots):
                    problem = (
                        f"write outside the clone and the scratch directory: {_describe(path)}"
                    )
                elif not _within(path, rules.read_roots):
                    problem = f"read of an undeclared path outside the clone: {_describe(path)}"
                if problem:
                    refuse(problem)
            finally:
                local.busy = False
            return

        if event == POPEN_EVENT:
            local.busy = True
            try:
                # Consumed the instant the event is observed, regardless of whether the checks
                # below pass. A token left alive after a *failed* check would let a later,
                # unrelated call reuse it without re-arming — the one-shot property has to hold on
                # the failure path, not only the success path.
                permitted = getattr(local, "pending", False)
                local.pending = False
                if not permitted:
                    refuse(
                        f"exec attempted outside an armed run_tool() call: {event}{args!r:.200}"
                    )
                executable, argv, cwd, env = (list(args) + [None] * 4)[:4]
                for token in list(argv or [])[1:]:
                    token = os.fsdecode(token) if isinstance(token, bytes) else str(token)
                    if os.path.isabs(token) or os.sep in token or ".." in token.split(os.sep):
                        refuse(
                            f"argv token {token!r} is not a bare filename in the run directory; "
                            f"a tool given only basenames in scratch has no path elsewhere"
                        )
                if cwd is None or not _within(str(cwd), (str(guard.scratch_root),)):
                    refuse(f"exec cwd {cwd!r} is not inside the declared scratch directory")
                if env is None or set(env) != REQUIRED_CHILD_ENV_KEYS:
                    refuse(
                        f"exec env keys {sorted(env or {})} do not exactly match the declared "
                        f"{sorted(REQUIRED_CHILD_ENV_KEYS)}"
                    )
                exe = os.fsdecode(executable) if isinstance(executable, bytes) else str(executable)
                candidate = _resolve_against_path(exe, env["PATH"])
                if candidate is None:
                    refuse(f"{exe!r} does not resolve against PATH {env['PATH']!r}")
                resolved = os.path.realpath(candidate)
                if resolved not in guard.allowed_executables:
                    refuse(
                        f"{resolved} is not in the allowlisted executable set "
                        f"{sorted(guard.allowed_executables)}"
                    )
                guard.execs.append({"path": resolved, "argv": argv})
            finally:
                local.busy = False
            return

    sys.addaudithook(hook)
    return guard


def arm(guard: ToolGuard) -> None:
    """Open the one-shot window `run_tool` execs inside.

    Not a context manager on purpose: the caller (`align.runner.run_tool`) both arms and
    immediately calls `subprocess.run` in the same function, so there is no window in which some
    other code on the same thread could observe "armed" and use it — `subprocess.Popen`'s audit
    event fires synchronously inside `Popen.__init__`, before `run_tool` regains control.
    """
    guard._thread_state.pending = True


def assert_no_violations(guard: ToolGuard) -> None:
    if guard.violations:
        detail = "; ".join(guard.violations)
        raise ToolExecError(
            f"the tool guard recorded {len(guard.violations)} violation(s): {detail}"
        )
