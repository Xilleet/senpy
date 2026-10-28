@echo off
chcp 65001 > nul
setlocal

echo ======================================================
echo          SENPY PYPI RELEASE AUTOMATION
echo ======================================================
echo.

:: Проверяем переданные флаги (--no-bump / --skip-bump)
set "SKIP_BUMP=0"
for %%a in (%*) do (
    if /i "%%a"=="--no-bump" set "SKIP_BUMP=1"
    if /i "%%a"=="--skip-bump" set "SKIP_BUMP=1"
)

:: 1. Проверяем и поднимаем версию в pyproject.toml, package.json и server.py
if "%SKIP_BUMP%"=="1" (
    echo [*] Flag --no-bump detected. Skipping bump_version.py...
    echo.
) else (
    echo [*] Checking and bumping version...
    python bump_version.py
    if errorlevel 1 (
        echo [ERROR] Failed to check or update version.
        pause
        exit /b 1
    )
    echo.
)

:: 2. Проверяем инструменты сборки
python -m pip install --upgrade --quiet build twine

:: 3. Очищаем старые артефакты
echo [*] Cleaning old dist/ and build/ folders...
if exist dist rd /s /q dist
if exist build rd /s /q build
for /d %%i in (*.egg-info) do rd /s /q "%%i"

:: 4. Собираем свежие пакеты
echo.
echo [*] Building package with pyproject.toml...
python -m build
if errorlevel 1 (
    echo [ERROR] Build failed! Aborting.
    pause
    exit /b 1
)

:: 5. Проверяем целостность архивов
echo.
echo [*] Checking distribution integrity...
python -m twine check dist/*
if errorlevel 1 (
    echo [ERROR] Twine metadata check failed! Aborting.
    pause
    exit /b 1
)

:: 6. Подтверждение перед выкатом
echo.
echo Artifacts ready in dist/:
dir /b dist
echo.
set /p CONFIRM="Upload this version to PyPI? [Y/n]: "
if /i "%CONFIRM%"=="n" (
    echo [!] Upload cancelled by user.
    pause
    exit /b 0
)

:: 7. Загрузка в PyPI (токен берётся из ~/.pypirc)
echo.
echo [*] Uploading to PyPI...
python -m twine upload dist/*
if errorlevel 1 (
    echo.
    echo [ERROR] Upload failed! (Did you try to upload an existing version or token expired?)
    pause
    exit /b 1
)

echo.
echo ======================================================
echo [SUCCESS] Package successfully released to PyPI!
echo ======================================================
pause