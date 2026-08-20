@echo off
REM Drag-and-drop one-shot CIF export (Cu Ka lab defaults).
REM Usage: drop CIF files/folders onto this script, or pass paths on the command line.
REM Delayed expansion stays disabled so exclamation marks in input paths survive.
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"

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

where diffractscout-quick-export >nul 2>&1
if not errorlevel 1 goto :run_installed

REM Prefer an interpreter only after proving it imports the installed package.
REM Once an actual export starts, its failure is final; there is no retry with
REM another runtime that could produce a second bundle or hide the first error.
where python >nul 2>&1
if errorlevel 1 goto :check_py_launcher
call python -c "import diffractscout" >nul 2>&1
if not errorlevel 1 goto :run_python

:check_py_launcher
where py >nul 2>&1
if errorlevel 1 goto :missing_runtime
call py -3 -c "import diffractscout" >nul 2>&1
if errorlevel 1 goto :missing_runtime
goto :run_py

:run_py
call py -3 -m diffractscout quick-export -o "%OUT%" %*
set "RC=%ERRORLEVEL%"
goto :report

:run_python
call python -m diffractscout quick-export -o "%OUT%" %*
set "RC=%ERRORLEVEL%"
goto :report

:run_installed
call diffractscout-quick-export -o "%OUT%" %*
set "RC=%ERRORLEVEL%"

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
echo Checked the installed diffractscout-quick-export command and Python import preflights.
echo Install or activate the package with:
echo   py -3 -m pip install -e .
pause
endlocal
exit /b 1
