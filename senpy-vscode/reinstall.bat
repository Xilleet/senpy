@echo off
:: =============================================================================
:: reinstall.bat - build and install Senpy VS Code extension
:: =============================================================================
:: ALL comments in English to avoid CP866/CP1251/UTF-8 encoding issues in cmd.
:: Russian text only inside echo statements (cmd handles echo better than
:: comments because echo just prints bytes, while comments are parsed).
::
:: Line endings: CRLF (mandatory for multi-line commands with ^).
:: Encoding: ASCII (this file). Output encoding: UTF-8 via chcp 65001.
:: =============================================================================

chcp 65001 > nul
setlocal enabledelayedexpansion

:: P0-9: %~dp0 is the directory of this .bat file (with trailing backslash).
:: pushd/popd is more robust than cd /d (handles UNC paths, restores cwd).
pushd "%~dp0" 2>nul
if errorlevel 1 (
    echo [ERROR] Cannot change directory to: %~dp0
    echo         Run reinstall.bat from its own folder.
    goto :error_pause
)

:: =============================================================================
:: STEP 1/7: Check environment
:: =============================================================================
echo [1/7] Checking environment...

:: Python
python --version >nul 2>&1
if errorlevel 1 (
    echo   [FAIL] Python not found in PATH. Install Python 3.11+.
    goto :error_pause
)
for /f "tokens=*" %%v in ('python --version 2^>^&1') do set "PY_VER=%%v"
echo   [OK] %PY_VER%

:: Node
node --version >nul 2>&1
if errorlevel 1 (
    echo   [FAIL] Node.js not found in PATH. Install Node.js 18+.
    goto :error_pause
)
for /f "tokens=*" %%v in ('node --version 2^>^&1') do set "NODE_VER=%%v"
echo   [OK] Node.js %NODE_VER%

:: vsce (optional - we install if missing)
where vsce >nul 2>&1
if errorlevel 1 (
    echo   [INFO] vsce not found, installing globally...
    call npm install -g @vscode/vsce
    if errorlevel 1 (
        echo   [FAIL] Cannot install vsce. Run manually: npm install -g @vscode/vsce
        goto :error_pause
    )
)
echo   [OK] vsce available

:: code CLI
where code >nul 2>&1
if errorlevel 1 (
    echo   [WARN] 'code' CLI not found in PATH.
    echo          After build, install VSIX manually via:
    echo          VS Code Extensions -> '...' menu -> Install from VSIX
    echo          File: senpy-vscode\senpy-vscode-*.vsix
    set "CODE_CLI=NO"
) else (
    echo   [OK] code CLI available
    set "CODE_CLI=YES"
)

:: npm dependencies (one-time)
if not exist "senpy-vscode\node_modules" (
    echo   [INFO] senpy-vscode\node_modules not found, running npm install...
    pushd senpy-vscode
    call npm install
    if errorlevel 1 (
        echo   [FAIL] npm install failed
        popd
        goto :error_pause
    )
    popd
    echo   [OK] npm dependencies installed
) else (
    echo   [OK] senpy-vscode\node_modules exists
)
echo.

:: =============================================================================
:: STEP 2/7: pip install -e . (editable Senpy)
:: =============================================================================
echo [2/7] Installing Senpy as editable package (pip install -e .)...

:: Activate venv if present
if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
)

python -m pip install -e . 2>&1 | findstr /V "already satisfied"
if errorlevel 1 (
    echo   [FAIL] pip install -e . failed
    goto :error_pause
)
echo   [OK] Senpy installed in editable mode
echo.

:: =============================================================================
:: STEP 3/7: PyInstaller: build senpy.exe
:: =============================================================================
if /I "%MODE%"=="noexe" (
    echo [3/7] SKIPPED: senpy.exe build (--noexe mode)
    echo       VSIX will not contain senpy.exe. Extension will use 'senpy' from PATH.
    echo.
    goto :step4
)

if /I "%MODE%"=="quick" (
    if exist "senpy-vscode\bin\senpy.exe" (
        echo [3/7] SKIPPED: senpy.exe build (--quick mode, using existing exe)
        echo       File: senpy-vscode\bin\senpy.exe
        echo.
        goto :step4
    ) else (
        echo [3/7] --quick mode but senpy.exe not found, building anyway...
    )
)

echo [3/7] Building senpy.exe with PyInstaller (2-5 minutes)...

:: Ensure PyInstaller
python -m pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo   [INFO] Installing PyInstaller...
    python -m pip install -U pyinstaller
    if errorlevel 1 (
        echo   [FAIL] Cannot install PyInstaller
        goto :error_pause
    )
)

:: Clean old artifacts
if exist "senpy-vscode\bin\senpy.exe" del /q "senpy-vscode\bin\senpy.exe"
if exist "build" rmdir /s /q "build"

:: Build (onefile)
echo   Running PyInstaller...
python -m PyInstaller --noconfirm --clean --onefile --name senpy ^
    --paths . --distpath "senpy-vscode\bin" ^
    --workpath "build" --specpath "build" "senpy\cli.py"
