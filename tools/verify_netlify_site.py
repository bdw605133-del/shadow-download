"""Verify the Netlify Drop folder is complete and self-contained.

Checks every local asset reference in every HTML file resolves to a file
inside the export, and reports anything that would 404 after deployment.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "netlify_site"

LOCAL_REF_RE = re.compile(r'(?:src|href)="([^"]+)"', re.IGNORECASE)
FORBIDDEN = ("127.0.0.1", "localhost", "/admin", ".py", ".db", "sitemap.xml")


def main() -> int:
    failures: list[str] = []
    html_files = sorted(SITE.rglob("*.html"))
    if not html_files:
        print(f"FAIL: no HTML files in {SITE}")
        return 1

    checked_refs = 0
    for html in html_files:
        text = html.read_text(encoding="utf-8")
        for marker in FORBIDDEN:
            if marker in text:
                failures.append(f"{html.relative_to(SITE)}: contains forbidden marker {marker!r}")
        for ref in LOCAL_REF_RE.findall(text):
            ref = ref.strip()
            if not ref or ref.startswith(("http://", "https://", "mailto:", "data:", "#")):
                continue
            checked_refs += 1
            path_part = unquote(urlsplit(ref).path)
            if path_part.startswith("/"):
                candidate = SITE / path_part.lstrip("/")
            else:
                candidate = (html.parent / path_part).resolve()
            if not candidate.exists():
                failures.append(f"{html.relative_to(SITE)}: missing local asset {ref!r}")

    # Required pages
    required = [
        "index.html",
        "download/index.html",
        "features/index.html",
        "release-notes/index.html",
        "system-requirements/index.html",
        "installation/index.html",
        "faq/index.html",
        "static/css/style.css",
        "static/js/main.js",
        "robots.txt",
    ]
    for rel in required:
        if not (SITE / rel).is_file():
            failures.append(f"missing required file {rel}")

    print(f"HTML pages: {len(html_files)}")
    print(f"Local references checked: {checked_refs}")
    if failures:
        print(f"FAILURES ({len(failures)}):")
        for item in failures:
            print("  -", item)
        return 1
    print("OK: all local references resolve; no backend/admin markers found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
