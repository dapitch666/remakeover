#!/usr/bin/env python3
"""Fail if any UI string lacks a non-empty, non-fuzzy translation.

Re-extracts messages with the same command as scripts/update_locales.sh (so
it always reflects current source, not whatever the committed .pot happens
to say) and compares against each non-English catalog in locales/.
"""

import subprocess
import sys
import tempfile
from pathlib import Path

from babel.messages.pofile import read_po

ROOT_DIR = Path(__file__).parent.parent
LOCALES_DIR = ROOT_DIR / "locales"
DOMAIN = "remakeover"

sys.path.insert(0, str(ROOT_DIR))

from src.i18n import SUPPORTED_LANGUAGES  # noqa: E402


def extracted_msgids() -> set[str | tuple[str, ...]]:
    with tempfile.NamedTemporaryFile(suffix=".pot") as tmp:
        subprocess.run(
            ["pybabel", "extract", "-F", "pyproject.toml", "-k", "_n:1,2", "-o", tmp.name, "."],
            cwd=ROOT_DIR,
            check=True,
            capture_output=True,
        )
        with open(tmp.name, "rb") as f:
            catalog = read_po(f)
    return {m.id for m in catalog if m.id}


def translated_msgids(po_path: Path) -> set[str | tuple[str, ...]]:
    with po_path.open("rb") as f:
        catalog = read_po(f)
    return {m.id for m in catalog if m.id and m.string and "fuzzy" not in m.flags}


def main() -> int:
    source_msgids = extracted_msgids()
    failures: list[str] = []

    for lang in SUPPORTED_LANGUAGES:
        if lang == "en":
            continue
        po_path = LOCALES_DIR / lang / "LC_MESSAGES" / f"{DOMAIN}.po"
        if not po_path.exists():
            failures.append(f"{lang}: {po_path} does not exist")
            continue
        for msgid in sorted(source_msgids - translated_msgids(po_path), key=str):
            failures.append(f"{lang}: missing or empty translation for {msgid!r}")

    if failures:
        print("Translation check failed:")
        for failure in failures:
            print(f"  - {failure}")
        print(
            "\nRun scripts/update_locales.sh, fill in the new msgstr entries "
            "(and remove any #, fuzzy flags), then retry."
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
