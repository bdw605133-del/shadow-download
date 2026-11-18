# Netlify Drop (pure static preview)

`netlify_site/` is a pure HTML/CSS/JS copy of the public website. It contains no Flask, Python, database, admin panel, C++ runtime or backend.

## What to drag

Drag this folder into <https://app.netlify.com/drop>:

```text
D:\SHADOW PDF AI\shadow-download\netlify_site
```

Or upload this archive:

```text
D:\SHADOW PDF AI\shadow-download\netlify_site.zip
```

Netlify will give you a public HTTPS URL such as:

```text
https://random-name-123456.netlify.app
```

## Important limitation

Installer buttons currently show **“Installer release pending”** instead of a fake download link. The 1.32 GB installer cannot be hosted by Netlify Drop, and no public GitHub Release exists yet. Once a real release URL is available, rebuild with that URL and the buttons become real.

To regenerate the static folder after local content changes:

```powershell
.\.venv\Scripts\python.exe tools\make_static_snapshot.py
.\.venv\Scripts\python.exe tools\build_netlify_site.py
```

## Verify after upload

Open these in Chrome using your Netlify URL:

```text
/<your-url>/
/<your-url>/download/
/<your-url>/features/
/<your-url>/release-notes/
```

Check that screenshots load and that no admin links or download links are broken.
