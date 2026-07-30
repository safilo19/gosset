"""Download the report engine's bundled fonts from their official OFL sources.

Run from the repo root:  python backend/report_engine/fonts/fetch_fonts.py

The TTFs are committed alongside this script, so a normal install never needs to run it. It exists so
the provenance of every file is auditable and so the set can be refreshed deliberately rather than by
someone dropping an unversioned font into the folder.

All five faces are SIL Open Font License 1.1. Both licences are downloaded with them — redistributing
an OFL font without its licence text is the one thing the licence actually forbids.
"""

from __future__ import annotations

import hashlib
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent

# Pinned versions: a font that silently changes metrics would reflow every report ever generated.
# jsDelivr and unpkg both 403 the @ibm/plex package; raw.githubusercontent at the tag serves it.
PLEX_VERSION = "6.4.0"
PLEX_BASE = f"https://raw.githubusercontent.com/IBM/plex/v{PLEX_VERSION}"
SERIF_REF = "release"

FILES: list[tuple[str, str]] = [
    # IBM Plex Sans / Mono — the app's interface and numeric faces, so the report matches the screen.
    (
        f"{PLEX_BASE}/IBM-Plex-Sans/fonts/complete/ttf/IBMPlexSans-Regular.ttf",
        "IBMPlexSans-Regular.ttf",
    ),
    (
        f"{PLEX_BASE}/IBM-Plex-Sans/fonts/complete/ttf/IBMPlexSans-Medium.ttf",
        "IBMPlexSans-Medium.ttf",
    ),
    (
        f"{PLEX_BASE}/IBM-Plex-Mono/fonts/complete/ttf/IBMPlexMono-Regular.ttf",
        "IBMPlexMono-Regular.ttf",
    ),
    # Source Serif 4 — the report's own voice. The screen has no serif; a printed document wants one.
    (
        f"https://github.com/adobe-fonts/source-serif/raw/{SERIF_REF}/TTF/SourceSerif4-Regular.ttf",
        "SourceSerif4-Regular.ttf",
    ),
    (
        f"https://github.com/adobe-fonts/source-serif/raw/{SERIF_REF}/TTF/SourceSerif4-Semibold.ttf",
        "SourceSerif4-Semibold.ttf",
    ),
    # The licences. Not optional.
    (f"{PLEX_BASE}/LICENSE.txt", "LICENSE-IBM-Plex.txt"),
    (f"https://github.com/adobe-fonts/source-serif/raw/{SERIF_REF}/LICENSE.md", "LICENSE-Source-Serif.md"),
]


def fetch(url: str, name: str) -> None:
    dest = HERE / name
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (gosset-report-engine)"})
    with urllib.request.urlopen(request, timeout=60) as response:
        data = response.read()
    if name.endswith(".ttf") and not data.startswith((b"\x00\x01\x00\x00", b"true", b"ttcf", b"OTTO")):
        raise SystemExit(f"{name}: not a TrueType file (got {data[:16]!r}) — the URL probably returned an HTML error page")
    if len(data) < 2000:
        raise SystemExit(f"{name}: only {len(data)} bytes, refusing to write a truncated font")
    dest.write_bytes(data)
    print(f"  {name:34} {len(data):>9,} bytes  sha256 {hashlib.sha256(data).hexdigest()[:16]}")


def main() -> None:
    print(f"Fetching fonts into {HERE}")
    for url, name in FILES:
        try:
            fetch(url, name)
        except SystemExit:
            raise
        except Exception as exc:  # noqa: BLE001 - report which file failed and keep going
            print(f"  {name:34} FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
    print("done")


if __name__ == "__main__":
    main()
