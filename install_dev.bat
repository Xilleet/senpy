@echo off
chcp 65001 > nul
setlocal

echo ======================================================
echo       SENPY: Editable Mode Installation
echo ======================================================
echo.

:: 1. Проверяем и активируем виртуальное окружение
if exist "venv\Scripts\activate.bat" (
    echo [*] Activating virtual environment...
    call venv\Scripts\activate.bat
) else (
    echo [WARNING] 'venv' folder not found. Installing to currently active Python.
)

:: 2. Устанавливаем сам пакет
echo [*] Running: pip install -e .
python -m pip install -e .

:: 3. Проверка на ошибки
if errorlevel 1 (
    echo.
    echo [ERROR] Installation failed!
    pause
    exit /b 1
)

echo.
echo ======================================================
echo [SUCCESS] Senpy is installed in editable mode!
echo Any changes in the code will apply instantly.
echo ======================================================
pause