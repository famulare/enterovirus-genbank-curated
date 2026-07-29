"""The staleness gate.

The site's data artifacts are committed rather than rebuilt on every deploy, so
the one failure mode worth engineering against is a figure computed from data that
has since changed. `site/data/manifest.json` records the SHA-256 of every `final/`
file the build read, plus the hash of the pipeline sources themselves. `cli.py
check` recomputes both and exits non-zero on any difference.

Build identity is derived from input hashes and source hashes, deliberately not
from the git SHA: two runs of the same sources over the same data must produce the
same identity.
"""

from __future__ import annotations

import hashlib
import json
import platform
import sys
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


def check() -> list[str]:
    """Return a list of human-readable problems; empty means the artifacts are current."""
    if not MANIFEST_PATH.exists():
        return [f"{contract.repo_relative(MANIFEST_PATH)} does not exist — nothing has been built."]

    recorded = json.loads(MANIFEST_PATH.read_text())
    problems: list[str] = []

    if recorded.get("schema") != SCHEMA:
        problems.append(
            f"manifest schema is {recorded.get('schema')}, this pipeline writes {SCHEMA}"
        )

    for label, actual in (("input", input_hashes()), ("source", source_hashes())):
        was = recorded.get(f"{label}s", {})
        for name in sorted(set(was) | set(actual)):
            if name not in was:
                problems.append(f"new {label} {name} is not covered by the manifest")
            elif name not in actual:
                problems.append(f"{label} {name} is in the manifest but no longer exists")
            elif was[name] != actual[name]:
                problems.append(f"{label} {name} changed since the artifacts were built")

    for name, digest in sorted(recorded.get("artifacts", {}).items()):
        path = contract.DATA_OUT / name
        if not path.exists():
            problems.append(f"artifact site/data/{name} is missing")
        elif hash_file(path) != digest:
            problems.append(f"artifact site/data/{name} does not match its recorded hash")

    return problems


def artifact_hashes(names: list[str]) -> dict[str, str]:
    return {name: hash_file(contract.DATA_OUT / name) for name in sorted(names)}


def report(problems: list[str]) -> int:
    if not problems:
        recorded = json.loads(MANIFEST_PATH.read_text())
        print(f"site data is current · build {recorded['build_identity']}")
        return 0
    print("site data is STALE:", file=sys.stderr)
    for problem in problems:
        print(f"  - {problem}", file=sys.stderr)
    print(
        "\nRebuild with:  uv run site/pipeline/cli.py build\n"
        "Then commit the regenerated site/data/.",
        file=sys.stderr,
    )
    return 1
