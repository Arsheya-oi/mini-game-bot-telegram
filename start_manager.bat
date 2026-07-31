@echo off
cd /d %~dp0

python -c "import flask" 2>nul
if errorlevel 1 (
    echo در حال نصب پیش نیاز اولیه ^(Flask^)، لطفا صبر کن...
    python -m pip install flask
)

start "Bot Manager" /min python bot_manager.py
timeout /t 2 >nul
start http://127.0.0.1:8099
