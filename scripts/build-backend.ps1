. "$PSScriptRoot\env.ps1"

Write-Step "Building Flask backend sidecar"
if (!(Test-Path $script:PyInstallerExe)) {
  throw "PyInstaller not found: $script:PyInstallerExe"
}

$distDir = Join-Path $script:DevTools "dist\backend"
$workDir = Join-Path $script:DevTools "build\backend"
$specDir = Join-Path $script:DevTools "build\spec"
$frontendDir = Join-Path $script:RepoRoot "frontend"
$configExample = Join-Path $script:RepoRoot "config_example.json"
New-Item -ItemType Directory -Force $distDir, $workDir, $specDir | Out-Null

& $script:PyInstallerExe `
  --noconfirm `
  --clean `
  --onefile `
  --name "musicdj-backend" `
  --distpath $distDir `
  --workpath $workDir `
  --specpath $specDir `
  --paths "backend" `
  --add-data "$frontendDir;frontend" `
  --add-data "$configExample;." `
  --hidden-import "agent.rules" `
  --hidden-import "agent.scheduler" `
  --hidden-import "agent.session" `
  --exclude-module "tkinter" `
  --exclude-module "pytest" `
  "backend\dj_server.py"

$built = Join-Path $distDir "musicdj-backend.exe"
if (!(Test-Path $built)) {
  throw "Backend sidecar was not created: $built"
}

New-Item -ItemType Directory -Force $script:TauriBinaries | Out-Null
$target = Join-Path $script:TauriBinaries $script:BackendBinName
Copy-Item -LiteralPath $built -Destination $target -Force

Write-Host "Backend sidecar: $target ($(Get-FileSizeMB $target) MB)"
