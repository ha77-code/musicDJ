. "$PSScriptRoot\env.ps1"

Write-Step "Checking Rust"
rustc --version
cargo --version
$hostTuple = rustc --print host-tuple
Write-Host "host tuple: $hostTuple"
if ($hostTuple -ne $script:TargetTriple) {
  throw "Expected Rust host tuple $script:TargetTriple, got $hostTuple"
}

Write-Step "Checking Visual Studio C++ tools"
$vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
if (!(Test-Path $vswhere)) {
  throw "vswhere.exe not found"
}
$vsPath = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if (!$vsPath) {
  throw "Visual Studio C++ build tools not found"
}
Write-Host "VS Build Tools: $vsPath"

Write-Step "Checking Python packaging environment"
if (!(Test-Path $script:PythonExe)) {
  throw "Python venv not found: $script:PythonExe"
}
& $script:PythonExe -c "import flask, requests, mutagen, Crypto, websocket, PyInstaller; print('python packaging deps ok')"
& $script:PyInstallerExe --version

Write-Step "Checking Node and Netease pkg"
node --version
npm.cmd --version
$pkgCmd = Join-Path $script:NeteaseRoot "node_modules\.bin\pkg.cmd"
if (!(Test-Path $pkgCmd)) {
  throw "pkg.cmd not found. Run npm.cmd --prefix $script:NeteaseRoot install"
}
& $pkgCmd --version

Write-Step "Checking WebView2"
$webviewPaths = @(
  "C:\Program Files (x86)\Microsoft\EdgeWebView\Application",
  "C:\Program Files\Microsoft\EdgeWebView\Application"
)
$webview = $webviewPaths | Where-Object { Test-Path $_ } | Select-Object -First 1
if (!$webview) {
  throw "Microsoft Edge WebView2 Runtime not found"
}
Write-Host "WebView2: $webview"

& "$PSScriptRoot\setup-nsis.ps1"

Write-Step "Environment OK"
