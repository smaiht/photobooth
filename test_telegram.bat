@echo off
cd /d "%~dp0"
echo Testing Telegram connection...
venv\Scripts\python.exe -c "import requests; r = requests.get('https://api.telegram.org'); print('OK:', r.status_code)" 2>&1
echo.
echo Testing bot token...
for /f "usebackq tokens=1,* delims==" %%a in (".env") do set %%a=%%b
venv\Scripts\python.exe -c "import os; import requests; token=os.environ.get('TG_BOT_TOKEN',''); r=requests.get(f'https://api.telegram.org/bot{token}/getMe'); print(r.json())" 2>&1
echo.
echo Testing send message...
venv\Scripts\python.exe -c "import os; import requests; token=os.environ.get('TG_BOT_TOKEN',''); chat=os.environ.get('TG_CHAT_ID',''); r=requests.post(f'https://api.telegram.org/bot{token}/sendMessage', json={'chat_id':chat,'text':'test from photobooth'}); print(r.json())" 2>&1
pause
