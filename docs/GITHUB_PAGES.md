# Free public deployment (GitHub Pages + GitHub Releases)

This is the genuinely free, always-on public option. It publishes the **distribution website** over HTTPS without using your computer. It does **not** publish a browser chat backend; see [Backend status](#backend-status) below.

## What gets deployed

- All 7 public pages, `robots.txt` and `sitemap.xml`, frozen into `site/`.
- The existing verified screenshots and branding.
- Download buttons pointing to a real GitHub Releases asset over HTTPS.
- No admin pages, no database, no sessions, no secrets and no API keys.

## One-time setup

1. Create a **public** GitHub repository, for example `shadow-download`, or `<your-account>.github.io` if you want the root URL.
2. Push this whole `shadow-download` folder to the `main` (or `master`) branch.
3. In the repository: **Settings → Pages → Build and deployment → Source: GitHub Actions**.
4. Create a GitHub Release with tag `v1.0.0` and upload this exact asset:

   ```text
   SHADOW-MODEL-1.0.0-setup.exe
   ```

   The file is already verified locally:

   ```text
   SHA-256: 3bb744cfc64f066ccbd9129e2805b85a25a09ba8d1606353412b9dc13c53236d
   Size:    1412554704 bytes
   ```

   GitHub's per-release file limit is high enough for this 1.32 GiB installer. Do not upload a renamed or repacked file; the checksum must stay identical.

5. Push any commit to `main`/`master` (or run the workflow manually). `.github/workflows/deploy-pages.yml` will:
   - compute the correct public URL and Releases URL,
   - verify the release asset is really downloadable,
   - export the static site,
   - publish it with GitHub Pages.

## Public URL

- Project repository: `https://<your-account>.github.io/<repository>/`
- User site repository (`<your-account>.github.io`): `https://<your-account>.github.io/`

A custom domain is optional and also free; configure it in GitHub Pages settings and set `SHADOW_BASE_URL` accordingly if you regenerate locally.

## Local regeneration

After changing site content in the local admin dashboard, refresh the public snapshot first:

```powershell
.\.venv\Scripts\python.exe tools\make_static_snapshot.py
```

Then export locally to inspect `site/`:

```powershell
$env:SHADOW_PUBLIC_BASE_URL = 'https://your-account.github.io/shadow-download/'
$env:SHADOW_STATIC_RELEASE_URL_TEMPLATE = 'https://github.com/your-account/shadow-download/releases/download/v{version}/{filename}'
.\.venv\Scripts\python.exe tools\export_static.py
```

`site/` is generated output and is intentionally gitignored; the workflow rebuilds it.

## Verification checklist

Open the public URL in Google Chrome and confirm:

1. Home, Download, Features, Release Notes, System Requirements, Installation and FAQ all open.
2. Screenshots load from `/static/screenshots/...`.
3. “Download Windows installer” goes to `github.com/<account>/<repo>/releases/download/v1.0.0/SHADOW-MODEL-1.0.0-setup.exe`.
4. The downloaded file is 1,412,554,704 bytes and its SHA-256 matches the value on the Download page.
5. `/sitemap.xml` contains public HTTPS URLs.
6. No `/admin` links or forms appear in the static site.

Run this from PowerShell against the real URL:

```powershell
curl.exe -I https://<your-account>.github.io/<repository>/
curl.exe -I https://<your-account>.github.io/<repository>/download/
curl.exe -I https://<your-account>.github.io/<repository>/sitemap.xml
```

## Free-plan limitations (important)

- **No browser chat backend.** The real SHADOW MODEL is a Windows C++/Qt desktop app with in-process inference. There is no headless HTTP/WebSocket server for it, and no trained `shadow-model.ckpt` was found in the project or user data. GitHub Pages serves static files only. This deployment cannot satisfy chat/image/document testing requirements.
- **No admin dashboard, database or download counter** on the public site. Release content changes require regenerating the snapshot with the local admin site, then pushing.
- **GitHub Releases bandwidth/disk limits** apply; abuse or unexpected traffic can be throttled by GitHub.
- The installer is **not code-signed**, so Chrome/SmartScreen may warn. Signing requires a paid certificate and would change the SHA-256.
- The public repo must be public for free GitHub Pages. Never put `.env`, `data/secret_key`, the admin database, API keys or the local `models.json` into it. `public_static/data.json` is sanitized and contains only public release/content data.

## Backend status

Cannot be deployed on this free plan without replacing or rewriting the model stack. Exact blockers:

- Native inference lives in `ShadowModel`/`ShadowTransformer` inside the Qt desktop app; there is no server target in `CMakeLists.txt`.
- `python/shadow_runtime/server.py` is loopback-only, has no auth/TLS and proxies chat to an external OpenAI-compatible provider — using it would replace the model.
- `llama-server.exe` serves the bundled Qwen GGUF, not native SHADOW.
- Windows-only APIs: DPAPI, SAPI, WinRT OCR, registry autostart and MSVC/Qt DLLs.
- Image understanding for native SHADOW is OCR text only; document reading needs a text layer or OCR.

The simplest non-replacing solution would be a new headless C++ `shadow-server` target that links `shadow_core`, loads the native checkpoint, exposes a private HTTP/SSE API behind Caddy TLS, and runs on an always-on Windows VM. That requires paid hosting and a trained native checkpoint; it was not started because you chose the free download-only option and no checkpoint is available.
