@echo off
REM Launch the DiffractScout desktop GUI from the repository (or install) root.
setlocal EnableExtensions
cd /d "%~dp0"

where py >nul 2>&1
if %ERRORLEVEL%==0 (
  py -3 -m diffractscout gui
  if not errorlevel 1 goto :done
)

where diffractscout-gui >nul 2>&1
if %ERRORLEVEL%==0 (
  diffractscout-gui
  if not errorlevel 1 goto :done
)

echo ERROR: Could not start DiffractScout GUI.
echo Install with:  py -3 -m pip install -e ".[gui-dnd]"
echo Or ensure  py -3 -m diffractscout gui  works from this directory.
pause
exit /b 1

:done
endlocal
exit /b 0
