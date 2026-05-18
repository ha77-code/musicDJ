. "$PSScriptRoot\env.ps1"

$appData = Join-Path $env:APPDATA "Music DJ"
New-Item -ItemType Directory -Force $appData | Out-Null

function Copy-IfExists {
  param(
    [string]$Source,
    [string]$Destination
  )
  if (Test-Path $Source) {
    New-Item -ItemType Directory -Force (Split-Path $Destination -Parent) | Out-Null
    Copy-Item -LiteralPath $Source -Destination $Destination -Force
    Write-Host "Copied $Source -> $Destination"
  }
}

function Copy-DirIfExists {
  param(
    [string]$Source,
    [string]$Destination
  )
  if (Test-Path $Source) {
    New-Item -ItemType Directory -Force $Destination | Out-Null
    Copy-Item -LiteralPath (Join-Path $Source "*") -Destination $Destination -Recurse -Force
    Write-Host "Copied $Source -> $Destination"
  }
}

Write-Step "Migrating local user data to $appData"

Copy-IfExists "config.json" (Join-Path $appData "config.json")
Copy-IfExists "data\playlist.json" (Join-Path $appData "data\playlist.json")
Copy-IfExists "data\listening_stats.json" (Join-Path $appData "data\listening_stats.json")
Copy-IfExists "data\state.db" (Join-Path $appData "data\state.db")
Copy-IfExists "data\personality.json" (Join-Path $appData "data\personality.json")
Copy-DirIfExists "data\listening_history\processed" (Join-Path $appData "data\listening_history\processed")
Copy-DirIfExists "user_profile" (Join-Path $appData "user_profile")

New-Item -ItemType Directory -Force `
  (Join-Path $appData "logs"), `
  (Join-Path $appData "data\voice_memos"), `
  (Join-Path $appData "data\.ncm_cache") | Out-Null

Write-Host "Migration complete: $appData"
