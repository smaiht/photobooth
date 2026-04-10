@echo off
cd /d "%~dp0"
for /f "usebackq tokens=1,* delims==" %%a in (".env") do set %%a=%%b
echo Testing Telegram...
venv\Scripts\python.exe -c "import asyncio,aiohttp,os;token=os.environ['TG_BOT_TOKEN'];chat=os.environ['TG_CHAT_ID'];exec('''async def t():\n async with aiohttp.ClientSession() as s:\n  r=await s.get(f\"https://api.telegram.org/bot{token}/getMe\")\n  print(\"Bot:\",await r.json())\n  r=await s.post(f\"https://api.telegram.org/bot{token}/sendMessage\",json={\"chat_id\":chat,\"text\":\"test from photobooth\"})\n  print(\"Send:\",await r.json())\nasyncio.run(t())''')" 2>&1
pause
