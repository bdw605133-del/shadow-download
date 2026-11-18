"""Set a GitHub Actions output indicating whether the real installer exists.

Never publishes a download link unless the asset responds to a real HTTP
range request. Missing or broken assets produce `available=false`.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "public_static" / "data.json"


def main() -> int:
    template = os.getenv("RELEASE_URL", "").strip()
    if not template or "{version}" not in template or "{filename}" not in template:
        print("RELEASE_URL is missing or invalid", file=sys.stderr)
        available = False
    else:
        data = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        release = data["releases"][0]
        url = template.format(
            version=release["version"],
            filename=release["installer_name"],
        )
        available = False
        try:
            request = urllib.request.Request(url, headers={"Range": "bytes=0-0"})
            with urllib.request.urlopen(request, timeout=60) as response:
                available = response.status in (200, 206)
        except (urllib.error.URLError, OSError) as exc:
            print(f"Release asset not available: {exc}")

    output = os.getenv("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write(f"available={'true' if available else 'false'}\n")
    print(f"Release asset available: {available}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
