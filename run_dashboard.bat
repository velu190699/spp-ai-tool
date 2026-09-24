@echo off
setlocal EnableDelayedExpansion

REM ===========================================================================
REM  run_dashboard.bat  -  opens the RR Control app (Streamlit) in the browser
REM
REM  PROTOTYPE. Read-only for the tool's data: it reads the watch list and
REM  writes only what the PM marks, into decisions.db. Closing the browser tab
REM  does not stop it -- close this window (or press Ctrl+C) to shut it down.
REM
REM  Same venv-if-present convention as the other .bat wrappers in this repo.
REM ===========================================================================

cd /d "%~dp0"

if exist ".venv\Scripts\activate.bat" (
    call ".venv\Scripts\activate.bat"
    set "USING_VENV=1"
) else (
    echo [%DATE% %TIME%] No .venv found; using system Python.
    set "USING_VENV="
)

python -c "import streamlit" 2>nul
if !ERRORLEVEL! neq 0 (
    echo [%DATE% %TIME%] Installing streamlit ...
    python -m pip install streamlit pandas
)

echo [%DATE% %TIME%] Starting the RR Control app on http://localhost:8501
python -m streamlit run dashboard_app.py
set EXIT_CODE=!ERRORLEVEL!

if defined USING_VENV call deactivate

if !EXIT_CODE! neq 0 (
    echo [%DATE% %TIME%] ERROR: the dashboard exited with code !EXIT_CODE!
)

exit /b !EXIT_CODE!
