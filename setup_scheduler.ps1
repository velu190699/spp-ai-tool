# setup_scheduler.ps1
# Registers (or updates) the single END-TO-END SPP RR weekly task in Windows Task Scheduler.
# Run once as the user who will own the task. No admin required for user-level tasks.
#
# The task runs run_agent.bat, which chains:
#   1. python main.py run
#   2. (on success) python main.py settlement-report --call-claude --stories
# i.e. the full weekly flow (RUNBOOK section 3). The old separate "report" task
# is gone: `run` already regenerates the briefing whenever a new CUF/SUF edition
# is published (Option B), so forcing a weekly briefing added only noise/cost.
#
# IMPORTANT: run this on exactly ONE machine. The tool shares State/metadata.json
# in the synced folder and posts to a real team Slack channel; two schedulers
# would duplicate Slack posts, double the LLM cost, and race on the ledger.
#
# Mode = "run only when the user is logged on" (Interactive): the settlement step
# renders redline screenshots via Microsoft Word COM, which needs a real desktop
# session. A locked screen is fine; a signed-off session is not.
#
# Usage:
#   .\setup_scheduler.ps1                                # Weekly Monday 10:00
#   .\setup_scheduler.ps1 -DayOfWeek Wednesday -Hour 8   # Weekly Wednesday 08:00
#   .\setup_scheduler.ps1 -Remove                        # Delete the task

param(
    [System.DayOfWeek]$DayOfWeek = [System.DayOfWeek]::Monday,
    [int]$Hour   = 10,
    [int]$Minute = 0,
    [switch]$Remove
)

$TASK_NAME   = "SPP-RR-Automation"
$PROJECT_DIR = $PSScriptRoot
$BAT_PATH    = Join-Path $PROJECT_DIR "run_agent.bat"
$LOG_DIR     = Join-Path $PROJECT_DIR "logs"
$LOG_PATH    = Join-Path $LOG_DIR "scheduler.log"

if ($Remove) {
    Unregister-ScheduledTask -TaskName $TASK_NAME -Confirm:$false -ErrorAction SilentlyContinue
    # Also remove the legacy report task if a previous version of this script created it.
    Unregister-ScheduledTask -TaskName "SPP-RR-Report" -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Task '$TASK_NAME' removed (and legacy 'SPP-RR-Report' if present)."
    exit 0
}

if (-not (Test-Path $BAT_PATH)) {
    Write-Error "run_agent.bat not found at: $BAT_PATH"
    exit 1
}

if (-not (Test-Path $LOG_DIR)) {
    New-Item -ItemType Directory -Path $LOG_DIR | Out-Null
}

# Remove the legacy separate report task if it exists (superseded by the end-to-end job).
Unregister-ScheduledTask -TaskName "SPP-RR-Report" -Confirm:$false -ErrorAction SilentlyContinue

$runTime = [datetime]::Today.AddHours($Hour).AddMinutes($Minute)

$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit  (New-TimeSpan -Hours 3) `
    -RestartCount        2 `
    -RestartInterval     (New-TimeSpan -Minutes 30) `
    -StartWhenAvailable  `
    -RunOnlyIfNetworkAvailable

$principal = New-ScheduledTaskPrincipal `
    -UserId    $env:USERNAME `
    -LogonType Interactive `
    -RunLevel  Limited

$action = New-ScheduledTaskAction `
    -Execute          "cmd.exe" `
    -Argument         "/c `"$BAT_PATH`" >> `"$LOG_PATH`" 2>&1" `
    -WorkingDirectory $PROJECT_DIR

$trigger = New-ScheduledTaskTrigger `
    -Weekly `
    -DaysOfWeek $DayOfWeek `
    -At $runTime

Register-ScheduledTask `
    -TaskName  $TASK_NAME `
    -Action    $action `
    -Trigger   $trigger `
    -Settings  $settings `
    -Principal $principal `
    -Force | Out-Null

Write-Host "Task '$TASK_NAME' registered successfully."
Write-Host "  Schedule : Every $DayOfWeek at $($runTime.ToString('HH:mm'))"
Write-Host "  Flow     : run  ->  settlement-report --call-claude --stories"
Write-Host "  Script   : $BAT_PATH"
Write-Host "  Log      : $LOG_PATH"
Write-Host ""
Write-Host "To verify  : Get-ScheduledTask -TaskName '$TASK_NAME' | Format-List"
Write-Host "To run now : Start-ScheduledTask -TaskName '$TASK_NAME'"
Write-Host "To remove  : .\setup_scheduler.ps1 -Remove"
