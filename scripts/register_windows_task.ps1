[CmdletBinding()]
param(
    [ValidateRange(1, 24)]
    [int]$IntervalHours = 3,
    [string]$TaskName = "CareerOS Job Pipeline"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$PythonPath = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$LogPath = Join-Path $ProjectRoot "careeros-pipeline.log"

if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
    throw "CareerOS virtual environment was not found at $PythonPath"
}

$escapedRoot = $ProjectRoot.Replace("'", "''")
$escapedPython = $PythonPath.Replace("'", "''")
$escapedLog = $LogPath.Replace("'", "''")
$command = "Set-Location -LiteralPath '$escapedRoot'; & '$escapedPython' -m scripts.run_career_pipeline --all *>> '$escapedLog'"
$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -NonInteractive -WindowStyle Hidden -Command `"$command`""
$trigger = New-ScheduledTaskTrigger `
    -Once `
    -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Hours $IntervalHours)
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -WakeToRun `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Runs the local CareerOS collection, evaluation, and notification pipeline." `
    -Force | Out-Null

Write-Output "Registered '$TaskName' to run every $IntervalHours hour(s)."
