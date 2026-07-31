"""Deterministic-within-a-run scratch directories for tool invocations.

`align.runner.run_tool` needs a fresh, writable directory per tool call — `mafft-xinsi` in
particular writes `_mccaskill*` files into its own working directory and bus-errors if that
directory is not both fresh and writable. `Scratch` is the one place that layout is decided.

Only the *root* varies between runs (`tempfile.mkdtemp`, by design — a build must not depend on a
fixed scratch location). Everything under it is a deterministic function of the call sequence, so
`align.validation`'s "no committed artifact contains an absolute path" check has exactly one thing
to strip before comparing two runs: the mkdtemp prefix, not an arbitrarily-ordered set of names.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

from enterovirus_genbank_curated.contracts import ContractError

RUN_DIR_PREFIX = "evgc-align-"


class ScratchError(ContractError):
    """A scratch directory could not be created where the caller asked for it."""


@dataclass(frozen=True)
class Scratch:
    root: Path

    def run_dir(self, index: int, label: str) -> Path:
        """`root/0007-mafft_add_backbone`, created fresh.

        `index` is the call's position in the build's own step sequence, not a random or
        timestamp-derived number — the same build run twice produces the same sequence of names,
        which is what makes two builds comparable path-for-path once the mkdtemp root is stripped.
        """
        name = f"{index:04d}-{_slug(label)}"
        path = self.root / name
        try:
            path.mkdir(parents=True, exist_ok=False)
        except FileExistsError as exc:
            raise ScratchError(
                f"{path} already exists; run_dir indices must be unique within one build "
                f"(step {index!r} was requested twice)"
            ) from exc
        return path


def _slug(label: str) -> str:
    """A label safe to use as one path component: ASCII, no separators, no leading dot."""
    cleaned = "".join(c if c.isalnum() or c in "-_" else "_" for c in label)
    return cleaned or "step"


def create() -> Scratch:
    """A fresh scratch tree, rooted under the default temp directory.

    Deliberately not configurable to an arbitrary caller-supplied root: `sandbox_exec
    .install_tool_guard` refuses a `scratch_root` outside the default scratch tree, so a `Scratch`
    built any other way would fail at guard-install time rather than at first use. If a build ever
    needs an alternate location, that constraint should move, not be worked around here.
    """
    return Scratch(root=Path(tempfile.mkdtemp(prefix=RUN_DIR_PREFIX)))
