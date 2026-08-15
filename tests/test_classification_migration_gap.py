"""`docs/classification-migration-gap.tsv` is derived, and this is what keeps it derived.

The table was maintained by hand and drifted twice — it claimed 536 differing records when there
were 529, then 512, and two rows sat in no category while the file's own headline was that every
row has one. Both drifts happened because nothing recomputed it.

`scripts/build_classification_migration_gap.py` computes it from the preserved 2.4.1 fixture, the
built canonical table and the provenance. This test asserts the committed file is what that script
produces, which is the same shape as the byte-parity check on `rules.tsv.gz`: a document nobody can
regenerate is a document nobody is checking.
"""

from __future__ import annotations

import csv
import importlib.util
from pathlib import Path

import pytest


def load_builder(repository_root: Path):
    path = repository_root / "scripts/build_classification_migration_gap.py"
    spec = importlib.util.spec_from_file_location("_gap_builder", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def builder(repository_root: Path):
    return load_builder(repository_root)


def test_the_committed_table_is_what_the_script_produces(
    repository_root: Path, builder
) -> None:
    """Byte-for-byte. A hand edit, or a change that moves the column, fails here."""
    committed = (repository_root / "docs/classification-migration-gap.tsv").read_text(
        encoding="utf-8"
    )
    assert builder.render(builder.build_rows()) == committed, (
        "docs/classification-migration-gap.tsv is stale. Regenerate it: "
        "pixi run -e align python scripts/build_classification_migration_gap.py"
    )


def test_every_row_is_categorised(repository_root: Path) -> None:
    """The file's own headline claim, asserted rather than described.

    It cannot fail while the generator is the only writer — an unrecognised provenance raises there
    instead — which is the point: the property moved from something a reader had to trust to
    something the producer cannot violate.
    """
    with (repository_root / "docs/classification-migration-gap.tsv").open(
        newline="", encoding="utf-8"
    ) as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    assert rows
    assert all(row["category"] for row in rows)


def test_a_difference_the_script_cannot_explain_is_refused(
    repository_root: Path, builder, monkeypatch
) -> None:
    """The load-bearing half: an unknown provenance must stop the build, not become a blank cell.

    Two rows once sat uncategorised in the hand-maintained file. Withdrawing the largest category's
    mapping stands in for any future rule emitting a reason nobody has classified.
    """
    monkeypatch.setitem(
        builder.CATEGORY_BY_REASON, "too_little_sequence_compared_to_measure_divergence", None
    )
    monkeypatch.delitem(
        builder.CATEGORY_BY_REASON, "too_little_sequence_compared_to_measure_divergence"
    )
    with pytest.raises(SystemExit, match="no category for"):
        builder.build_rows()


def test_every_differing_record_appears_exactly_once(repository_root: Path) -> None:
    with (repository_root / "docs/classification-migration-gap.tsv").open(
        newline="", encoding="utf-8"
    ) as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    versions = [row["version"] for row in rows]
    assert len(versions) == len(set(versions))
    # Every row is a real difference; the script filters on exactly this, so a row where the two
    # values agree would mean the filter and the writer disagree.
    assert all(row["release_classification"] != row["built_classification"] for row in rows)
