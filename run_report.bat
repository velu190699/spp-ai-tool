@echo off
setlocal EnableDelayedExpansion

REM ===========================================================================
REM  run_report.bat  -  MANUAL escape hatch (NOT scheduled)
REM
REM  Forces a Market Changes Summary (briefing) HTML on demand, outside the
REM  weekly schedule. The scheduled end-to-end job (run_agent.bat) already
REM  regenerates the briefing automatically whenever a new CUF/SUF edition is
REM  published (Option B), so this is only for ad-hoc reruns.
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

echo [%DATE% %TIME%] python main.py report
python main.py report
set EXIT_CODE=!ERRORLEVEL!

if defined USING_VENV call deactivate

if !EXIT_CODE! neq 0 (
    echo [%DATE% %TIME%] ERROR: Report generation exited with code !EXIT_CODE!
)

exit /b !EXIT_CODE!
