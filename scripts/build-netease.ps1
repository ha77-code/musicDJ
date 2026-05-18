. "$PSScriptRoot\env.ps1"

Write-Step "Building Netease API sidecar"
if (!(Test-Path $script:NeteaseRoot)) {
  throw "Netease API directory not found: $script:NeteaseRoot"
}

$env:CI = "true"
$env:NO_PROGRESS = "1"

$pkgCmd = Join-Path $script:RepoRoot "node_modules\.bin\pkg.cmd"
if (!(Test-Path $pkgCmd)) {
  $pkgCmd = Join-Path $script:NeteaseRoot "node_modules\.bin\pkg.cmd"
}
if (!(Test-Path $pkgCmd)) {
  throw "pkg.cmd not found. Run npm.cmd install and npm.cmd --prefix $script:NeteaseRoot install"
}

$outputBase = Join-Path $script:NeteaseRoot "precompiled\app"
New-Item -ItemType Directory -Force (Split-Path $outputBase -Parent) | Out-Null

Push-Location $script:NeteaseRoot
try {
  & $pkgCmd . -t node18-win-x64 -C GZip -o $outputBase
} finally {
  Pop-Location
}

$built = Join-Path $script:NeteaseRoot "precompiled\app.exe"
if (!(Test-Path $built)) {
  throw "Netease sidecar was not created: $built"
}

New-Item -ItemType Directory -Force $script:TauriBinaries | Out-Null
$target = Join-Path $script:TauriBinaries $script:NeteaseBinName
Copy-Item -LiteralPath $built -Destination $target -Force

Write-Host "Netease sidecar: $target ($(Get-FileSizeMB $target) MB)"
