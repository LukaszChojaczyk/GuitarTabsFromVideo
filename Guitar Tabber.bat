@echo off
rem Starts Guitar Tabber with its own Python environment.
rem Installs the packages on first run, after a failed install, and whenever
rem requirements.txt changes (e.g. after a git pull).
set "VENV=%LOCALAPPDATA%\guitar-tab-venv"
set "STAMP=%VENV%\requirements.installed"

if not exist "%VENV%\Scripts\python.exe" goto :create
if not exist "%STAMP%" goto :install
fc /b "%~dp0requirements.txt" "%STAMP%" >nul 2>&1 || goto :install
goto :run

:create
echo First run: setting up Guitar Tabber. This downloads about 3 GB and takes a while...
py -3.11 -m venv "%VENV%" 2>nul || "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" -m venv "%VENV%" || goto :fail

:install
echo Installing Guitar Tabber's Python packages...
"%VENV%\Scripts\python.exe" -m pip install --upgrade pip || goto :fail
"%VENV%\Scripts\python.exe" -m pip install -r "%~dp0requirements.txt" || goto :fail
copy /y "%~dp0requirements.txt" "%STAMP%" >nul

:run
start "" "%VENV%\Scripts\pythonw.exe" "%~dp0app.py"
exit /b 0

:fail
echo.
echo Setup failed. Make sure Python 3.11 and ffmpeg are installed:
echo   winget install Python.Python.3.11
echo   winget install Gyan.FFmpeg
echo Then run Guitar Tabber.bat again.
pause
exit /b 1
