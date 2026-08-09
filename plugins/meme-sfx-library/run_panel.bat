@echo off
rem ---------------------------------------------------------------------------
rem  Meme & SFX library — double-click this to open the panel.
rem
rem  Deliberately does NOT change the working directory. This folder often lives
rem  on a UNC path (\\wsl.localhost\...), which cmd.exe cannot use as a CWD, so
rem  the script passes an absolute script path instead. panel\__main__.py puts
rem  its own parent folder on sys.path, so imports work from anywhere.
rem ---------------------------------------------------------------------------
setlocal

set "PYW="
for %%P in (pythonw.exe) do if not defined PYW set "PYW=%%~$PATH:P"
if not defined PYW if exist "E:\Python\pythonw.exe" set "PYW=E:\Python\pythonw.exe"
if not defined PYW for /f "delims=" %%P in ('py -3 -c "import sys,os;print(os.path.join(os.path.dirname(sys.executable),'pythonw.exe'))" 2^>nul') do set "PYW=%%P"

if not defined PYW (
    echo.
    echo   Could not find Python on this machine.
    echo   Install Python 3.10+ from https://python.org and tick "Add to PATH",
    echo   then run install.bat in this folder.
    echo.
    pause
    exit /b 1
)

rem pythonw has no console, so send any crash output somewhere findable.
start "" "%PYW%" "%~dp0panel\__main__.py" 2>"%TEMP%\meme-sfx-panel.log"
exit /b 0
