@echo off
setlocal EnableDelayedExpansion

cd /d "%~dp0"

if not exist ".venv\Scripts\activate.bat" (
    echo ERROR: Virtual environment not found at .venv\Scripts\activate.bat
    exit /b 1
)

call ".venv\Scripts\activate.bat"

python main.py run
set EXIT_CODE=!ERRORLEVEL!

deactivate

if !EXIT_CODE! neq 0 (
    echo ERROR: Agent exited with code !EXIT_CODE!
)

exit /b !EXIT_CODE!
