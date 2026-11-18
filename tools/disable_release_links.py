"""Replace unverified installer links with an honest pending state.

Used by the GitHub Pages workflow when no public GitHub Release asset exists
yet. This keeps the site publishable without ever showing a fake/broken link.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"

RELEASE_LINK_RE = re.compile(
    r'<a\s+[^>]*href="https://github\.com/[^"]+/releases/download/[^"]+"[^>]*>.*?</a>',
    re.IGNORECASE | re.DOTALL,
)
PENDING_BUTTON = (
    '<span class="btn btn--primary btn--disabled" aria-disabled="true">'
    "Installer release pending</span>"
)
NOTICE = (
    '<div class="container" style="padding-top:1rem">'
    '<div class="flash flash--warning" role="status">'
    "The verified installer is ready locally. Public download hosting is being prepared; "
    "the checksum below is already published for verification."
    "</div></div>\n"
)


def main() -> int:
    replaced = 0
    for target in sorted(SITE.rglob("*.html")):
        text = target.read_text(encoding="utf-8")
        text, count = RELEASE_LINK_RE.subn(PENDING_BUTTON, text)
        replaced += count
        if target.name == "index.html" and target.parent.name == "download":
            text = text.replace('<main id="main">', '<main id="main">\n' + NOTICE, 1)
        target.write_text(text, encoding="utf-8")

    css = SITE / "static" / "css" / "style.css"
    if css.is_file() and ".btn--disabled" not in css.read_text(encoding="utf-8"):
        with css.open("a", encoding="utf-8") as handle:
            handle.write("\n.btn--disabled{opacity:.55;cursor:not-allowed;pointer-events:none}\n")

    print(f"Disabled {replaced} unverified installer link(s) in {SITE.relative_to(ROOT)}")
    if replaced == 0:
        print("WARNING: no installer links were found to disable", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
