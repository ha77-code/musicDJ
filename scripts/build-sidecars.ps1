. "$PSScriptRoot\env.ps1"

& "$PSScriptRoot\check-env.ps1"
& "$PSScriptRoot\build-backend.ps1"
& "$PSScriptRoot\build-netease.ps1"

Write-Step "Sidecar summary"
Get-ChildItem $script:TauriBinaries -Filter "*.exe" | Select-Object Name,@{n="SizeMB";e={[math]::Round($_.Length / 1MB, 1)}} | Format-Table -AutoSize
