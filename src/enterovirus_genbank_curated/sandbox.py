"""Enforce, at runtime, that the build reads nothing it has not declared.

The reproducibility claim this repository makes is that a fresh clone regenerates the release from
`raw/` plus the committed registry, with no sibling repository, no home directory, no external
workbook and no network. Documentation cannot enforce that: the private pipeline this work replaces
read `~/Downloads/*.xlsx` and a sibling repo by absolute path for two stages, and nobody noticed
until the source files had been deleted.

So the claim is checked by an audit hook that fails the build on the first undeclared access.

Two properties are deliberate:

- **It raises *and* records.** An audit hook signals by raising, and a caller wrapping its open in
  `try/except OSError` would silence it. Every violation is therefore also appended to a list that
  `assert_no_violations` re-checks after the build, so a swallowed exception still fails.
- **It is irreversible.** `sys.addaudithook` cannot be undone, so a guarded build must be its own
  process. `install_input_guard` is called from the CLI behind an explicit flag; tests exercise it
  through `subprocess`.

What it covers is enumerated in the event tables below rather than described in prose, because the
gap that motivated the 2026-07-29 hardening was precisely a prose claim ("no subprocess", "no write
into `final/`") that the event set did not implement: `os.system` and `os.spawn*` ran children
unseen, and every filesystem mutation that does not go through `open` — `os.remove`, `os.rename`,
`os.replace` — was invisible. Anything not in these tables is not enforced. In particular the
stat family (`os.stat`, `Path.exists`, `os.listdir`, `os.scandir`) raises no event this hook
subscribes to, so existence probes of undeclared paths are **not** caught; see
`docs/reproducibility.md` for the full list of what this does not prove.
"""

from __future__ import annotations

import os
import sys
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path

from enterovirus_genbank_curated.contracts import ContractError

NETWORK_EVENTS = frozenset({
    "socket.connect",
    "socket.getaddrinfo",
    "socket.gethostbyname",
    "socket.sendto",
    "urllib.Request",
    "ftplib.connect",
})

# A child process is not guarded, so it could read anything; every way of starting one has to be
# refused. `os.system` and the `os.spawn*` family were missing until 2026-07-29, which made the
# documented "no subprocess" guarantee false for the two most convenient ways to shell out.
#
# `os.fork` is the one that actually closes the family. On POSIX, `os.spawnl` is implemented in
# Python as fork+exec and raises *only* `os.fork` — verified empirically, not read off the audit
# table, which lists an `os.spawn` event that does not fire on this platform. `os.spawn` is kept for
# platforms where it does. Blocking fork also blocks `multiprocessing`, which is correct: the build
# is single-process by design, and a worker would be outside the guard.
ESCAPE_EVENTS = frozenset({
    "subprocess.Popen",
    "os.exec",
    "os.posix_spawn",
    "os.system",
    "os.spawn",
    "os.fork",
    "os.forkpty",
    "os.vfork",
})

# Filesystem mutations that never raise an `open` event. Each entry maps the audit event to the
# positions of its path arguments, every one of which is checked against the same immutable-tree and
# write-root rules that an `open` for writing gets. Without these, `os.replace(tmp, final/...)` —
# the ordinary way to publish an artifact atomically — rewrites the immutable release while the
# guard reports a clean build.
MUTATION_EVENTS: dict[str, tuple[int, ...]] = {
    "os.remove": (0,),
    "os.rename": (0, 1),
    "os.mkdir": (0,),
    "os.rmdir": (0,),
    "os.truncate": (0,),
    "os.symlink": (1,),
    # Both ends of a hardlink, not just the destination. Checking only the destination let
    # `os.link(final/x, scratch/alias)` succeed — the destination is legitimately in scratch — after
    # which `open(scratch/alias, "w")` writes through the shared inode and rewrites shipped release
    # bytes with zero violations recorded. Linking an inode *out* of a protected tree is itself the
    # mutation to refuse, because nothing downstream can tell the alias apart from a real scratch
    # file.
    "os.link": (0, 1),
    # NOT here, deliberately: `os.mkfifo` and `os.mknod`. Both plant a node inside `final/`
    # undetected, but CPython raises **no audit event** for either — verified empirically, after
    # first adding them to this table and watching the probe still escape. An entry for an event
    # that never fires is itself a check that cannot fail, which is the bug class this repository
    # exists to kill, so the honest move is to leave them out and record the gap in
    # docs/reproducibility.md.
    "os.chmod": (0,),
    "os.chown": (0,),
    "os.chflags": (0,),
    "os.utime": (0,),
    "shutil.rmtree": (0,),
    "shutil.move": (0, 1),
    "shutil.copyfile": (1,),
    "shutil.copymode": (1,),
    "shutil.copystat": (1,),
    "shutil.unpack_archive": (1,),
}

