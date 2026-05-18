$ErrorActionPreference = "Stop"

$script:RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$script:DevTools = Join-Path $script:RepoRoot ".devtools"

$env:RUSTUP_HOME = Join-Path $script:DevTools "rustup"
$env:CARGO_HOME = Join-Path $script:DevTools "cargo"
$env:PIP_CACHE_DIR = Join-Path $script:DevTools "pip-cache"
$env:npm_config_cache = Join-Path $script:DevTools "npm-cache"
$env:PKG_CACHE_PATH = Join-Path $script:DevTools "pkg-cache"
$script:NsisRoot = Join-Path $script:DevTools "nsis-3.11\nsis-3.11"
$script:NsisBin = Join-Path $script:NsisRoot "Bin"
$script:NsisZip = "D:\chrome\nsis-3.11.zip"
$script:NsisZipSha1 = "EF7FF767E5CBD9EDD22ADD3A32C9B8F4500BB10D"
$script:NsisUtilsDll = "D:\chrome\nsis_tauri_utils.dll"
$script:NsisUtilsUrl = "https://github.com/tauri-apps/nsis-tauri-utils/releases/download/nsis_tauri_utils-v0.5.3/nsis_tauri_utils.dll"
$script:NsisUtilsSha1 = "75197FEE3C6A814FE035788D1C34EAD39349B860"
$script:TauriToolsDir = Join-Path $script:RepoRoot "src-tauri\target\.tauri"
$script:TauriNsisDir = Join-Path $script:TauriToolsDir "NSIS"
$env:NSISDIR = $script:NsisRoot
$env:NSISCONFDIR = $script:NsisRoot
$env:Path = "$($env:CARGO_HOME)\bin;$script:NsisBin;$script:NsisRoot;$env:Path"

New-Item -ItemType Directory -Force `
  $env:RUSTUP_HOME, `
  $env:CARGO_HOME, `
  $env:PIP_CACHE_DIR, `
  $env:npm_config_cache, `
  $env:PKG_CACHE_PATH, `
  (Join-Path $script:DevTools "nsis-3.11"), `
  (Join-Path $script:DevTools "dist"), `
  (Join-Path $script:DevTools "build"), `
  $script:TauriToolsDir | Out-Null

$script:PythonExe = Join-Path $script:RepoRoot ".venv-tauri\Scripts\python.exe"
$script:PyInstallerExe = Join-Path $script:RepoRoot ".venv-tauri\Scripts\pyinstaller.exe"
$script:NeteaseRoot = Join-Path $script:RepoRoot "NeteaseCloudMusicApi\api-enhanced-main"
$script:TargetTriple = "x86_64-pc-windows-msvc"
$script:BackendBinName = "musicdj-backend-$script:TargetTriple.exe"
$script:NeteaseBinName = "netease-api-$script:TargetTriple.exe"
$script:TauriBinaries = Join-Path $script:RepoRoot "src-tauri\binaries"

function Write-Step {
  param([string]$Message)
  Write-Host ""
  Write-Host "==> $Message" -ForegroundColor Cyan
}

function Get-FileSizeMB {
  param([string]$Path)
  if (!(Test-Path $Path)) { return 0 }
  $item = Get-Item $Path
  if ($item.PSIsContainer) {
    $sum = (Get-ChildItem $Path -Recurse -File -ErrorAction SilentlyContinue | Measure-Object Length -Sum).Sum
  } else {
    $sum = $item.Length
  }
  return [math]::Round(($sum / 1MB), 1)
}
