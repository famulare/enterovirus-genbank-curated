"""Provenance for the artifacts this build produces.

`site/data/manifest.json` records the SHA-256 of every `final/` file the build read
and of the pipeline sources themselves, and ships alongside the figures — so a
published page can be traced back to the exact inputs and code that made it.

This was a staleness gate when site/data/ was committed: `check` recomputed the
hashes and failed if the artifacts predated their inputs. The artifacts are built
per deploy now, so nothing can be stale and the gate is gone. What it recorded is
still worth publishing, which is why `write` remains.

Build identity is derived from input hashes and source hashes, deliberately not
from the git SHA: two runs of the same sources over the same data must produce the
same identity. Note that this holds per platform, not across them — the genus-wide
consensus panels differ between macOS and Linux.
"""

from __future__ import annotations

import hashlib
import json
import platform
from pathlib import Path

import contract

MANIFEST_PATH = contract.DATA_OUT / "manifest.json"
SCHEMA = 1
PIPELINE_DIR = Path(__file__).resolve().parent


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def input_hashes() -> dict[str, str]:
    out = {}
    for path in contract.gated_inputs():
        if not path.exists():
            raise FileNotFoundError(
                f"declared input {contract.repo_relative(path)} is missing. If the upstream "
                "layout changed, update site/pipeline/contract.py."
            )
        out[contract.repo_relative(path)] = hash_file(path)
    return out


def source_hashes() -> dict[str, str]:
    return {
        contract.repo_relative(path): hash_file(path)
        for path in sorted(PIPELINE_DIR.glob("*.py"))
    }


def build_identity(inputs: dict[str, str], sources: dict[str, str]) -> str:
    payload = json.dumps({"inputs": inputs, "sources": sources}, sort_keys=True)
    return "src-" + hashlib.sha256(payload.encode()).hexdigest()[:16]


def tool_versions() -> dict[str, str]:
    versions = {"python": platform.python_version()}
    try:
        import numpy

        versions["numpy"] = numpy.__version__
    except ImportError:  # pragma: no cover - numpy is a declared dependency
        pass
    return versions


def write(artifacts: dict[str, str], notes: dict | None = None) -> dict:
    inputs = input_hashes()
    sources = source_hashes()
    manifest = {
        "schema": SCHEMA,
        "build_identity": build_identity(inputs, sources),
        "tool_versions": tool_versions(),
        "inputs": inputs,
        "sources": sources,
        "artifacts": artifacts,
        "notes": notes or {},
    }
    contract.DATA_OUT.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest


def artifact_hashes(names: list[str]) -> dict[str, str]:
    return {name: hash_file(contract.DATA_OUT / name) for name in sorted(names)}
