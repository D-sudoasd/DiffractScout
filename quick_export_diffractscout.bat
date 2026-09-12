@echo off
REM Drag-and-drop one-shot CIF export (Cu Ka lab defaults).
REM Usage: drop CIF files/folders onto this script, or pass paths on the command line.
REM Delayed expansion stays disabled so exclamation marks in input paths survive.
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
set "ENTRY=%~dp0scripts\diffractscout_entry.py"

if "%~1"=="" goto :usage

REM Normalize the first argument before deriving its sibling output name.  A
REM dropped directory commonly has a trailing backslash, for which %~n1 is
REM empty; trimming it makes the directory name the output stem.
set "FIRST=%~1"
:trim_first
if not "%FIRST:~-1%"=="\" goto :first_ready
if "%FIRST:~1%"=="" goto :first_ready
if "%FIRST:~2%"=="\" goto :first_ready
set "FIRST=%FIRST:~0,-1%"
goto :trim_first

:first_ready
for %%I in ("%FIRST%") do set "FIRST_FULL=%%~fI"
for %%I in ("%FIRST_FULL%") do set "OUT=%%~dpI%%~nI_diffractscout.xlsx"

REM Match the GUI launcher: checkout .venv first so a README venv install
REM works without activating the environment or a global package import.
if exist "%~dp0.venv\Scripts\python.exe" goto :venv_python

where diffractscout-quick-export >nul 2>&1
if not errorlevel 1 goto :run_installed

REM Prefer an interpreter that can start; scripts\diffractscout_entry.py
REM adds the checkout src/ path so a global `import diffractscout` is not
REM required. Once an actual export starts, its failure is final.
where python >nul 2>&1
if errorlevel 1 goto :check_py_launcher
python -c "import sys" >nul 2>&1
if errorlevel 1 goto :check_py_launcher
goto :run_python

:check_py_launcher
where py >nul 2>&1
if errorlevel 1 goto :missing_runtime
goto :run_py

:venv_python
"%~dp0.venv\Scripts\python.exe" "%ENTRY%" quick-export -o "%OUT%" %*
set "RC=%ERRORLEVEL%"
goto :report

:run_python
python "%ENTRY%" quick-export -o "%OUT%" %*
set "RC=%ERRORLEVEL%"
goto :report

:run_py
py -3 "%ENTRY%" quick-export -o "%OUT%" %*
set "RC=%ERRORLEVEL%"
goto :report

:run_installed
call diffractscout-quick-export -o "%OUT%" %*
set "RC=%ERRORLEVEL%"
goto :report

:report
if "%RC%"=="0" goto :success
echo.
echo quick-export finished with exit code %RC%
pause
set "FINAL_RC=%RC%"
endlocal
exit /b %FINAL_RC%

:success
echo.
echo(Excel: "%OUT%"
echo(Done.
pause
endlocal
exit /b 0

:usage
echo Drag CIF files or folders onto this script, or run:
echo   %~nx0 path\to\sample.cif [more paths...]
echo.
echo Output defaults to ^<first-file-dir^>\^<first-stem^>_diffractscout.xlsx
echo with a verifiable bundle at ^<stem^>_diffractscout_bundle\
pause
endlocal
exit /b 1

:missing_runtime
echo ERROR: DiffractScout quick-export is unavailable in the current environment.
echo Checked the repository .venv, installed diffractscout-quick-export, python, and py -3.
echo Install or activate the package with:
echo   py -3 -m pip install -e .
pause
endlocal
exit /b 1
