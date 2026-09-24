@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Python ortami hazirlaniyor...
    where py >nul 2>nul
    if not errorlevel 1 (
        py -3.12 -V >nul 2>nul
        if not errorlevel 1 (
            py -3.12 -m venv ".venv"
        ) else (
            py -3.11 -V >nul 2>nul
            if not errorlevel 1 (
                py -3.11 -m venv ".venv"
            ) else (
                py -3 -m venv ".venv"
            )
        )
    ) else (
        python -m venv ".venv"
    )
    if errorlevel 1 goto failed
)

if not exist ".venv\Scripts\python.exe" goto failed
if not exist ".venv\video-ayiklayici-deps-v2.ok" (
    echo Bagimliliklar kuruluyor. Ilk calistirmada birkac dakika surebilir...
    ".venv\Scripts\python.exe" -m pip install -r "requirements.txt"
    if errorlevel 1 goto failed
    type nul > ".venv\video-ayiklayici-deps-v2.ok"
)

if /I "%~1"=="--only-install" exit /b 0

".venv\Scripts\python.exe" "gui.py"
if errorlevel 1 goto failed
exit /b 0

:failed
echo.
echo Kurulum veya uygulama baslatma hatasi. Yukaridaki hata metnini kontrol edin.
pause
exit /b 1
