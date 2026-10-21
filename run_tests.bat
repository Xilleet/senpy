@echo off
chcp 65001 > nul
setlocal enabledelayedexpansion

:: 1. Переходим в корень проекта
cd /d "%~dp0"

echo ======================================================
echo              RUNNING SENPY PYTEST SUITE
echo ======================================================
echo.

:: 2. Активируем venv (если есть)
if exist "venv\Scripts\activate.bat" (
    echo [*] Activating venv...
    call "venv\Scripts\activate.bat"
) else if exist ".venv\Scripts\activate.bat" (
    echo [*] Activating .venv...
    call ".venv\Scripts\activate.bat"
) else (
    echo [!] No virtualenv found. Using system Python...
)

:: 3. Добавляем корень проекта в PYTHONPATH, чтобы импорты 'senpy.*' находились всегда
set PYTHONPATH=%~dp0;%PYTHONPATH%

:: 4. Проверяем наличие pytest без медленного вызова pip на каждом клике
python -c "import pytest" 2>nul
if errorlevel 1 (
    echo [*] Installing pytest...
    python -m pip install pytest
)

:: 5. Запуск тестов
echo [*] Running tests...
echo.
python -m pytest -v --tb=short

if errorlevel 1 (
    echo.
    echo ======================================================
    echo [ERROR] Some tests failed!
    echo Check test_report.txt for detailed tracebacks.
    echo ======================================================
    echo.
    pause
    exit /b 1
)

echo.
echo ======================================================
echo [SUCCESS] All tests passed! Ready to code or release.
echo Full report saved to test_report.txt and test_report.json
echo ======================================================
echo.
pause