if errorlevel 1 (
    echo   [FAIL] PyInstaller build failed
    goto :error_pause
)

:: Verify
"senpy-vscode\bin\senpy.exe" --version >nul 2>&1
if errorlevel 1 (
    echo   [FAIL] senpy.exe built but does not run
    goto :error_pause
)
for /f "tokens=*" %%v in ('"senpy-vscode\bin\senpy.exe" --version 2^>^&1') do set "SENPY_VER=%%v"
echo   [OK] Built senpy.exe: !SENPY_VER!
echo.

:step4
:: =============================================================================
:: STEP 4/7: Compile TypeScript extension
:: =============================================================================
echo [4/7] Compiling TypeScript extension (esbuild)...

pushd senpy-vscode
call npm run compile
if errorlevel 1 (
    echo   [FAIL] esbuild compilation failed
    popd
    goto :error_pause
)
popd
echo   [OK] extension.js compiled
echo.

:: =============================================================================
:: STEP 5/7: Package VSIX with dev version (timestamp)
:: =============================================================================
echo [5/7] Packaging VSIX with dev version...

:: Read base version from package.json
pushd senpy-vscode
for /f "delims=" %%V in ('powershell -NoProfile -Command "(Get-Content package.json | ConvertFrom-Json).version"') do set "BASE_VERSION=%%V"
if not defined BASE_VERSION (
    echo   [FAIL] Cannot read version from package.json
    popd
    goto :error_pause
)

:: Generate timestamp: YYYYMMDD.HHmm
for /f "tokens=2 delims==" %%a in ('wmic OS Get localdatetime /value 2^>nul') do set "dt=%%a"
if not defined dt (
    for /f "delims=" %%a in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd.HHmm"') do set "dt=%%a"
    set "TIMESTAMP=!dt!"
) else (
    set "TIMESTAMP=!dt:~0,8!.!dt:~8,4!"
)
set "DEV_VERSION=%BASE_VERSION%-dev.%TIMESTAMP%"
echo   Base version: %BASE_VERSION%
echo   Dev version:  %DEV_VERSION%

:: Delete old VSIX
if exist "*.vsix" del /q "*.vsix" 2>nul

:: Package
echo   Running vsce package...
call vsce package --no-git-tag-version --no-update-package-json --pre-release
if errorlevel 1 (
    echo   [INFO] Retrying without --pre-release flag...
    call vsce package --no-git-tag-version --no-update-package-json
    if errorlevel 1 (
        echo   [FAIL] vsce package failed
        popd
        goto :error_pause
    )
)

:: Find VSIX
set "VSIX="
for %%f in (*.vsix) do set "VSIX=%%f"
if not defined VSIX (
    echo   [FAIL] No .vsix file created
    popd
    goto :error_pause
)

:: Size
for %%F in ("!VSIX!") do set "VSIX_SIZE=%%~zF"
set /a VSIX_MB="VSIX_SIZE / 1024 / 1024"
echo   [OK] Built: !VSIX!  (!VSIX_MB! MB)
popd
echo.

:: =============================================================================
:: STEP 6/7: Install in VS Code
:: =============================================================================
echo [6/7] Installing VSIX in VS Code...

if "!CODE_CLI!"=="NO" (
    echo   [SKIP] 'code' CLI not in PATH.
    echo          Install manually: VS Code Extensions -> '...' -> Install from VSIX
    echo          File: senpy-vscode\!VSIX!
    echo.
    goto :step7
)

call code --install-extension "senpy-vscode\!VSIX!" --force
if errorlevel 1 (
    echo   [FAIL] code --install-extension failed
    echo          Install manually: VS Code Extensions -> '...' -> Install from VSIX
    echo          File: senpy-vscode\!VSIX!
    goto :error_pause
)
echo   [OK] Installed in VS Code
echo.

:step7
:: =============================================================================
:: STEP 7/7: Done — remind to reload
:: =============================================================================
echo ==========================================================
echo   SUCCESS!  All steps complete.
echo.
echo   Next: in VS Code, press Ctrl+Shift+P and run:
echo         Developer: Reload Window
echo.
echo   Then test:
echo     1. Open DDLC project, wait 10 sec for scan
echo     2. In day1a.rpy type 'jump '  -> should show labels from ALL files
echo     3. F2 on label -> preview + rename
echo     4. Hover on variable -> 'Declared at' is clickable
echo     5. Output -> Senpy Language Server -> [completions] debug logs
echo ==========================================================
echo.
echo   Build artifacts:
echo     - senpy-vscode\bin\senpy.exe   (PyInstaller binary)
echo     - senpy-vscode\!VSIX! (VSIX package)
echo.
popd
goto :success_pause

:cancelled
echo.
echo Packaging cancelled by user.
popd
goto :error_pause

:error_pause
echo.
echo [x] reinstall.bat failed. Exit code: %errorlevel%
echo.
pause
endlocal
exit /b 1

:success_pause
echo.
pause
endlocal
exit /b 0
