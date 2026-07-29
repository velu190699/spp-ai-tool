@echo off
setlocal EnableDelayedExpansion

REM ===========================================================================
REM  run_agent.bat  -  END-TO-END weekly job (RUNBOOK section 3)
REM
REM    1. python main.py run
REM         scrape spp.org, refresh the watch list + market initiatives,
REM         (re)download each watched RR's Recommendation Report, and post the
REM         briefing / RR Control / heartbeat to Slack as Option B decides.
REM    2. on success -> python main.py settlement-report --call-claude --stories
REM         generate the per-RR Jira story workbooks (with redline crops) for
REM         the RRs whose Recommendation Report changed.
REM
REM  If step 1 fails the job aborts before step 2 (main.py already posts a Slack
REM  failure alert). Word COM redline rendering needs a real desktop session, so
REM  the scheduled task must run "only when the user is logged on".
REM ===========================================================================

cd /d "%~dp0"

REM --- Use the project virtualenv if one exists; otherwise the system Python ---
if exist ".venv\Scripts\activate.bat" (
    call ".venv\Scripts\activate.bat"
    set "USING_VENV=1"
) else (
    echo [%DATE% %TIME%] No .venv found; using system Python.
    set "USING_VENV="
)

REM --- Step 1: data collection + briefing / RR Control / heartbeat -------------
echo [%DATE% %TIME%] STEP 1/2: python main.py run
python main.py run
set RUN_EXIT=!ERRORLEVEL!

if !RUN_EXIT! neq 0 (
    echo [%DATE% %TIME%] ERROR: 'run' exited with code !RUN_EXIT!; skipping settlement-report.
    if defined USING_VENV call deactivate
    exit /b !RUN_EXIT!
)

REM --- Step 2: settlement stories for RRs whose Rec Report changed -------------
echo [%DATE% %TIME%] STEP 2/2: python main.py settlement-report --call-claude --stories
python main.py settlement-report --call-claude --stories
set STORY_EXIT=!ERRORLEVEL!

if defined USING_VENV call deactivate

if !STORY_EXIT! neq 0 (
    echo [%DATE% %TIME%] ERROR: 'settlement-report' exited with code !STORY_EXIT!.
    exit /b !STORY_EXIT!
)

echo [%DATE% %TIME%] End-to-end run completed successfully.
exit /b 0
