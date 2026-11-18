# Reproducible release process

This process uses the existing SHADOW MODEL desktop application repository. Nothing is copied back into that application; only its finished portable build is consumed.

## Prerequisites

- Visual Studio 2022 with Desktop development with C++ (for `cl.exe` and the VC++ runtime).
- CMake 3.21+ and the Qt 6.8.3 MSVC 2022 x64 kit used by the project.
- Python 3.10+ for this website's tooling.

## 1. Build and package the portable application

From the SHADOW_AI source root:

```powershell
.\scripts\build.ps1 -Configuration Release -SkipTests
.\scripts\package.ps1 -SkipBuild -IncludeModels -Zip
```

This produces `dist\ShadowAI\` with `ShadowAI.exe`, Qt plugins, VC++ runtime, llama.cpp/whisper.cpp engines, models and licence notices. Verify the build directly:

```powershell
.\dist\ShadowAI\ShadowAI.exe --smoke-test
```

The command must exit with code 0.

## 2. Build the signed-ready installer

From this website folder:

```powershell
.\.venv\Scripts\python.exe tools\package_release.py `
  --source-dir "C:\Users\shado\OneDrive\Desktop\SHADOW_AI\dist\ShadowAI" `
  --version 1.0.0 `
  --output-dir dist\release
```

The tool:

- refuses incomplete builds (missing application, Qt, runtime, engine, model or licence files);
- runs the application smoke test unless `--skip-smoke-test` is used;
- excludes development files, temporary files, debug symbols, user settings, encrypted keys, conversation history and user-trained checkpoints;
- appends a length-prefixed payload to the native installer stub;
- streams SHA-256 for every embedded file into `manifest.json`;
- writes `SHADOW-MODEL-<version>-setup.exe`.

Skip the smoke test **only** for local experiments. A release without a passing smoke test cannot be labelled stable.

Optional code signing (do this before computing the public checksum):

```powershell
signtool sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 /a dist\release\SHADOW-MODEL-1.0.0-setup.exe
```

After signing, re-run `package_release.py` manifest generation or use `verify_release.py --expected-sha256` with the new hash; update the manifest's `installer.sha256` field to the signed installer's hash.

## 3. Independently verify

```powershell
.\.venv\Scripts\python.exe tools\verify_release.py dist\release\SHADOW-MODEL-1.0.0-setup.exe --version 1.0.0
```

All checks must report `ok: true`: PE header, readable payload, no private/dev files, manifest present, version match, checksum match, required files present, licences included, smoke test recorded and footer present.

## 4. Stage or publish

Stage only (remains invisible to the public):

```powershell
.\.venv\Scripts\python.exe tools\publish_release.py `
  --version 1.0.0 `
  --installer dist\release\SHADOW-MODEL-1.0.0-setup.exe `
  --notes-file docs\RELEASE_NOTES_1.0.0.txt `
  --requirements-file docs\REQUIREMENTS_1.0.0.txt
```

Publish immediately after verification:

```powershell
.\.venv\Scripts\python.exe tools\publish_release.py ... --publish
```

Publishing can also be done from the admin dashboard. The dashboard re-verifies the installer immediately before allowing publication.

## 5. Screenshots

Only real captures of the verified build may be published. Add them through **New/Edit release → Screenshots**, or place verified PNG/JPEG/WebP files in `storage/releases/<version>/` and insert rows into the `screenshots` table. The published screenshots are the final 18 November captures from `SHADOW_AI\screenshots\` (`agents_after`, `settings_after` and their English versions), checked against the same build. Older captures in `docs\screenshots\` are not used.

## 6. Rollback

- **Unpublish:** admin dashboard → Unpublish, or `publish_release.py` can be re-run without `--publish`.
- **Replace installer:** upload a new file in the edit form. Verification is cleared automatically and must be run again.
- **Delete release:** admin edit page → Danger zone. This removes metadata, screenshots and stored installer files.

## 7. Versioning rules

- Use semantic versions (`MAJOR.MINOR.PATCH`) matching `CMakeLists.txt`.
- Never reuse a version number for different bytes.
- A new installer binary requires a new checksum and a new verification run.
- Beta releases are supported via `--channel beta`, but only stable releases appear as "latest".
