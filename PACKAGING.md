# Music DJ Desktop Packaging

This project packages the existing Flask + React/Babel + Netease API app as a
Windows x64 Tauri desktop application.

## Local Tooling

The packaging toolchain is intentionally local to this repository:

- Rust/Cargo: `.devtools/cargo` and `.devtools/rustup`
- Python packaging venv: `.venv-tauri`
- npm/pip/pkg caches: `.devtools/*-cache`
- Tauri sidecars: `src-tauri/binaries`
- Tauri NSIS tools cache: `src-tauri/target/.tauri/NSIS`

Run all packaging commands through `npm.cmd`, not `npm`, on this PowerShell
setup.

## First-Time User Data Migration

Before testing the packaged app with your current personal data:

```powershell
powershell.exe -ExecutionPolicy Bypass -File scripts/migrate-user-data.ps1
```

This copies private runtime data to:

```text
%APPDATA%\Music DJ
```

The installer does not bundle `config.json`, `data/`, `user_profile/`, or local
music files.

## Build

```powershell
npm.cmd run check:env
npm.cmd run build:sidecars
npm.cmd run setup:nsis
npm.cmd run tauri:build
```

Or run the full release flow:

```powershell
npm.cmd run build:release
```

If `npm.cmd install` or `build:netease` needs network access, run those commands
from a normal PowerShell session so npm/pkg can download Tauri packages and the
pkg Node base binary into the D-drive caches.

The NSIS installer toolchain is prepared by `scripts/setup-nsis.ps1`. It uses
`D:\chrome\nsis-3.11.zip` for the NSIS base files and downloads the extra Tauri
plugin `nsis_tauri_utils.dll` if it is not already present at
`D:\chrome\nsis_tauri_utils.dll`.

If the sandbox blocks that plugin download, download it manually from:

```text
https://github.com/tauri-apps/nsis-tauri-utils/releases/download/nsis_tauri_utils-v0.5.3/nsis_tauri_utils.dll
```

Then run:

```powershell
npm.cmd run setup:nsis
npm.cmd run tauri:build
```

## Update Flow

1. Reproduce the bug in source mode.
2. Modify `frontend/index.html`, `backend/dj_server.py`, or `backend/agent/*`.
3. Run `npm.cmd run check:env` and Python compile checks.
4. Run `npm.cmd run build:release`.
5. Install the new build over the old one.

User data remains in `%APPDATA%\Music DJ`, so covering installs should preserve
config, playlist, memory, stats, logs, and profile notes.