IMMUTABLE_DIRS = ("final", "raw")

# Carried for provenance, read by nothing. `registry/legacy/` holds the frozen output of two private
# stages whose inputs no longer exist; a build that read it would silently reintroduce the
# undeclared upstream dependency this rewrite exists to remove. Enforcing that here rather than by
# grepping the source makes it independent of how a future caller spells the path.
FROZEN_DIRS = ("registry/legacy",)

# Trees a build may not READ at all. `FROZEN_DIRS` for the reason above, plus `final/`, which is the
# comparison target (`docs/pipeline.md` boundary 1). Refusing to *write* `final/` was never enough:
# a build that reads the shipped canonical table can reproduce it perfectly and prove nothing, and
# that read is exactly the mistake a derive stage makes while someone calibrates a rule against the
# oracle. The parity comparison legitimately reads `final/`, which is why the comparison runs in the
# unguarded parent and the build runs in a guarded child — see `oracle/parity.py`.
READ_REFUSED_DIRS = (*FROZEN_DIRS, "final")

_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC


class UndeclaredInputError(ContractError):
    """The build touched something outside its declared inputs."""


@dataclass
class InputGuard:
    """The record of what a guarded process touched.

    Deliberately holds no enable/disable flag. There used to be an `_active: bool = True` that
    nothing ever set, and a `_reentrant: bool` on the instance. Both were reachable from build code
    — `next(o for o in gc.get_objects() if isinstance(o, InputGuard))._active = False` switched the
    whole hook off, network and subprocess checks included. Neutralising a guard is not something
    build code should be able to do by accident, and no caller needed either flag, so reentrancy now
    lives in a thread-local owned by the hook's closure and there is no kill switch at all.
    """

    repository_root: Path
    allowed_read_roots: tuple[str, ...]
    allowed_write_roots: tuple[str, ...]
    violations: list[str] = field(default_factory=list)

    def record(self, message: str) -> None:
        if message not in self.violations:
            self.violations.append(message)


def _roots(*candidates: str | Path | None) -> tuple[str, ...]:
    """Absolute and symlink-resolved forms of each root.

    Both forms are kept because `/tmp` is a symlink to `/private/tmp` on macOS: comparing only
    resolved paths misses a caller that opens the unresolved name, and comparing only literal paths
    misses the reverse.
    """
    out: set[str] = set()
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate)
        for form in (path.absolute(), path.resolve()):
            out.add(os.path.normpath(str(form)))
    return tuple(sorted(out))


def _within(path: str, roots: tuple[str, ...]) -> bool:
    """True only if `path`, **after symlink resolution**, is inside one of `roots`.

    Resolution happens first, not as a fallback. It used to be a fallback — the literal path was
    compared, `True` returned on a match, and `realpath` consulted only when that failed. That made
    the syscall an optimisation, but it also meant resolution could only ever *widen* the allowlist:
    a symlink whose own path sat under an allowed root was admitted without its target being looked
    at. `$TMPDIR/shim -> /etc/hosts` therefore read outside the clone, and a symlink into `$HOME`
    wrote there, both with zero violations recorded and a clean PASS. The realistic form is a
    developer symlinking `raw/sequence.gb.zip` at a copy in `~/Downloads` — precisely the undeclared
    dependency this guard exists to detect.

    Every audited event now pays one `realpath`. Correctness of a narrowing decision cannot be
    conditional on a cheap comparison that answers a different question.
    """
    try:
        candidate = os.path.realpath(path)
    except OSError:
        candidate = path
    return any(candidate == root or candidate.startswith(root + os.sep) for root in roots)


