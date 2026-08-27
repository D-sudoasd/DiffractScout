@echo off
REM Launch the DiffractScout desktop GUI from the repository (or install) root.
setlocal EnableExtensions
cd /d "%~dp0"
set "ENTRY=%~dp0scripts\diffractscout_entry.py"
set "EXIT_CODE=1"

if exist "%~dp0.venv\Scripts\python.exe" goto :venv_python

where python >nul 2>&1
if errorlevel 1 goto :check_py_launcher
python -c "import sys" >nul 2>&1
if errorlevel 1 goto :check_py_launcher
goto :current_python

:check_py_launcher
where py >nul 2>&1
if not errorlevel 1 goto :py_launcher

echo ERROR: Could not start DiffractScout GUI: no usable Python interpreter was found.
echo Install with:  python -m pip install -e ".[gui-dnd]"
echo Or install Python and use:  py -3 -m pip install -e ".[gui-dnd]"
goto :finish

:venv_python
"%~dp0.venv\Scripts\python.exe" "%ENTRY%" gui
set "EXIT_CODE=%ERRORLEVEL%"
goto :finish

:current_python
python "%ENTRY%" gui
set "EXIT_CODE=%ERRORLEVEL%"
goto :finish

:py_launcher
py -3 "%ENTRY%" gui
set "EXIT_CODE=%ERRORLEVEL%"

:finish
if "%EXIT_CODE%"=="0" goto :success
echo ERROR: DiffractScout GUI exited with code %EXIT_CODE%.
pause
:success
endlocal & exit /b %EXIT_CODE%
