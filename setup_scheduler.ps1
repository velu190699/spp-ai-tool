# setup_scheduler.ps1
# Registers (or updates) the SPP RR Automation task in Windows Task Scheduler.
# Run once as the user who will own the task. No admin required for user-level tasks.
#
# Usage:
#   .\setup_scheduler.ps1                          # Monthly on the 1st at 09:00
#   .\setup_scheduler.ps1 -DayOfMonth 15 -Hour 8  # Monthly on the 15th at 08:00
#   .\setup_scheduler.ps1 -Remove                  # Delete the task

param(
    [int]$DayOfMonth = 1,
    [int]$Hour       = 9,
    [int]$Minute     = 0,
    [switch]$Remove
)

$TASK_NAME = "SPP-RR-Automation"
$PROJECT_DIR = $PSScriptRoot
$BAT_PATH    = Join-Path $PROJECT_DIR "run_agent.bat"

if ($Remove) {
    Unregister-ScheduledTask -TaskName $TASK_NAME -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Task '$TASK_NAME' removed."
    exit 0
}

if (-not (Test-Path $BAT_PATH)) {
    Write-Error "run_agent.bat not found at: $BAT_PATH"
    exit 1
}

$action = New-ScheduledTaskAction `
    -Execute    "cmd.exe" `
    -Argument   "/c `"$BAT_PATH`" >> `"$PROJECT_DIR\logs\scheduler.log`" 2>&1" `
    -WorkingDirectory $PROJECT_DIR

$trigger = New-ScheduledTaskTrigger `
    -Monthly `
    -DaysOfMonth $DayOfMonth `
    -At ([datetime]::Today.AddHours($Hour).AddMinutes($Minute))

$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit  (New-TimeSpan -Hours 3) `
    -RestartCount        2 `
    -RestartInterval     (New-TimeSpan -Minutes 30) `
    -StartWhenAvailable  `
    -RunOnlyIfNetworkAvailable

$principal = New-ScheduledTaskPrincipal `
    -UserId   $env:USERNAME `
    -LogonType Interactive `
    -RunLevel Limited

Register-ScheduledTask `
    -TaskName  $TASK_NAME `
    -Action    $action `
    -Trigger   $trigger `
    -Settings  $settings `
    -Principal $principal `
    -Force | Out-Null

Write-Host "Task '$TASK_NAME' registered successfully."
Write-Host "  Schedule : Day $DayOfMonth of every month at $($Hour.ToString('00')):$($Minute.ToString('00'))"
Write-Host "  Script   : $BAT_PATH"
Write-Host "  Log      : $PROJECT_DIR\logs\scheduler.log"
Write-Host ""
Write-Host "To verify: Get-ScheduledTask -TaskName '$TASK_NAME' | Format-List"
Write-Host "To run now: Start-ScheduledTask -TaskName '$TASK_NAME'"
Write-Host "To remove : .\setup_scheduler.ps1 -Remove"
