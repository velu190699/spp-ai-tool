# setup_scheduler.ps1
# Registers (or updates) the SPP RR Automation and Report tasks in Windows Task Scheduler.
# Run once as the user who will own the tasks. No admin required for user-level tasks.
#
# Both tasks run weekly on the same day. The report task is offset later in the day
# so the SharePoint-synced CUF/SUF folders have time to pick up that day's documents.
#
# Usage:
#   .\setup_scheduler.ps1                                   # Weekly on Monday: run at 09:00, report at 14:00
#   .\setup_scheduler.ps1 -DayOfWeek Wednesday -Hour 8       # Weekly on Wednesday: run at 08:00, report at 13:00
#   .\setup_scheduler.ps1 -ReportDelayHours 3                # Report 3 hours after run instead of 5
#   .\setup_scheduler.ps1 -Remove                            # Delete both tasks

param(
    [System.DayOfWeek]$DayOfWeek     = [System.DayOfWeek]::Monday,
    [int]$Hour              = 9,
    [int]$Minute            = 0,
    [int]$ReportDelayHours  = 5,
    [switch]$Remove
)

$RUN_TASK_NAME    = "SPP-RR-Automation"
$REPORT_TASK_NAME = "SPP-RR-Report"
$PROJECT_DIR      = $PSScriptRoot
$RUN_BAT_PATH     = Join-Path $PROJECT_DIR "run_agent.bat"
$REPORT_BAT_PATH  = Join-Path $PROJECT_DIR "run_report.bat"

if ($Remove) {
    Unregister-ScheduledTask -TaskName $RUN_TASK_NAME -Confirm:$false -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $REPORT_TASK_NAME -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Tasks '$RUN_TASK_NAME' and '$REPORT_TASK_NAME' removed."
    exit 0
}

if (-not (Test-Path $RUN_BAT_PATH)) {
    Write-Error "run_agent.bat not found at: $RUN_BAT_PATH"
    exit 1
}

if (-not (Test-Path $REPORT_BAT_PATH)) {
    Write-Error "run_report.bat not found at: $REPORT_BAT_PATH"
    exit 1
}

$runTime    = [datetime]::Today.AddHours($Hour).AddMinutes($Minute)
$reportTime = $runTime.AddHours($ReportDelayHours)

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

# --- Data collection / RR crossing task ---
$runAction = New-ScheduledTaskAction `
    -Execute    "cmd.exe" `
    -Argument   "/c `"$RUN_BAT_PATH`" >> `"$PROJECT_DIR\logs\scheduler.log`" 2>&1" `
    -WorkingDirectory $PROJECT_DIR

$runTrigger = New-ScheduledTaskTrigger `
    -Weekly `
    -DaysOfWeek $DayOfWeek `
    -At $runTime

Register-ScheduledTask `
    -TaskName  $RUN_TASK_NAME `
    -Action    $runAction `
    -Trigger   $runTrigger `
    -Settings  $settings `
    -Principal $principal `
    -Force | Out-Null

# --- Report generation task (Slack notification fires as soon as the report is written) ---
$reportAction = New-ScheduledTaskAction `
    -Execute    "cmd.exe" `
    -Argument   "/c `"$REPORT_BAT_PATH`" >> `"$PROJECT_DIR\logs\scheduler.log`" 2>&1" `
    -WorkingDirectory $PROJECT_DIR

$reportTrigger = New-ScheduledTaskTrigger `
    -Weekly `
    -DaysOfWeek $DayOfWeek `
    -At $reportTime

Register-ScheduledTask `
    -TaskName  $REPORT_TASK_NAME `
    -Action    $reportAction `
    -Trigger   $reportTrigger `
    -Settings  $settings `
    -Principal $principal `
    -Force | Out-Null

Write-Host "Task '$RUN_TASK_NAME' registered successfully."
Write-Host "  Schedule : Every $DayOfWeek at $($runTime.ToString('HH:mm'))"
Write-Host "  Script   : $RUN_BAT_PATH"
Write-Host ""
Write-Host "Task '$REPORT_TASK_NAME' registered successfully."
Write-Host "  Schedule : Every $DayOfWeek at $($reportTime.ToString('HH:mm')) ($ReportDelayHours h after the run task)"
Write-Host "  Script   : $REPORT_BAT_PATH"
Write-Host ""
Write-Host "  Log      : $PROJECT_DIR\logs\scheduler.log"
Write-Host ""
Write-Host "To verify  : Get-ScheduledTask -TaskName '$RUN_TASK_NAME','$REPORT_TASK_NAME' | Format-List"
Write-Host "To run now : Start-ScheduledTask -TaskName '$RUN_TASK_NAME'  (or '$REPORT_TASK_NAME')"
Write-Host "To remove  : .\setup_scheduler.ps1 -Remove"
