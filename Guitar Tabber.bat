@echo off
rem Starts Guitar Tabber with its Python environment, creating it on first run.
set "VENV=%LOCALAPPDATA%\guitar-tab-venv"
if not exist "%VENV%\Scripts\pythonw.exe" (
    echo First run: setting up the Python environment, this downloads about 3 GB...
    py -3.11 -m venv "%VENV%" || "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" -m venv "%VENV%" || goto :fail
    "%VENV%\Scripts\python.exe" -m pip install --upgrade pip
    "%VENV%\Scripts\python.exe" -m pip install -r "%~dp0requirements.txt" || goto :fail
)
start "" "%VENV%\Scripts\pythonw.exe" "%~dp0app.py"
exit /b 0

:fail
echo Setup failed. Install Python 3.11 and ffmpeg first:
echo   winget install Python.Python.3.11
echo   winget install Gyan.FFmpeg
pause
exit /b 1
