# ApplyPilot - Daily Report Scheduler
# Runs discovery + scoring for the last 24h and sends results via Telegram.
# Schedule this via Windows Task Scheduler to run daily (e.g., 8:00 AM).

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ApplyPilotDir = "C:\Users\dandr\ApplyPilot\ApplyPilot"
$SrcDir = "$ApplyPilotDir\src"
$LogDir = "$env:USERPROFILE\.applypilot\logs"
$LogFile = Join-Path $LogDir "daily_report_$(Get-Date -Format 'yyyy-MM-dd_HHmmss').log"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$env:PYTHONPATH = $SrcDir

Set-Location -LiteralPath $SrcDir

& python -m applypilot.cli daily-report 2>&1 | Tee-Object -FilePath $LogFile

Write-Host ""
Write-Host "Log saved: $LogFile"
