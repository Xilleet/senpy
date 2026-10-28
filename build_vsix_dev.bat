@echo off
:: =============================================================================
:: build_vsix_dev.bat - Build VSIX with dev version (timestamp suffix)
:: =============================================================================
:: PROBLEM: senpy-vscode/package.json version is 0.4.7. vsce package
:: produces senpy-vscode-0.4.7.vsix. When you install multiple dev builds,
:: VS Code can't distinguish them (same version = same extension).
::
:: SOLUTION: This script creates a dev VSIX with a version like
:: 0.4.7-dev.20261028.1430 (timestamp). You can install multiple dev
:: builds side-by-side and VS Code will treat them as upgrades.
::
:: USAGE:
::   1. Run install_dev.bat (installs Senpy from source: pip install -e .)
::   2. Run build_exe.bat (builds senpy-vscode\bin\senpy.exe)
::   3. Run THIS script: build_vsix_dev.bat
::   4. (Optional) Run senpy-vscode\reinstall.bat to install in VS Code
::
:: This script is for LOCAL development only. For releases, use CI
:: (release.yml on git tag) - it bumps version properly.
::
:: Line endings: CRLF (mandatory for multi-line commands with ^).
:: =============================================================================

chcp 65001 > nul
setlocal enabledelayedexpansion

pushd "%~dp0senpy-vscode" 2>nul
if errorlevel 1 (
    echo [ERROR] Cannot cd to senpy-vscode/
    echo         Run build_vsix_dev.bat from project root.
    goto :error_pause
)

echo === Build VSIX (dev) - timestamped version ===
echo Current directory: %CD%
echo.

:: --- Step 1: Read base version from package.json ---
:: Using PowerShell to parse JSON safely (cmd can't parse JSON)
for /f "delims=" %%V in ('powershell -NoProfile -Command "(Get-Content package.json | ConvertFrom-Json).version"') do set "BASE_VERSION=%%V"
if not defined BASE_VERSION (
    echo [ERROR] Cannot read version from package.json
    goto :error_pause
)
echo [1/5] Base version from package.json: %BASE_VERSION%

:: --- Step 2: Generate dev version with timestamp ---
:: Format: 0.4.7-dev.20261028.1430
for /f "tokens=2 delims==" %%a in ('wmic OS Get localdatetime /value 2^>nul') do set "dt=%%a"
if not defined dt (
    :: Fallback: PowerShell
    for /f "delims=" %%a in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd.HHmm"') do set "dt=%%a"
    set "TIMESTAMP=!dt!"
) else (
    :: wmic returns YYYYMMDDHHMMSS.ffffff, take first 8 + . + next 4
    set "TIMESTAMP=!dt:~0,8!.!dt:~8,4!"
)
set "DEV_VERSION=%BASE_VERSION%-dev.%TIMESTAMP%"
echo [2/5] Dev version (timestamped): %DEV_VERSION%
echo.

:: --- Step 3: Compile TypeScript ---
echo [3/5] Compiling extension (esbuild)...
call npm run compile
if errorlevel 1 (
    echo.
    echo [ERROR] TypeScript/esbuild compilation failed!
    echo         Make sure you ran 'npm install' in senpy-vscode/ at least once.
    goto :error_pause
)
echo Compiled OK.
echo.

:: --- Step 4: Check senpy.exe ---
if not exist "bin\senpy.exe" (
    echo [4/5] WARNING: bin\senpy.exe not found!
    echo        VSIX will be built WITHOUT bundled senpy.exe.
    echo        Run build_exe.bat first to enable autonomous mode.
    echo.
    choice /C YN /N /M "Continue without senpy.exe? [Y/N]: "
    if errorlevel 2 goto :cancelled
) else (
    echo [4/5] senpy.exe found: bin\senpy.exe
    :: Check freshness
    if exist "_check_freshness.ps1" (
        powershell -NoProfile -ExecutionPolicy Bypass -File "_check_freshness.ps1"
        if errorlevel 1 (
            echo        WARNING: senpy.exe is OLDER than source files.
            echo        Recommended: run build_exe.bat first.
            echo.
            choice /C YN /N /M "Continue with stale senpy.exe? [Y/N]: "
            if errorlevel 2 goto :cancelled
        )
    )
)
echo.

:: --- Step 5: Package VSIX with dev version ---
echo [5/5] Packaging VSIX with version %DEV_VERSION%...

:: Delete old .vsix files
if exist "*.vsix" del /q "*.vsix" 2>nul

:: --no-git-tag-version: don't try to create git tag (would fail on dev builds)
:: --pre-release: mark as pre-release (allows dev version syntax)
:: We pass --no-git-tag-version to skip version check
call vsce package --no-git-tag-version --no-update-package-json --pre-release
if errorlevel 1 (
    :: Fallback: try without --pre-release (older vsce)
    echo Retrying without --pre-release flag...
    call vsce package --no-git-tag-version --no-update-package-json
    if errorlevel 1 (
        echo.
        echo [ERROR] Failed to build .vsix!
        echo         Make sure vsce is installed: 'npm install -g @vscode/vsce'
        goto :error_pause
    )
)

:: Find the built .vsix file
set "VSIX="
for %%f in (*.vsix) do set "VSIX=%%f"
if not defined VSIX (
    echo.
    echo [ERROR] No .vsix file found after packaging!
    goto :error_pause
)

:: Show VSIX size
for %%F in ("!VSIX!") do set "VSIX_SIZE=%%~zF"
set /a VSIX_MB="VSIX_SIZE / 1024 / 1024"

echo.
echo ======================================================
echo  SUCCESS! Built: !VSIX!  (!VSIX_MB! MB)
echo.
echo  Version: %DEV_VERSION%
echo  (Different from any release version, so VS Code will
echo   treat it as an upgrade when you install it.)
echo.
echo  NEXT:
echo   - Install: senpy-vscode\reinstall.bat (re-uses this VSIX)
echo   - Or manually: code --install-extension "!VSIX!" --force
echo   - Then: Ctrl+Shift+P -> Developer: Reload Window
echo ======================================================
popd
goto :success_pause

:cancelled
echo.
echo Packaging cancelled by user.
popd
goto :error_pause

:error_pause
echo.
echo [x] build_vsix_dev.bat failed. Exit code: %errorlevel%
echo.
pause
endlocal
exit /b 1

:success_pause
echo.
pause
endlocal
exit /b 0
