@echo off
REM Drag-and-drop one-shot CIF export (Cu Ka lab defaults).
REM Usage: drop CIF files/folders onto this script, or pass paths on the command line.
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

if "%~1"=="" (
  echo Drag CIF files or folders onto this script, or run:
  echo   %~nx0 path\to\sample.cif [more paths...]
  echo.
  echo Output defaults to ^<first-file-dir^>\^<first-stem^>_diffractscout.xlsx
  echo with a verifiable bundle at ^<stem^>_diffractscout_bundle\
  pause
  exit /b 1
)

REM Default Excel path next to the first dropped input.
set "OUT=%~dp1%~n1_diffractscout.xlsx"

where py >nul 2>&1
if %ERRORLEVEL%==0 (
  py -3 -m diffractscout quick-export -o "!OUT!" %*
  set "RC=!ERRORLEVEL!"
) else (
  where diffractscout-quick-export >nul 2>&1
  if !ERRORLEVEL!==0 (
    diffractscout-quick-export -o "!OUT!" %*
    set "RC=!ERRORLEVEL!"
  ) else (
    echo ERROR: Neither "py -3" nor diffractscout-quick-export was found.
    echo Install with:  py -3 -m pip install -e .
    pause
    exit /b 1
  )
)

if not "!RC!"=="0" (
  echo.
  echo quick-export finished with exit code !RC!
  pause
  exit /b !RC!
)

echo.
echo Excel: !OUT!
echo Done.
pause
endlocal
exit /b 0
