@echo off
chcp 65001 > nul
echo === [build_exe] Сборка senpy.exe из ТЕКУЩЕГО кода ===
cd /d "%~dp0"

echo.
echo [1/4] Проверка PyInstaller...
python -m pip show pyinstaller >nul 2>&1
if %errorlevel% neq 0 (
    echo PyInstaller не найден, устанавливаю...
    python -m pip install -U pyinstaller
    if errorlevel 1 (
        echo [ОШИБКА] Не удалось установить PyInstaller!
        pause
        exit /b 1
    )
)

echo.
echo [2/4] Очистка старых артефактов...
if exist "senpy-vscode\bin\senpy.exe" del /q "senpy-vscode\bin\senpy.exe"
if exist "build" rmdir /s /q "build"

echo.
echo [3/4] Сборка onefile (2-5 минут, не закрывай окно)...
python -m PyInstaller --noconfirm --clean --onefile --name senpy --paths . --distpath "senpy-vscode\bin" --workpath "build" --specpath "build" "senpy\cli.py"
if %errorlevel% neq 0 (
    echo [ОШИБКА] Сборка не удалась!
    pause
    exit /b %errorlevel%
)

echo.
echo [4/4] Проверка собранного бинаря...
"senpy-vscode\bin\senpy.exe" --help >nul 2>&1
if %errorlevel% neq 0 (
    echo [ОШИБКА] senpy.exe собрался, но не запускается!
    pause
    exit /b 1
)

echo.
echo ==============================================================
echo  УСПЕХ! senpy-vscode\bin\senpy.exe собран из текущего кода.
echo  Теперь запускай reinstall.bat - он упакует свежий exe в vsix.
echo ==============================================================
pause