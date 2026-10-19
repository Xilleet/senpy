@echo off
chcp 65001 > nul
setlocal

:: 1. Всегда гарантированно переходим в папку проекта
cd /d "%~dp0"

echo ======================================================
echo              RUNNING SENPY PYTEST SUITE
echo ======================================================
echo.

:: 2. Активируем venv
if exist "venv\Scripts\activate.bat" (
    echo [*] Activating venv...
    call "venv\Scripts\activate.bat"
) else (
    if exist ".venv\Scripts\activate.bat" (
        echo [*] Activating .venv...
        call ".venv\Scripts\activate.bat"
    )
)

:: 3. Проверяем и при необходимости доставляем pytest в venv
python -m pip install --quiet pytest

:: 4. Запускаем тесты
echo [*] Running tests...
echo.
python -m pytest tests/ -v --tb=short
if errorlevel 1 (
    echo.
    echo [ERROR] Some tests failed!
    pause
    exit /b 1
)

echo.
echo ======================================================
echo [SUCCESS] All tests passed! Ready to code or release.
echo ======================================================
pause