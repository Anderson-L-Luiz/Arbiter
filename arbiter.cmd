@echo off
setlocal EnableExtensions EnableDelayedExpansion
rem ============================================================
rem  Arbiter launcher — Claude Code builder vs. Gemini judge TUI
rem  Double-click to run interactively, or pass args:
rem    arbiter.cmd "C:\path\to\project" "Task description" [rounds] [stop_score]
rem ============================================================

rem Always run from the script's own directory
cd /d "%~dp0"

rem --- Locate Python -----------------------------------------------------
set "PYEXE="
if exist "C:\Users\ander\AppData\Local\Python\bin\python.exe" (
    set "PYEXE=C:\Users\ander\AppData\Local\Python\bin\python.exe"
) else (
    for %%P in (python.exe py.exe) do (
        if not defined PYEXE (
            where %%P >nul 2>nul && set "PYEXE=%%P"
        )
    )
)
if not defined PYEXE (
    echo [arbiter] Python not found on PATH. Install Python 3.10+ and retry.
    pause
    exit /b 1
)

rem --- Verify claude + gemini CLIs --------------------------------------
where claude >nul 2>nul || (
    echo [arbiter] WARNING: 'claude' CLI not found on PATH.
    echo           Install Claude Code and make sure 'claude' works from cmd.
)
where gemini >nul 2>nul || (
    echo [arbiter] WARNING: 'gemini' CLI not found on PATH.
    echo           Install Google Gemini CLI and make sure 'gemini' works from cmd.
)

rem --- Ensure textual is installed --------------------------------------
"%PYEXE%" -c "import textual" 1>nul 2>nul
if errorlevel 1 (
    echo [arbiter] Installing textual ^(first run^)...
    "%PYEXE%" -m pip install --quiet --disable-pip-version-check textual>=0.60 || (
        echo [arbiter] pip install textual failed. Try: "%PYEXE%" -m pip install textual
        pause
        exit /b 1
    )
)

rem --- Parse args, prompt if missing ------------------------------------
set "PROJECT=%~1"
set "TASK=%~2"
set "TASKFILE=%~3"
set "ROUNDS=%~4"
set "STOPSCORE=%~5"

if "%PROJECT%"=="" (
    echo.
    set /p "PROJECT=Project directory (Claude will work here): "
)
if "%TASK%"=="" if "%TASKFILE%"=="" (
    echo.
    echo Enter task inline, or type FILE to provide a task file path:
    set /p "TASK=Task: "
)
if /i "%TASK%"=="FILE" (
    set "TASK="
    set /p "TASKFILE=Task file path: "
)
if "%ROUNDS%"=="" set "ROUNDS=5"
if "%STOPSCORE%"=="" set "STOPSCORE=9.0"

if "%PROJECT%"=="" (
    echo [arbiter] No project directory provided. Aborting.
    pause
    exit /b 1
)
if "%TASK%"=="" if "%TASKFILE%"=="" (
    echo [arbiter] No task provided. Aborting.
    pause
    exit /b 1
)

if not exist "%PROJECT%\" (
    echo [arbiter] Creating project directory: %PROJECT%
    mkdir "%PROJECT%" 2>nul
)

rem --- Launch TUI --------------------------------------------------------
echo.
echo [arbiter] Launching split-pane TUI...
echo   project = %PROJECT%
echo   rounds  = %ROUNDS%
echo   stop@   = %STOPSCORE%
echo.

if not "%TASKFILE%"=="" (
    "%PYEXE%" -m arbiter.app --task-file "%TASKFILE%" "%PROJECT%" -n %ROUNDS% --stop-score %STOPSCORE%
) else (
    "%PYEXE%" -m arbiter.app -t "%TASK%" "%PROJECT%" -n %ROUNDS% --stop-score %STOPSCORE%
)
set "RC=%ERRORLEVEL%"

if not "%RC%"=="0" (
    echo.
    echo [arbiter] Exited with code %RC%.
    pause
)
endlocal & exit /b %RC%