def _describe(path: str) -> str:
    """Name a path, and its target too when the two differ.

    Without this a symlink violation reads as a contradiction: the reported path sits inside the
    scratch directory while the message says the access was outside it.
    """
    try:
        real = os.path.realpath(path)
    except OSError:
        return path
    return path if real == path else f"{path} -> {real}"


def _as_path_str(raw: object) -> str | None:
    """Normalize an audit-event path argument, or None if it is not a path at all."""
    if raw is None or isinstance(raw, int):
        return None  # an already-open descriptor; the call that opened it was itself audited
    if isinstance(raw, bytes):
        raw = os.fsdecode(raw)
    elif not isinstance(raw, str):
        raw = str(raw)
    return os.path.normpath(os.path.abspath(raw))


class ScratchRootError(ContractError):
    """The scratch directory the guard was asked to trust is not trustworthy."""


def _safe_scratch_root() -> str | None:
    """The temp directory, unless honouring it would allowlist part of `$HOME`.

    The guard used to fold `tempfile.gettempdir()` straight into both the read and the write roots.
    That reads `$TMPDIR`, which the caller controls, so `TMPDIR=$HOME` made the whole home directory
    readable *and* writable under a clean PASS — reintroducing exactly the `~/Downloads/*.xlsx`
    dependency this guard exists to catch, and nullifying the "the home directory is not permitted"
    property stated one sentence away from it in the docs. `TMPDIR=~/tmp` is a common real setup, so
    this is an accident waiting to happen rather than an attack.

    Returning None drops the temp root from the allowlist entirely, which is the safe direction: the
    build then fails loudly on its own scratch writes instead of silently trusting `$HOME`.
    """
    candidate = tempfile.gettempdir()
    home = os.path.realpath(str(Path.home()))
    resolved = os.path.realpath(candidate)
    if resolved == home or resolved.startswith(home + os.sep):
        return None
    return candidate


def _interpreter_roots() -> tuple[str, ...]:
    """Everything the interpreter and its installed packages legitimately read.

    Imports, `site-packages`, DuckDB's bundled extensions and Biopython's data files all live
    outside the clone. Excluding them would make the guard fire on `import`, which tests nothing.
    Entries of `sys.path` that fall *inside* the clone are already covered by the repository root.
    """
    candidates: list[str | Path | None] = [
        sys.prefix, sys.base_prefix, sys.exec_prefix, sys.base_exec_prefix,
        _safe_scratch_root(), "/tmp", "/var/folders",
    ]
    candidates.extend(entry for entry in sys.path if entry)
    # Shared libraries the dynamic loader pulls in, and the locale/timezone data the stdlib reads.
    candidates.extend(["/usr/lib", "/usr/share", "/System/Library", "/Library/Frameworks",
                       "/dev/null", "/dev/urandom", "/etc/localtime"])
    return _roots(*candidates)


