param(
  [string]$NsisZip,
  [string]$UtilsDll,
  [switch]$NoDownload
)

. "$PSScriptRoot\env.ps1"

if (!$NsisZip) {
  $NsisZip = $script:NsisZip
}
if (!$UtilsDll) {
  $UtilsDll = $script:NsisUtilsDll
}

$requiredNsisFiles = @(
  "makensis.exe",
  "Bin\makensis.exe",
  "Stubs\lzma-x86-unicode",
  "Stubs\lzma_solid-x86-unicode",
  "Plugins\x86-unicode\additional\nsis_tauri_utils.dll",
  "Include\MUI2.nsh",
  "Include\FileFunc.nsh",
  "Include\x64.nsh",
  "Include\nsDialogs.nsh",
  "Include\WinMessages.nsh",
  "Include\Win\COM.nsh",
  "Include\Win\Propkey.nsh",
  "Include\Win\RestartManager.nsh"
)

function Assert-FileHash {
  param(
    [string]$Path,
    [string]$ExpectedSha1
  )

  if (!(Test-Path -LiteralPath $Path)) {
    throw "File not found: $Path"
  }

  $actual = (Get-FileHash -LiteralPath $Path -Algorithm SHA1).Hash.ToUpperInvariant()
  if ($actual -ne $ExpectedSha1.ToUpperInvariant()) {
    throw "Hash mismatch for $Path. Expected $ExpectedSha1, got $actual"
  }
}

function Get-ValidUtilsDll {
  param([string]$PreferredPath)

  $candidates = @(
    $PreferredPath,
    (Join-Path $script:DevTools "dist\nsis_tauri_utils.dll"),
    (Join-Path $script:NsisRoot "Plugins\x86-unicode\additional\nsis_tauri_utils.dll")
  ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }

  foreach ($candidate in $candidates) {
    try {
      Assert-FileHash -Path $candidate -ExpectedSha1 $script:NsisUtilsSha1
      return $candidate
    } catch {
      Write-Warning $_.Exception.Message
    }
  }

  return $null
}

Write-Step "Preparing local NSIS tools"

if (!(Test-Path -LiteralPath $script:NsisRoot)) {
  if (!(Test-Path -LiteralPath $NsisZip)) {
    throw "NSIS zip not found: $NsisZip"
  }

  Assert-FileHash -Path $NsisZip -ExpectedSha1 $script:NsisZipSha1
  $extractDir = Join-Path $script:DevTools "nsis-3.11"
  Expand-Archive -LiteralPath $NsisZip -DestinationPath $extractDir -Force
}

$utilsSource = Get-ValidUtilsDll -PreferredPath $UtilsDll
if (!$utilsSource) {
  if ($NoDownload) {
    throw "nsis_tauri_utils.dll is missing. Download it to $UtilsDll from $($script:NsisUtilsUrl), or run scripts/setup-nsis.ps1 without -NoDownload."
  }

  $downloadPath = Join-Path $script:DevTools "dist\nsis_tauri_utils.dll"
  Write-Host "Downloading nsis_tauri_utils.dll"
  Invoke-WebRequest -Uri $script:NsisUtilsUrl -OutFile $downloadPath
  Assert-FileHash -Path $downloadPath -ExpectedSha1 $script:NsisUtilsSha1
  $utilsSource = $downloadPath
}

$sourceAdditionalDir = Join-Path $script:NsisRoot "Plugins\x86-unicode\additional"
New-Item -ItemType Directory -Force $sourceAdditionalDir | Out-Null
Copy-Item -LiteralPath $utilsSource -Destination (Join-Path $sourceAdditionalDir "nsis_tauri_utils.dll") -Force

New-Item -ItemType Directory -Force $script:TauriNsisDir | Out-Null
Copy-Item -Path (Join-Path $script:NsisRoot "*") -Destination $script:TauriNsisDir -Recurse -Force

$targetUtilsDll = Join-Path $script:TauriNsisDir "Plugins\x86-unicode\additional\nsis_tauri_utils.dll"
Assert-FileHash -Path $targetUtilsDll -ExpectedSha1 $script:NsisUtilsSha1

$missing = $requiredNsisFiles | Where-Object { !(Test-Path -LiteralPath (Join-Path $script:TauriNsisDir $_)) }
if ($missing) {
  throw "Local NSIS cache is missing required files: $($missing -join ', ')"
}

& (Join-Path $script:TauriNsisDir "Bin\makensis.exe") /VERSION
Write-Host "NSIS cache: $script:TauriNsisDir ($(Get-FileSizeMB $script:TauriNsisDir) MB)"
