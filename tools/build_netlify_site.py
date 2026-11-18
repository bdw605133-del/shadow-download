"""Build a pure HTML/CSS/JS drop-in folder for Netlify Drop.

No Flask, Python, database, admin routes or backend. The installer is not
bundled: download buttons become a clear "pending" state until a real public
release URL exists, so no fake or broken download link is published.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "netlify_site"
SITE_DIR = ROOT / "site"

RELEASE_LINK_RE = re.compile(
    r'<a\s+[^>]*href="https://github\.com/[^"]+/releases/download/[^"]+"[^>]*>.*?</a>',
    re.IGNORECASE | re.DOTALL,
)
PENDING_BUTTON = (
    '<span class="btn btn--primary btn--disabled" aria-disabled="true">'
    'Installer release pending</span>'
)
NOTICE = (
    '<div class="container" style="padding-top:1rem">'
    '<div class="flash flash--warning" role="status">'
    'The verified installer is ready locally. Public download hosting is being prepared; '
    'the checksum below is already published for verification.'
    '</div></div>\n'
)


def main() -> int:
    env = os.environ.copy()
    env["SHADOW_PUBLIC_BASE_URL"] = "https://netlify-static-preview.invalid"
    env["SHADOW_STATIC_RELEASE_URL_TEMPLATE"] = (
        "https://github.com/static-preview/static-preview/releases/download/v{version}/{filename}"
    )
    env["SHADOW_SECRET_KEY"] = "static-export-only-not-a-runtime-secret"

    result = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "export_static.py")],
        cwd=ROOT,
        env=env,
        check=False,
    )
    if result.returncode != 0:
        return result.returncode

    if OUTPUT.exists():
        shutil.rmtree(OUTPUT)
    shutil.copytree(SITE_DIR, OUTPUT)

    for target in OUTPUT.rglob("*.html"):
        text = target.read_text(encoding="utf-8")
        text = RELEASE_LINK_RE.sub(PENDING_BUTTON, text)
        if target.name == "index.html" and target.parent.name == "download":
            text = text.replace('<main id="main">', '<main id="main">\n' + NOTICE, 1)
        target.write_text(text, encoding="utf-8")

    # The public hostname is not known until Netlify creates it, so do not ship
    # a sitemap containing a guessed domain.
    for stale in ("sitemap.xml", ".nojekyll"):
        path = OUTPUT / stale
        if path.exists():
            path.unlink()
    (OUTPUT / "robots.txt").write_text("User-agent: *\nAllow: /\n", encoding="utf-8")

    css = OUTPUT / "static" / "css" / "style.css"
    if css.is_file():
        with css.open("a", encoding="utf-8") as handle:
            handle.write("\n.btn--disabled{opacity:.55;cursor:not-allowed;pointer-events:none}\n")

    print(f"Pure static Netlify site written to {OUTPUT.relative_to(ROOT)}")
    print("Download buttons are intentionally disabled until a real release URL exists.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