def install_input_guard(
    repository_root: Path, *, extra_read_roots: tuple[Path, ...] = ()
) -> InputGuard:
    """Install the audit hook. The hook cannot be removed for the life of the process.

    Raises `ScratchRootError` when `$TMPDIR` points inside `$HOME`, rather than quietly allowlisting
    the home directory. Re-run with a `TMPDIR` outside `$HOME`, or unset it.
    """
    root = repository_root.resolve()

    scratch = _safe_scratch_root()
    if scratch is None:
        raise ScratchRootError(
            f"$TMPDIR resolves inside the home directory ({tempfile.gettempdir()}), so trusting it "
            f"as scratch space would allowlist part of $HOME for both reading and writing — the "
            f"exact undeclared-dependency class this guard exists to catch. Re-run with TMPDIR "
            f"outside $HOME, or unset it."
        )

    read_roots = _roots(root, scratch, *extra_read_roots) + _interpreter_roots()
    write_roots = _roots(root, scratch)
    immutable = _roots(*[root / name for name in IMMUTABLE_DIRS])
    frozen = _roots(*[root / name for name in FROZEN_DIRS])
    read_refused = _roots(*[root / name for name in READ_REFUSED_DIRS])

    guard = InputGuard(
        repository_root=root,
        allowed_read_roots=read_roots,
        allowed_write_roots=write_roots,
    )

    def mutation_problem(path: str) -> str:
        if _within(path, frozen):
            return f"refusing to mutate a frozen inputs-of-record tree: {_describe(path)}"
        if _within(path, immutable):
            return f"refusing to write into an immutable release tree: {_describe(path)}"
        if not _within(path, guard.allowed_write_roots):
            return f"write outside the clone and the scratch directory: {_describe(path)}"
        return ""

    # Thread-local, not per-instance. A single shared flag was set for the whole process while the
    # hook worked, so any *other* thread doing I/O inside that window was skipped entirely — one
    # undeclared read slipped through undetected in a two-thread probe. `os.fork` is refused, which
    # covers `multiprocessing`, but `threading` is not and cannot be.
    local = threading.local()

    def hook(event: str, args: tuple[object, ...]) -> None:
        if getattr(local, "busy", False):
            return
        if event in NETWORK_EVENTS:
            local.busy = True
            try:
                message = f"network access is not a declared input: {event}{args!r:.200}"
                guard.record(message)
            finally:
                local.busy = False
            raise UndeclaredInputError(message)
        if event in ESCAPE_EVENTS:
            local.busy = True
            try:
                message = f"subprocess execution would escape the guard: {event}{args!r:.200}"
                guard.record(message)
            finally:
                local.busy = False
            raise UndeclaredInputError(message)
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
                    trouble = mutation_problem(path)
                    if trouble:
                        found.append(f"{event} would mutate an undeclared path: {trouble}")
                for message in found:
                    guard.record(message)
            finally:
                local.busy = False
            if found:
                raise UndeclaredInputError(found[0])
            return
        if event != "open":
            return

        raw_path, mode, flags = (list(args) + [None, None, None])[:3]
        path = _as_path_str(raw_path)
        if path is None:
            return

        local.busy = True
        try:
            writing = (isinstance(mode, str) and any(c in mode for c in "wxa+")) or (
                isinstance(flags, int) and bool(flags & _WRITE_FLAGS)
            )
            problem = ""
            if _within(path, frozen):
                problem = (
                    f"the frozen legacy registries are carried for provenance and read by nothing; "
                    f"the build may not open them: {_describe(path)}"
                )
            elif not writing and _within(path, read_refused):
                problem = (
                    f"the shipped release is a comparison target, never a pipeline input; the "
                    f"build may not read it: {_describe(path)}"
                )
            elif os.path.isdir(path) and (_within(path, immutable) or _within(path, frozen)):
                # A directory descriptor is the one thing that gets a caller *past* every check in
                # this hook: `openat`-style calls take `dir_fd=` plus a bare relative name, and the
                # audit event carries neither, so the guard judges `CWD/name` while the kernel acts
                # inside the protected tree. One keyword argument defeated the immutable-tree rule,
                # the atomic-publish rule and the frozen-read rule together.
                #
                # The hook cannot see `dir_fd`, so this refuses the descriptor instead of the use.
                # It is a partial defence — a caller who already holds a descriptor to a parent, or
                # who walks in via a C extension, is unaffected — and the residual is documented in
                # docs/reproducibility.md rather than claimed as closed.
                problem = (
                    f"refusing to open a directory inside a protected tree, because a directory "
                    f"descriptor bypasses every path check this guard makes: {_describe(path)}"
                )
            elif writing and _within(path, immutable):
                problem = (
                    f"refusing to write into an immutable release tree: {_describe(path)}"
                )
            elif writing and not _within(path, guard.allowed_write_roots):
                problem = f"write outside the clone and the scratch directory: {_describe(path)}"
            elif not _within(path, guard.allowed_read_roots):
                problem = f"read of an undeclared path outside the clone: {_describe(path)}"
            if problem:
                guard.record(problem)
        finally:
            local.busy = False

        if problem:
            raise UndeclaredInputError(problem)

    sys.addaudithook(hook)
    return guard


def assert_no_violations(guard: InputGuard) -> None:
    """Fail the build if anything was recorded, even if the raise was swallowed."""
    if guard.violations:
        detail = "; ".join(guard.violations)
        raise UndeclaredInputError(
            f"the build touched {len(guard.violations)} undeclared input(s): {detail}"
        )
