. "$PSScriptRoot\env.ps1"

& "$PSScriptRoot\build-sidecars.ps1"
& "$PSScriptRoot\setup-nsis.ps1"

Write-Step "Building Tauri installer"
npm.cmd run tauri:build

Write-Step "Release artifacts"
$bundleDir = Join-Path $script:RepoRoot "src-tauri\target\release\bundle"
if (Test-Path $bundleDir) {
  Get-ChildItem $bundleDir -Recurse -File |
    Select-Object FullName,@{n="SizeMB";e={[math]::Round($_.Length / 1MB, 1)}} |
    Format-Table -AutoSize
} else {
  Write-Warning "Bundle directory not found yet: $bundleDir"
}
