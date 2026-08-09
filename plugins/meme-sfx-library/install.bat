@echo off
rem ---------------------------------------------------------------------------
rem  One-time setup. Installs the panel's Python dependencies and puts a
rem  shortcut on the Desktop and in the Start Menu.
rem ---------------------------------------------------------------------------
setlocal

echo.
echo   Meme ^& SFX library - setup
echo   ==========================
echo.

set "PY="
for %%P in (python.exe) do if not defined PY set "PY=%%~$PATH:P"
if not defined PY if exist "E:\Python\python.exe" set "PY=E:\Python\python.exe"
if not defined PY for /f "delims=" %%P in ('py -3 -c "import sys;print(sys.executable)" 2^>nul') do set "PY=%%P"

if not defined PY (
    echo   Python was not found.
    echo   Install Python 3.10+ from https://python.org, tick "Add python.exe to PATH",
    echo   then run this file again.
    echo.
    pause
    exit /b 1
)

echo   Using: %PY%
echo.
echo   [1/3] Installing dependencies ^(this pulls ~250 MB of Qt the first time^)...
"%PY%" -m pip install --disable-pip-version-check -r "%~dp0requirements.txt"
if errorlevel 1 (
    echo.
    echo   Dependency install failed. Scroll up for the reason.
    pause
    exit /b 1
)

echo.
echo   [2/3] Drawing the app icon...
"%PY%" "%~dp0scripts\make_icon.py"

echo.
echo   [3/3] Creating shortcuts...
"%PY%" "%~dp0scripts\install_shortcut.py"

echo.
echo   Done. Launch it from the Desktop shortcut, the Start Menu,
echo   or by double-clicking run_panel.bat in this folder.
echo.
pause
