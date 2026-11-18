# Production deployment

## 1. Prepare the host

- Windows Server 2019/2022 or Windows 10/11 with Python 3.10+.
- A TLS certificate. The site must be served over HTTPS in production.
- A dedicated service account with read/write access only to this project folder.
- At least 5 GB free disk space for every published release (installer plus staging), plus room for growth.

```powershell
cd "D:\SHADOW PDF AI\shadow-download"
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## 2. Environment

Create `.env` (never commit it):

```dotenv
SHADOW_ENV=production
SHADOW_SECRET_KEY=<long-random-secret>
SHADOW_BASE_URL=https://download.example.com
SHADOW_HOST=127.0.0.1
SHADOW_PORT=8000
SHADOW_COOKIE_SECURE=1
SHADOW_FORCE_HTTPS=1
SHADOW_TRUSTED_PROXY_COUNT=1
SHADOW_ADMIN_USERNAME=admin
```

Generate a secret with:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Create the administrator and save the printed one-time password in your password manager:

```powershell
.\.venv\Scripts\python.exe tools/init_admin.py --username admin
```

## 3. TLS reverse proxy

Waitress serves plain HTTP. Put it behind a TLS-terminating reverse proxy (IIS ARR, nginx, Caddy or a cloud load balancer) and forward `X-Forwarded-For`. Set `SHADOW_TRUSTED_PROXY_COUNT` to the number of trusted proxies.

Example Caddyfile:

```caddyfile
download.example.com {
    reverse_proxy 127.0.0.1:8000
    header {
        Strict-Transport-Security "max-age=31536000; includeSubDomains"
    }
}
```

If the proxy already adds HSTS and security headers, keep the application headers as a second layer.

## 4. Run the service

Foreground test:

```powershell
.\.venv\Scripts\python.exe wsgi.py
```

### Persistent per-user autostart (no admin rights)

The project includes a Windows Task Scheduler manager that works for the current user:

```powershell
.\.venv\Scripts\python.exe tools\service_manager.py install
.\.venv\Scripts\python.exe tools\service_manager.py status
```

It creates the hidden task **SHADOW DOWNLOAD Website**, runs `boot_server.py` with the base `pythonw.exe` at logon (so Task Scheduler owns the actual server process), rechecks/restarts the site every minute if it is down, and logs diagnostics to `logs/server.log`. Daily control:

```powershell
.\.venv\Scripts\python.exe tools\service_manager.py start
.\.venv\Scripts\python.exe tools\service_manager.py stop
.\.venv\Scripts\python.exe tools\service_manager.py restart
.\.venv\Scripts\python.exe tools\service_manager.py uninstall
```

`stop` disables the task so the minute check does not immediately restart the site; `start` re-enables it.

Equivalent one-click scripts are in `scripts\`: `install_autostart.bat`, `start_server.bat`, `stop_server.bat`, `restart_server.bat`, `server_status.bat` and `uninstall_autostart.bat`.

This mode requires the configured Windows account to be logged in. It is the recommended option on a single-user workstation such as the current SHADOW machine.

### Machine-level Windows service (administrator required)

If the site must start before any user logs in, install it as a real service from an elevated shell with NSSM (or another service wrapper):

```powershell
nssm install ShadowDownload "D:\SHADOW PDF AI\shadow-download\.venv\Scripts\python.exe" "D:\SHADOW PDF AI\shadow-download\wsgi.py"
nssm set ShadowDownload AppDirectory "D:\SHADOW PDF AI\shadow-download"
nssm set ShadowDownload DisplayName "SHADOW DOWNLOAD website"
nssm set ShadowDownload AppRestartDelay 60000
nssm start ShadowDownload
```

Do not install both modes at once; they would compete for the same port. Do not expose port 8000 directly to the internet.

## 5. File permissions and backups

- `data/` — writable by the service account; contains the SQLite database and local secret.
- `storage/releases/` — writable by the service account; contains installers and screenshots.
- `storage/staging/` — writable by the service account; temporary files only.
- `tools/`, `app/`, `*.py` — read-only for the service account where practical.

Back up `data/shadow_download.db` and `storage/releases/` together. Use SQLite's online backup API or stop the service during a file copy. Never back up only the database: installer bytes live on disk.

## 6. Operational checks

```powershell
curl.exe https://download.example.com/health
curl.exe https://download.example.com/download/latest -I
```

Monitor:

- HTTP errors on `/download/latest` and `/download/<id>/installer`.
- Free disk space in `storage/`.
- Failed-login spikes in the `login_attempts` table.
- `audit_log` for unexpected publish/unpublish events.

## 7. Updating

1. Stop the service.
2. Replace Python source/templates/static files.
3. Run `python -c "from db import init_db; import config; init_db(config.config_for().DB_PATH)"` (schema creation is idempotent).
4. Start the service and re-run the test suite.

## 8. Known deployment caveats

- The generated installer is not code-signed. Windows SmartScreen may warn until an EV/OV code-signing certificate is used. Sign the final `.exe` with `signtool sign` before uploading a new release; the checksum must be regenerated after signing.
- Large uploads are buffered by Werkzeug. For multi-gigabyte installers, upload via `tools/publish_release.py` on the server or add chunked/resumable upload support behind the admin UI.
- SQLite is sufficient for one application node. For multiple web nodes, migrate the metadata store to PostgreSQL and keep release storage on shared object storage with a verified checksum.
