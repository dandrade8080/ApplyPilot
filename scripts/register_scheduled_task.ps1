# Register ApplyPilot Daily Report in Windows Task Scheduler
# Run this ONCE as Administrator to create the scheduled task.
# Edit the trigger time below (default: 8:00 AM daily).

$TaskName = "ApplyPilot Daily Report"
$ScriptPath = "C:\Users\dandr\ApplyPilot\ApplyPilot\scripts\daily_report.ps1"
$PythonPath = "C:\Users\dandr\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe"

$Action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$ScriptPath`""

$Trigger = New-ScheduledTaskTrigger `
    -Daily `
    -At "08:00"

$Principal = New-ScheduledTaskPrincipal `
    -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive `
    -RunLevel Limited

$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable `
    -MultipleInstances IgnoreNew

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Principal $Principal `
    -Settings $Settings `
    -Description "ApplyPilot - Daily job discovery + scoring + Telegram report" `
    -Force

Write-Host "Task '$TaskName' registered successfully!"
Write-Host "Runs daily at 8:00 AM."
Write-Host ""
Write-Host "To change the schedule:"
Write-Host "  taskschd.msc  ->  find '$TaskName' -> right-click -> Properties -> Triggers"
Write-Host ""
Write-Host "To run now (test):"
Write-Host "  Start-ScheduledTask -TaskName '$TaskName'"
