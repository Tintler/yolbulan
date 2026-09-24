@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

call "KUR_VE_BASLAT.cmd" --only-install
if errorlevel 1 goto failed

".venv\Scripts\python.exe" -m pip install pyinstaller
if errorlevel 1 goto failed

".venv\Scripts\python.exe" "derle.py"
if errorlevel 1 goto failed

echo.
echo Derlendi: dist\Yolbulan\Yolbulan.exe
echo Dagitirken dist\Yolbulan klasorunu tum icerigiyle kopyalayin.
pause
exit /b 0

:failed
echo.
echo Derleme hatasi. Yukaridaki hata metnini kontrol edin.
pause
exit /b 1
