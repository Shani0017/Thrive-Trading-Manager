@echo off
setlocal enabledelayedexpansion

for /f "delims=" %%v in ('python -c "from update_check import APP_VERSION; print(APP_VERSION)"') do set VERSION=%%v
set TAG=v%VERSION%

echo ============================================
echo Publishing release %TAG%
echo ============================================

echo.
echo [1/5] Running tests...
python -m pytest -q
if errorlevel 1 (
    echo Tests failed -- aborting release.
    exit /b 1
)

echo.
echo [2/5] Building THRIVE Trade Manager.exe...
if exist "dist\THRIVE Trade Manager.exe" del "dist\THRIVE Trade Manager.exe"
pyinstaller --onefile --windowed --name "THRIVE Trade Manager" --icon "assets\icon.ico" --collect-data customtkinter --collect-data matplotlib --add-data "assets;assets" --exclude-module PyQt5 --exclude-module PyQt6 --exclude-module PySide2 --exclude-module PySide6 --exclude-module pandas --exclude-module scipy --exclude-module torch --exclude-module tensorflow --exclude-module IPython --exclude-module notebook main.py
if errorlevel 1 (
    echo Build failed -- aborting release.
    exit /b 1
)
if not exist "dist\THRIVE Trade Manager.exe" (
    echo Build did not produce an exe -- aborting release.
    exit /b 1
)

echo.
echo [3/5] Generating release notes from commit history...
REM Local tags only exist if fetched -- `gh release create` tags the
REM remote when publishing, but never updates this local clone's own
REM tag refs, so a plain `git describe` here would silently see no
REM prior tag and dump the ENTIRE commit history as "what changed."
git fetch --tags --quiet
python generate_release_notes.py > release_notes.txt

echo.
echo [4/5] Pushing code to GitHub...
git push origin main
if errorlevel 1 (
    echo git push failed -- aborting release.
    exit /b 1
)

echo.
echo [5/5] Creating GitHub release %TAG% and uploading exe...
gh release create %TAG% "dist\THRIVE Trade Manager.exe" --title "%TAG%" --notes-file release_notes.txt
if errorlevel 1 (
    echo gh release create failed -- check if %TAG% already exists ^(gh release list^).
    exit /b 1
)
del release_notes.txt

echo.
echo Done! %TAG% is now live: https://github.com/Shani0017/Thrive-Trading-Manager/releases/tag/%TAG%
