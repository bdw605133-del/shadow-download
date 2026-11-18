# SHADOW DOWNLOAD

Official, standalone download website for the **SHADOW MODEL** Windows desktop application.

This project is completely separate from the AI chat website. It publishes verified application releases, checksums, release notes, screenshots and documentation. **No placeholder or test file is presented as a real release.**

## Current published release

| Field | Value |
| --- | --- |
| Version | 1.0.0 |
| File | `SHADOW-MODEL-1.0.0-setup.exe` |
| Size | 1,412,554,704 bytes (~1.32 GiB) |
| SHA-256 | `3bb744cfc64f066ccbd9129e2805b85a25a09ba8d1606353412b9dc13c53236d` |
| Source | Existing `SHADOW_AI` portable build, smoke-tested before packaging |
| Status | Verified and published |

The installer is a self-extracting Windows executable built from the native stub in `tools/installer_stub/`. It extracts the actual application, Qt/VC++ runtimes, local engines and licensed models to `%LOCALAPPDATA%\SHADOW MODEL\ShadowAI`, creates a Start Menu shortcut and launches `ShadowAI.exe`.

## Pages

- `/` — Home
- `/download` — Download and release details
- `/features` — Verified application features
- `/release-notes` — Version history
- `/system-requirements` — Requirements
- `/installation` — Installation and checksum guide
- `/faq` — FAQ
- `/admin/login` — Administrator sign-in
- `/admin/dashboard` — Release and content management
- `/sitemap.xml`, `/robots.txt` — SEO endpoints

## Local startup (Windows)

```powershell
cd "D:\SHADOW PDF AI\shadow-download"
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# Create the first administrator (prints a one-time password)
.\.venv\Scripts\python.exe tools/init_admin.py --username admin

# Start the development server
.\.venv\Scripts\python.exe app.py
```

Open <http://127.0.0.1:8000>.

Or run `scripts\start_local.bat`.

### Keep the server running (Windows)

For a persistent local link, install the built-in autostart task instead of leaving a terminal open:

```powershell
.\.venv\Scripts\python.exe tools\service_manager.py install
```

Or double-click `scripts\install_autostart.bat`.

This registers a hidden Task Scheduler task named **SHADOW DOWNLOAD Website** for the current Windows account. It starts the site at every logon, rechecks it every minute and restarts it automatically if it is not running, and writes startup/error details to `logs/server.log`. No administrator rights are required.

```powershell
# Check the task, port and health endpoint
.\.venv\Scripts\python.exe tools\service_manager.py status

# Control the server without opening a terminal
.\scripts\start_server.bat
.\scripts\stop_server.bat
.\scripts\restart_server.bat
.\scripts\server_status.bat

# Remove autostart completely
.\.venv\Scripts\python.exe tools\service_manager.py uninstall
```

`stop` also disables the autostart check so the site stays down until you run `start` or `restart` again.

The link stays available at <http://127.0.0.1:8000> for as long as that Windows user is logged in. For a machine-level service that starts before login, see `docs/DEPLOYMENT.md`.

### Free public website (works with this PC off)

A fully free, always-on public HTTPS deployment is available as a **static download site**: GitHub Pages + GitHub Releases. It uses no API keys, no admin database and no local server. See `docs/GITHUB_PAGES.md` for the one-time setup and verification steps. It does not provide browser chat to the native SHADOW backend; see that document for the exact compatibility status.

### Configuration

Copy `.env.example` to `.env` and adjust as needed:

| Variable | Purpose |
| --- | --- |
| `SHADOW_SECRET_KEY` | Session/Cookie signing secret. If absent, a random key is persisted in `data/secret_key`. |
| `SHADOW_BASE_URL` | Canonical URL used in SEO metadata and sitemap. |
| `SHADOW_HOST`, `SHADOW_PORT` | Bind address and port. |
| `SHADOW_THREADS` | Waitress worker threads (default 8). |
| `SHADOW_COOKIE_SECURE` | Set to `1` only when serving over HTTPS. |
| `SHADOW_FORCE_HTTPS` | Redirect HTTP to HTTPS (use behind a TLS proxy). |
| `SHADOW_DB_PATH` | SQLite database path. |
| `SHADOW_STORAGE_PATH` | Root for release files (installers and screenshots). |
| `SHADOW_MAX_UPLOAD_MB` | Maximum installer upload size (default 2048). |
| `SHADOW_LOGIN_MAX_ATTEMPTS` | Failed sign-ins before throttling. |

Never commit `.env`, `data/*.db`, `data/secret_key` or `storage/releases/*`.

## Administrator workflow

1. Sign in at `/admin/login`.
2. Change the generated password when prompted.
3. In **Dashboard → Publish a new version**, enter metadata, upload the installer and `manifest.json`, and add screenshots.
4. Run **Verify** — this checks file presence, readability, SHA-256, size, PE header and every required embedded file.
5. Only after verification passes, use **Publish**.
6. Manage homepage text, features, FAQ, requirements and install steps under **Site content**.

See `docs/RELEASE_PROCESS.md` for the reproducible packaging commands.

## Project layout

```text
app.py                 Flask application and public routes
admin.py               Authenticated release/content management
security.py            Scrypt hashing, sessions, CSRF, throttling, headers
storage.py             Release storage, checksum generation, verification
release_format.py      Private SFX payload format shared by site and tools
db.py                  SQLite schema and content helpers
repositories.py        Read helpers used by templates
config.py              Environment-based configuration
wsgi.py                Waitress production entry point
boot_server.py         Hidden bootstrap that loads the venv without a launcher
server_runner.py       Hidden autostart runner with file logging
tools/service_manager.py  Install/start/stop the Windows autostart task
tools/make_static_snapshot.py  Export sanitized public data for GitHub Pages
tools/export_static.py Freeze public pages into site/
public_static/         Sanitized snapshot data and public screenshots
site/                  Generated GitHub Pages output (not committed)
.github/workflows/     GitHub Pages build and deploy workflow
scripts/*.bat          One-click local and autostart controls
logs/server.log        Autostart/server diagnostics (created at runtime)
app/templates/         Public and admin pages
app/static/            CSS, JS, logo, verified screenshots
storage/releases/      Installers and screenshots (never in the database)
storage/staging/       Temporary upload staging
tools/                 Admin bootstrap, packaging, verification, publishing
tests/                 Security, release and packaging tests
docs/                  Deployment, release process, security documentation
```

## Tests

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The suite covers public pages, no-fake-release behaviour, authentication, CSRF, cookie hardening, security headers, path traversal, HTML escaping, rate limiting, unpublished release protection, packaging, private-file exclusion and pre-publication verification.

## Notes about the application itself

Features shown on the website were verified from the existing SHADOW MODEL source tree (`SHADOW_MODEL_FINAL_STATUS.md`, `CMakeLists.txt`, README, Qt Test results). The native SHADOW model is experimental and CPU-first; image understanding requires a configured vision-capable provider; scanned PDFs need OCR; Arabic SAPI narration needs an Arabic voice installed in Windows. These limits are stated publicly rather than hidden.

Model licences are included in the installer: Qwen2.5 GGUF (Apache-2.0), Whisper Base (MIT), llama.cpp/whisper.cpp (MIT), Qt (LGPL-3.0 dynamic linking). See `THIRD_PARTY_NOTICES.md` and `licenses/` in the release payload.
