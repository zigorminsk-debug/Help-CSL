@echo off
chcp 65001 >nul
cd /d "%~dp0\.."
py -3 -m pip install -r web\requirements-web.txt
echo.
echo Откройте в браузере http://127.0.0.1:8080
echo.
py -3 web\server.py
pause
