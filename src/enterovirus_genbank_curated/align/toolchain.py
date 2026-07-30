"""Resolve the native alignment binaries and prove they are the ones the lock declares.

Two independent sources of truth, cross-checked against each other, so neither can drift alone:

- **static** — `.pixi/envs/<env>/conda-meta/<pkg>-<version>-<build>.json`, read as an ordinary file
  inside the clone. No `pixi` subprocess, no network.
- **dynamic** — the binary's own self-report, obtained by running it.

Either alone is satisfiable by a lie. Together they are not: the static half catches a lock that
resolved something unexpected, and the dynamic half catches a `PATH` or `MAFFT_BINARIES` pointing at
a binary somewhere other than the prefix just inspected. Upstream recorded neither, so a
`pixi update` there could silently change alignment output.

## Measured facts this module encodes

Version probes are quirky and the quirks were measured on the real binaries rather than assumed:

- `mafft --version` writes `v7.526 (2024/Apr/26)` to **stderr** and exits **0**. Both halves matter:
  a probe reading only stdout sees nothing, and one requiring a nonzero exit (as an earlier design
  predicted) would mis-report a working mafft as broken. So exit codes are not asserted at
  all, and stdout and stderr are both searched.
- `cmalign -h` and `cmbuild -h` write `# INFERNAL 1.1.5 (Sep 2023)` to **stdout** and exit 0.

The child environment uses a **PATH prefix**, not `PATH=<prefix>/bin` alone. mafft's conda package
declares only `gawk`, so the prefix has no `dirname`, `basename`, `uname` or `grep`, and mafft's
entry points are POSIX shell scripts that need all four — verified by running it with `env -i` and
watching it fail on each in turn. `/usr/bin:/bin` is appended for exactly that reason, and no conda
`python` or `perl` ends up ahead of anything the parent uses.

`Tool.sha256` is recorded but **not asserted**. A conda repack bumps the build string, so the build
string already carries that signal; asserting the digest would add nothing while creating a check
that fires on every platform the declaration does not enumerate. An assertion that cannot pass is
worse than no assertion.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from enterovirus_genbank_curated.contracts import ContractError

TOOLCHAIN_DECLARATION = "registry/toolchain.json"
PIXI_LOCK = "pixi.lock"
PIXI_MANIFEST = "pixi.toml"

ENV_ALIGN = "align"
ENV_SEED = "seed"

# The platform whose bytes are gated. Cross-platform byte identity is deliberately not claimed:
# score ties in mafft and Infernal break on floating-point comparisons, and libm differs.
CANONICAL_PLATFORM = "linux-64"

# Appended to the child's PATH because the conda prefix is not self-sufficient. See the module
# docstring for the measurement.
SYSTEM_PATH_SUFFIX = ("/usr/bin", "/bin")


@dataclass(frozen=True)
class ToolProbe:
    package: str
    argv: tuple[str, ...]
    pattern: re.Pattern[str]


# name -> how to identify it. Exit codes are deliberately absent from this table: `mafft --version`
# and `mafft-xinsi --version` both exit 0 and write to stderr; the other three write to stdout.
# Measured directly rather than assumed, same as the routine tier's mafft/Infernal probes.
PROBES: dict[str, ToolProbe] = {
    "mafft": ToolProbe("mafft", ("--version",), re.compile(r"v(\d+\.\d+)")),
    "mafft-linsi": ToolProbe("mafft", ("--version",), re.compile(r"v(\d+\.\d+)")),
    "mafft-xinsi": ToolProbe("mafft", ("--version",), re.compile(r"v(\d+\.\d+)")),
    "cmalign": ToolProbe("infernal", ("-h",), re.compile(r"INFERNAL (\d+\.\d+\.\d+)")),
    "cmbuild": ToolProbe("infernal", ("-h",), re.compile(r"INFERNAL (\d+\.\d+\.\d+)")),
    "RNAalifold": ToolProbe("viennarna", ("--version",), re.compile(r"RNAalifold (\d+\.\d+\.\d+)")),
}

# Tools each tier is allowed to need. Derived by union in the completeness test rather than
# hand-maintained in two places.
#
# The seed tier's set matches upstream's own `REQUIRED_TOOLS` for the NCR structural build
# (`mafft-xinsi`, `RNAalifold`, `cmbuild`, `cmalign`) exactly -- not `mafft`/`mafft-linsi`, which
# are routine-tier CDS tools the seed tier has no use for.
ROUTINE_TOOLS = ("mafft", "mafft-linsi", "cmalign")
SEED_TOOLS = ("mafft-xinsi", "RNAalifold", "cmbuild", "cmalign")


class ToolchainError(ContractError):
    """The resolved toolchain is not the one the repository declares."""


@dataclass(frozen=True)
class Tool:
    name: str
    package: str
    path: Path
    version: str          # from conda-meta
    build: str             # from conda-meta
    self_reported: str     # verbatim line the binary printed
    sha256: str


@dataclass(frozen=True)
class Toolchain:
    environment: str
    platform: str
    prefix: Path
    bin_dir: Path
    tools: dict[str, Tool]
    # Populated only for the seed tier, since only mafft-xinsi needs it. None on the routine tier.
    mxscarnamod: Path | None = None

    def child_path(self) -> str:
        return os.pathsep.join([str(self.bin_dir), *SYSTEM_PATH_SUFFIX])

    def provenance(self) -> dict:
        return {
            "environment": self.environment,
            "platform": self.platform,
            "tools": {
                name: {
                    "package": tool.package,
                    "version": tool.version,
                    "build": tool.build,
                    "self_reported": tool.self_reported,
                    "sha256": tool.sha256,
                }
                for name, tool in sorted(self.tools.items())
            },
        }


def current_platform() -> str:
    machine = platform.machine()
    system = platform.system()
    if system == "Darwin" and machine == "arm64":
        return "osx-arm64"
    if system == "Linux" and machine in {"x86_64", "AMD64"}:
        return "linux-64"
    raise ToolchainError(
        f"unsupported platform {system}/{machine}; pixi.toml declares linux-64 and osx-arm64"
    )


def _conda_meta(prefix: Path) -> dict[str, dict]:
    meta_dir = prefix / "conda-meta"
    if not meta_dir.is_dir():
        raise ToolchainError(
            f"{meta_dir} does not exist. Reconstruct the environment with "
            f"`pixi install --locked -e {ENV_ALIGN}`."
        )
    out: dict[str, dict] = {}
    for path in sorted(meta_dir.glob("*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ToolchainError(f"cannot read {path}: {exc}") from exc
        name = record.get("name")
        if name:
            out[name] = record
    return out


def _self_report(binary: Path, probe: ToolProbe, bin_dir: Path, scratch: Path) -> str:
    """Run the binary and return the line carrying its version.

    Exit codes are not checked: `mafft --version` exits 0 but writes to stderr, and a table that
    asserted either polarity would be wrong for one of the two tool families.
    """
    env = {
        "PATH": os.pathsep.join([str(bin_dir), *SYSTEM_PATH_SUFFIX]),
        "HOME": str(scratch),
        "TMPDIR": str(scratch),
        "LC_ALL": "C",
    }
    try:
        result = subprocess.run(  # noqa: S603 - argv is fixed by PROBES, never user input
            [str(binary), *probe.argv],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(scratch),
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ToolchainError(f"cannot run {binary}: {exc}") from exc
    for line in (result.stdout or "").splitlines() + (result.stderr or "").splitlines():
        if probe.pattern.search(line):
            return line.strip()
    raise ToolchainError(
        f"{binary.name} did not report a version matching {probe.pattern.pattern!r}; "
        f"stdout={result.stdout[:200]!r} stderr={result.stderr[:200]!r}"
    )


def resolve(repository_root: Path, *, environment: str = ENV_ALIGN, scratch: Path | None = None,
            tools: tuple[str, ...] = ROUTINE_TOOLS) -> Toolchain:
    """Locate the tools, read their conda records, and make each one identify itself."""
    prefix = (repository_root / ".pixi" / "envs" / environment).resolve()
    bin_dir = prefix / "bin"
    if not bin_dir.is_dir():
        raise ToolchainError(
            f"{bin_dir} does not exist. Reconstruct it with "
            f"`pixi install --locked -e {environment}`."
        )
    root = repository_root.resolve()
    meta = _conda_meta(prefix)
    work = scratch or Path(os.environ.get("TMPDIR", "/tmp"))

    resolved: dict[str, Tool] = {}
    for name in tools:
        probe = PROBES.get(name)
        if probe is None:
            raise ToolchainError(f"no version probe declared for {name!r}")
        binary = bin_dir / name
        if not binary.exists():
            raise ToolchainError(f"{binary} is missing from the {environment} environment")
        real = Path(os.path.realpath(binary))
        # The property that keeps the alignment stage inside the existing guard's read roots
        # without widening the allowlist. Measured to hold: rattler hardlinks rather than
        # symlinking to a cache under $HOME.
        if not str(real).startswith(str(root) + os.sep):
            raise ToolchainError(
                f"{name} resolves to {real}, outside the clone. The alignment stage requires its "
                f"binaries to live inside the repository so that reading and exec'ing them needs "
                f"no widening of sandbox.py's read roots."
            )
        record = meta.get(probe.package)
        if record is None:
            raise ToolchainError(
                f"{probe.package} has no conda-meta record in {prefix}; cannot establish "
                f"{name}'s identity statically"
            )
        reported = _self_report(binary, probe, bin_dir, work)
        found = probe.pattern.search(reported)
        assert found is not None  # _self_report only returns a matching line
        if not record["version"].startswith(found.group(1)):
            raise ToolchainError(
                f"{name} reports version {found.group(1)} but conda-meta declares "
                f"{record['version']}. Something other than the pixi prefix is being run."
            )
        resolved[name] = Tool(
            name=name,
            package=probe.package,
            path=binary,
            version=record["version"],
            build=record["build"],
            self_reported=reported,
            sha256=hashlib.sha256(real.read_bytes()).hexdigest(),
        )

    mxscarnamod = None
    if environment == ENV_SEED:
        mxscarnamod = prefix / "libexec" / "mafft" / "mxscarnamod"
        if not mxscarnamod.is_file():
            raise ToolchainError(
                f"{mxscarnamod} is missing. bioconda's mafft package omits it; build it with "
                f"scripts/setup_mxscarna.sh (network + a C++ compiler, not expected to run on a "
                f"fresh clone)."
            )
        # Content-based, not exit-code-based: mxscarnamod refuses to run with no arguments and
        # exits 1 by design, which is not the same thing as being missing or broken. Captured
        # separately from the exit-code check for the same reason scripts/setup_mxscarna.sh does:
        # under `pipefail`, piping it straight into a grep would fail the check on its designed
        # non-zero exit regardless of whether the probe text was found.
        try:
            probe = subprocess.run(
                [str(mxscarnamod)],
                capture_output=True,
                text=True,
                env={"PATH": str(bin_dir), "HOME": str(work), "LC_ALL": "C"},
                cwd=str(work),
                timeout=30,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise ToolchainError(f"cannot run {mxscarnamod}: {exc}") from exc
        if "SCARNA" not in (probe.stdout + probe.stderr):
            raise ToolchainError(
                f"{mxscarnamod} exists but does not respond to the liveness probe; it may be "
                f"corrupted or built for the wrong platform"
            )

    return Toolchain(
        environment=environment,
        platform=current_platform(),
        prefix=prefix,
        bin_dir=bin_dir,
        tools=resolved,
        mxscarnamod=mxscarnamod,
    )


def load_declaration(repository_root: Path) -> dict:
    path = repository_root / TOOLCHAIN_DECLARATION
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ToolchainError(f"cannot read {TOOLCHAIN_DECLARATION}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ToolchainError(f"{TOOLCHAIN_DECLARATION} is not valid JSON: {exc}") from exc


def lock_sha256(repository_root: Path) -> str:
    return hashlib.sha256((repository_root / PIXI_LOCK).read_bytes()).hexdigest()


def assert_declared(repository_root: Path, toolchain: Toolchain) -> None:
    """Require the resolved toolchain to match `registry/toolchain.json` for this platform."""
    declaration = load_declaration(repository_root)

    expected_lock = declaration.get("pixi_lock_sha256")
    actual_lock = lock_sha256(repository_root)
    if expected_lock != actual_lock:
        raise ToolchainError(
            f"pixi.lock sha256 {actual_lock} does not match {TOOLCHAIN_DECLARATION} "
            f"({expected_lock}). The environment moved; re-stamp the declaration and review the "
            f"lock diff before rebuilding any alignment."
        )

    platforms = declaration.get("platforms", {})
    entry = platforms.get(toolchain.platform, {}).get(toolchain.environment)
    if entry is None:
        raise ToolchainError(
            f"{TOOLCHAIN_DECLARATION} declares nothing for "
            f"{toolchain.platform}/{toolchain.environment}"
        )
    for name, tool in sorted(toolchain.tools.items()):
        declared = entry.get(tool.package)
        if declared is None:
            raise ToolchainError(
                f"{TOOLCHAIN_DECLARATION} does not declare {tool.package} for "
                f"{toolchain.platform}/{toolchain.environment}"
            )
        for field in ("version", "build"):
            if declared.get(field) != getattr(tool, field):
                raise ToolchainError(
                    f"{name}: {tool.package} {field} is {getattr(tool, field)!r} but "
                    f"{TOOLCHAIN_DECLARATION} declares {declared.get(field)!r}"
                )


def packages_from_lock(
    repository_root: Path, environment: str, target_platform: str, packages: tuple[str, ...]
) -> dict[str, dict]:
    """Read `(version, build)` for named conda packages out of `pixi.lock`.

    Needed because the declaration covers **both** platforms while any one machine can only probe
    the one it is running on. The lock is committed, so this is a static source of the same fact,
    and the runtime cross-check in `resolve` still applies on whichever platform is live.
    """
    lock = (repository_root / PIXI_LOCK).read_text(encoding="utf-8")
    block = re.search(
        rf"^  {re.escape(environment)}:\n(.*?)(?=^  \w[\w-]*:\n|^packages:)",
        lock,
        re.S | re.M,
    )
    if block is None:
        raise ToolchainError(f"{PIXI_LOCK} has no {environment} environment")
    # Two traps here, both found by tests rather than by reading.
    #
    # Entries under a platform are `      - conda: …` at the *same* six-space indent as the platform
    # header, so the lookahead must require a word character: `^      \S` matches the first list
    # item and yields an empty block.
    #
    # And `\Z` is load-bearing. The *last* platform in an environment has no following key, so a
    # lookahead offering only "next key" alternatives fails to match at all — which made this
    # function report `osx-arm64` as absent while `linux-64`, which happens to be followed by it,
    # parsed fine.
    platform_block = re.search(
        rf"^      {re.escape(target_platform)}:\n(.*?)(?=^      \w|^    \w|^  \w|^packages:|\Z)",
        block.group(1),
        re.S | re.M,
    )
    if platform_block is None:
        raise ToolchainError(f"{PIXI_LOCK}: {environment} does not cover {target_platform}")
    out: dict[str, dict] = {}
    for package in packages:
        found = re.search(
            rf"/{re.escape(package)}-(?P<version>[^-/]+)-(?P<build>[^-/]+)\."
            rf"(?:conda|tar\.bz2)",
            platform_block.group(1),
        )
        if found is None:
            raise ToolchainError(
                f"{PIXI_LOCK}: {environment}/{target_platform} does not resolve {package}"
            )
        out[package] = {"version": found["version"], "build": found["build"]}
    return out


def _environment_platforms(repository_root: Path) -> dict[str, set[str]]:
    """Which platforms each pixi environment actually covers, per `pixi.toml`.

    `seed` overrides its feature's platforms to `["osx-arm64"]` only; `align` inherits the
    workspace's full list. Needed so `build_declaration` never asks the lock for a
    (environment, platform) pair the manifest itself doesn't declare — e.g. `seed`/`linux-64`,
    which does not exist and never will.
    """
    import tomllib

    manifest = tomllib.loads((repository_root / PIXI_MANIFEST).read_text(encoding="utf-8"))
    workspace_platforms = set(manifest["workspace"]["platforms"])
    out: dict[str, set[str]] = {}
    for env_name, env_spec in manifest["environments"].items():
        platforms = set(workspace_platforms)
        for feature_name in env_spec["features"]:
            feature = manifest.get("feature", {}).get(feature_name, {})
            if "platforms" in feature:
                platforms &= set(feature["platforms"])
        out[env_name] = platforms
    return out


def build_declaration(
    repository_root: Path,
    toolchains: list[Toolchain],
    *,
    also_from_lock: tuple[str, ...] = (CANONICAL_PLATFORM,),
) -> dict:
    """Assemble the declaration: probed entries for live platforms, lock-derived for the rest.

    `toolchains` may span more than one environment (`align` and `seed`), and each is filled in
    independently for `also_from_lock` — a single toolchain list used to assume "the" environment
    silently dropped whichever environment was not `toolchains[0]`'s.
    """
    platforms: dict[str, dict] = {}
    packages_by_environment: dict[str, set[str]] = {}
    for toolchain in toolchains:
        packages: dict[str, dict] = {}
        for tool in toolchain.tools.values():
            packages[tool.package] = {"version": tool.version, "build": tool.build}
            packages_by_environment.setdefault(toolchain.environment, set()).add(tool.package)
        platforms.setdefault(toolchain.platform, {})[toolchain.environment] = packages

    environment_platforms = _environment_platforms(repository_root)
    for target in also_from_lock:
        for environment, packages_seen in packages_by_environment.items():
            if environment in platforms.get(target, {}):
                continue
            if target not in environment_platforms.get(environment, set()):
                continue
            platforms.setdefault(target, {})[environment] = packages_from_lock(
                repository_root, environment, target, tuple(sorted(packages_seen))
            )
    return {
        "schema": 1,
        "pixi_lock_sha256": lock_sha256(repository_root),
        "canonical_platform": CANONICAL_PLATFORM,
        "platforms": platforms,
    }
